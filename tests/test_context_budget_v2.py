from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.context import ContextAssembler, ContextRequest
from wsa.repositories import WorldRepository
from wsa.workspace import create_world


class ContextBudgetV2Tests(TestCase):
    def test_optional_token_budget_is_reported_and_enforced_deterministically(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Token World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Mina")
            for index in range(8):
                repo.create_fact(
                    actor.entity_id,
                    f"detail_{index}",
                    "long visible value " * 8,
                    status="canon",
                )

            packet = ContextAssembler(repo).assemble(
                ContextRequest(
                    actor=actor,
                    scene_id=None,
                    scene_goal="inspect details",
                    character_budget=20_000,
                    token_budget=80,
                )
            ).to_dict()

            receipt = packet["receipt"]
            self.assertEqual(receipt["token_budget"], 80)
            self.assertLessEqual(receipt["estimated_tokens_used"], 80)
            self.assertTrue(
                any(item["reason"] == "token_budget_exceeded" for item in receipt["excluded"])
            )
            self.assertEqual(
                packet["compression"]["policy"],
                "deterministic_character_and_token_budget_v1",
            )

    def test_goal_overlap_orders_equal_priority_facts_first(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Retrieval World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Mina")
            unrelated = repo.create_fact(
                actor.entity_id,
                "hobby",
                "painting",
                status="canon",
            )
            relevant = repo.create_fact(
                actor.entity_id,
                "harbor_signal",
                "red beacon",
                status="canon",
            )

            packet = ContextAssembler(repo).assemble(
                ContextRequest(
                    actor=actor,
                    scene_id=None,
                    scene_goal="investigate harbor signal",
                    character_budget=100_000,
                )
            ).to_dict()

            included = [
                item["item_id"]
                for item in packet["receipt"]["included"]
                if item["source"] == "facts"
            ]
            self.assertLess(included.index(relevant.fact_id), included.index(unrelated.fact_id))
