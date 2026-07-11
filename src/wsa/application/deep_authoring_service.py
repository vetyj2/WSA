from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping

from ..repositories import TicketRecord, WorldRepository
from ..ticket_contracts import (
    DEEP_AUTHORING_CHANGE_TYPES,
    DEEP_AUTHORING_UPDATE_TARGET_TYPES,
    DEEP_LIFECYCLE_REVISION_FIELDS,
)
from ..tickets import (
    create_pr_packet,
    validate_change_payloads,
    validate_deep_authoring_references,
)


PROFILE_FRAGMENT_ALIASES = {
    "core": "core",
    "core_profile": "core",
    "goal": "goal",
    "goals": "goal",
    "secret": "secret",
    "secrets": "secret",
    "speech": "speech",
    "speech_style": "speech",
    "style": "style",
}
LIFECYCLE_CHANGE_TYPES_BY_RECORD = {
    record_type: change_type
    for change_type, record_type in DEEP_AUTHORING_UPDATE_TARGET_TYPES.items()
}
_UNSET = object()


@dataclass(frozen=True)
class DeepAuthoringPreview:
    world_id: str
    title: str
    changes: List[Dict[str, Any]]
    risk: str
    source_ref: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "wsa.deep_authoring.preview.v1",
            "world_id": self.world_id,
            "title": self.title,
            "changes": self.changes,
            "change_count": len(self.changes),
            "risk": self.risk,
            "source_ref": self.source_ref,
            "review_policy": "preview_then_concrete_ticket_then_review_then_apply",
            "side_effect_status": "read_only_preview_no_world_mutation",
        }


class DeepAuthoringService:
    """Build typed world-authoring proposals without mutating world data."""

    def __init__(self, repo: WorldRepository) -> None:
        self.repo = repo

    def preview(
        self,
        title: str,
        changes: Iterable[Dict[str, Any]],
        *,
        risk: str = "medium",
        source_ref: str,
    ) -> DeepAuthoringPreview:
        return deep_authoring_preview(
            self.repo,
            title,
            changes,
            risk=risk,
            source_ref=source_ref,
        )

    def write_ticket(self, preview: DeepAuthoringPreview) -> TicketRecord:
        return write_deep_authoring_ticket(self.repo, preview)


