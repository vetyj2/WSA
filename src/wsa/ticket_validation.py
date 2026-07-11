from __future__ import annotations

import json
import math
from typing import Any, Dict, Iterable, List

from .repositories import TicketChangeRecord, infer_attribute_value_type
from .ticket_contracts import (
    APPLIED_CONTENT_STATUSES,
    DEEP_AUTHORING_TARGET_TYPES,
    DEEP_AUTHORING_UPDATE_CHANGE_TYPES,
    DEEP_LIFECYCLE_REVISION_FIELDS,
    DEEP_LIFECYCLE_STATUSES,
    FACT_STATUSES,
    KNOWLEDGE_STATES,
    KNOWLEDGE_TARGET_TABLES,
    PORTABLE_CHANGE_TABLES,
    PROFILE_FRAGMENT_TYPES,
    NonApplicableTicketError,
    UnsupportedTicketChangeError,
)


def validate_change_payloads(
    changes: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    payloads = [dict(change) for change in changes]
    records = [
        TicketChangeRecord(
            ticket_change_id=f"preview-{index}",
            ticket_id="preview",
            change_type=str(change.get("change_type") or ""),
            target_type=str(change.get("target_type") or "fact"),
            target_id=change.get("target_id"),
            payload=change,
        )
        for index, change in enumerate(payloads, start=1)
    ]
    _validate_ticket_changes(records)
    if not records:
        raise NonApplicableTicketError("applicable change set requires at least one change")
    return payloads


def _validate_ticket_changes(
    changes: Iterable[TicketChangeRecord],
) -> List[TicketChangeRecord]:
    change_list = list(changes)
    for change in change_list:
        payload = change.payload
        if payload.get("portable_id") is not None:
            _require_text(change.change_type, payload, "portable_id")
            if change.change_type not in PORTABLE_CHANGE_TABLES:
                raise UnsupportedTicketChangeError(
                    f"portable_id is unsupported for {change.change_type}"
                )
        if change.change_type == "add_entity":
            for key in ("entity_type", "display_name"):
                if not str(payload.get(key) or "").strip():
                    raise UnsupportedTicketChangeError(f"add_entity requires {key}")
        elif change.change_type == "add_fact":
            if not payload.get("subject_id") and not payload.get("subject_change_ref"):
                raise UnsupportedTicketChangeError(
                    "add_fact requires subject_id or subject_change_ref"
                )
            if not payload.get("predicate"):
                raise UnsupportedTicketChangeError("add_fact requires predicate")
        elif change.change_type == "add_world_edge":
            for key in ("subject_type", "edge_type", "object_type"):
                if not str(payload.get(key) or "").strip():
                    raise UnsupportedTicketChangeError(
                        f"add_world_edge requires {key}"
                    )
            if not payload.get("subject_id") and not payload.get(
                "subject_change_ref"
            ):
                raise UnsupportedTicketChangeError(
                    "add_world_edge requires subject_id or subject_change_ref"
                )
            if (
                payload.get("object_id") is None
                and payload.get("object_value") is None
                and not payload.get("object_change_ref")
            ):
                raise UnsupportedTicketChangeError(
                    "add_world_edge requires object_id, object_value, or "
                    "object_change_ref"
                )
        elif change.change_type == "add_timeline_point":
            for key in ("label", "sort_key"):
                if not str(payload.get(key) or "").strip():
                    raise UnsupportedTicketChangeError(
                        f"add_timeline_point requires {key}"
                    )
        elif change.change_type == "update_fact_status":
            target_id = change.target_id or payload.get("target_id")
            if not target_id:
                raise UnsupportedTicketChangeError(
                    "update_fact_status requires target_id"
                )
            if not payload.get("status"):
                raise UnsupportedTicketChangeError(
                    "update_fact_status requires status"
                )
            if payload["status"] not in FACT_STATUSES:
                raise UnsupportedTicketChangeError(
                    f"unsupported fact status: {payload['status']}"
                )
        elif change.change_type in DEEP_AUTHORING_UPDATE_CHANGE_TYPES:
            _validate_deep_lifecycle_change(change)
        elif change.change_type == "add_actor_profile":
            _validate_deep_common(change.change_type, payload)
            _validate_deep_target_type(change.change_type, payload)
            _require_text(change.change_type, payload, "entity_id")
            fragment_type = _require_text(
                change.change_type,
                payload,
                "fragment_type",
            )
            if (
                payload.get("fragment_type") != fragment_type
                or fragment_type not in PROFILE_FRAGMENT_TYPES
            ):
                raise UnsupportedTicketChangeError(
                    f"unsupported actor profile fragment: {fragment_type}"
                )
            if payload.get("portable_id") is not None:
                _require_mapping(change.change_type, payload, "payload")
            else:
                _require_content_payload(change.change_type, payload)
            _validate_interval(payload.get("valid_from"), payload.get("valid_until"))
        elif change.change_type == "add_entity_attribute_span":
            _validate_deep_common(change.change_type, payload)
            _validate_deep_target_type(change.change_type, payload)
            _require_text(change.change_type, payload, "entity_id")
            _require_text(change.change_type, payload, "dimension_key")
            supplied_values = [
                payload.get("value_number") is not None,
                payload.get("value_text") is not None,
                payload.get("value_ref_id") is not None,
                payload.get("value_json") is not None,
            ]
            if sum(supplied_values) != 1:
                raise UnsupportedTicketChangeError(
                    "add_entity_attribute_span requires exactly one typed value"
                )
            if payload.get("value_number") is not None:
                _validate_finite_number(
                    change.change_type,
                    "value_number",
                    payload["value_number"],
                )
            if payload.get("value_text") is not None and not isinstance(
                payload["value_text"], str
            ):
                raise UnsupportedTicketChangeError(
                    "add_entity_attribute_span value_text must be a string"
                )
            if payload.get("value_ref_id") is not None:
                _require_text(change.change_type, payload, "value_ref_id")
            if payload.get("value_json") is not None:
                _validate_json_value(change.change_type, payload["value_json"])
            dimension = payload.get("dimension")
            if not isinstance(dimension, dict):
                raise UnsupportedTicketChangeError(
                    "add_entity_attribute_span requires dimension metadata"
                )
            for key in (
                "display_name",
                "dimension_type",
                "value_type",
                "applies_to",
                "missing_policy",
            ):
                _require_text(change.change_type, dimension, key)
            if not isinstance(dimension.get("temporal"), bool):
                raise UnsupportedTicketChangeError(
                    "add_entity_attribute_span dimension.temporal must be boolean"
                )
            if dimension.get("portable_id") is not None:
                _require_text(change.change_type, dimension, "portable_id")
                _require_text(change.change_type, dimension, "authority")
                _require_text(change.change_type, dimension, "status")
                _require_mapping(change.change_type, dimension, "payload")
            inferred_type = infer_attribute_value_type(
                payload.get("value_number"),
                payload.get("value_text"),
                payload.get("value_ref_id"),
                payload.get("value_json"),
            )
            if dimension["value_type"] != inferred_type:
                raise UnsupportedTicketChangeError(
                    "attribute dimension value_type does not match the supplied value"
                )
            _validate_interval(payload.get("valid_from"), payload.get("valid_until"))
            _validate_level(change.change_type, payload, "stability_level")
            _validate_level(change.change_type, payload, "revision_cost_level")
            _require_mapping(change.change_type, payload, "payload")
        elif change.change_type == "add_knowledge_attribution":
            _validate_deep_common(change.change_type, payload)
            _validate_deep_target_type(change.change_type, payload)
            _require_text(change.change_type, payload, "actor_entity_id")
            target_type = _require_text(
                change.change_type,
                payload,
                "knowledge_target_type",
            )
            if (
                payload.get("knowledge_target_type") != target_type
                or target_type not in KNOWLEDGE_TARGET_TABLES
            ):
                raise UnsupportedTicketChangeError(
                    f"unsupported knowledge target type: {target_type}"
                )
            _require_text(change.change_type, payload, "knowledge_target_id")
            state = _require_text(change.change_type, payload, "knowledge_state")
            if payload.get("knowledge_state") != state or state not in KNOWLEDGE_STATES:
                raise UnsupportedTicketChangeError(
                    f"unsupported knowledge state: {state}"
                )
            _validate_interval(payload.get("acquired_at"), payload.get("valid_until"))
            _require_mapping(change.change_type, payload, "payload")
        elif change.change_type == "add_actor_memory_packet":
            _validate_deep_common(change.change_type, payload)
            _validate_deep_target_type(change.change_type, payload)
            _require_text(change.change_type, payload, "entity_id")
            _require_text(change.change_type, payload, "time_scope")
            if payload.get("portable_id") is not None:
                _require_mapping(change.change_type, payload, "payload")
            else:
                _require_content_payload(change.change_type, payload)
        else:
            raise UnsupportedTicketChangeError(
                f"unsupported change_type: {change.change_type}"
            )
    return change_list


def _validate_deep_lifecycle_change(change: TicketChangeRecord) -> None:
    change_type = change.change_type
    payload = change.payload
    _validate_deep_target_type(change_type, payload)
    target_id = _require_text(change_type, payload, "target_id")
    if payload["target_id"] != target_id:
        raise UnsupportedTicketChangeError(
            f"{change_type} target_id must not contain surrounding whitespace"
        )
    if change.target_id is not None and str(change.target_id) != target_id:
        raise UnsupportedTicketChangeError(
            f"{change_type} target_id does not match the ticket target"
        )
    _require_text(change_type, payload, "authority")
    _require_text(change_type, payload, "source_ref")

    revision_fields = set(DEEP_LIFECYCLE_REVISION_FIELDS[change_type])
    allowed_fields = {
        "change_type",
        "target_type",
        "target_id",
        "authority",
        "source_ref",
        "expected_revision",
        *revision_fields,
    }
    unsupported_fields = sorted(set(payload) - allowed_fields)
    if unsupported_fields:
        raise UnsupportedTicketChangeError(
            f"{change_type} has unsupported fields: {', '.join(unsupported_fields)}"
        )
    supplied_revisions = revision_fields.intersection(payload)
    if not supplied_revisions:
        raise UnsupportedTicketChangeError(
            f"{change_type} requires at least one lifecycle revision"
        )

    if "status" in payload:
        status = _require_text(change_type, payload, "status")
        if payload["status"] != status or status not in DEEP_LIFECYCLE_STATUSES:
            raise UnsupportedTicketChangeError(
                f"unsupported lifecycle status for {change_type}: {payload['status']}"
            )
    for field in supplied_revisions - {"status"}:
        value = payload[field]
        if field == "time_scope":
            normalized = _require_text(change_type, payload, field)
            if value != normalized:
                raise UnsupportedTicketChangeError(
                    f"{change_type} {field} must not contain surrounding whitespace"
                )
        elif value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            raise UnsupportedTicketChangeError(
                f"{change_type} {field} must be null or a non-blank string"
            )

    if change_type in {
        "update_actor_profile",
        "update_entity_attribute_span",
    }:
        _validate_supplied_interval(payload, "valid_from", "valid_until")
    elif change_type == "update_knowledge_attribution":
        _validate_supplied_interval(payload, "acquired_at", "valid_until")
    else:
        _validate_supplied_interval(payload, "time_scope", "valid_until")

    if "expected_revision" in payload:
        expected = _require_mapping(change_type, payload, "expected_revision")
        updated_at = expected.get("updated_at")
        if not isinstance(updated_at, str) or not updated_at.strip():
            raise UnsupportedTicketChangeError(
                f"{change_type} expected_revision requires updated_at"
            )


def _validate_deep_common(change_type: str, payload: Dict[str, Any]) -> None:
    _require_text(change_type, payload, "authority")
    _require_text(change_type, payload, "source_ref")
    status = _require_text(change_type, payload, "status")
    if status not in APPLIED_CONTENT_STATUSES and payload.get("portable_id") is None:
        raise UnsupportedTicketChangeError(
            f"{change_type} requires an applied content status, got: {status}"
        )
    confidence = payload.get("confidence", 1.0)
    _validate_finite_number(change_type, "confidence", confidence)
    if not 0.0 <= float(confidence) <= 1.0:
        raise UnsupportedTicketChangeError(
            f"{change_type} confidence must be between 0 and 1"
        )


def _validate_deep_target_type(change_type: str, payload: Dict[str, Any]) -> None:
    expected = DEEP_AUTHORING_TARGET_TYPES[change_type]
    if payload.get("target_type") != expected:
        raise UnsupportedTicketChangeError(
            f"{change_type} target_type must be {expected}"
        )


def _require_text(
    change_type: str,
    payload: Dict[str, Any],
    key: str,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise UnsupportedTicketChangeError(f"{change_type} requires {key}")
    return value.strip()


def _require_mapping(
    change_type: str,
    payload: Dict[str, Any],
    key: str,
) -> Dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise UnsupportedTicketChangeError(f"{change_type} {key} must be an object")
    return value


def _require_content_payload(change_type: str, payload: Dict[str, Any]) -> None:
    content = _require_mapping(change_type, payload, "payload")
    if not any(key != "_wsa" for key in content):
        raise UnsupportedTicketChangeError(f"{change_type} payload requires content")


def _validate_finite_number(change_type: str, key: str, value: Any) -> None:
    if isinstance(value, bool):
        raise UnsupportedTicketChangeError(f"{change_type} {key} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise UnsupportedTicketChangeError(
            f"{change_type} {key} must be numeric"
        ) from exc
    if not math.isfinite(number):
        raise UnsupportedTicketChangeError(f"{change_type} {key} must be finite")


def _validate_level(change_type: str, payload: Dict[str, Any], key: str) -> None:
    try:
        value = int(payload.get(key, 4))
    except (TypeError, ValueError) as exc:
        raise UnsupportedTicketChangeError(
            f"{change_type} {key} must be an integer from 1 to 5"
        ) from exc
    if value < 1 or value > 5:
        raise UnsupportedTicketChangeError(
            f"{change_type} {key} must be an integer from 1 to 5"
        )


def _validate_json_value(change_type: str, value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise UnsupportedTicketChangeError(
            f"{change_type} value_json must be JSON serializable"
        ) from exc


def _validate_interval(valid_from: Any, valid_until: Any) -> None:
    for name, value in (("valid_from", valid_from), ("valid_until", valid_until)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise UnsupportedTicketChangeError(f"{name} must be a non-blank string")
    if valid_from is not None and valid_until is not None and valid_from >= valid_until:
        raise UnsupportedTicketChangeError(
            "valid_from must be earlier than valid_until"
        )


def _validate_supplied_interval(
    payload: Dict[str, Any],
    start_field: str,
    end_field: str,
) -> None:
    if start_field not in payload or end_field not in payload:
        return
    start = payload[start_field]
    end = payload[end_field]
    if start is not None and end is not None and start >= end:
        raise UnsupportedTicketChangeError(
            f"{start_field} must be earlier than {end_field}"
        )
