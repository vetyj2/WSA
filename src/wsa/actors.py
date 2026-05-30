from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .repositories import EntityRecord


@dataclass(frozen=True)
class MockActorResponse:
    actor_id: str
    response_type: str
    payload: Dict[str, Any]


class MockActorRuntime:
    """Deterministic actor runtime used before Hermes integration."""

    def propose(self, actor: EntityRecord, scene_goal: str) -> MockActorResponse:
        return MockActorResponse(
            actor_id=actor.entity_id,
            response_type="action_proposal",
            payload={
                "actor_id": actor.entity_id,
                "actor_name": actor.display_name,
                "action": f"{actor.display_name} acknowledges the scene goal.",
                "dialogue": f"{actor.display_name}: Understood.",
                "scene_goal": scene_goal,
            },
        )
