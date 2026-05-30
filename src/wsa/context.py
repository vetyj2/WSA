from __future__ import annotations

from typing import Any, Dict

from .repositories import EntityRecord, WorldRepository
from .workspace import SCHEMA_VERSION


class ContextBuilder:
    def __init__(self, repo: WorldRepository) -> None:
        self.repo = repo

    def build_actor_context(
        self,
        actor: EntityRecord,
        scene_id: str | None,
        scene_goal: str,
    ) -> Dict[str, Any]:
        facts = self.repo.list_facts(actor.entity_id)
        packet = {
            "schema_version": SCHEMA_VERSION,
            "world_id": self.repo.world_id,
            "scene_id": scene_id,
            "actor": {
                "entity_id": actor.entity_id,
                "display_name": actor.display_name,
                "entity_type": actor.entity_type,
                "payload": actor.payload,
            },
            "scene": {
                "goal": scene_goal,
            },
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "subject_id": fact.subject_id,
                    "predicate": fact.predicate,
                    "object_value": fact.object_value,
                    "authority": fact.authority,
                    "status": fact.status,
                    "confidence": fact.confidence,
                    "payload": fact.payload,
                }
                for fact in facts
            ],
            "compression": {
                "priority": [
                    "high_authority_canon",
                    "current_scene_essentials",
                    "actor_long_term_memory",
                    "relationships_and_goals",
                    "semantic_search_results",
                    "style_references",
                ],
                "overload_warning": False,
            },
        }
        self.repo.create_context_packet(
            "actor_context",
            packet,
            scene_id=scene_id,
            actor_entity_id=actor.entity_id,
        )
        return packet
