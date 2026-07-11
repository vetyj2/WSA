from __future__ import annotations

from sqlite3 import Connection
from typing import Any, Dict, Iterable, List

from .repositories import (
    TicketChangeRecord,
    WorldRepository,
    decode_payload,
    encode_payload,
)
from .ticket_contracts import (
    DEEP_AUTHORING_CHANGE_TYPES,
    DEEP_AUTHORING_UPDATE_CHANGE_TYPES,
    DEEP_LIFECYCLE_RECORD_TABLES,
    DEEP_LIFECYCLE_REVISION_FIELDS,
    KNOWLEDGE_TARGET_TABLES,
    PORTABLE_CHANGE_TABLES,
    UnsupportedTicketChangeError,
)
from .ticket_validation import validate_change_payloads


def _portable_pending_ids(
    changes: Iterable[TicketChangeRecord],
) -> Dict[str, set[str]]:
    pending: Dict[str, set[str]] = {}
    for change in changes:
        portable_id = change.payload.get("portable_id")
        if portable_id is None:
            continue
        table, _ = PORTABLE_CHANGE_TABLES[change.change_type]
        pending.setdefault(table, set()).add(str(portable_id).strip())
    return pending


def _validate_portable_changes_in_connection(
    conn: Connection,
    world_id: str,
    changes: Iterable[TicketChangeRecord],
) -> None:
    change_list = list(changes)
    portable_changes = [
        change
        for change in change_list
        if change.payload.get("portable_id") is not None
    ]
    if not portable_changes:
        return

    pending: Dict[str, set[str]] = {}
    change_refs: Dict[str, tuple[str, str]] = {}
    for change in portable_changes:
        table, id_column = PORTABLE_CHANGE_TABLES[change.change_type]
        portable_id = str(change.payload["portable_id"]).strip()
        table_ids = pending.setdefault(table, set())
        if portable_id in table_ids:
            raise UnsupportedTicketChangeError(
                f"duplicate portable ID for {table}: {portable_id}"
            )
        table_ids.add(portable_id)
        collision = conn.execute(
            f"SELECT 1 FROM {table} WHERE {id_column} = ?",
            (portable_id,),
        ).fetchone()
        if collision is not None:
            raise UnsupportedTicketChangeError(
                f"portable ID collision in {table}: {portable_id}"
            )
        change_ref = change.payload.get("change_ref")
        if change_ref is not None:
            normalized_ref = str(change_ref).strip()
            if not normalized_ref:
                raise UnsupportedTicketChangeError(
                    "portable change_ref must not be blank"
                )
            if normalized_ref in change_refs:
                raise UnsupportedTicketChangeError(
                    f"duplicate portable change_ref: {normalized_ref}"
                )
            change_refs[normalized_ref] = (table, portable_id)

    dimensions_by_key: Dict[str, Dict[str, Any]] = {}
    dimension_keys_by_id: Dict[str, str] = {}
    for change in portable_changes:
        if change.change_type != "add_entity_attribute_span":
            continue
        dimension = dict(change.payload["dimension"])
        dimension_key = str(change.payload["dimension_key"]).strip()
        dimension_id = str(dimension["portable_id"]).strip()
        signature = {
            key: dimension.get(key)
            for key in (
                "portable_id",
                "display_name",
                "dimension_type",
                "value_type",
                "applies_to",
                "temporal",
                "missing_policy",
                "authority",
                "status",
                "payload",
            )
        }
        previous = dimensions_by_key.get(dimension_key)
        if previous is not None and previous != signature:
            raise UnsupportedTicketChangeError(
                f"portable dimension metadata conflicts for key: {dimension_key}"
            )
        previous_key = dimension_keys_by_id.get(dimension_id)
        if previous_key is not None and previous_key != dimension_key:
            raise UnsupportedTicketChangeError(
                f"portable dimension ID is reused across keys: {dimension_id}"
            )
        if previous is not None:
            continue
        dimensions_by_key[dimension_key] = signature
        dimension_keys_by_id[dimension_id] = dimension_key
        id_collision = conn.execute(
            "SELECT 1 FROM dimension_definitions WHERE dimension_id = ?",
            (dimension_id,),
        ).fetchone()
        if id_collision is not None:
            raise UnsupportedTicketChangeError(
                f"portable ID collision in dimension_definitions: {dimension_id}"
            )
        key_collision = conn.execute(
            """
            SELECT 1 FROM dimension_definitions
            WHERE world_id = ? AND dimension_key = ?
            """,
            (world_id, dimension_key),
        ).fetchone()
        if key_collision is not None:
            raise UnsupportedTicketChangeError(
                f"portable dimension key collision: {dimension_key}"
            )

    for change in portable_changes:
        payload = change.payload
        if change.change_type == "add_fact":
            _validate_portable_change_ref(
                payload.get("subject_change_ref"),
                payload.get("subject_id"),
                world_id,
                "entities",
                pending,
                change_refs,
                "fact subject",
            )
            if payload.get("object_change_ref") is not None:
                _require_portable_change_ref(
                    str(payload["object_change_ref"]),
                    "entities",
                    change_refs,
                    "fact object",
                )
            elif payload.get("object_ref_id") is not None:
                _require_pending_reference(
                    pending,
                    "entities",
                    str(payload["object_ref_id"]),
                    "fact object",
                )
        elif change.change_type == "add_world_edge":
            if payload.get("subject_change_ref") is not None:
                _require_portable_change_ref(
                    str(payload["subject_change_ref"]),
                    "entities",
                    change_refs,
                    "world edge subject",
                )
            else:
                _require_portable_typed_reference(
                    pending,
                    str(payload["subject_type"]),
                    str(payload.get("subject_id") or ""),
                    world_id,
                    "world edge subject",
                )
            if payload.get("object_change_ref") is not None:
                _require_portable_change_ref(
                    str(payload["object_change_ref"]),
                    "entities",
                    change_refs,
                    "world edge object",
                )
            elif payload.get("object_id") is not None:
                _require_portable_typed_reference(
                    pending,
                    str(payload["object_type"]),
                    str(payload["object_id"]),
                    world_id,
                    "world edge object",
                )


