from __future__ import annotations

from sqlite3 import Connection
from typing import Any, Dict, List

from .repositories import (
    TicketChangeRecord,
    decode_payload,
    encode_json_value,
    encode_payload,
    new_id,
)
from .ticket_contracts import (
    DEEP_AUTHORING_UPDATE_CHANGE_TYPES,
    DEEP_LIFECYCLE_RECORD_TABLES,
    DEEP_LIFECYCLE_REVISION_FIELDS,
    UnsupportedTicketChangeError,
)
from .workspace import SCHEMA_VERSION


def _record_id(payload: Dict[str, Any], prefix: str) -> str:
    portable_id = payload.get("portable_id")
    return str(portable_id).strip() if portable_id is not None else new_id(prefix)


def _apply_deep_authoring_change(
    conn: Connection,
    world_id: str,
    change: TicketChangeRecord,
    now: str,
) -> List[str] | None:
    payload = change.payload
    if change.change_type in DEEP_AUTHORING_UPDATE_CHANGE_TYPES:
        return _apply_deep_lifecycle_change(
            conn,
            world_id,
            change,
            now,
        )
    if change.change_type == "add_actor_profile":
        actor_profile_id = _record_id(payload, "profile")
        conn.execute(
            """
            INSERT INTO actor_profiles (
                actor_profile_id, world_id, entity_id, fragment_type,
                status, payload, schema_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_profile_id,
                world_id,
                payload["entity_id"],
                payload["fragment_type"],
                payload["status"],
                encode_payload(_stored_deep_payload(payload)),
                SCHEMA_VERSION,
                now,
                now,
            ),
        )
        return [actor_profile_id]

    if change.change_type == "add_entity_attribute_span":
        applied: List[str] = []
        dimension_key = str(payload["dimension_key"]).strip()
        existing = conn.execute(
            """
            SELECT dimension_id FROM dimension_definitions
            WHERE world_id = ? AND dimension_key = ?
            """,
            (world_id, dimension_key),
        ).fetchone()
        if existing is None:
            dimension = payload["dimension"]
            dimension_id = _record_id(dimension, "dimension")
            dimension_payload = dimension.get("payload")
            if dimension.get("portable_id") is None:
                dimension_payload = {
                    "created_via": "reviewed_attribute_ticket",
                    "source_ref": payload["source_ref"],
                }
            conn.execute(
                """
                INSERT INTO dimension_definitions (
                    dimension_id, world_id, dimension_key, display_name,
                    dimension_type, value_type, applies_to, temporal,
                    missing_policy, authority, status, payload,
                    schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dimension_id,
                    world_id,
                    dimension_key,
                    dimension["display_name"],
                    dimension["dimension_type"],
                    dimension["value_type"],
                    dimension["applies_to"],
                    1 if dimension.get("temporal", True) else 0,
                    dimension["missing_policy"],
                    dimension.get("authority", payload["authority"]),
                    dimension.get("status", payload["status"]),
                    encode_payload(dimension_payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            applied.append(dimension_id)
        attribute_span_id = _record_id(payload, "attrspan")
        conn.execute(
            """
            INSERT INTO entity_attribute_spans (
                attribute_span_id, world_id, entity_id, dimension_key,
                value_number, value_text, value_ref_id, value_json,
                valid_from, valid_until, source_event_id, authority, status,
                confidence, stability_level, revision_cost_level, payload,
                schema_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attribute_span_id,
                world_id,
                payload["entity_id"],
                dimension_key,
                payload.get("value_number"),
                payload.get("value_text"),
                payload.get("value_ref_id"),
                encode_json_value(payload.get("value_json")),
                payload.get("valid_from"),
                payload.get("valid_until"),
                payload.get("source_event_id"),
                payload["authority"],
                payload["status"],
                float(payload.get("confidence", 1.0)),
                int(payload.get("stability_level", 4)),
                int(payload.get("revision_cost_level", 4)),
                encode_payload(_stored_deep_payload(payload)),
                SCHEMA_VERSION,
                now,
                now,
            ),
        )
        applied.append(attribute_span_id)
        return applied

    if change.change_type == "add_knowledge_attribution":
        knowledge_id = _record_id(payload, "knowledge")
        conn.execute(
            """
            INSERT INTO knowledge_attributions (
                knowledge_id, world_id, actor_entity_id, target_type,
                target_id, knowledge_state, acquired_at, acquired_event_id,
                source_entity_id, valid_until, authority, status,
                confidence, payload, schema_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                knowledge_id,
                world_id,
                payload["actor_entity_id"],
                payload["knowledge_target_type"],
                payload["knowledge_target_id"],
                payload["knowledge_state"],
                payload.get("acquired_at"),
                payload.get("acquired_event_id"),
                payload.get("source_entity_id"),
                payload.get("valid_until"),
                payload["authority"],
                payload["status"],
                float(payload.get("confidence", 1.0)),
                encode_payload(_stored_deep_payload(payload)),
                SCHEMA_VERSION,
                now,
                now,
            ),
        )
        return [knowledge_id]

    if change.change_type == "add_actor_memory_packet":
        memory_packet_id = _record_id(payload, "memory")
        conn.execute(
            """
            INSERT INTO actor_memory_packets (
                memory_packet_id, world_id, entity_id, time_scope, status,
                payload, schema_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_packet_id,
                world_id,
                payload["entity_id"],
                payload["time_scope"],
                payload["status"],
                encode_payload(_stored_deep_payload(payload)),
                SCHEMA_VERSION,
                now,
                now,
            ),
        )
        return [memory_packet_id]
    return None


def _apply_deep_lifecycle_change(
    conn: Connection,
    world_id: str,
    change: TicketChangeRecord,
    now: str,
) -> List[str]:
    change_type = change.change_type
    payload = change.payload
    target_id = str(payload["target_id"])
    table, id_column = DEEP_LIFECYCLE_RECORD_TABLES[change_type]
    row = conn.execute(
        f"SELECT * FROM {table} WHERE world_id = ? AND {id_column} = ?",
        (world_id, target_id),
    ).fetchone()
    if row is None:
        raise KeyError(f"{table} lifecycle target not found in world: {target_id}")

    current = _lifecycle_state(change_type, row)
    expected = payload.get("expected_revision")
    if expected is not None and dict(expected) != current:
        raise UnsupportedTicketChangeError(
            f"{change_type} target changed before apply: {target_id}"
        )

    revision_fields = DEEP_LIFECYCLE_REVISION_FIELDS[change_type]
    revised = dict(current)
    for field in revision_fields:
        if field in payload:
            revised[field] = payload[field]
    if not any(revised[field] != current[field] for field in revision_fields):
        raise UnsupportedTicketChangeError(
            f"{change_type} requires at least one actual revision: {target_id}"
        )
    _validate_effective_interval(change_type, revised)

    before = {field: current[field] for field in revision_fields}
    after = {field: revised[field] for field in revision_fields}
    content = decode_payload(row["payload"])
    content["_wsa"] = _lifecycle_metadata(
        content.get("_wsa"),
        change_type=change_type,
        before=before,
        after=after,
        source_ref=str(payload["source_ref"]),
        authority=str(payload["authority"]),
        changed_at=now,
    )

    updates: Dict[str, Any] = {}
    if "status" in payload:
        updates["status"] = revised["status"]
    if change_type == "update_entity_attribute_span":
        for field in ("valid_from", "valid_until"):
            if field in payload:
                updates[field] = revised[field]
    elif change_type == "update_knowledge_attribution":
        for field in ("acquired_at", "valid_until"):
            if field in payload:
                updates[field] = revised[field]
    elif change_type == "update_actor_memory_packet" and "time_scope" in payload:
        updates["time_scope"] = revised["time_scope"]
    updates["payload"] = encode_payload(content)
    updates["updated_at"] = now

    assignments = ", ".join(f"{column} = ?" for column in updates)
    result = conn.execute(
        f"""
        UPDATE {table}
        SET {assignments}
        WHERE world_id = ? AND {id_column} = ? AND updated_at = ?
        """,
        (*updates.values(), world_id, target_id, current["updated_at"]),
    )
    if result.rowcount != 1:
        raise UnsupportedTicketChangeError(
            f"{change_type} target changed concurrently during apply: {target_id}"
        )
    return [target_id]


def _lifecycle_state(change_type: str, row: Any) -> Dict[str, Any]:
    content = decode_payload(row["payload"])
    metadata = content.get("_wsa")
    if not isinstance(metadata, dict):
        metadata = {}
    if change_type == "update_actor_profile":
        state = {
            "status": row["status"],
            "valid_from": metadata.get("valid_from"),
            "valid_until": metadata.get("valid_until"),
        }
    elif change_type == "update_entity_attribute_span":
        state = {
            "status": row["status"],
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
        }
    elif change_type == "update_knowledge_attribution":
        state = {
            "status": row["status"],
            "acquired_at": row["acquired_at"],
            "valid_until": row["valid_until"],
        }
    else:
        state = {
            "status": row["status"],
            "time_scope": row["time_scope"],
            "valid_until": metadata.get("valid_until"),
        }
    state["updated_at"] = row["updated_at"]
    return state


def _validate_effective_interval(
    change_type: str,
    state: Dict[str, Any],
) -> None:
    start_field = {
        "update_actor_profile": "valid_from",
        "update_entity_attribute_span": "valid_from",
        "update_knowledge_attribution": "acquired_at",
        "update_actor_memory_packet": "time_scope",
    }[change_type]
    start = state[start_field]
    end = state["valid_until"]
    if start is not None and end is not None and start >= end:
        raise UnsupportedTicketChangeError(
            f"{change_type} {start_field} must be earlier than valid_until"
        )


def _lifecycle_metadata(
    existing: Any,
    *,
    change_type: str,
    before: Dict[str, Any],
    after: Dict[str, Any],
    source_ref: str,
    authority: str,
    changed_at: str,
) -> Dict[str, Any]:
    if isinstance(existing, dict):
        metadata = dict(existing)
    else:
        metadata = {}
        if existing is not None:
            metadata["legacy_metadata"] = existing

    previous_history = metadata.get("lifecycle_history")
    if isinstance(previous_history, list):
        history = list(previous_history)
    elif previous_history is None:
        history = []
    else:
        history = [{"legacy_history": previous_history}]
    history.append(
        {
            "change_type": change_type,
            "changed_at": changed_at,
            "source_ref": source_ref,
            "authority": authority,
            "before": before,
            "after": after,
        }
    )
    metadata["lifecycle_history"] = history
    metadata.setdefault("source_ref", source_ref)
    metadata.setdefault("authority", authority)
    start_field = {
        "update_actor_profile": "valid_from",
        "update_entity_attribute_span": "valid_from",
        "update_knowledge_attribution": "acquired_at",
        "update_actor_memory_packet": "time_scope",
    }[change_type]
    metadata["valid_from"] = after[start_field]
    metadata["valid_until"] = after["valid_until"]
    return metadata


def _stored_deep_payload(change_payload: Dict[str, Any]) -> Dict[str, Any]:
    content = dict(change_payload.get("payload") or {})
    existing = content.get("_wsa")
    metadata = dict(existing) if isinstance(existing, dict) else {}
    metadata.update(
        {
            "authority": change_payload["authority"],
            "source_ref": change_payload["source_ref"],
            "valid_from": change_payload.get(
                "valid_from",
                change_payload.get("acquired_at", change_payload.get("time_scope")),
            ),
            "valid_until": change_payload.get("valid_until"),
        }
    )
    content["_wsa"] = metadata
    return content
