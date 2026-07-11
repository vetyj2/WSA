from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List

from ..repositories import TicketRecord, WorldRepository
from ..startup import StartupProfileManager
from ..tickets import (
    create_pr_packet,
    materialize_candidate_ticket,
    validate_change_payloads,
)
from ..workspace import WorldRecord


@dataclass(frozen=True)
class ProposalPreview:
    proposal_type: str
    world_id: str
    title: str
    changes: List[Dict[str, Any]]
    source_ref: str
    provenance: str
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "wsa.proposal.preview.v1",
            "proposal_type": self.proposal_type,
            "world_id": self.world_id,
            "title": self.title,
            "changes": self.changes,
            "change_count": len(self.changes),
            "source_ref": self.source_ref,
            "provenance": self.provenance,
            "warnings": self.warnings,
            "side_effect_status": "read_only_preview_no_world_mutation",
        }


def startup_proposal_preview(world: WorldRecord) -> ProposalPreview:
    manager = StartupProfileManager(world)
    summary = manager.summary()
    changes: List[Dict[str, Any]] = []
    for answer in summary["explicit_world_assertions"]:
        provenance = dict(answer.get("provenance") or {})
        source = dict(answer.get("source") or {})
        changes.append(
            {
                "change_type": "add_fact",
                "target_type": "fact",
                "subject_id": world.world_id,
                "predicate": f"startup.{answer['dimension']}",
                "object_value": str(answer["semantic_value"]),
                "authority": str(provenance.get("authority") or "user_explicit"),
                "status": "canon",
                "confidence": 1.0,
                "source_ref": str(
                    source.get("source_ref") or "startup/startup_profile.json"
                ),
                "payload": {
                    "question_id": answer["question_id"],
                    "answer_role": answer["answer_role"],
                    "answer_text": answer["answer"],
                    "choice_code": answer.get("choice_code"),
                    "choice_label": answer.get("choice_label"),
                    "semantic_value": answer["semantic_value"],
                    "source": source,
                    "provenance": provenance,
                    "question_pack_id": summary.get("question_pack_id"),
                    "defaults_revision": summary.get("defaults_revision"),
                    "startup_answer_status": answer["status"],
                    "legacy_preserved": answer.get("legacy_preserved", False),
                },
            }
        )
    warnings = []
    if summary["unresolved_blockers"]:
        warnings.append(
            "startup has "
            f"{len(summary['unresolved_blockers'])} unresolved minimum-frame blockers"
        )
    if not changes:
        warnings.append("startup has no explicit world assertions to materialize")
    return ProposalPreview(
        proposal_type="startup_explicit_world_assertions",
        world_id=world.world_id,
        title=f"Startup world assertions for {world.display_name}",
        changes=changes,
        source_ref="startup/startup_profile.json",
        provenance="startup_profile_explicit_world_assertions",
        warnings=warnings,
    )


def entity_proposal_preview(
    world: WorldRecord,
    display_name: str,
    entity_type: str,
) -> ProposalPreview:
    name = display_name.strip()
    kind = entity_type.strip()
    if not name or not kind:
        raise ValueError("entity name and type are required")
    return ProposalPreview(
        proposal_type="user_direct_entity",
        world_id=world.world_id,
        title=f"Add {kind}: {name}",
        changes=[
            {
                "change_type": "add_entity",
                "target_type": "entity",
                "entity_type": kind,
                "display_name": name,
                "status": "active",
                "payload": {"provenance": "user_explicit"},
            }
        ],
        source_ref="user_cli",
        provenance="user_explicit",
        warnings=[],
    )


def fact_proposal_preview(
    world: WorldRecord,
    subject_id: str,
    predicate: str,
    object_value: str | None,
    object_ref_id: str | None = None,
    time_scope: str | None = None,
    location_scope: str | None = None,
) -> ProposalPreview:
    if not subject_id.strip() or not predicate.strip():
        raise ValueError("fact subject_id and predicate are required")
    if object_value is None and object_ref_id is None:
        raise ValueError("fact requires object_value or object_ref_id")
    return ProposalPreview(
        proposal_type="user_direct_fact",
        world_id=world.world_id,
        title=f"Add fact: {predicate.strip()}",
        changes=[
            {
                "change_type": "add_fact",
                "target_type": "fact",
                "subject_id": subject_id.strip(),
                "predicate": predicate.strip(),
                "object_value": object_value,
                "object_ref_id": object_ref_id,
                "time_scope": time_scope,
                "location_scope": location_scope,
                "authority": "user_explicit",
                "status": "canon",
                "confidence": 1.0,
                "source_ref": "user_cli",
                "payload": {"provenance": "user_explicit"},
            }
        ],
        source_ref="user_cli",
        provenance="user_explicit",
        warnings=[],
    )