def _validate_portable_change_ref(
    change_ref: Any,
    direct_id: Any,
    world_id: str,
    expected_table: str,
    pending: Dict[str, set[str]],
    change_refs: Dict[str, tuple[str, str]],
    label: str,
) -> None:
    if change_ref is not None:
        _require_portable_change_ref(
            str(change_ref),
            expected_table,
            change_refs,
            label,
        )
        return
    resolved_id = str(direct_id or "")
    if resolved_id == world_id:
        return
    _require_pending_reference(pending, expected_table, resolved_id, label)


def _require_portable_change_ref(
    change_ref: str,
    expected_table: str,
    change_refs: Dict[str, tuple[str, str]],
    label: str,
) -> None:
    resolved = change_refs.get(change_ref)
    if resolved is None or resolved[0] != expected_table:
        raise KeyError(
            f"{label} change_ref is not present in portable import: {change_ref}"
        )


def _require_pending_reference(
    pending: Dict[str, set[str]],
    table: str,
    target_id: str,
    label: str,
) -> None:
    if target_id not in pending.get(table, set()):
        raise KeyError(f"{label} is not present in portable import: {target_id}")


def _require_portable_typed_reference(
    pending: Dict[str, set[str]],
    target_type: str,
    target_id: str,
    world_id: str,
    label: str,
) -> None:
    normalized_type = target_type.strip().lower()
    if normalized_type == "world":
        if target_id != world_id:
            raise KeyError(f"{label} references a different world: {target_id}")
        return
    target = KNOWLEDGE_TARGET_TABLES.get(normalized_type)
    if target is not None:
        _require_pending_reference(pending, target[0], target_id, label)
        return
    _require_pending_reference(pending, "entities", target_id, label)


