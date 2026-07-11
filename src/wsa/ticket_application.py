from __future__ import annotations

import json
import warnings
from typing import Any, Dict, List

from .repositories import WorldRepository, encode_payload, new_id
from .ticket_contracts import (
    CANDIDATE_TICKET_TYPES,
    PORTABLE_APPLY_ORDER,
    PROPOSED_APPLY_COMPAT_WARNING,
    InvalidTicketStateError,
    NonApplicableTicketError,
    TicketApplyResult,
    UnsupportedTicketChangeError,
)
from .ticket_deep_persistence import _apply_deep_authoring_change, _record_id
from .ticket_references import (
    _validate_deep_authoring_references_in_connection,
    _validate_portable_changes_in_connection,
)
from .ticket_store import _ticket_changes_in_connection
from .ticket_validation import _validate_ticket_changes
from .unit_of_work import WorldUnitOfWork
from .workspace import SCHEMA_VERSION, utc_now


def apply_ticket(
    repo: WorldRepository,
    ticket_id: str,
    idempotency_key: str | None = None,
    *,
    allow_proposed_compat: bool = False,
) -> TicketApplyResult:
    applied: List[str] = []
    resolved_change_refs: Dict[str, str] = {}
    application_key = (idempotency_key or ticket_id).strip()
    if not application_key:
        raise ValueError("idempotency_key must not be blank")
    repo._ensure_additive_world_schema()

    with WorldUnitOfWork(repo, immediate=True) as conn:
        receipt = conn.execute(
            """
            SELECT ticket_id, status, result_payload
            FROM ticket_applications
            WHERE idempotency_key = ?
            """,
            (application_key,),
        ).fetchone()
        if receipt is not None:
            if receipt["ticket_id"] != ticket_id:
                raise InvalidTicketStateError(
                    "idempotency key is already bound to ticket "
                    f"{receipt['ticket_id']}"
                )
            receipt_payload = _application_receipt_payload(
                receipt["result_payload"]
            )
            return TicketApplyResult(
                ticket_id=ticket_id,
                previous_status="applied",
                status=receipt["status"],
                applied_ids=[],
                side_effect_status="already_applied_no_new_world_mutation",
                compatibility_mode=receipt_payload.get("compatibility_mode"),
                deprecation_warning=receipt_payload.get("deprecation_warning"),
            )
        row = conn.execute(
            "SELECT ticket_type, status FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"ticket not found: {ticket_id}")
        previous_status = str(row["status"])
        if previous_status == "applied":
            return TicketApplyResult(
                ticket_id=ticket_id,
                previous_status=previous_status,
                status=previous_status,
                applied_ids=[],
                side_effect_status="already_applied_no_new_world_mutation",
            )
        if row["ticket_type"] in CANDIDATE_TICKET_TYPES:
            raise NonApplicableTicketError(
                "candidate ticket must be materialized into a concrete change-set "
                "ticket before apply"
            )
        compatibility_mode = None
        deprecation_warning = None
        if previous_status == "proposed":
            if not allow_proposed_compat:
                raise InvalidTicketStateError(
                    f"ticket {ticket_id} must be reviewed and approved before apply"
                )
            compatibility_mode = "allow_proposed_compat"
            deprecation_warning = PROPOSED_APPLY_COMPAT_WARNING
            warnings.warn(
                deprecation_warning,
                DeprecationWarning,
                stacklevel=2,
            )
        elif previous_status != "approved":
            raise InvalidTicketStateError(
                f"ticket {ticket_id} cannot be applied from status {previous_status}"
            )
        changes = _validate_ticket_changes(
            _ticket_changes_in_connection(conn, ticket_id)
        )
        if not changes:
            raise NonApplicableTicketError(
                "ticket contains candidate material but no concrete changes; "
                "materialize a reviewed change set before apply"
            )
        _validate_portable_changes_in_connection(conn, repo.world_id, changes)
        _validate_deep_authoring_references_in_connection(
            conn,
            repo.world_id,
            changes,
        )
        application_changes = changes
        if any(change.payload.get("portable_id") is not None for change in changes):
            application_changes = sorted(
                changes,
                key=lambda change: PORTABLE_APPLY_ORDER.get(change.change_type, 99),
            )
        for change in application_changes:
            payload = change.payload
            now = utc_now()
            applied_record_id: str | None = None
            deep_applied = _apply_deep_authoring_change(
                conn,
                repo.world_id,
                change,
                now,
            )
            if deep_applied is not None:
                applied.extend(deep_applied)
                applied_record_id = _record_id(payload, "unused")
            elif change.change_type == "add_entity":
                entity_id = _record_id(payload, "entity")
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
                        repo.world_id,
                        payload["entity_type"],
                        payload["display_name"],
                        payload.get("status", "active"),
                        encode_payload(payload.get("payload", {})),
                        SCHEMA_VERSION,
                        now,
                        now,
                    ),
                )
                applied.append(entity_id)
                applied_record_id = entity_id
            elif change.change_type == "add_fact":
                fact_id = _record_id(payload, "fact")
                subject_id = payload.get("subject_id")
                if payload.get("subject_change_ref"):
                    subject_id = resolved_change_refs.get(
                        str(payload["subject_change_ref"])
                    )
                    if subject_id is None:
                        raise UnsupportedTicketChangeError(
                            "unresolved subject_change_ref: "
                            f"{payload['subject_change_ref']}"
                        )
                object_ref_id = payload.get("object_ref_id")
                if payload.get("object_change_ref"):
                    object_ref_id = resolved_change_refs.get(
                        str(payload["object_change_ref"])
                    )
                    if object_ref_id is None:
                        raise UnsupportedTicketChangeError(
                            "unresolved object_change_ref: "
                            f"{payload['object_change_ref']}"
                        )
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
                        subject_id,
                        payload["predicate"],
                        payload.get("object_value"),
                        object_ref_id,
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
                applied_record_id = fact_id
            elif change.change_type == "add_world_edge":
                edge_id = _record_id(payload, "edge")
                subject_id = payload.get("subject_id")
                if payload.get("subject_change_ref"):
                    subject_id = resolved_change_refs.get(
                        str(payload["subject_change_ref"])
                    )
                    if subject_id is None:
                        raise UnsupportedTicketChangeError(
                            "unresolved subject_change_ref: "
                            f"{payload['subject_change_ref']}"
                        )
                object_id = payload.get("object_id")
                if payload.get("object_change_ref"):
                    object_id = resolved_change_refs.get(
                        str(payload["object_change_ref"])
                    )
                    if object_id is None:
                        raise UnsupportedTicketChangeError(
                            "unresolved object_change_ref: "
                            f"{payload['object_change_ref']}"
                        )
                stability = max(
                    1,
                    min(5, int(payload.get("stability_level", 4))),
                )
                revision_cost = max(
                    1,
                    min(5, int(payload.get("revision_cost_level", stability))),
                )
                conn.execute(
                    """
                    INSERT INTO world_edges (
                        edge_id, world_id, subject_type, subject_id, edge_type,
                        object_type, object_id, object_value, valid_from, valid_until,
                        source_event_id, authority, status, confidence,
                        stability_level, revision_cost_level, payload,
                        schema_version, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge_id,
                        repo.world_id,
                        payload["subject_type"],
                        subject_id,
                        payload["edge_type"],
                        payload["object_type"],
                        object_id,
                        payload.get("object_value"),
                        payload.get("valid_from"),
                        payload.get("valid_until"),
                        payload.get("source_event_id"),
                        payload.get("authority", "user_explicit"),
                        payload.get("status", "canon"),
                        float(payload.get("confidence", 1.0)),
                        stability,
                        revision_cost,
                        encode_payload(payload.get("payload", {})),
                        SCHEMA_VERSION,
                        now,
                        now,
                    ),
                )
                applied.append(edge_id)
                applied_record_id = edge_id
            elif change.change_type == "update_fact_status":
                target_id = change.target_id or payload.get("target_id")
                resolved_target_id = str(target_id)
                result = conn.execute(
                    "UPDATE facts SET status = ?, updated_at = ? WHERE fact_id = ?",
                    (payload["status"], now, resolved_target_id),
                )
                if result.rowcount == 0:
                    raise KeyError(f"fact not found: {resolved_target_id}")
                applied.append(resolved_target_id)
            elif change.change_type == "add_timeline_point":
                timeline_point_id = _record_id(payload, "time")
                conn.execute(
                    """
                    INSERT INTO timeline_points (
                        timeline_point_id, world_id, label, sort_key, payload,
                        schema_version, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timeline_point_id,
                        repo.world_id,
                        payload["label"],
                        payload["sort_key"],
                        encode_payload(payload.get("payload", {})),
                        SCHEMA_VERSION,
                        now,
                        now,
                    ),
                )
                applied.append(timeline_point_id)
                applied_record_id = timeline_point_id
            if payload.get("change_ref") and applied_record_id is not None:
                resolved_change_refs[str(payload["change_ref"])] = applied_record_id

        side_effect_status = (
            "world_changes_applied_via_deprecated_proposed_compat"
            if compatibility_mode
            else "world_changes_applied"
        )
        conn.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_id = ?",
            ("applied", utc_now(), ticket_id),
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
                "ticket_applied",
                "ticket",
                ticket_id,
                int(current) + 1,
                encode_payload(
                    {
                        "applied": applied,
                        "previous_status": previous_status,
                        "compatibility_mode": compatibility_mode,
                        "deprecation_warning": deprecation_warning,
                    }
                ),
                SCHEMA_VERSION,
                utc_now(),
            ),
        )
        receipt_payload = {
            "ticket_id": ticket_id,
            "applied_ids": applied,
            "side_effect_status": side_effect_status,
            "compatibility_mode": compatibility_mode,
            "deprecation_warning": deprecation_warning,
        }
        applied_at = utc_now()
        conn.execute(
            """
            INSERT INTO ticket_applications (
                ticket_id, idempotency_key, status, result_payload,
                created_at, updated_at
            )
            VALUES (?, ?, 'applied', ?, ?, ?)
            """,
            (
                ticket_id,
                application_key,
                json.dumps(receipt_payload, ensure_ascii=False, sort_keys=True),
                applied_at,
                applied_at,
            ),
        )
    return TicketApplyResult(
        ticket_id=ticket_id,
        previous_status=previous_status,
        status="applied",
        applied_ids=applied,
        side_effect_status=side_effect_status,
        compatibility_mode=compatibility_mode,
        deprecation_warning=deprecation_warning,
    )


def _application_receipt_payload(value: str) -> Dict[str, Any]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def approve_ticket(repo: WorldRepository, ticket_id: str) -> List[str]:
    """Compatibility wrapper for the pre-0.3 approve-and-apply API."""

    return apply_ticket(
        repo,
        ticket_id,
        allow_proposed_compat=True,
    ).applied_ids
