from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable

from ..workspace import WorldRecord
from .world_service import WorldInspectionService


class WorldForkService:
    """Build portable, read-only selections for an explicit world fork plan."""

    def __init__(self, world: WorldRecord) -> None:
        self.world = world

    def selective_export(
        self,
        entity_ids: Iterable[str] = (),
        *,
        include_timeline: bool = False,
    ) -> Dict[str, Any]:
        portable = WorldInspectionService(self.world).export_data()
        requested = _unique(entity_ids)
        if not requested:
            payload = deepcopy(portable)
            payload["selection"] = {
                "mode": "full_world",
                "requested_entity_ids": [],
                "selected_entity_ids": [
                    item["entity_id"] for item in payload["entities"]
                ],
                "auto_included_dependency_ids": [],
                "timeline_included": True,
            }
            return payload

        entities = {item["entity_id"]: item for item in portable["entities"]}
        missing = [entity_id for entity_id in requested if entity_id not in entities]
        if missing:
            raise KeyError("unknown entity selection: " + ", ".join(missing))

        selected = set(requested)
        changed = True
        while changed:
            changed = False
            for fact in portable["facts"]:
                if fact.get("subject_id") not in selected:
                    continue
                target_id = fact.get("object_ref_id")
                if target_id in entities and target_id not in selected:
                    selected.add(target_id)
                    changed = True
            for edge in portable["world_edges"]:
                if edge.get("subject_id") not in selected:
                    continue
                target_id = edge.get("object_id")
                if target_id in entities and target_id not in selected:
                    selected.add(target_id)
                    changed = True
            for span in portable["entity_attribute_spans"]:
                if span.get("entity_id") not in selected:
                    continue
                target_id = span.get("value_ref_id")
                if target_id in entities and target_id not in selected:
                    selected.add(target_id)
                    changed = True

        selected_entities = [
            deepcopy(item)
            for item in portable["entities"]
            if item["entity_id"] in selected
        ]
        selected_facts = [
            deepcopy(item)
            for item in portable["facts"]
            if (
                item.get("subject_id") in selected
                or item.get("subject_id") == self.world.world_id
            )
            and (
                item.get("object_ref_id") is None
                or item.get("object_ref_id") in selected
            )
        ]
        selected_edges = [
            deepcopy(item)
            for item in portable["world_edges"]
            if (
                item.get("subject_id") in selected
                or item.get("subject_id") == self.world.world_id
            )
            and (
                item.get("object_id") is None
                or item.get("object_id") in selected
            )
        ]
        selected_profiles = [
            deepcopy(item)
            for item in portable["actor_profiles"]
            if item.get("entity_id") in selected
        ]
        selected_spans = [
            deepcopy(item)
            for item in portable["entity_attribute_spans"]
            if item.get("entity_id") in selected
            and (
                item.get("value_ref_id") is None
                or item.get("value_ref_id") in selected
            )
        ]
        selected_memories = [
            deepcopy(item)
            for item in portable["actor_memory_packets"]
            if item.get("entity_id") in selected
        ]
        selected_timeline = (
            deepcopy(portable["timeline_points"]) if include_timeline else []
        )
        used_dimension_keys = {
            str(item["dimension_key"])
            for item in selected_spans
            if item.get("dimension_key")
        }
        selected_dimensions = [
            deepcopy(item)
            for item in portable["dimension_definitions"]
            if item.get("dimension_key") in used_dimension_keys
        ]
        target_ids = {
            "entity": {item["entity_id"] for item in selected_entities},
            "fact": {item["fact_id"] for item in selected_facts},
            "world_edge": {item["edge_id"] for item in selected_edges},
            "edge": {item["edge_id"] for item in selected_edges},
            "entity_attribute_span": {
                item["attribute_span_id"] for item in selected_spans
            },
            "actor_profile": {
                item["actor_profile_id"] for item in selected_profiles
            },
            "actor_memory_packet": {
                item["memory_packet_id"] for item in selected_memories
            },
            "timeline_point": {
                item["timeline_point_id"] for item in selected_timeline
            },
        }
        selected_knowledge = [
            deepcopy(item)
            for item in portable["knowledge_attributions"]
            if item.get("actor_entity_id") in selected
            and item.get("target_id")
            in target_ids.get(str(item.get("target_type") or ""), set())
            and (
                item.get("source_entity_id") is None
                or item.get("source_entity_id") in selected
            )
        ]
        payload = {
            **deepcopy(portable),
            "schema": "wsa.world.portable_export.v1",
            "export_profile": "selective_entities_v1",
            "entities": selected_entities,
            "facts": selected_facts,
            "world_edges": selected_edges,
            "timeline_points": selected_timeline,
            "dimension_definitions": selected_dimensions,
            "entity_attribute_spans": selected_spans,
            "actor_profiles": selected_profiles,
            "actor_memory_packets": selected_memories,
            "knowledge_attributions": selected_knowledge,
            "selection_policy": (
                "explicit_entities_plus_outgoing_reference_dependencies_"
                "no_runtime_state"
            ),
            "selection": {
                "mode": "selected_entities",
                "requested_entity_ids": requested,
                "selected_entity_ids": [
                    item["entity_id"] for item in selected_entities
                ],
                "auto_included_dependency_ids": [
                    item["entity_id"]
                    for item in selected_entities
                    if item["entity_id"] not in requested
                ],
                "timeline_included": bool(include_timeline),
            },
        }
        return payload

    def fork_plan(
        self,
        target_display_name: str,
        entity_ids: Iterable[str] = (),
        *,
        include_timeline: bool = False,
    ) -> Dict[str, Any]:
        name = target_display_name.strip()
        if not name:
            raise ValueError("fork target display name is required")
        export = self.selective_export(
            entity_ids,
            include_timeline=include_timeline,
        )
        return {
            "schema": "wsa.world.fork_plan.v1",
            "source_world_id": self.world.world_id,
            "target_display_name": name,
            "selection": deepcopy(export["selection"]),
            "counts": {
                "entities": len(export["entities"]),
                "facts": len(export["facts"]),
                "world_edges": len(export["world_edges"]),
                "timeline_points": len(export["timeline_points"]),
                "dimension_definitions": len(export["dimension_definitions"]),
                "entity_attribute_spans": len(export["entity_attribute_spans"]),
                "actor_profiles": len(export["actor_profiles"]),
                "actor_memory_packets": len(export["actor_memory_packets"]),
                "knowledge_attributions": len(export["knowledge_attributions"]),
            },
            "portable_export": export,
            "excluded": list(export["excluded"]),
            "execution": "not_performed_plan_only",
            "next_actions": [
                f"wsa world create {name!r}",
                "save portable_export as JSON only for expert/automation import",
                "wsa world import-preview NEW_WORLD_ID EXPORT.json --write-ticket",
                "wsa ticket review NEW_WORLD_ID TICKET_ID",
                "wsa ticket apply NEW_WORLD_ID TICKET_ID",
            ],
            "side_effect_status": "read_only_no_world_or_workspace_mutation",
        }


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result
