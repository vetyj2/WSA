from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING, Any, ContextManager, List, Optional

from .repository_common import (
    Payload,
    decode_payload,
    encode_payload,
    new_id,
)
from .repository_records import (
    ContextPacketRecord,
    DiagnosticLogRecord,
    ReportRecord,
    SceneRecord,
    TicketChangeRecord,
    TicketRecord,
)
from .workspace import (
    SCHEMA_VERSION,
    utc_now,
)

class WorldWorkflowRepositoryMixin:
    if TYPE_CHECKING:
        world_id: str

        def _connect(self) -> ContextManager[sqlite3.Connection]: ...

    def create_scene(
        self,
        name: str,
        timeline_position: str | None = None,
        payload: Optional[Payload] = None,
        status: str = "draft",
    ) -> SceneRecord:
        scene_id = new_id("scene")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scenes (
                    scene_id, world_id, name, timeline_position, status,
                    payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scene_id,
                    self.world_id,
                    name,
                    timeline_position,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return SceneRecord(scene_id, name, status, payload or {})


    def add_scene_event(
        self,
        scene_id: str,
        event_type: str,
        payload: Optional[Payload] = None,
        commit_status: str = "committed",
    ) -> str:
        event_id = new_id("event")
        now = utc_now()
        with self._connect() as conn:
            current = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM scene_events WHERE scene_id = ?",
                (scene_id,),
            ).fetchone()[0]
            sequence = int(current) + 1
            conn.execute(
                """
                INSERT INTO scene_events (
                    event_id, world_id, scene_id, sequence, event_type,
                    commit_status, payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    self.world_id,
                    scene_id,
                    sequence,
                    event_type,
                    commit_status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return event_id


    def create_ticket(
        self,
        title: str,
        ticket_type: str = "pr_packet",
        status: str = "proposed",
        risk: str = "low",
        payload: Optional[Payload] = None,
    ) -> TicketRecord:
        ticket_id = new_id("ticket")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tickets (
                    ticket_id, world_id, ticket_type, title, status, risk,
                    payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    self.world_id,
                    ticket_type,
                    title,
                    status,
                    risk,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return TicketRecord(ticket_id, ticket_type, title, status, risk, payload or {})


    def get_ticket(self, ticket_id: str) -> TicketRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT ticket_id, ticket_type, title, status, risk, payload
                FROM tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"ticket not found: {ticket_id}")
        return TicketRecord(
            ticket_id=row["ticket_id"],
            ticket_type=row["ticket_type"],
            title=row["title"],
            status=row["status"],
            risk=row["risk"],
            payload=decode_payload(row["payload"]),
        )


    def list_tickets(self, status: str | None = None) -> List[TicketRecord]:
        sql = """
            SELECT ticket_id, ticket_type, title, status, risk, payload
            FROM tickets
        """
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            TicketRecord(
                ticket_id=row["ticket_id"],
                ticket_type=row["ticket_type"],
                title=row["title"],
                status=row["status"],
                risk=row["risk"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]


    def update_ticket_status(self, ticket_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_id = ?",
                (status, utc_now(), ticket_id),
            )
            conn.commit()


    def add_ticket_change(
        self,
        ticket_id: str,
        change_type: str,
        target_type: str,
        target_id: str | None = None,
        payload: Optional[Payload] = None,
    ) -> TicketChangeRecord:
        ticket_change_id = new_id("change")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ticket_changes (
                    ticket_change_id, world_id, ticket_id, change_type,
                    target_type, target_id, payload, schema_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_change_id,
                    self.world_id,
                    ticket_id,
                    change_type,
                    target_type,
                    target_id,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return TicketChangeRecord(
            ticket_change_id=ticket_change_id,
            ticket_id=ticket_id,
            change_type=change_type,
            target_type=target_type,
            target_id=target_id,
            payload=payload or {},
        )


    def list_ticket_changes(self, ticket_id: str) -> List[TicketChangeRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticket_change_id, ticket_id, change_type, target_type,
                       target_id, payload
                FROM ticket_changes
                WHERE ticket_id = ?
                ORDER BY created_at ASC
                """,
                (ticket_id,),
            ).fetchall()
        return [
            TicketChangeRecord(
                ticket_change_id=row["ticket_change_id"],
                ticket_id=row["ticket_id"],
                change_type=row["change_type"],
                target_type=row["target_type"],
                target_id=row["target_id"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]


    def create_report(
        self,
        title: str,
        purpose: str,
        risk: str = "low",
        status: str = "inbox",
        payload: Optional[Payload] = None,
        artifact_ref: str | None = None,
    ) -> ReportRecord:
        report_id = new_id("report")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reports (
                    report_id, world_id, purpose, title, risk, status,
                    payload, artifact_ref, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    self.world_id,
                    purpose,
                    title,
                    risk,
                    status,
                    encode_payload(payload),
                    artifact_ref,
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return ReportRecord(report_id, purpose, title, risk, status, payload or {}, artifact_ref)


    def get_report(self, report_id: str) -> ReportRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT report_id, purpose, title, risk, status, payload, artifact_ref
                FROM reports
                WHERE report_id = ?
                """,
                (report_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"report not found: {report_id}")
        return ReportRecord(
            report_id=row["report_id"],
            purpose=row["purpose"],
            title=row["title"],
            risk=row["risk"],
            status=row["status"],
            payload=decode_payload(row["payload"]),
            artifact_ref=row["artifact_ref"],
        )


    def update_report_status(
        self,
        report_id: str,
        status: str,
        artifact_ref: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reports
                SET status = ?,
                    artifact_ref = COALESCE(?, artifact_ref),
                    updated_at = ?
                WHERE report_id = ?
                """,
                (status, artifact_ref, utc_now(), report_id),
            )
            conn.commit()


    def list_reports(self, status: str | None = None) -> List[ReportRecord]:
        sql = """
            SELECT report_id, purpose, title, risk, status, payload, artifact_ref
            FROM reports
        """
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            ReportRecord(
                report_id=row["report_id"],
                purpose=row["purpose"],
                title=row["title"],
                risk=row["risk"],
                status=row["status"],
                payload=decode_payload(row["payload"]),
                artifact_ref=row["artifact_ref"],
            )
            for row in rows
        ]


    def update_fact_status(self, fact_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE facts SET status = ?, updated_at = ? WHERE fact_id = ?",
                (status, utc_now(), fact_id),
            )
            conn.commit()


    def create_diagnostic_log(
        self,
        diagnostic_type: str,
        status: str,
        payload: Optional[Payload] = None,
        fingerprint: str | None = None,
    ) -> DiagnosticLogRecord:
        normalized_payload = payload or {}
        resolved_fingerprint = fingerprint or hashlib.sha256(
            json.dumps(
                {"diagnostic_type": diagnostic_type, "payload": normalized_payload},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        diagnostic_log_id = new_id("diag")
        now = utc_now()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT diagnostic_log_id, diagnostic_type, status, payload
                FROM diagnostic_logs
                WHERE world_id = ? AND fingerprint = ?
                """,
                (self.world_id, resolved_fingerprint),
            ).fetchone()
            if existing is not None:
                return DiagnosticLogRecord(
                    diagnostic_log_id=existing["diagnostic_log_id"],
                    diagnostic_type=existing["diagnostic_type"],
                    status=existing["status"],
                    payload=decode_payload(existing["payload"]),
                )
            conn.execute(
                """
                INSERT INTO diagnostic_logs (
                    diagnostic_log_id, world_id, diagnostic_type, status,
                    fingerprint, payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    diagnostic_log_id,
                    self.world_id,
                    diagnostic_type,
                    status,
                    resolved_fingerprint,
                    encode_payload(normalized_payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return DiagnosticLogRecord(
            diagnostic_log_id=diagnostic_log_id,
            diagnostic_type=diagnostic_type,
            status=status,
            payload=normalized_payload,
        )


    def create_context_packet(
        self,
        packet_type: str,
        payload: Optional[Payload] = None,
        scene_id: str | None = None,
        actor_entity_id: str | None = None,
        status: str = "active",
    ) -> ContextPacketRecord:
        context_packet_id = new_id("context")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO context_packets (
                    context_packet_id, world_id, scene_id, actor_entity_id,
                    packet_type, status, payload, schema_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context_packet_id,
                    self.world_id,
                    scene_id,
                    actor_entity_id,
                    packet_type,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return ContextPacketRecord(
            context_packet_id=context_packet_id,
            packet_type=packet_type,
            status=status,
            payload=payload or {},
        )


    def append_commit(
        self,
        action: str,
        target_type: str,
        target_id: str | None = None,
        payload: Optional[Payload] = None,
    ) -> str:
        commit_id = new_id("commit")
        with self._connect() as conn:
            current = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM commit_log WHERE world_id = ?",
                (self.world_id,),
            ).fetchone()[0]
            sequence = int(current) + 1
            conn.execute(
                """
                INSERT INTO commit_log (
                    commit_id, world_id, action, target_type, target_id,
                    sequence, payload, schema_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    commit_id,
                    self.world_id,
                    action,
                    target_type,
                    target_id,
                    sequence,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    utc_now(),
                ),
            )
            conn.commit()
        return commit_id