def validate_deep_authoring_references(
    repo: WorldRepository,
    changes: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Validate typed authoring references without writing ticket or world data."""

    payloads = validate_change_payloads(changes)
    records = [
        TicketChangeRecord(
            ticket_change_id=f"reference-preview-{index}",
            ticket_id="reference-preview",
            change_type=str(payload["change_type"]),
            target_type=str(payload.get("target_type") or ""),
            target_id=payload.get("target_id"),
            payload=payload,
        )
        for index, payload in enumerate(payloads, start=1)
    ]
    repo._ensure_additive_world_schema()
    with repo._connect() as conn:
        _validate_deep_authoring_references_in_connection(
            conn,
            repo.world_id,
            records,
        )
    return payloads


def _validate_deep_authoring_references_in_connection(
    conn: Connection,
    world_id: str,
    changes: Iterable[TicketChangeRecord],
) -> None:
    change_list = list(changes)
    pending = _portable_pending_ids(change_list)
    pending_dimension_types: Dict[str, str] = {}
    lifecycle_targets: set[tuple[str, str]] = set()
    for change in change_list:
        if change.change_type not in DEEP_AUTHORING_CHANGE_TYPES:
            continue
        payload = change.payload
        if change.change_type in DEEP_AUTHORING_UPDATE_CHANGE_TYPES:
            target_id = str(payload["target_id"])
            target_key = (change.change_type, target_id)
            if target_key in lifecycle_targets:
                raise UnsupportedTicketChangeError(
                    "ticket contains duplicate lifecycle revisions for "
                    f"{payload['target_type']}: {target_id}"
                )
            lifecycle_targets.add(target_key)
            _validate_lifecycle_target_in_connection(
                conn,
                world_id,
                change,
            )
            continue
        portable = payload.get("portable_id") is not None
        if change.change_type in {
            "add_actor_profile",
            "add_entity_attribute_span",
            "add_actor_memory_packet",
        }:
            if portable:
                _require_pending_reference(
                    pending,
                    "entities",
                    str(payload["entity_id"]),
                    f"{change.change_type} entity",
                )
            else:
                _require_world_row(
                    conn,
                    world_id,
                    "entities",
                    "entity_id",
                    str(payload["entity_id"]),
                )
        if change.change_type == "add_entity_attribute_span":
            dimension_key = str(payload["dimension_key"]).strip()
            proposed_value_type = str(payload["dimension"]["value_type"])
            pending_value_type = pending_dimension_types.get(dimension_key)
            if pending_value_type is not None and pending_value_type != proposed_value_type:
                raise UnsupportedTicketChangeError(
                    "ticket defines one dimension with conflicting value types"
                )
            pending_dimension_types[dimension_key] = proposed_value_type
            if payload.get("value_ref_id") is not None:
                if portable:
                    _require_pending_reference(
                        pending,
                        "entities",
                        str(payload["value_ref_id"]),
                        "attribute span value_ref_id",
                    )
                else:
                    _require_world_row(
                        conn,
                        world_id,
                        "entities",
                        "entity_id",
                        str(payload["value_ref_id"]),
                    )
            if payload.get("source_event_id") is not None and not portable:
                _require_world_row(
                    conn,
                    world_id,
                    "scene_events",
                    "event_id",
                    str(payload["source_event_id"]),
                )
            existing = conn.execute(
                """
                SELECT value_type FROM dimension_definitions
                WHERE world_id = ? AND dimension_key = ?
                """,
                (world_id, dimension_key),
            ).fetchone()
            if existing is not None and existing["value_type"] != proposed_value_type:
                raise UnsupportedTicketChangeError(
                    "attribute value type conflicts with the existing dimension definition"
                )
        elif change.change_type == "add_knowledge_attribution":
            if portable:
                _require_pending_reference(
                    pending,
                    "entities",
                    str(payload["actor_entity_id"]),
                    "knowledge actor",
                )
            else:
                _require_world_row(
                    conn,
                    world_id,
                    "entities",
                    "entity_id",
                    str(payload["actor_entity_id"]),
                )
            table, id_column = KNOWLEDGE_TARGET_TABLES[
                str(payload["knowledge_target_type"])
            ]
            if portable:
                _require_pending_reference(
                    pending,
                    table,
                    str(payload["knowledge_target_id"]),
                    "knowledge target",
                )
            else:
                _require_world_row(
                    conn,
                    world_id,
                    table,
                    id_column,
                    str(payload["knowledge_target_id"]),
                )
            if payload.get("acquired_event_id") is not None and not portable:
                _require_world_row(
                    conn,
                    world_id,
                    "scene_events",
                    "event_id",
                    str(payload["acquired_event_id"]),
                )
            if payload.get("source_entity_id") is not None:
                if portable:
                    _require_pending_reference(
                        pending,
                        "entities",
                        str(payload["source_entity_id"]),
                        "knowledge source entity",
                    )
                else:
                    _require_world_row(
                        conn,
                        world_id,
                        "entities",
                        "entity_id",
                        str(payload["source_entity_id"]),
                    )


def _validate_lifecycle_target_in_connection(
    conn: Connection,
    world_id: str,
    change: TicketChangeRecord,
) -> None:
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
            f"{change_type} target changed after the revision was prepared: {target_id}"
        )

    revision_fields = DEEP_LIFECYCLE_REVISION_FIELDS[change_type]
    if not any(
        field in payload and payload[field] != current[field]
        for field in revision_fields
    ):
        raise UnsupportedTicketChangeError(
            f"{change_type} requires at least one actual revision: {target_id}"
        )

    revised = dict(current)
    for field in revision_fields:
        if field in payload:
            revised[field] = payload[field]
    _validate_lifecycle_interval(change_type, revised)

    if expected is None:
        payload["expected_revision"] = current
        if change.ticket_id != "reference-preview":
            conn.execute(
                """
                UPDATE ticket_changes
                SET payload = ?
                WHERE world_id = ? AND ticket_id = ? AND ticket_change_id = ?
                """,
                (
                    encode_payload(payload),
                    world_id,
                    change.ticket_id,
                    change.ticket_change_id,
                ),
            )


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


def _validate_lifecycle_interval(
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
    for field, value in ((start_field, start), ("valid_until", end)):
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            raise UnsupportedTicketChangeError(
                f"{change_type} target has invalid {field}"
            )
    if start is not None and end is not None and start >= end:
        raise UnsupportedTicketChangeError(
            f"{change_type} {start_field} must be earlier than valid_until"
        )


def _require_world_row(
    conn: Connection,
    world_id: str,
    table: str,
    id_column: str,
    target_id: str,
) -> None:
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE world_id = ? AND {id_column} = ?",
        (world_id, target_id),
    ).fetchone()
    if row is None:
        raise KeyError(f"{table} reference not found in world: {target_id}")
