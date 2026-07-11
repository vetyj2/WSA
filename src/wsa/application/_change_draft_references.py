from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

from ..repositories import WorldRepository
from ._change_draft_contracts import (
    DRAFT_CHANGE_TYPES,
    DRAFT_TARGET_TYPES,
    AmbiguousEntityNameError,
    ChangeDraftError,
    EntityNameNotFoundError,
    _required,
)


@dataclass(frozen=True)
class _EntityTarget:
    entity_type: str
    entity_id: str | None = None
    change_ref: str | None = None


def resolve_change_references(
    repo: WorldRepository,
    changes: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    normalized = [deepcopy(dict(change)) for change in changes]
    existing_entities = repo.list_entities()
    existing_by_id = {item.entity_id: item for item in existing_entities}
    targets_by_name: Dict[str, List[_EntityTarget]] = {}
    targets_by_ref: Dict[str, _EntityTarget] = {}
    used_refs = {
        str(change.get("change_ref"))
        for change in normalized
        if change.get("change_ref")
    }

    for item in existing_entities:
        targets_by_name.setdefault(_name_key(item.display_name), []).append(
            _EntityTarget(item.entity_type, entity_id=item.entity_id)
        )

    generated_ref_index = 1
    for change in normalized:
        if change.get("change_type") != "add_entity":
            continue
        display_name = _required(change.get("display_name"), "entity display_name")
        entity_type = _required(change.get("entity_type"), "entity entity_type")
        change["display_name"] = display_name
        change["entity_type"] = entity_type
        change_ref = str(change.get("change_ref") or "").strip()
        if not change_ref:
            while f"draft_entity:{generated_ref_index}" in used_refs:
                generated_ref_index += 1
            change_ref = f"draft_entity:{generated_ref_index}"
            generated_ref_index += 1
            change["change_ref"] = change_ref
        if change_ref in targets_by_ref:
            raise ChangeDraftError(f"duplicate entity change_ref: {change_ref}")
        target = _EntityTarget(entity_type, change_ref=change_ref)
        targets_by_ref[change_ref] = target
        targets_by_name.setdefault(_name_key(display_name), []).append(target)

    for change in normalized:
        change_type = str(change.get("change_type") or "")
        if change_type not in DRAFT_CHANGE_TYPES:
            raise ChangeDraftError(f"unsupported draft change_type: {change_type}")
        change.setdefault("target_type", DRAFT_TARGET_TYPES[change_type])
        if change_type == "add_fact":
            _resolve_subject(
                change,
                repo.world_id,
                existing_by_id,
                targets_by_name,
                targets_by_ref,
            )
            _resolve_fact_object(
                change,
                repo.world_id,
                existing_by_id,
                targets_by_name,
                targets_by_ref,
            )
        elif change_type == "add_world_edge":
            subject = _resolve_subject(
                change,
                repo.world_id,
                existing_by_id,
                targets_by_name,
                targets_by_ref,
            )
            object_target = _resolve_edge_object(
                change,
                repo.world_id,
                existing_by_id,
                targets_by_name,
                targets_by_ref,
            )
            change.setdefault("subject_type", subject.entity_type)
            if object_target is not None:
                change.setdefault("object_type", object_target.entity_type)
            else:
                change.setdefault("object_type", "value")

    entities = [item for item in normalized if item["change_type"] == "add_entity"]
    others = [item for item in normalized if item["change_type"] != "add_entity"]
    return entities + others


def _resolve_subject(
    change: Dict[str, Any],
    world_id: str,
    existing_by_id: Mapping[str, Any],
    targets_by_name: Mapping[str, List[_EntityTarget]],
    targets_by_ref: Mapping[str, _EntityTarget],
) -> _EntityTarget:
    if change.get("subject_id") and change.get("subject_change_ref"):
        raise ChangeDraftError("change cannot have both subject_id and subject_change_ref")
    if change.get("subject_change_ref"):
        ref = str(change["subject_change_ref"])
        target = targets_by_ref.get(ref)
        if target is None:
            raise EntityNameNotFoundError(f"unknown subject_change_ref: {ref}")
        return target
    if change.get("subject_id"):
        return _target_for_explicit_id(
            str(change["subject_id"]),
            world_id,
            existing_by_id,
        )
    reference = _pop_first(
        change,
        "_draft_subject_name",
        "subject_name",
        "subject",
    )
    if reference is None:
        raise ChangeDraftError(
            f"{change.get('change_type')} requires a subject reference"
        )
    target = _resolve_entity_target(
        str(reference),
        world_id,
        existing_by_id,
        targets_by_name,
        targets_by_ref,
    )
    if target.change_ref:
        change["subject_change_ref"] = target.change_ref
    else:
        change["subject_id"] = target.entity_id
    return target


def _resolve_fact_object(
    change: Dict[str, Any],
    world_id: str,
    existing_by_id: Mapping[str, Any],
    targets_by_name: Mapping[str, List[_EntityTarget]],
    targets_by_ref: Mapping[str, _EntityTarget],
) -> None:
    if change.get("object_ref_id") and change.get("object_change_ref"):
        raise ChangeDraftError(
            "add_fact cannot have both object_ref_id and object_change_ref"
        )
    reference = _pop_first(change, "_draft_object_name", "object_name")
    if reference is None:
        if "object" in change and "object_value" not in change:
            change["object_value"] = change.pop("object")
        return
    target = _resolve_entity_target(
        str(reference),
        world_id,
        existing_by_id,
        targets_by_name,
        targets_by_ref,
    )
    if target.change_ref:
        change["object_change_ref"] = target.change_ref
    else:
        change["object_ref_id"] = target.entity_id


def _resolve_edge_object(
    change: Dict[str, Any],
    world_id: str,
    existing_by_id: Mapping[str, Any],
    targets_by_name: Mapping[str, List[_EntityTarget]],
    targets_by_ref: Mapping[str, _EntityTarget],
) -> _EntityTarget | None:
    if change.get("object_id") and change.get("object_change_ref"):
        raise ChangeDraftError(
            "add_world_edge cannot have both object_id and object_change_ref"
        )
    if change.get("object_change_ref"):
        ref = str(change["object_change_ref"])
        target = targets_by_ref.get(ref)
        if target is None:
            raise EntityNameNotFoundError(f"unknown object_change_ref: {ref}")
        return target
    if change.get("object_id"):
        return _target_for_explicit_id(
            str(change["object_id"]),
            world_id,
            existing_by_id,
        )
    reference = _pop_first(change, "_draft_object_name", "object_name", "object")
    if reference is None:
        if change.get("object_value") is None:
            raise ChangeDraftError("add_world_edge requires an object reference or value")
        return None
    target = _resolve_entity_target(
        str(reference),
        world_id,
        existing_by_id,
        targets_by_name,
        targets_by_ref,
    )
    if target.change_ref:
        change["object_change_ref"] = target.change_ref
    else:
        change["object_id"] = target.entity_id
    return target


def _resolve_entity_target(
    value: str,
    world_id: str,
    existing_by_id: Mapping[str, Any],
    targets_by_name: Mapping[str, List[_EntityTarget]],
    targets_by_ref: Mapping[str, _EntityTarget],
) -> _EntityTarget:
    reference = _required(value, "entity reference")
    if reference.startswith("id:"):
        return _target_for_explicit_id(reference[3:], world_id, existing_by_id)
    if reference.startswith("ref:"):
        ref = reference[4:]
        target = targets_by_ref.get(ref)
        if target is None:
            raise EntityNameNotFoundError(f"unknown entity change_ref: {ref}")
        return target
    if reference.startswith("name:"):
        reference = reference[5:]
    elif reference.startswith("@"):
        reference = reference[1:]
    if reference == world_id or reference.casefold() == "world":
        return _EntityTarget("world", entity_id=world_id)
    if reference in existing_by_id:
        item = existing_by_id[reference]
        return _EntityTarget(item.entity_type, entity_id=item.entity_id)
    if reference in targets_by_ref:
        return targets_by_ref[reference]
    matches = targets_by_name.get(_name_key(reference), [])
    if not matches:
        raise EntityNameNotFoundError(
            f"entity display name not found in world or draft: {reference}"
        )
    if len(matches) != 1:
        raise AmbiguousEntityNameError(
            f"ambiguous entity display name {reference!r}: {len(matches)} matches"
        )
    return matches[0]


def _target_for_explicit_id(
    entity_id: str,
    world_id: str,
    existing_by_id: Mapping[str, Any],
) -> _EntityTarget:
    value = _required(entity_id, "entity ID")
    if value == world_id:
        return _EntityTarget("world", entity_id=world_id)
    item = existing_by_id.get(value)
    if item is None:
        return _EntityTarget("entity", entity_id=value)
    return _EntityTarget(item.entity_type, entity_id=item.entity_id)


def _pop_first(change: Dict[str, Any], *keys: str) -> Any:
    present = [key for key in keys if key in change and change[key] is not None]
    if len(present) > 1:
        raise ChangeDraftError(
            f"change supplies duplicate reference fields: {', '.join(present)}"
        )
    if not present:
        return None
    return change.pop(present[0])


def _name_key(value: str) -> str:
    return " ".join(_required(value, "entity display name").split()).casefold()
