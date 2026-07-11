from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from ..repositories import WorldRepository
from ..workspace import WorldRecord


class WorldInspectionService:
    def __init__(self, world: WorldRecord) -> None:
        self.world = world
        self.repo = WorldRepository(world.world_id, world.path)

    def summary(self) -> Dict[str, Any]:
        entities = self.repo.list_entities()
        facts = self.repo.list_facts()
        edges = self.repo.query_world_edges()
        dimensions = self.repo.list_dimension_definitions()
        timeline = self.repo.list_timeline_points()
        return {
            "schema": "wsa.world.summary.v1",
            "world": {
                "world_id": self.world.world_id,
                "display_name": self.world.display_name,
                "status": self.world.status,
                "schema_version": self.world.schema_version,
            },
            "counts": {
                "entities": len(entities),
                "facts": len(facts),
                "world_edges": len(edges),
                "dimensions": len(dimensions),
                "timeline_points": len(timeline),
            },
            "side_effect_status": "read_only_no_world_mutation",
        }

    def entities(
        self,
        entity_type: str | None = None,
        status: str | None = None,
    ) -> Dict[str, Any]:
        return _collection(
            "wsa.world.entities.v1",
            self.world.world_id,
            [asdict(item) for item in self.repo.list_entities(entity_type, status)],
        )

    def entity(self, entity_id: str) -> Dict[str, Any]:
        return _item(
            "wsa.world.entity.v1",
            self.world.world_id,
            asdict(self.repo.get_entity(entity_id)),
        )

    def facts(self, subject_id: str | None = None) -> Dict[str, Any]:
        return _collection(
            "wsa.world.facts.v1",
            self.world.world_id,
            [asdict(item) for item in self.repo.list_facts(subject_id)],
        )

    def fact(self, fact_id: str) -> Dict[str, Any]:
        return _item(
            "wsa.world.fact.v1",
            self.world.world_id,
            asdict(self.repo.get_fact(fact_id)),
        )

    def edges(
        self,
        subject_id: str | None = None,
        edge_type: str | None = None,
        status: str | None = None,
    ) -> Dict[str, Any]:
        return _collection(
            "wsa.world.edges.v1",
            self.world.world_id,
            [
                asdict(item)
                for item in self.repo.query_world_edges(
                    subject_id=subject_id,
                    edge_type=edge_type,
                    status=status,
                )
            ],
        )

    def timeline(self) -> Dict[str, Any]:
        return _collection(
            "wsa.world.timeline.v1",
            self.world.world_id,
            [asdict(item) for item in self.repo.list_timeline_points()],
        )

    def actor_authoring(self, entity_id: str) -> Dict[str, Any]:
        entity = asdict(self.repo.get_entity(entity_id))
        return {
            "schema": "wsa.world.actor_authoring.v1",
            "world_id": self.world.world_id,
            "actor": entity,
            "profiles": [
                asdict(item) for item in self.repo.list_actor_profiles(entity_id)
            ],
            "temporal_attributes": [
                asdict(item)
                for item in self.repo.query_entity_attribute_spans(entity_id)
            ],
            "knowledge_attributions": [
                asdict(item)
                for item in self.repo.query_knowledge_attributions(entity_id)
            ],
            "memories": [
                asdict(item)
                for item in self.repo.list_actor_memory_packets(entity_id)
            ],
            "side_effect_status": "read_only_no_world_mutation",
        }

    def export_data(self) -> Dict[str, Any]:
        entities = [asdict(item) for item in self.repo.list_entities()]
        entity_ids = [item["entity_id"] for item in entities]
        edges = [asdict(item) for item in self.repo.query_world_edges()]
        spans = [asdict(item) for item in self.repo.query_entity_attribute_spans()]
        knowledge = [asdict(item) for item in self.repo.query_knowledge_attributions()]
        return {
            "schema": "wsa.world.portable_export.v1",
            "world": self.summary()["world"],
            "entities": entities,
            "facts": [asdict(item) for item in self.repo.list_facts()],
            "world_edges": edges,
            "timeline_points": [
                asdict(item) for item in self.repo.list_timeline_points()
            ],
            "dimension_definitions": [
                asdict(item) for item in self.repo.list_dimension_definitions()
            ],
            "entity_attribute_spans": spans,
            "actor_profiles": [
                asdict(profile)
                for entity_id in entity_ids
                for profile in self.repo.list_actor_profiles(entity_id)
            ],
            "actor_memory_packets": [
                asdict(memory)
                for entity_id in entity_ids
                for memory in self.repo.list_actor_memory_packets(entity_id)
            ],
            "knowledge_attributions": knowledge,
            "selection_policy": "portable_world_data_no_runtime_state",
            "excluded": [
                "runtime_messages",
                "callbacks",
                "private_hermes_overlay",
                "report_html",
            ],
            "side_effect_status": "read_only_no_world_mutation",
        }


def _collection(schema: str, world_id: str, items: list[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schema": schema,
        "world_id": world_id,
        "count": len(items),
        "items": items,
        "side_effect_status": "read_only_no_world_mutation",
    }


def _item(schema: str, world_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": schema,
        "world_id": world_id,
        "item": item,
        "side_effect_status": "read_only_no_world_mutation",
    }
