from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

from .repositories import (
    TicketChangeRecord,
    TicketRecord,
    WorldRepository,
    encode_payload,
    new_id,
)
from .workspace import SCHEMA_VERSION, utc_now


class UnsupportedTicketChangeError(ValueError):
    """Raised when a PR packet contains a change this MVP cannot apply."""


def create_pr_packet(
    repo: WorldRepository,
    title: str,
    changes: Iterable[Dict[str, Any]],
    risk: str = "low",
    compact: bool = False,
) -> TicketRecord:
    change_list = list(changes)
    ticket = repo.create_ticket(
        title=title,
        ticket_type="pr_packet_compact" if compact else "pr_packet",
        status="proposed",
        risk=risk,
        payload={"changes": change_list, "compact": compact},
    )
    for change in change_list:
        repo.add_ticket_change(
            ticket.ticket_id,
            change_type=change["change_type"],
            target_type=change.get("target_type", "fact"),
            target_id=change.get("target_id"),
            payload=change,
        )
    repo.append_commit(
        "ticket_created",
        "ticket",
        ticket.ticket_id,
        payload={"title": title, "change_count": len(change_list)},
    )
    return ticket


def _validate_ticket_changes(changes: Iterable[TicketChangeRecord]) -> List[TicketChangeRecord]:
    change_list = list(changes)
    for change in change_list:
        payload = change.payload
        if change.change_type == "add_fact":
            for key in ("subject_id", "predicate"):
                if not payload.get(key):
                    raise UnsupportedTicketChangeError(f"add_fact requires {key}")
        elif change.change_type == "update_fact_status":
            target_id = change.target_id or payload.get("target_id")
            if not target_id:
                raise UnsupportedTicketChangeError("update_fact_status requires target_id")
            if not payload.get("status"):
                raise UnsupportedTicketChangeError("update_fact_status requires status")
        else:
            raise UnsupportedTicketChangeError(f"unsupported change_type: {change.change_type}")
    return change_list


def approve_ticket(repo: WorldRepository, ticket_id: str) -> List[str]:
    ticket = repo.get_ticket(ticket_id)
    if ticket.status == "approved":
        return []

    changes = _validate_ticket_changes(repo.list_ticket_changes(ticket_id))
    applied: List[str] = []

    with repo._connect() as conn:
        for change in changes:
            payload = change.payload
            now = utc_now()
            if change.change_type == "add_fact":
                fact_id = new_id("fact")
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
                        repo.world_id,
                        payload["subject_id"],
                        payload["predicate"],
                        payload.get("object_value"),
                        payload.get("object_ref_id"),
                        payload.get("time_scope"),
                        payload.get("location_scope"),
                        payload.get("authority", "approved"),
                        payload.get("status", "canon"),
                        float(payload.get("confidence", 1.0)),
                        payload.get("source_ref"),
                        json.dumps(payload.get("tags", []), ensure_ascii=False),
                        encode_payload(payload.get("payload", {})),
                        SCHEMA_VERSION,
                        now,
                        now,
                    ),
                )
                applied.append(fact_id)
            elif change.change_type == "update_fact_status":
                target_id = change.target_id or payload.get("target_id")
                result = conn.execute(
                    "UPDATE facts SET status = ?, updated_at = ? WHERE fact_id = ?",
                    (payload["status"], now, target_id),
                )
                if result.rowcount == 0:
                    raise KeyError(f"fact not found: {target_id}")
                applied.append(target_id)

        conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_id = ?",
            ("approved", utc_now(), ticket_id),
        )
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
                "ticket_approved",
                "ticket",
                ticket_id,
                int(current) + 1,
                encode_payload({"applied": applied}),
                SCHEMA_VERSION,
                utc_now(),
            ),
        )
    return applied
