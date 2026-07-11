"""Source contracts, eligibility policy, and normalization for Startup inputs."""

from __future__ import annotations

import copy
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Dict, List, Optional, Tuple


STARTUP_SOURCE_RECORD_SCHEMA = "wsa.world_startup.source_record.v1"

ALLOWED_SOURCE_TYPES = frozenset(
    {
        "import",
        "import_record",
        "imported",
        "imported_record",
        "note",
        "notes",
        "startup_answer",
        "startup_answers",
        "startup_summary_answer",
        "user_note",
        "user_notes",
        "world_note",
        "world_notes",
    }
)
PRIVATE_SOURCE_TYPES = frozenset(
    {
        "beta_memory",
        "manager_memory",
        "user_memory",
        "user_profile",
    }
)

_PROVENANCE_VALUES = frozenset(
    {
        "approved",
        "approved_by_author",
        "approved_by_user",
        "author_approved",
        "author_direct",
        "author_explicit",
        "user_approved",
        "user_explicit",
        "user_supplied",
    }
)


def startup_source_record_contract() -> Dict[str, Any]:
    return {
        "schema": STARTUP_SOURCE_RECORD_SCHEMA,
        "required_fields": [
            "source_id",
            "world_id",
            "source_type",
            "source_ref",
            "provenance",
        ],
        "content_requirement": "non_empty_excerpt_or_structured_claims",
        "provenance_requirement": "user_supplied_or_user_approved",
        "allowed_source_types": sorted(ALLOWED_SOURCE_TYPES),
        "excluded_source_types": sorted(PRIVATE_SOURCE_TYPES),
        "scope": "current_world_only",
    }


def startup_source_input_policy() -> Dict[str, Any]:
    return {
        "allowed_inputs": [
            "current_world_startup_summary",
            "current_world_user_registered_source_records",
        ],
        "excluded_inputs": sorted(PRIVATE_SOURCE_TYPES),
        "reads_beta_memory": False,
        "reads_manager_memory": False,
        "reads_user_profile": False,
        "reads_other_world_sources": False,
        "model_provider_dependency": False,
        "free_content_policy": "quote_or_classify_only_no_lore_inference",
    }


def _summary_world_id(startup_summary: Mapping[str, Any]) -> str:
    if not isinstance(startup_summary, Mapping):
        raise TypeError("startup_summary must be a mapping")
    world_id = _non_empty_string(startup_summary.get("world_id"))
    if world_id is None:
        raise ValueError("startup_summary requires a non-empty world_id")
    return world_id


def _minimum_frame_ready(startup_summary: Mapping[str, Any]) -> bool:
    value = startup_summary.get("minimum_frame_ready")
    if isinstance(value, bool):
        return value
    readiness = startup_summary.get("readiness")
    if isinstance(readiness, Mapping):
        nested = readiness.get("minimum_frame_ready")
        if isinstance(nested, bool):
            return nested
    return False


