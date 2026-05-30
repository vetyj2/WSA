from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ContextManager, Dict, List, Optional

from .workspace import SCHEMA_VERSION, control_db_path, sqlite_connection, utc_now, world_db_path


Payload = Dict[str, Any]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def encode_payload(payload: Optional[Payload]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def decode_payload(value: str) -> Payload:
    decoded = json.loads(value)
    if isinstance(decoded, dict):
        return decoded
    return {"value": decoded}


@dataclass(frozen=True)
class RuntimeSessionRecord:
    session_id: str
    workspace_id: str
    world_id: Optional[str]
    scene_id: Optional[str]
    role: str
    runtime_target: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class RuntimeMessageRecord:
    message_id: str
    session_id: str
    message_type: str
    sequence: int
    payload: Payload
    status: str


class ControlRepository:
    def __init__(self, workspace: Path, workspace_id: str = "local") -> None:
        self.workspace = workspace
        self.workspace_id = workspace_id

    def _connect(self) -> ContextManager[sqlite3.Connection]:
        return sqlite_connection(control_db_path(self.workspace), schema_name="control")

    def get_runtime_session(self, session_id: str) -> RuntimeSessionRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, workspace_id, world_id, scene_id, role,
                       runtime_target, status, payload
                FROM runtime_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"runtime session not found: {session_id}")
        return RuntimeSessionRecord(
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            world_id=row["world_id"],
            scene_id=row["scene_id"],
            role=row["role"],
            runtime_target=row["runtime_target"],
            status=row["status"],
            payload=decode_payload(row["payload"]),
        )

    def create_runtime_session(
        self,
        role: str,
        runtime_target: str = "mock",
        world_id: str | None = None,
        scene_id: str | None = None,
        payload: Optional[Payload] = None,
        status: str = "created",
    ) -> RuntimeSessionRecord:
        session_id = new_id("session")
        now = utc_now()
        encoded = encode_payload(payload)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_sessions (
                    session_id, workspace_id, world_id, scene_id, role,
                    runtime_target, status, payload, schema_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    self.workspace_id,
                    world_id,
                    scene_id,
                    role,
                    runtime_target,
                    status,
                    encoded,
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return RuntimeSessionRecord(
            session_id=session_id,
            workspace_id=self.workspace_id,
            world_id=world_id,
            scene_id=scene_id,
            role=role,
            runtime_target=runtime_target,
            status=status,
            payload=payload or {},
        )

    def add_runtime_message(
        self,
        session_id: str,
        role: str,
        message_type: str,
        payload: Optional[Payload] = None,
        world_id: str | None = None,
        scene_id: str | None = None,
        parent_message_id: str | None = None,
        artifact_refs: Optional[List[str]] = None,
        status: str = "queued",
    ) -> RuntimeMessageRecord:
        message_id = new_id("msg")
        with self._connect() as conn:
            current = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM runtime_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            sequence = int(current) + 1
            conn.execute(
                """
                INSERT INTO runtime_messages (
                    message_id, protocol_version, workspace_id, world_id,
                    scene_id, session_id, role, message_type, sequence,
                    parent_message_id, payload, artifact_refs, status,
                    schema_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    1,
                    self.workspace_id,
                    world_id,
                    scene_id,
                    session_id,
                    role,
                    message_type,
                    sequence,
                    parent_message_id,
                    encode_payload(payload),
                    json.dumps(artifact_refs or [], ensure_ascii=False),
                    status,
                    SCHEMA_VERSION,
                    utc_now(),
                ),
            )
            conn.commit()
        return RuntimeMessageRecord(
            message_id=message_id,
            session_id=session_id,
            message_type=message_type,
            sequence=sequence,
            payload=payload or {},
            status=status,
        )

    def list_runtime_messages(self, session_id: str) -> List[RuntimeMessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT message_id, session_id, message_type, sequence, payload, status
                FROM runtime_messages
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            RuntimeMessageRecord(
                message_id=row["message_id"],
                session_id=row["session_id"],
                message_type=row["message_type"],
                sequence=row["sequence"],
                payload=decode_payload(row["payload"]),
                status=row["status"],
            )
            for row in rows
        ]


@dataclass(frozen=True)
class EntityRecord:
    entity_id: str
    entity_type: str
    display_name: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class FactRecord:
    fact_id: str
    subject_id: str
    predicate: str
    object_value: Optional[str]
    authority: str
    status: str
    confidence: float
    payload: Payload


@dataclass(frozen=True)
class SceneRecord:
    scene_id: str
    name: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class TicketRecord:
    ticket_id: str
    ticket_type: str
    title: str
    status: str
    risk: str
    payload: Payload


@dataclass(frozen=True)
class TicketChangeRecord:
    ticket_change_id: str
    ticket_id: str
    change_type: str
    target_type: str
    target_id: Optional[str]
    payload: Payload


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    purpose: str
    title: str
    risk: str
    status: str
    payload: Payload
    artifact_ref: Optional[str] = None


@dataclass(frozen=True)
class DiagnosticLogRecord:
    diagnostic_log_id: str
    diagnostic_type: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class ContextPacketRecord:
    context_packet_id: str
    packet_type: str
    status: str
    payload: Payload


class WorldRepository:
    def __init__(self, world_id: str, world_path: Path) -> None:
        self.world_id = world_id
        self.world_path = world_path

    def _connect(self) -> ContextManager[sqlite3.Connection]:
        return sqlite_connection(world_db_path(self.world_path), schema_name="world")

    def create_entity(
        self,
        entity_type: str,
        display_name: str,
        payload: Optional[Payload] = None,
        status: str = "active",
    ) -> EntityRecord:
        entity_id = new_id("entity")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO entities (
                    entity_id, world_id, entity_type, display_name, status,
                    payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    self.world_id,
                    entity_type,
                    display_name,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return EntityRecord(entity_id, entity_type, display_name, status, payload or {})

    def list_entities(
        self,
        entity_type: str | None = None,
        status: str | None = None,
    ) -> List[EntityRecord]:
        sql = """
            SELECT entity_id, entity_type, display_name, status, payload
            FROM entities
        """
        clauses = []
        params: list[Any] = []
        if entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC"

        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            EntityRecord(
                entity_id=row["entity_id"],
                entity_type=row["entity_type"],
                display_name=row["display_name"],
                status=row["status"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

    def create_fact(
        self,
        subject_id: str,
        predicate: str,
        object_value: str | None = None,
        object_ref_id: str | None = None,
        time_scope: str | None = None,
        location_scope: str | None = None,
        authority: str = "generated",
        status: str = "proposed",
        confidence: float = 1.0,
        source_ref: str | None = None,
        tags: Optional[List[str]] = None,
        payload: Optional[Payload] = None,
    ) -> FactRecord:
        fact_id = new_id("fact")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO facts (
                    fact_id, world_id, subject_id, predicate, object_value,
                    object_ref_id, time_scope, location_scope, authority, status,
                    confidence, source_ref, tags, payload, schema_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    self.world_id,
                    subject_id,
                    predicate,
                    object_value,
                    object_ref_id,
                    time_scope,
                    location_scope,
                    authority,
                    status,
                    confidence,
                    source_ref,
                    json.dumps(tags or [], ensure_ascii=False),
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return FactRecord(
            fact_id=fact_id,
            subject_id=subject_id,
            predicate=predicate,
            object_value=object_value,
            authority=authority,
            status=status,
            confidence=confidence,
            payload=payload or {},
        )

    def list_facts(self, subject_id: str | None = None) -> List[FactRecord]:
        sql = """
            SELECT fact_id, subject_id, predicate, object_value, authority,
                   status, confidence, payload
            FROM facts
        """
        params: tuple[Any, ...] = ()
        if subject_id is not None:
            sql += " WHERE subject_id = ?"
            params = (subject_id,)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            FactRecord(
                fact_id=row["fact_id"],
                subject_id=row["subject_id"],
                predicate=row["predicate"],
                object_value=row["object_value"],
                authority=row["authority"],
                status=row["status"],
                confidence=row["confidence"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

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
    ) -> DiagnosticLogRecord:
        diagnostic_log_id = new_id("diag")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO diagnostic_logs (
                    diagnostic_log_id, world_id, diagnostic_type, status,
                    payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    diagnostic_log_id,
                    self.world_id,
                    diagnostic_type,
                    status,
                    encode_payload(payload),
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
            payload=payload or {},
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