def actor_profile_change(
    entity_id: str,
    fragment_type: str,
    content: Mapping[str, Any],
    *,
    source_ref: str,
    authority: str = "user_explicit",
    status: str = "active",
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> Dict[str, Any]:
    normalized_fragment = PROFILE_FRAGMENT_ALIASES.get(fragment_type.strip().lower())
    if normalized_fragment is None:
        raise ValueError(f"unsupported actor profile fragment: {fragment_type}")
    body = _with_provenance(
        content,
        source_ref=source_ref,
        authority=authority,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    if normalized_fragment == "secret":
        body.setdefault("visibility", "hidden")
    return {
        "change_type": "add_actor_profile",
        "target_type": "actor_profile",
        "entity_id": entity_id,
        "fragment_type": normalized_fragment,
        "status": status,
        "authority": authority,
        "source_ref": source_ref,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "payload": body,
    }


def temporal_attribute_change(
    entity_id: str,
    dimension_key: str,
    *,
    source_ref: str,
    value_number: float | None = None,
    value_text: str | None = None,
    value_ref_id: str | None = None,
    value_json: Any = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
    source_event_id: str | None = None,
    authority: str = "user_explicit",
    status: str = "canon",
    confidence: float = 1.0,
    stability_level: int = 4,
    revision_cost_level: int | None = None,
    dimension_display_name: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    value_type = _attribute_value_type(
        value_number,
        value_text,
        value_ref_id,
        value_json,
    )
    return {
        "change_type": "add_entity_attribute_span",
        "target_type": "entity_attribute_span",
        "entity_id": entity_id,
        "dimension_key": dimension_key,
        "dimension": {
            "display_name": dimension_display_name or dimension_key.replace("_", " "),
            "dimension_type": "attribute",
            "value_type": value_type,
            "applies_to": "entity",
            "temporal": True,
            "missing_policy": "gap_report",
        },
        "value_number": value_number,
        "value_text": value_text,
        "value_ref_id": value_ref_id,
        "value_json": value_json,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "source_event_id": source_event_id,
        "authority": authority,
        "status": status,
        "confidence": confidence,
        "stability_level": stability_level,
        "revision_cost_level": (
            stability_level if revision_cost_level is None else revision_cost_level
        ),
        "source_ref": source_ref,
        "payload": _with_provenance(
            payload or {},
            source_ref=source_ref,
            authority=authority,
            valid_from=valid_from,
            valid_until=valid_until,
        ),
    }


def knowledge_attribution_change(
    actor_entity_id: str,
    target_type: str,
    target_id: str,
    knowledge_state: str,
    *,
    source_ref: str,
    acquired_at: str | None = None,
    valid_until: str | None = None,
    acquired_event_id: str | None = None,
    source_entity_id: str | None = None,
    authority: str = "user_explicit",
    status: str = "canon",
    confidence: float = 1.0,
    payload: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    normalized_target_type = target_type.strip().lower()
    normalized_state = knowledge_state.strip().lower()
    return {
        "change_type": "add_knowledge_attribution",
        "target_type": "knowledge_attribution",
        "actor_entity_id": actor_entity_id,
        "knowledge_target_type": normalized_target_type,
        "knowledge_target_id": target_id,
        "knowledge_state": normalized_state,
        "acquired_at": acquired_at,
        "valid_until": valid_until,
        "acquired_event_id": acquired_event_id,
        "source_entity_id": source_entity_id,
        "authority": authority,
        "status": status,
        "confidence": confidence,
        "source_ref": source_ref,
        "payload": _with_provenance(
            payload or {},
            source_ref=source_ref,
            authority=authority,
            valid_from=acquired_at,
            valid_until=valid_until,
        ),
    }


def actor_memory_change(
    entity_id: str,
    time_scope: str,
    content: Mapping[str, Any],
    *,
    source_ref: str,
    authority: str = "user_explicit",
    status: str = "active",
) -> Dict[str, Any]:
    return {
        "change_type": "add_actor_memory_packet",
        "target_type": "actor_memory_packet",
        "entity_id": entity_id,
        "time_scope": time_scope,
        "status": status,
        "authority": authority,
        "source_ref": source_ref,
        "payload": _with_provenance(
            content,
            source_ref=source_ref,
            authority=authority,
            valid_from=time_scope,
            valid_until=None,
        ),
    }


def lifecycle_revision_change(
    record_type: str,
    record_id: str,
    *,
    source_ref: str,
    authority: str = "user_explicit",
    status: Any = _UNSET,
    valid_from: Any = _UNSET,
    valid_until: Any = _UNSET,
    acquired_at: Any = _UNSET,
    time_scope: Any = _UNSET,
) -> Dict[str, Any]:
    """Build a typed in-place status or validity revision for a deep record."""

    normalized_type = record_type.strip().lower()
    change_type = LIFECYCLE_CHANGE_TYPES_BY_RECORD.get(normalized_type)
    if change_type is None:
        raise ValueError(f"unsupported deep lifecycle record type: {record_type}")
    normalized_id = record_id.strip()
    normalized_source = source_ref.strip()
    normalized_authority = authority.strip()
    if not normalized_id:
        raise ValueError("deep lifecycle record_id is required")
    if not normalized_source:
        raise ValueError("deep lifecycle source_ref is required")
    if not normalized_authority:
        raise ValueError("deep lifecycle authority is required")

    candidates = {
        "status": status,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "acquired_at": acquired_at,
        "time_scope": time_scope,
    }
    supported = set(DEEP_LIFECYCLE_REVISION_FIELDS[change_type])
    supplied = {
        field: value
        for field, value in candidates.items()
        if value is not _UNSET
    }
    unsupported = sorted(set(supplied) - supported)
    if unsupported:
        raise ValueError(
            f"{normalized_type} does not support lifecycle fields: "
            + ", ".join(unsupported)
        )
    if not supplied:
        raise ValueError("deep lifecycle change requires at least one revision")

    normalized_revisions: Dict[str, Any] = {}
    for field, value in supplied.items():
        if field == "status":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("deep lifecycle status must be a non-blank string")
            normalized_revisions[field] = value.strip().lower()
        elif field == "time_scope":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("deep lifecycle time_scope must be a non-blank string")
            normalized_revisions[field] = value.strip()
        elif value is None:
            normalized_revisions[field] = None
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"deep lifecycle {field} must be null or a non-blank string"
            )
        else:
            normalized_revisions[field] = value.strip()

    return {
        "change_type": change_type,
        "target_type": normalized_type,
        "target_id": normalized_id,
        "authority": normalized_authority,
        "source_ref": normalized_source,
        **normalized_revisions,
    }


def deep_record_replacement_changes(
    record_type: str,
    record_id: str,
    replacement_change: Mapping[str, Any],
    *,
    source_ref: str,
    authority: str = "user_explicit",
    lifecycle_status: str = "deprecated",
    valid_until: Any = _UNSET,
) -> List[Dict[str, Any]]:
    """Pair an old-record lifecycle update with a normal typed add change."""

    normalized_type = record_type.strip().lower()
    expected_add_type = f"add_{normalized_type}"
    replacement = dict(replacement_change)
    if replacement.get("change_type") != expected_add_type:
        raise ValueError(
            f"replacement for {normalized_type} must use {expected_add_type}"
        )
    if replacement.get("target_type") != normalized_type:
        raise ValueError(
            f"replacement target_type must be {normalized_type}"
        )
    revision_args: Dict[str, Any] = {"status": lifecycle_status}
    if valid_until is not _UNSET:
        revision_args["valid_until"] = valid_until
    return [
        lifecycle_revision_change(
            normalized_type,
            record_id,
            source_ref=source_ref,
            authority=authority,
            **revision_args,
        ),
        replacement,
    ]


def deep_authoring_preview(
    repo: WorldRepository,
    title: str,
    changes: Iterable[Dict[str, Any]],
    *,
    risk: str = "medium",
    source_ref: str,
) -> DeepAuthoringPreview:
    normalized_title = title.strip()
    normalized_source = source_ref.strip()
    if not normalized_title:
        raise ValueError("deep authoring title is required")
    if not normalized_source:
        raise ValueError("deep authoring source_ref is required")
    validated = validate_change_payloads(changes)
    unsupported = sorted(
        {
            str(change.get("change_type") or "")
            for change in validated
            if change.get("change_type") not in DEEP_AUTHORING_CHANGE_TYPES
        }
    )
    if unsupported:
        raise ValueError(
            "deep authoring preview only accepts typed changes: "
            + ", ".join(unsupported)
        )
    validated = validate_deep_authoring_references(repo, validated)
    return DeepAuthoringPreview(
        world_id=repo.world_id,
        title=normalized_title,
        changes=validated,
        risk=risk,
        source_ref=normalized_source,
    )


def write_deep_authoring_ticket(
    repo: WorldRepository,
    preview: DeepAuthoringPreview,
) -> TicketRecord:
    if preview.world_id != repo.world_id:
        raise ValueError("deep authoring preview belongs to another world")
    validated = validate_deep_authoring_references(repo, preview.changes)
    return create_pr_packet(
        repo,
        preview.title,
        validated,
        risk=preview.risk,
        source_ref=preview.source_ref,
    )


def _with_provenance(
    content: Mapping[str, Any],
    *,
    source_ref: str,
    authority: str,
    valid_from: str | None,
    valid_until: str | None,
) -> Dict[str, Any]:
    result = dict(content)
    existing = result.get("_wsa")
    metadata = dict(existing) if isinstance(existing, dict) else {}
    metadata.update(
        {
            "authority": authority,
            "source_ref": source_ref,
            "valid_from": valid_from,
            "valid_until": valid_until,
        }
    )
    result["_wsa"] = metadata
    return result


def _attribute_value_type(
    value_number: float | None,
    value_text: str | None,
    value_ref_id: str | None,
    value_json: Any,
) -> str:
    supplied = [
        value_number is not None,
        value_text is not None,
        value_ref_id is not None,
        value_json is not None,
    ]
    if sum(supplied) != 1:
        raise ValueError("temporal attribute requires exactly one typed value")
    if value_number is not None:
        return "number"
    if value_ref_id is not None:
        return "ref"
    if value_json is not None:
        return "json"
    if str(value_text).lower() in {"true", "false"}:
        return "boolean"
    return "text"
