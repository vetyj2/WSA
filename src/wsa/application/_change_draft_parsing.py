from __future__ import annotations

import csv
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ._change_draft_contracts import (
    DRAFT_CHANGE_TYPES,
    STRUCTURED_CANDIDATE_KEYS,
    ChangeSpecError,
    _required,
)


def parse_change_specs(
    *,
    add_entity: Iterable[str] = (),
    add_fact: Iterable[str] = (),
    add_world_edge: Iterable[str] = (),
    add_timeline_point: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    changes.extend(_parse_entity_spec(value) for value in add_entity or ())
    changes.extend(_parse_fact_spec(value) for value in add_fact or ())
    changes.extend(_parse_edge_spec(value) for value in add_world_edge or ())
    changes.extend(_parse_timeline_spec(value) for value in add_timeline_point or ())
    return changes


def extract_structured_candidate_changes(
    payload: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    extracted: List[Dict[str, Any]] = []
    seen_lists = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key in STRUCTURED_CANDIDATE_KEYS:
                candidate_list = value.get(key)
                if not isinstance(candidate_list, list):
                    continue
                typed = [
                    deepcopy(dict(item))
                    for item in candidate_list
                    if isinstance(item, Mapping)
                    and item.get("change_type") in DRAFT_CHANGE_TYPES
                ]
                fingerprint = _freeze(typed)
                if typed and fingerprint not in seen_lists:
                    seen_lists.add(fingerprint)
                    extracted.extend(typed)
            for key, child in value.items():
                if key not in STRUCTURED_CANDIDATE_KEYS:
                    visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(payload)
    return extracted


def _parse_entity_spec(value: str) -> Dict[str, Any]:
    fields = _named_fields(value)
    if fields is not None:
        _reject_unknown(
            fields,
            {
                "type",
                "entity_type",
                "name",
                "display_name",
                "ref",
                "change_ref",
                "status",
            },
            "add_entity",
        )
        entity_type = _field(fields, "entity_type", "type", label="entity type")
        display_name = _field(fields, "display_name", "name", label="entity name")
        change_ref = _field(fields, "change_ref", "ref", required=False)
        status = _field(fields, "status", required=False) or "active"
    else:
        parts = _positional_fields(value, (2, 3), "add_entity")
        entity_type, display_name = parts[:2]
        change_ref = parts[2] if len(parts) == 3 else None
        status = "active"
    change = {
        "change_type": "add_entity",
        "target_type": "entity",
        "entity_type": entity_type,
        "display_name": display_name,
        "status": status,
    }
    if change_ref:
        change["change_ref"] = change_ref
    return change


def _parse_fact_spec(value: str) -> Dict[str, Any]:
    fields = _named_fields(value)
    allowed = {
        "subject",
        "subject_name",
        "subject_id",
        "predicate",
        "object",
        "value",
        "object_value",
        "object_name",
        "object_id",
        "object_ref_id",
        "time",
        "time_scope",
        "location",
        "location_scope",
    }
    if fields is not None:
        _reject_unknown(fields, allowed, "add_fact")
        predicate = _field(fields, "predicate", label="fact predicate")
        subject_id = _field(fields, "subject_id", required=False)
        subject_name = _field(fields, "subject_name", "subject", required=False)
        if bool(subject_id) == bool(subject_name):
            raise ChangeSpecError(
                "add_fact requires exactly one of subject/subject_name or subject_id"
            )
        object_entries = [
            _field(fields, "object", "value", "object_value", required=False),
            _field(fields, "object_name", required=False),
            _field(fields, "object_ref_id", "object_id", required=False),
        ]
        if sum(item is not None for item in object_entries) != 1:
            raise ChangeSpecError(
                "add_fact requires exactly one object value, object_name, or object_ref_id"
            )
        object_value, object_name, object_ref_id = object_entries
        time_scope = _field(fields, "time_scope", "time", required=False)
        location_scope = _field(fields, "location_scope", "location", required=False)
    else:
        subject_name, predicate, object_value = _positional_fields(
            value,
            (3,),
            "add_fact",
        )
        subject_id = None
        object_name = None
        object_ref_id = None
        time_scope = None
        location_scope = None

    change: Dict[str, Any] = {
        "change_type": "add_fact",
        "target_type": "fact",
        "predicate": predicate,
    }
    if subject_id:
        change["subject_id"] = subject_id
    else:
        _store_reference(change, "subject", str(subject_name), allow_value=False)
    if object_name:
        change["_draft_object_name"] = object_name
    elif object_ref_id:
        change["object_ref_id"] = object_ref_id
    else:
        _store_fact_object(change, str(object_value))
    if time_scope:
        change["time_scope"] = time_scope
    if location_scope:
        change["location_scope"] = location_scope
    return change


def _parse_edge_spec(value: str) -> Dict[str, Any]:
    fields = _named_fields(value)
    allowed = {
        "subject",
        "subject_name",
        "subject_id",
        "subject_type",
        "edge",
        "edge_type",
        "object",
        "object_name",
        "object_id",
        "object_value",
        "object_type",
    }
    if fields is not None:
        _reject_unknown(fields, allowed, "add_world_edge")
        subject_type = _field(fields, "subject_type", required=False)
        subject_id = _field(fields, "subject_id", required=False)
        subject_name = _field(fields, "subject_name", "subject", required=False)
        if bool(subject_id) == bool(subject_name):
            raise ChangeSpecError(
                "add_world_edge requires exactly one subject name or subject_id"
            )
        edge_type = _field(fields, "edge_type", "edge", label="edge type")
        object_type = _field(fields, "object_type", required=False)
        object_name = _field(fields, "object_name", "object", required=False)
        object_id = _field(fields, "object_id", required=False)
        object_value = _field(fields, "object_value", required=False)
        if sum(item is not None for item in (object_name, object_id, object_value)) != 1:
            raise ChangeSpecError(
                "add_world_edge requires exactly one object, object_id, or object_value"
            )
    else:
        parts = _positional_fields(value, (3, 5), "add_world_edge")
        if len(parts) == 3:
            subject_name, edge_type, object_name = parts
            subject_type = None
            object_type = None
        else:
            subject_type, subject_name, edge_type, object_type, object_name = parts
        subject_id = None
        object_id = None
        object_value = None

    change: Dict[str, Any] = {
        "change_type": "add_world_edge",
        "target_type": "world_edge",
        "edge_type": edge_type,
    }
    if subject_type:
        change["subject_type"] = subject_type
    if subject_id:
        change["subject_id"] = subject_id
    else:
        _store_reference(change, "subject", str(subject_name), allow_value=False)
    if object_type:
        change["object_type"] = object_type
    if object_id:
        change["object_id"] = object_id
    elif object_value is not None:
        change["object_value"] = object_value
    else:
        _store_edge_object(change, str(object_name))
    return change


def _parse_timeline_spec(value: str) -> Dict[str, Any]:
    fields = _named_fields(value)
    if fields is not None:
        _reject_unknown(fields, {"label", "sort", "sort_key"}, "add_timeline_point")
        label = _field(fields, "label", label="timeline label")
        sort_key = _field(fields, "sort_key", "sort", label="timeline sort key")
    else:
        label, sort_key = _positional_fields(value, (2,), "add_timeline_point")
    return {
        "change_type": "add_timeline_point",
        "target_type": "timeline_point",
        "label": label,
        "sort_key": sort_key,
    }


def _store_reference(
    change: Dict[str, Any],
    prefix: str,
    value: str,
    *,
    allow_value: bool,
) -> None:
    reference = _required(value, f"{prefix} reference")
    if reference.startswith("id:"):
        change[f"{prefix}_id"] = _required(reference[3:], f"{prefix} ID")
    elif reference.startswith("ref:"):
        change[f"{prefix}_change_ref"] = _required(
            reference[4:],
            f"{prefix} change_ref",
        )
    elif allow_value and reference.startswith("value:"):
        change[f"{prefix}_value"] = reference[6:]
    else:
        change[f"_draft_{prefix}_name"] = reference


def _store_fact_object(change: Dict[str, Any], value: str) -> None:
    object_value = _required(value, "fact object")
    if object_value.startswith(("@", "name:")):
        change["_draft_object_name"] = object_value
    elif object_value.startswith("id:"):
        change["object_ref_id"] = _required(object_value[3:], "fact object ID")
    elif object_value.startswith("ref:"):
        change["object_change_ref"] = _required(
            object_value[4:],
            "fact object change_ref",
        )
    elif object_value.startswith("value:"):
        change["object_value"] = object_value[6:]
    else:
        change["object_value"] = object_value


def _store_edge_object(change: Dict[str, Any], value: str) -> None:
    object_value = _required(value, "edge object")
    if object_value.startswith("value:"):
        change["object_value"] = object_value[6:]
    elif object_value.startswith("id:"):
        change["object_id"] = _required(object_value[3:], "edge object ID")
    elif object_value.startswith("ref:"):
        change["object_change_ref"] = _required(
            object_value[4:],
            "edge object change_ref",
        )
    else:
        change["_draft_object_name"] = object_value


def _named_fields(value: str) -> Dict[str, str] | None:
    text = _required(value, "change spec")
    if text.startswith(("{", "[")):
        raise ChangeSpecError(
            "JSON change specs are not supported; use repeated typed CLI flags"
        )
    delimiter = next((item for item in ("|", ";", ",") if item in text), None)
    parts = _csv_parts(text, delimiter) if delimiter else [text]
    if not all("=" in part for part in parts):
        return None
    fields: Dict[str, str] = {}
    for part in parts:
        key, raw = part.split("=", 1)
        name = _required(key, "change spec key").lower().replace("-", "_")
        if name in fields:
            raise ChangeSpecError(f"duplicate change spec field: {name}")
        fields[name] = _required(raw, f"change spec field {name}")
    return fields


def _positional_fields(
    value: str,
    allowed_counts: Sequence[int],
    label: str,
) -> List[str]:
    text = _required(value, f"{label} spec")
    if "|" in text:
        parts = _csv_parts(text, "|")
    elif ":" in text:
        parts = [item.strip() for item in text.split(":")]
    else:
        parts = [text]
    if len(parts) not in allowed_counts:
        expected = " or ".join(str(item) for item in allowed_counts)
        raise ChangeSpecError(
            f"{label} expects {expected} fields separated by '|', got {len(parts)}"
        )
    return [_required(item, f"{label} field") for item in parts]


def _csv_parts(value: str, delimiter: str | None) -> List[str]:
    if delimiter is None:
        return [value.strip()]
    try:
        parts = next(
            csv.reader(
                [value],
                delimiter=delimiter,
                quotechar='"',
                escapechar="\\",
                skipinitialspace=True,
                strict=True,
            )
        )
    except csv.Error as exc:
        raise ChangeSpecError(f"invalid quoted change spec: {exc}") from exc
    return [item.strip() for item in parts]


def _field(
    fields: Mapping[str, str],
    *names: str,
    label: str | None = None,
    required: bool = True,
) -> str | None:
    present = [(name, fields[name]) for name in names if name in fields]
    if len(present) > 1:
        raise ChangeSpecError(f"use only one of {', '.join(names)} in a change spec")
    if not present:
        if required:
            raise ChangeSpecError(f"change spec requires {label or names[0]}")
        return None
    return _required(present[0][1], label or present[0][0])


def _reject_unknown(
    fields: Mapping[str, str],
    allowed: set[str],
    label: str,
) -> None:
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise ChangeSpecError(
            f"{label} has unsupported field(s): {', '.join(unknown)}"
        )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), _freeze(child)) for key, child in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(child) for child in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze(child) for child in value))
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value
