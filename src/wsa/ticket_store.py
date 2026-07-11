from __future__ import annotations

import json
from sqlite3 import Connection
from typing import Any, Dict, Iterable, List

from .repositories import (
    TicketChangeRecord,
    TicketRecord,
    WorldRepository,
    encode_payload,
    new_id,
)
from .ticket_contracts import (
    CANDIDATE_TICKET_TYPES,
    REVISIONABLE_TICKET_STATUSES,
    InvalidTicketStateError,
    NonApplicableTicketError,
    TicketApplyResult,
)
from .ticket_references import (
    _validate_deep_authoring_references_in_connection,
    _validate_portable_changes_in_connection,
)
from .ticket_validation import _validate_ticket_changes, validate_change_payloads
from .unit_of_work import WorldUnitOfWork
from .workspace import SCHEMA_VERSION, utc_now


def create_pr_packet(
    repo: WorldRepository,
    title: str,
    changes: Iterable[Dict[str, Any]],
    risk: str = "low",
    compact: bool = False,
    source_ref: str | None = None,
) -> TicketRecord:
    change_list = validate_change_payloads(changes)
    repo._ensure_additive_world_schema()
    with WorldUnitOfWork(repo, immediate=True) as conn:
        return _create_pr_packet_in_connection(
            repo,
            conn,
            title,
            change_list,
            risk,
            compact,
            source_ref,
            None,
        )


def _append_commit_in_connection(
    repo: WorldRepository,
    conn: Connection,
    action: str,
    target_type: str,
    target_id: str,
    payload: Dict[str, Any],
) -> None:
    current = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) FROM commit_log WHERE world_id = ?",
        (repo.world_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO commit_log (
            commit_id, world_id, action, target_type, target_id,
            sequence, payload, schema_version, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id("commit"),
            repo.world_id,
            action,
            target_type,
            target_id,
            int(current) + 1,
            encode_payload(payload),
            SCHEMA_VERSION,
            utc_now(),
        ),
    )