def _mapping_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _filter_source_records(
    current_world_id: str,
    source_records: Iterable[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if isinstance(source_records, Mapping) or isinstance(
        source_records,
        (str, bytes, bytearray),
    ):
        raise TypeError("source_records must be an iterable of mappings")
    try:
        records = list(source_records)
    except TypeError as exc:
        raise TypeError("source_records must be an iterable of mappings") from exc

    candidates: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            excluded.append(
                _exclusion(
                    index=index,
                    source_id=None,
                    source_type=None,
                    reason="invalid_source_record",
                    detail="source record must be a mapping",
                )
            )
            continue

        source_id = _non_empty_string(record.get("source_id"))
        source_type_raw = _non_empty_string(record.get("source_type"))
        source_type = _normalize_token(source_type_raw) if source_type_raw else None
        if source_type in PRIVATE_SOURCE_TYPES or _contains_private_input_key(record):
            excluded.append(
                _exclusion(
                    index=index,
                    source_id=source_id,
                    source_type=source_type,
                    reason="private_memory_category_not_allowed",
                    detail="private memory cannot be a Startup follow-up source",
                )
            )
            continue

        world_id = _non_empty_string(record.get("world_id"))
        source_ref = _non_empty_string(record.get("source_ref"))
        provenance = record.get("provenance")
        missing = [
            name
            for name, value in (
                ("source_id", source_id),
                ("world_id", world_id),
                ("source_type", source_type),
                ("source_ref", source_ref),
                ("provenance", provenance),
            )
            if value in (None, "")
        ]
        if missing:
            excluded.append(
                _exclusion(
                    index=index,
                    source_id=source_id,
                    source_type=source_type,
                    reason="invalid_source_record",
                    detail=f"missing required fields: {', '.join(missing)}",
                )
            )
            continue
        if world_id != current_world_id:
            excluded.append(
                _exclusion(
                    index=index,
                    source_id=source_id,
                    source_type=source_type,
                    reason="other_world_source_not_allowed",
                    detail="source world_id does not match the current Startup summary",
                )
            )
            continue
        if source_type not in ALLOWED_SOURCE_TYPES:
            excluded.append(
                _exclusion(
                    index=index,
                    source_id=source_id,
                    source_type=source_type,
                    reason="unsupported_source_type",
                    detail="only registered note, import, or Startup answer sources are allowed",
                )
            )
            continue

        excerpt = record.get("excerpt")
        if excerpt is not None and not isinstance(excerpt, str):
            excluded.append(
                _exclusion(
                    index=index,
                    source_id=source_id,
                    source_type=source_type,
                    reason="invalid_source_record",
                    detail="excerpt must be text",
                )
            )
            continue
        excerpt = excerpt.strip() if isinstance(excerpt, str) else None
        structured_claims = record.get("structured_claims")
        if not excerpt and structured_claims in (None, "", [], {}):
            excluded.append(
                _exclusion(
                    index=index,
                    source_id=source_id,
                    source_type=source_type,
                    reason="source_content_required",
                    detail="source requires a non-empty excerpt or structured_claims",
                )
            )
            continue

        provenance_qualification = _provenance_qualification(provenance)
        if provenance_qualification is None:
            excluded.append(
                _exclusion(
                    index=index,
                    source_id=source_id,
                    source_type=source_type,
                    reason="unverified_provenance",
                    detail="provenance must show user-supplied or user-approved authority",
                )
            )
            continue

        candidates.append(
            {
                "input_index": index,
                "source_id": source_id,
                "world_id": world_id,
                "source_type": source_type,
                "source_ref": source_ref,
                "excerpt": excerpt,
                "structured_claims": copy.deepcopy(structured_claims),
                "provenance_qualification": provenance_qualification,
            }
        )

    duplicate_ids = {
        source_id
        for source_id, count in Counter(
            source["source_id"] for source in candidates
        ).items()
        if count > 1
    }
    accepted: List[Dict[str, Any]] = []
    for source in candidates:
        if source["source_id"] in duplicate_ids:
            excluded.append(
                _exclusion(
                    index=source["input_index"],
                    source_id=source["source_id"],
                    source_type=source["source_type"],
                    reason="duplicate_source_id",
                    detail="source_id must be unique within a compilation",
                )
            )
        else:
            accepted.append(source)
    accepted.sort(
        key=lambda source: (
            source["source_id"],
            source["source_ref"],
            source["source_type"],
        )
    )
    excluded.sort(key=_exclusion_sort_key)
    return accepted, excluded


def _contains_private_input_key(record: Mapping[str, Any]) -> bool:
    return any(_normalize_token(str(key)) in PRIVATE_SOURCE_TYPES for key in record)


def _exclude_private_inputs(
    private_inputs: Optional[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    if private_inputs is None:
        return []
    if not isinstance(private_inputs, Mapping):
        raise TypeError("private_inputs must be a mapping when provided")
    exclusions = []
    for index, key in enumerate(sorted(str(item) for item in private_inputs)):
        category = _normalize_token(key)
        reason = (
            "private_memory_category_not_allowed"
            if category in PRIVATE_SOURCE_TYPES
            else "unsupported_input_category"
        )
        exclusions.append(
            _exclusion(
                index=index,
                source_id=None,
                source_type=category,
                reason=reason,
                detail="only the Startup summary and registered current-world sources are read",
            )
        )
    return exclusions


def _provenance_qualification(provenance: Any) -> Optional[str]:
    if isinstance(provenance, str):
        value = _normalize_token(provenance)
        return value if value in _PROVENANCE_VALUES else None
    if not isinstance(provenance, Mapping):
        return None
    for key in (
        "user_supplied",
        "approved",
        "user_approved",
        "approved_by_user",
        "approved_by_author",
    ):
        if provenance.get(key) is True:
            return key
    for key in ("authority", "origin", "approval", "status"):
        field_value = provenance.get(key)
        if isinstance(field_value, str):
            normalized = _normalize_token(field_value)
            if normalized in _PROVENANCE_VALUES:
                return normalized
    return None




def _exclusion(
    *,
    index: int,
    source_id: Optional[str],
    source_type: Optional[str],
    reason: str,
    detail: str,
) -> Dict[str, Any]:
    return {
        "input_index": index,
        "source_id": source_id,
        "source_type": source_type,
        "reason": reason,
        "detail": detail,
        "content_retained": False,
    }


def _exclusion_sort_key(item: Mapping[str, Any]) -> Tuple[str, str, str, int]:
    return (
        str(item.get("source_id") or ""),
        str(item.get("source_type") or ""),
        str(item.get("reason") or ""),
        int(item.get("input_index") or 0),
    )


def _non_empty_string(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _first_non_empty_string(*values: Any) -> Optional[str]:
    for value in values:
        normalized = _non_empty_string(value)
        if normalized is not None:
            return normalized
    return None


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