def edge_proposal_preview(
    world: WorldRecord,
    subject_type: str,
    subject_id: str,
    edge_type: str,
    object_type: str,
    object_id: str | None = None,
    object_value: str | None = None,
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> ProposalPreview:
    required = (subject_type, subject_id, edge_type, object_type)
    if any(not value.strip() for value in required):
        raise ValueError("edge subject/object types, subject_id, and edge_type are required")
    if object_id is None and object_value is None:
        raise ValueError("edge requires object_id or object_value")
    return ProposalPreview(
        proposal_type="user_direct_edge",
        world_id=world.world_id,
        title=f"Add edge: {edge_type.strip()}",
        changes=[
            {
                "change_type": "add_world_edge",
                "target_type": "world_edge",
                "subject_type": subject_type.strip(),
                "subject_id": subject_id.strip(),
                "edge_type": edge_type.strip(),
                "object_type": object_type.strip(),
                "object_id": object_id,
                "object_value": object_value,
                "valid_from": valid_from,
                "valid_until": valid_until,
                "authority": "user_explicit",
                "status": "canon",
                "confidence": 1.0,
                "payload": {"provenance": "user_explicit"},
            }
        ],
        source_ref="user_cli",
        provenance="user_explicit",
        warnings=[],
    )


def portable_import_preview(
    world: WorldRecord,
    payload: Dict[str, Any],
) -> ProposalPreview:
    if payload.get("schema") != "wsa.world.portable_export.v1":
        raise ValueError("unsupported portable world export schema")
    source_world = dict(payload.get("world") or {})
    source_world_id = str(source_world.get("world_id") or "")
    source_entities = _portable_records(payload, "entities")
    source_facts = _portable_records(payload, "facts")
    source_edges = _portable_records(payload, "world_edges")
    source_timeline = _portable_records(payload, "timeline_points")
    source_dimensions = _portable_records(payload, "dimension_definitions")
    source_spans = _portable_records(payload, "entity_attribute_spans")
    source_profiles = _portable_records(payload, "actor_profiles")
    source_memories = _portable_records(payload, "actor_memory_packets")
    source_knowledge = _portable_records(payload, "knowledge_attributions")
    collection_ids = (
        (source_entities, "entity_id", "entities"),
        (source_facts, "fact_id", "facts"),
        (source_edges, "edge_id", "world_edges"),
        (source_timeline, "timeline_point_id", "timeline_points"),
        (source_dimensions, "dimension_id", "dimension_definitions"),
        (source_spans, "attribute_span_id", "entity_attribute_spans"),
        (source_profiles, "actor_profile_id", "actor_profiles"),
        (source_memories, "memory_packet_id", "actor_memory_packets"),
        (source_knowledge, "knowledge_id", "knowledge_attributions"),
    )
    for records, id_key, collection_name in collection_ids:
        _require_unique_portable_ids(records, id_key, collection_name)
    dimensions_by_key = _portable_index(
        source_dimensions,
        "dimension_key",
        "dimension_definitions",
    )
    source_entity_ids = {str(item["entity_id"]) for item in source_entities}
    changes: List[Dict[str, Any]] = []
    for item in source_entities:
        source_id = str(item["entity_id"])
        changes.append(
            {
                "change_type": "add_entity",
                "target_type": "entity",
                "portable_id": source_id,
                "change_ref": f"entity:{source_id}",
                "entity_type": str(item.get("entity_type") or "entity"),
                "display_name": str(item.get("display_name") or source_id),
                "status": str(item.get("status") or "active"),
                "payload": _portable_payload(
                    item.get("payload"),
                    "entity",
                    source_id,
                    source_key="source_entity_id",
                ),
            }
        )
    for item in source_facts:
        source_id = str(item["fact_id"])
        source_subject = str(item.get("subject_id") or "")
        change: Dict[str, Any] = {
            "change_type": "add_fact",
            "target_type": "fact",
            "portable_id": source_id,
            "change_ref": f"fact:{source_id}",
            "predicate": str(item.get("predicate") or ""),
            "object_value": item.get("object_value"),
            "time_scope": item.get("time_scope"),
            "location_scope": item.get("location_scope"),
            "authority": str(item.get("authority") or "imported"),
            "status": str(item.get("status") or "proposed"),
            "confidence": float(item.get("confidence", 1.0)),
            "source_ref": str(item.get("source_ref") or "portable_import"),
            "tags": list(item.get("tags") or []),
            "payload": _portable_payload(
                item.get("payload"),
                "fact",
                source_id,
                source_key="source_fact_id",
            ),
        }
        if source_subject in source_entity_ids:
            change["subject_change_ref"] = f"entity:{source_subject}"
        else:
            change["subject_id"] = (
                world.world_id if source_subject == source_world_id else source_subject
            )
        object_ref_id = item.get("object_ref_id")
        if object_ref_id in source_entity_ids:
            change["object_change_ref"] = f"entity:{object_ref_id}"
        elif object_ref_id:
            change["object_ref_id"] = object_ref_id
        changes.append(change)
    for item in source_edges:
        source_id = str(item["edge_id"])
        source_subject = str(item.get("subject_id") or "")
        change = {
            "change_type": "add_world_edge",
            "target_type": "world_edge",
            "portable_id": source_id,
            "change_ref": f"world_edge:{source_id}",
            "subject_type": str(item.get("subject_type") or "entity"),
            "edge_type": str(item.get("edge_type") or "related_to"),
            "object_type": str(item.get("object_type") or "entity"),
            "object_value": item.get("object_value"),
            "valid_from": item.get("valid_from"),
            "valid_until": item.get("valid_until"),
            "authority": str(item.get("authority") or "imported"),
            "status": str(item.get("status") or "proposed"),
            "confidence": float(item.get("confidence", 1.0)),
            "stability_level": int(item.get("stability_level", 2)),
            "revision_cost_level": int(item.get("revision_cost_level", 2)),
            "source_event_id": item.get("source_event_id"),
            "payload": _portable_payload(
                item.get("payload"),
                "world_edge",
                source_id,
                source_key="source_edge_id",
            ),
        }
        if source_subject in source_entity_ids:
            change["subject_change_ref"] = f"entity:{source_subject}"
        else:
            change["subject_id"] = (
                world.world_id if source_subject == source_world_id else source_subject
            )
        object_id = item.get("object_id")
        if object_id in source_entity_ids:
            change["object_change_ref"] = f"entity:{object_id}"
        elif object_id:
            change["object_id"] = object_id
        changes.append(change)
    for item in source_timeline:
        source_id = str(item["timeline_point_id"])
        changes.append(
            {
                "change_type": "add_timeline_point",
                "target_type": "timeline_point",
                "portable_id": source_id,
                "change_ref": f"timeline_point:{source_id}",
                "label": str(item.get("label") or "Imported timeline point"),
                "sort_key": str(item.get("sort_key") or ""),
                "payload": _portable_payload(
                    item.get("payload"),
                    "timeline_point",
                    source_id,
                    source_key="source_timeline_point_id",
                ),
            }
        )
    for item in source_profiles:
        source_id = str(item["actor_profile_id"])
        metadata = _portable_metadata(item.get("payload"), "actor_profiles")
        changes.append(
            {
                "change_type": "add_actor_profile",
                "target_type": "actor_profile",
                "portable_id": source_id,
                "change_ref": f"actor_profile:{source_id}",
                "entity_id": str(item.get("entity_id") or ""),
                "fragment_type": str(item.get("fragment_type") or ""),
                "status": str(item.get("status") or "active"),
                "authority": str(metadata.get("authority") or "imported"),
                "source_ref": str(metadata.get("source_ref") or "portable_import"),
                "valid_from": metadata.get("valid_from"),
                "valid_until": metadata.get("valid_until"),
                "payload": _portable_payload(
                    item.get("payload"),
                    "actor_profile",
                    source_id,
                    mark_provenance=False,
                ),
            }
        )
    for item in source_spans:
        source_id = str(item["attribute_span_id"])
        dimension_key = str(item.get("dimension_key") or "")
        dimension = dimensions_by_key.get(dimension_key)
        if dimension is None:
            raise ValueError(
                f"entity_attribute_spans references missing dimension: {dimension_key}"
            )
        metadata = _portable_metadata(item.get("payload"), "entity_attribute_spans")
        dimension_id = str(dimension["dimension_id"])
        changes.append(
            {
                "change_type": "add_entity_attribute_span",
                "target_type": "entity_attribute_span",
                "portable_id": source_id,
                "change_ref": f"entity_attribute_span:{source_id}",
                "entity_id": str(item.get("entity_id") or ""),
                "dimension_key": dimension_key,
                "dimension": {
                    "portable_id": dimension_id,
                    "display_name": str(dimension.get("display_name") or ""),
                    "dimension_type": str(dimension.get("dimension_type") or ""),
                    "value_type": str(dimension.get("value_type") or ""),
                    "applies_to": str(dimension.get("applies_to") or ""),
                    "temporal": bool(dimension.get("temporal")),
                    "missing_policy": str(dimension.get("missing_policy") or ""),
                    "authority": str(dimension.get("authority") or "imported"),
                    "status": str(dimension.get("status") or "proposed"),
                    "payload": _portable_payload(
                        dimension.get("payload"),
                        "dimension_definition",
                        dimension_id,
                        mark_provenance=False,
                    ),
                },
                "value_number": item.get("value_number"),
                "value_text": item.get("value_text"),
                "value_ref_id": item.get("value_ref_id"),
                "value_json": item.get("value_json"),
                "valid_from": item.get("valid_from"),
                "valid_until": item.get("valid_until"),
                "source_event_id": item.get("source_event_id"),
                "authority": str(item.get("authority") or "imported"),
                "status": str(item.get("status") or "proposed"),
                "confidence": float(item.get("confidence", 1.0)),
                "stability_level": int(item.get("stability_level", 2)),
                "revision_cost_level": int(item.get("revision_cost_level", 2)),
                "source_ref": str(metadata.get("source_ref") or "portable_import"),
                "payload": _portable_payload(
                    item.get("payload"),
                    "entity_attribute_span",
                    source_id,
                    mark_provenance=False,
                ),
            }
        )
    for item in source_memories:
        source_id = str(item["memory_packet_id"])
        metadata = _portable_metadata(item.get("payload"), "actor_memory_packets")
        changes.append(
            {
                "change_type": "add_actor_memory_packet",
                "target_type": "actor_memory_packet",
                "portable_id": source_id,
                "change_ref": f"actor_memory_packet:{source_id}",
                "entity_id": str(item.get("entity_id") or ""),
                "time_scope": str(item.get("time_scope") or ""),
                "status": str(item.get("status") or "active"),
                "authority": str(metadata.get("authority") or "imported"),
                "source_ref": str(metadata.get("source_ref") or "portable_import"),
                "valid_until": metadata.get("valid_until"),
                "payload": _portable_payload(
                    item.get("payload"),
                    "actor_memory_packet",
                    source_id,
                    mark_provenance=False,
                ),
            }
        )
    for item in source_knowledge:
        source_id = str(item["knowledge_id"])
        metadata = _portable_metadata(item.get("payload"), "knowledge_attributions")
        changes.append(
            {
                "change_type": "add_knowledge_attribution",
                "target_type": "knowledge_attribution",
                "portable_id": source_id,
                "change_ref": f"knowledge_attribution:{source_id}",
                "actor_entity_id": str(item.get("actor_entity_id") or ""),
                "knowledge_target_type": str(
                    item.get("target_type")
                    or item.get("knowledge_target_type")
                    or ""
                ),
                "knowledge_target_id": str(
                    item.get("target_id")
                    or item.get("knowledge_target_id")
                    or ""
                ),
                "knowledge_state": str(item.get("knowledge_state") or ""),
                "acquired_at": item.get("acquired_at"),
                "acquired_event_id": item.get("acquired_event_id"),
                "source_entity_id": item.get("source_entity_id"),
                "valid_until": item.get("valid_until"),
                "authority": str(item.get("authority") or "imported"),
                "status": str(item.get("status") or "proposed"),
                "confidence": float(item.get("confidence", 1.0)),
                "source_ref": str(metadata.get("source_ref") or "portable_import"),
                "payload": _portable_payload(
                    item.get("payload"),
                    "knowledge_attribution",
                    source_id,
                    mark_provenance=False,
                ),
            }
        )
    warnings = [
        "import is proposal-only until the generated ticket is explicitly applied",
        "review destination conflicts and duplicate meanings before apply",
    ]
    if not changes:
        warnings.append("portable export contains no supported world records")
    return ProposalPreview(
        proposal_type="portable_world_import",
        world_id=world.world_id,
        title=f"Import portable world data into {world.display_name}",
        changes=changes,
        source_ref="portable_export_json",
        provenance="portable_import",
        warnings=warnings,
    )


def _portable_records(payload: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"portable export {key} must be an array")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"portable export {key} entries must be objects")
    return [dict(item) for item in value]