def _create_pr_packet_in_connection(
    repo: WorldRepository,
    conn: Connection,
    title: str,
    change_list: List[Dict[str, Any]],
    risk: str,
    compact: bool,
    source_ref: str | None,
    payload_extra: Dict[str, Any] | None,
    *,
    ticket_id: str | None = None,
) -> TicketRecord:
    ticket_id = ticket_id or new_id("ticket")
    ticket_type = "pr_packet_compact" if compact else "pr_packet"
    now = utc_now()
    ticket_payload = {
        "changes": change_list,
        "compact": compact,
        "source_ref": source_ref,
    }
    if payload_extra:
        ticket_payload.update(payload_extra)
    conn.execute(
        """
        INSERT INTO tickets (
            ticket_id, world_id, ticket_type, title, status, risk,
            payload, schema_version, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            repo.world_id,
            ticket_type,
            title,
            risk,
            encode_payload(ticket_payload),
            SCHEMA_VERSION,
            now,
            now,
        ),
    )
    for change in change_list:
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
                new_id("change"),
                repo.world_id,
                ticket_id,
                change["change_type"],
                change.get("target_type", "fact"),
                change.get("target_id"),
                encode_payload(change),
                SCHEMA_VERSION,
                now,
                now,
            ),
        )
    _append_commit_in_connection(
        repo,
        conn,
        "ticket_created",
        "ticket",
        ticket_id,
        {"title": title, "change_count": len(change_list)},
    )
    return TicketRecord(
        ticket_id,
        ticket_type,
        title,
        "proposed",
        risk,
        ticket_payload,
    )


def materialize_candidate_ticket(
    repo: WorldRepository,
    candidate_ticket_id: str,
    title: str,
    changes: Iterable[Dict[str, Any]],
    source_ref: str,
) -> TicketRecord:
    change_list = validate_change_payloads(changes)
    repo._ensure_additive_world_schema()
    with WorldUnitOfWork(repo, immediate=True) as conn:
        candidate = conn.execute(
            "SELECT ticket_type, status FROM tickets WHERE ticket_id = ?",
            (candidate_ticket_id,),
        ).fetchone()
        if candidate is None:
            raise KeyError(f"ticket not found: {candidate_ticket_id}")
        if candidate["ticket_type"] not in CANDIDATE_TICKET_TYPES:
            raise ValueError(
                f"ticket is not a candidate container: {candidate_ticket_id}"
            )
        if candidate["status"] != "proposed":
            raise InvalidTicketStateError(
                "candidate ticket cannot be materialized from status "
                f"{candidate['status']}"
            )
        ticket = _create_pr_packet_in_connection(
            repo,
            conn,
            title,
            change_list,
            "medium",
            False,
            source_ref,
            None,
        )
        conn.execute(
            "UPDATE tickets SET status = 'converted', updated_at = ? "
            "WHERE ticket_id = ?",
            (utc_now(), candidate_ticket_id),
        )
        _append_commit_in_connection(
            repo,
            conn,
            "candidate_materialized",
            "ticket",
            ticket.ticket_id,
            {"source_ticket_id": candidate_ticket_id},
        )
        return ticket


def create_revision_packet(
    repo: WorldRepository,
    source_ticket_id: str,
    title: str,
    changes: Iterable[Dict[str, Any]],
    *,
    risk: str | None = None,
    compact: bool = False,
    skipped_change_indexes: Iterable[int] = (),
    source_ref: str | None = None,
) -> TicketRecord:
    """Create a replacement ticket and supersede its source atomically."""

    change_list = validate_change_payloads(changes)
    skipped_indexes = sorted({int(index) for index in skipped_change_indexes})
    repo._ensure_additive_world_schema()
    with WorldUnitOfWork(repo, immediate=True) as conn:
        source = conn.execute(
            """
            SELECT ticket_type, title, status, risk, payload
            FROM tickets
            WHERE ticket_id = ?
            """,
            (source_ticket_id,),
        ).fetchone()
        if source is None:
            raise KeyError(f"ticket not found: {source_ticket_id}")
        source_status = str(source["status"])
        if source_status not in REVISIONABLE_TICKET_STATUSES:
            raise InvalidTicketStateError(
                f"ticket {source_ticket_id} cannot be revised from status "
                f"{source_status}"
            )
        if source["ticket_type"] in CANDIDATE_TICKET_TYPES:
            raise NonApplicableTicketError(
                "candidate ticket must be accepted through candidate materialization"
            )

        source_payload = _decode_mapping(source["payload"])
        source_lineage = source_payload.get("lineage")
        if not isinstance(source_lineage, dict):
            source_lineage = {}
        root_ticket_id = str(
            source_lineage.get("root_ticket_id") or source_ticket_id
        )
        try:
            source_revision = int(source_lineage.get("revision_number", 1))
        except (TypeError, ValueError):
            source_revision = 1
        revision_number = source_revision + 1
        lineage = {
            "root_ticket_id": root_ticket_id,
            "parent_ticket_id": source_ticket_id,
            "revision_number": revision_number,
        }
        ticket = _create_pr_packet_in_connection(
            repo,
            conn,
            title,
            change_list,
            str(risk or source["risk"]),
            compact,
            source_ref or f"ticket:{source_ticket_id}",
            {
                "revision_of": source_ticket_id,
                "lineage": lineage,
                "skipped_change_indexes": skipped_indexes,
            },
        )

        source_payload["superseded_by"] = ticket.ticket_id
        source_payload["lineage"] = {
            **source_lineage,
            "root_ticket_id": root_ticket_id,
            "revision_number": source_revision,
            "superseded_by_ticket_id": ticket.ticket_id,
        }
        result = conn.execute(
            """
            UPDATE tickets
            SET status = 'superseded', payload = ?, updated_at = ?
            WHERE ticket_id = ? AND status = ?
            """,
            (
                encode_payload(source_payload),
                utc_now(),
                source_ticket_id,
                source_status,
            ),
        )
        if result.rowcount != 1:
            raise InvalidTicketStateError(
                f"ticket {source_ticket_id} changed while its revision was being written"
            )
        _append_commit_in_connection(
            repo,
            conn,
            "ticket_revised",
            "ticket",
            ticket.ticket_id,
            {
                "source_ticket_id": source_ticket_id,
                "source_previous_status": source_status,
                "revision_number": revision_number,
                "skipped_change_indexes": skipped_indexes,
            },
        )
        return ticket




def review_ticket(repo: WorldRepository, ticket_id: str) -> TicketApplyResult:
    repo._ensure_additive_world_schema()
    with WorldUnitOfWork(repo, immediate=True) as conn:
        row = conn.execute(
            "SELECT ticket_type, status FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"ticket not found: {ticket_id}")
        previous_status = str(row["status"])
        if row["ticket_type"] in CANDIDATE_TICKET_TYPES:
            raise NonApplicableTicketError(
                "candidate ticket must be materialized into a concrete change-set "
                "ticket before review approval"
            )
        if previous_status == "approved":
            return TicketApplyResult(
                ticket_id,
                previous_status,
                "approved",
                [],
                "already_reviewed_no_world_mutation",
            )
        if previous_status != "proposed":
            raise InvalidTicketStateError(
                f"ticket {ticket_id} cannot be reviewed from status {previous_status}"
            )
        changes = _validate_ticket_changes(
            _ticket_changes_in_connection(conn, ticket_id)
        )
        if not changes:
            raise NonApplicableTicketError(
                "candidate ticket must be materialized before review approval"
            )
        _validate_portable_changes_in_connection(conn, repo.world_id, changes)
        _validate_deep_authoring_references_in_connection(
            conn,
            repo.world_id,
            changes,
        )
        conn.execute(
            "UPDATE tickets SET status = 'approved', updated_at = ? "
            "WHERE ticket_id = ?",
            (utc_now(), ticket_id),
        )
        _append_commit_in_connection(
            repo,
            conn,
            "ticket_reviewed",
            "ticket",
            ticket_id,
            {"previous_status": previous_status, "status": "approved"},
        )
    return TicketApplyResult(
        ticket_id,
        previous_status,
        "approved",
        [],
        "approved_for_application_no_world_mutation",
    )


def _ticket_changes_in_connection(
    conn: Connection,
    ticket_id: str,
) -> List[TicketChangeRecord]:
    rows = conn.execute(
        """
        SELECT ticket_change_id, ticket_id, change_type, target_type,
               target_id, payload
        FROM ticket_changes
        WHERE ticket_id = ?
        ORDER BY created_at ASC, rowid ASC
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
            payload=json.loads(row["payload"]),
        )
        for row in rows
    ]


def _decode_mapping(value: Any) -> Dict[str, Any]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}
