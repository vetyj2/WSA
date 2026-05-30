from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.context import ContextBuilder
from wsa.diagnostics import detect_explicit_fact_conflicts
from wsa.repositories import WorldRepository
from wsa.workspace import SCHEMA_VERSION, create_world


class ContextAndDiagnosticsTests(TestCase):
    def test_context_builder_includes_actor_facts_and_schema_version(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Context World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Sol")
            repo.create_fact(
                actor.entity_id,
                "has_goal",
                "escape",
                authority="canon",
                status="canon",
            )

            packet = ContextBuilder(repo).build_actor_context(
                actor,
                scene_id="scene_demo",
                scene_goal="reach exit",
            )

            self.assertEqual(packet["schema_version"], SCHEMA_VERSION)
            self.assertEqual(packet["actor"]["entity_id"], actor.entity_id)
            self.assertEqual(packet["facts"][0]["predicate"], "has_goal")

    def test_explicit_conflict_detection_logs_conflict(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Conflict World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ren")
            repo.create_fact(actor.entity_id, "location", "north", status="canon")
            repo.create_fact(actor.entity_id, "location", "south", status="proposed")

            findings = detect_explicit_fact_conflicts(repo)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].conflict_type, "explicit_contradiction")
            self.assertEqual(findings[0].predicate, "location")