def _require_unique_portable_ids(
    records: List[Dict[str, Any]],
    id_key: str,
    collection_name: str,
) -> None:
    seen: set[str] = set()
    for item in records:
        value = item.get(id_key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"portable export {collection_name} requires {id_key}")
        normalized = value.strip()
        item[id_key] = normalized
        if normalized in seen:
            raise ValueError(
                f"portable export {collection_name} contains duplicate {id_key}: "
                f"{normalized}"
            )
        seen.add(normalized)


def _portable_index(
    records: List[Dict[str, Any]],
    key: str,
    collection_name: str,
) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for item in records:
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"portable export {collection_name} requires {key}")
        normalized = value.strip()
        if normalized in result:
            raise ValueError(
                f"portable export {collection_name} contains duplicate {key}: "
                f"{normalized}"
            )
        result[normalized] = item
    return result


def _portable_payload(
    value: Any,
    record_type: str,
    source_id: str,
    *,
    source_key: str | None = None,
    mark_provenance: bool = True,
) -> Dict[str, Any]:
    if value is None:
        body: Dict[str, Any] = {}
    elif isinstance(value, dict):
        body = deepcopy(value)
    else:
        raise ValueError(f"portable export {record_type} payload must be an object")
    existing = body.get("_wsa")
    metadata = deepcopy(existing) if isinstance(existing, dict) else {}
    metadata["portable_import"] = {
        "source_record_type": record_type,
        "source_id": source_id,
    }
    body["_wsa"] = metadata
    if mark_provenance:
        body.setdefault("provenance", "portable_import")
    if source_key is not None:
        body[source_key] = source_id
    return body


