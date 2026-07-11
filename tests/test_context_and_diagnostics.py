from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.context import ContextBuilder
from wsa.diagnostics import (
    detect_explicit_fact_conflicts,
    find_temporal_attribute_conflicts,
)
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

    def test_hidden_fact_requires_viewpoint_knowledge(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Visibility World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Sol")
            secret = repo.create_fact(
                world.world_id,
                "sealed_truth",
                "the gate is false",
                authority="canon",
                status="canon",
                payload={"visibility": "hidden"},
            )

            hidden_packet = ContextBuilder(repo).build_actor_context(
                actor,
                scene_id="scene_hidden",
                scene_goal="inspect the gate",
            )
            self.assertEqual(hidden_packet["facts"], [])
            self.assertIn(
                "hidden_from_viewpoint",
                {item["reason"] for item in hidden_packet["receipt"]["excluded"]},
            )

            repo.add_knowledge_attribution(
                actor.entity_id,
                "fact",
                secret.fact_id,
                "known",
                authority="canon",
                status="canon",
            )
            known_packet = ContextBuilder(repo).build_actor_context(
                actor,
                scene_id="scene_known",
                scene_goal="inspect the gate",
            )

            self.assertEqual(known_packet["facts"][0]["fact_id"], secret.fact_id)

    def test_context_changes_with_time_location_and_memory(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Temporal Context World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ren")
            place = repo.create_entity("location", "Harbor")
            repo.set_entity_attribute_span(
                actor.entity_id,
                "condition",
                value_text="unhurt",
                valid_from="001",
                valid_until="002",
                authority="canon",
                status="canon",
            )
            repo.set_entity_attribute_span(
                actor.entity_id,
                "condition",
                value_text="injured",
                valid_from="002",
                authority="canon",
                status="canon",
            )
            repo.add_world_edge(
                "entity",
                actor.entity_id,
                "located_at",
                "entity",
                object_id=place.entity_id,
                valid_from="002",
                authority="canon",
                status="canon",
            )
            repo.create_actor_memory_packet(
                actor.entity_id,
                "001",
                {"summary": "arrived alone"},
            )
            repo.create_actor_memory_packet(
                actor.entity_id,
                "002",
                {"summary": "saw the signal"},
            )
            repo.create_fact(
                world.world_id,
                "weather",
                "rain",
                location_scope="harbor",
                authority="canon",
                status="canon",
            )

            before = ContextBuilder(repo).build_actor_context(
                actor,
                scene_id="scene_1",
                scene_goal="arrive",
                time_scope="001",
                location_scope="inland",
            )
            after = ContextBuilder(repo).build_actor_context(
                actor,
                scene_id="scene_2",
                scene_goal="respond",
                time_scope="002",
                location_scope="harbor",
            )

            self.assertEqual(before["temporal_attributes"][0]["value_text"], "unhurt")
            self.assertEqual(after["temporal_attributes"][0]["value_text"], "injured")
            self.assertEqual(before["relationships"], [])
            self.assertEqual(after["relationships"][0]["edge_type"], "located_at")
            self.assertEqual(len(before["memories"]), 1)
            self.assertEqual(len(after["memories"]), 2)
            self.assertEqual(before["facts"], [])
            self.assertEqual(after["facts"][0]["predicate"], "weather")

    def test_context_budget_receipt_reports_excluded_sources(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Budget World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Mira")
            repo.create_fact(
                actor.entity_id,
                "goal",
                "leave",
                authority="canon",
                status="canon",
            )
            repo.create_actor_profile(
                actor.entity_id,
                "voice",
                {"notes": "x" * 2_000},
            )

            packet = ContextBuilder(repo).build_actor_context(
                actor,
                scene_id="scene_budget",
                scene_goal="leave",
                character_budget=500,
            )

            self.assertEqual(packet["facts"][0]["predicate"], "goal")
            self.assertEqual(packet["actor_profiles"], [])
            self.assertTrue(packet["compression"]["overload_warning"])
            self.assertIn(
                "character_budget_exceeded",
                {item["reason"] for item in packet["receipt"]["excluded"]},
            )
            self.assertLessEqual(
                packet["receipt"]["characters_used"],
                packet["receipt"]["character_budget"],
            )

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

    def test_adjacent_temporal_spans_do_not_overlap(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Adjacent Temporal World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ren")
            repo.set_entity_attribute_span(
                actor.entity_id,
                "condition",
                value_text="well",
                valid_from="001",
                valid_until="002",
                status="canon",
            )
            repo.set_entity_attribute_span(
                actor.entity_id,
                "condition",
                value_text="injured",
                valid_from="002",
                status="canon",
            )

            self.assertEqual(find_temporal_attribute_conflicts(repo), [])