def _portable_metadata(value: Any, collection_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"portable export {collection_name} payload must be an object")
    metadata = value.get("_wsa")
    return dict(metadata) if isinstance(metadata, dict) else {}


def write_proposal_ticket(
    repo: WorldRepository,
    preview: ProposalPreview,
) -> TicketRecord:
    if not preview.changes:
        raise ValueError("proposal preview has no concrete changes")
    return create_pr_packet(
        repo,
        preview.title,
        preview.changes,
        risk="low",
        compact=len(preview.changes) <= 3,
        source_ref=preview.source_ref,
    )


def candidate_materialization_preview(
    repo: WorldRepository,
    candidate_ticket_id: str,
    changes: List[Dict[str, Any]],
) -> ProposalPreview:
    candidate = repo.get_ticket(candidate_ticket_id)
    if candidate.ticket_type not in {"meeting_candidate", "orchestrator_candidate"}:
        raise ValueError(f"ticket is not a candidate container: {candidate_ticket_id}")
    if candidate.status != "proposed":
        raise ValueError(
            f"candidate ticket cannot be materialized from status {candidate.status}"
        )
    validated = validate_change_payloads(changes)
    return ProposalPreview(
        proposal_type="candidate_materialization",
        world_id=repo.world_id,
        title=f"Materialized changes from {candidate.title}",
        changes=validated,
        source_ref=f"ticket:{candidate_ticket_id}",
        provenance="author_reviewed_candidate",
        warnings=["review each concrete change before ticket apply"],
    )


def write_materialized_candidate_ticket(
    repo: WorldRepository,
    candidate_ticket_id: str,
    preview: ProposalPreview,
) -> TicketRecord:
    return materialize_candidate_ticket(
        repo,
        candidate_ticket_id,
        preview.title,
        preview.changes,
        source_ref=preview.source_ref,
    )
