from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.artifact_map import write_artifact_architecture_map
from wsa.manager import WorldManager
from wsa.orchestrator import SceneOrchestrator
from wsa.repositories import WorldRepository
from wsa.tickets import create_pr_packet
from wsa.workspace import create_world, sqlite_connection, world_db_path


class WorldManagerTests(TestCase):
    def test_diagnostics_find_pending_tickets_and_unfinished_tmp(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Manager World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")
            create_pr_packet(
                repo,
                "Pending fact",
                [
                    {
                        "change_type": "add_fact",
                        "subject_id": actor.entity_id,
                        "predicate": "knows",
                        "object_value": "secret",
                    }
                ],
            )
            tmp_dir = world.path / "scenes" / "scene_demo" / "tmp"
            tmp_dir.mkdir(parents=True)
            (tmp_dir / "prep_receipt.json").write_text("{}", encoding="utf-8")

            findings = WorldManager(workspace).run_diagnostics()
            finding_types = {item.finding_type for item in findings}
            with sqlite_connection(world_db_path(world.path)) as conn:
                diagnostic_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM diagnostic_logs"
                ).fetchone()["count"]

            self.assertIn("pending_tickets", finding_types)
            self.assertIn("unfinished_scene_tmp", finding_types)
            self.assertEqual(diagnostic_count, 0)

    def test_completed_mock_scene_tmp_is_not_reported_unfinished(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Completed Tmp World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")

            result = SceneOrchestrator(workspace, world).run_mock_scene(
                "Completed Scene",
                "finish cleanly",
                [actor],
            )
            findings = WorldManager(workspace).run_diagnostics()
            finding_types = {item.finding_type for item in findings}

            self.assertTrue((result.scene_dir / "tmp" / ".wsa_completed").exists())
            self.assertNotIn("unfinished_scene_tmp", finding_types)

    def test_diagnostics_empty_report_cleanup_requires_fix(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            write_artifact_architecture_map(workspace)
            empty_report = workspace / "reports" / "inbox" / "empty.html"
            empty_report.parent.mkdir(parents=True, exist_ok=True)
            empty_report.write_text("", encoding="utf-8")

            findings = WorldManager(workspace).run_diagnostics()

            self.assertTrue(empty_report.exists())
            self.assertEqual([item.finding_type for item in findings], ["empty_report_files"])

            fixed_findings = WorldManager(workspace).run_diagnostics(fix=True)

            self.assertFalse(empty_report.exists())
            self.assertEqual(
                [item.finding_type for item in fixed_findings],
                ["empty_report_cleanup"],
            )

    def test_diagnostics_can_create_missing_artifact_map(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Artifact Map Diagnostic World")
            map_path = workspace / "manager" / "artifact_map" / "artifact_architecture_map.json"

            findings = WorldManager(workspace).run_diagnostics()
            fixed = WorldManager(workspace).run_diagnostics(fix=True)

            self.assertIn(
                "artifact_architecture_map_missing_or_invalid",
                {item.finding_type for item in findings},
            )
            self.assertIn(
                "artifact_architecture_map_created",
                {item.finding_type for item in fixed},
            )
            self.assertTrue(map_path.exists())
            self.assertIn(world.world_id, map_path.read_text(encoding="utf-8"))

    def test_diagnostics_find_dynamic_dimension_missing_values(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Dynamic Diagnostic World")
            repo = WorldRepository(world.world_id, world.path)
            first = repo.create_entity("character", "First")
            repo.create_entity("character", "Second")
            repo.define_dimension("combat_power", value_type="number", status="canon")
            repo.set_entity_attribute_span(
                first.entity_id,
                "combat_power",
                value_number=500,
                status="canon",
            )

            findings = WorldManager(workspace).run_diagnostics()
            finding_types = {item.finding_type for item in findings}
            fixed_findings = WorldManager(workspace).run_diagnostics(fix=True)
            with sqlite_connection(world_db_path(world.path)) as conn:
                diagnostic_count = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM diagnostic_logs
                    WHERE diagnostic_type = 'dynamic_dimension_missing_values'
                    """
                ).fetchone()["count"]

            self.assertIn("dynamic_dimension_missing_values", finding_types)
            self.assertIn(
                "dynamic_dimension_missing_values",
                {item.finding_type for item in fixed_findings},
            )
            self.assertEqual(diagnostic_count, 1)

    def test_manager_diagnostics_surface_explicit_fact_conflicts(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Manager Conflict World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")
            repo.create_fact(actor.entity_id, "location", "north", status="canon")
            repo.create_fact(actor.entity_id, "location", "south", status="proposed")

            findings = WorldManager(workspace).run_diagnostics()

            conflicts = [
                item for item in findings if item.finding_type == "explicit_contradiction"
            ]
            self.assertEqual(len(conflicts), 1)
            self.assertIn("conflicting values", conflicts[0].detail)

            WorldManager(workspace).run_diagnostics(fix=True)
            WorldManager(workspace).run_diagnostics(fix=True)
            with sqlite_connection(world_db_path(world.path)) as conn:
                persisted = conn.execute(
                    """
                    SELECT COUNT(*) FROM diagnostic_logs
                    WHERE diagnostic_type = 'explicit_contradiction'
                    """
                ).fetchone()[0]
            self.assertEqual(persisted, 1)

    def test_temporal_and_singleton_edge_conflicts_include_severity(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Temporal Conflict World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")
            north = repo.create_entity("location", "North")
            south = repo.create_entity("location", "South")
            repo.set_entity_attribute_span(
                actor.entity_id,
                "condition",
                value_text="well",
                valid_from="001",
                valid_until="003",
                status="canon",
            )
            repo.set_entity_attribute_span(
                actor.entity_id,
                "condition",
                value_text="injured",
                valid_from="002",
                status="canon",
            )
            repo.add_world_edge(
                "entity",
                actor.entity_id,
                "located_at",
                "entity",
                object_id=north.entity_id,
                valid_from="001",
                valid_until="003",
                status="canon",
            )
            repo.add_world_edge(
                "entity",
                actor.entity_id,
                "located_at",
                "entity",
                object_id=south.entity_id,
                valid_from="002",
                status="canon",
            )
            repo.add_world_edge(
                "entity",
                actor.entity_id,
                "affiliated_with",
                "faction",
                object_value="A",
                status="canon",
            )
            repo.add_world_edge(
                "entity",
                actor.entity_id,
                "affiliated_with",
                "faction",
                object_value="B",
                status="canon",
            )

            findings = WorldManager(workspace).run_diagnostics()
            temporal = [
                item
                for item in findings
                if item.finding_type == "temporal_attribute_overlap"
            ]
            edge_findings = [
                item for item in findings if item.finding_type == "singleton_edge_overlap"
            ]

            self.assertEqual(len(temporal), 1)
            self.assertEqual(temporal[0].severity, "error")
            self.assertEqual(len(edge_findings), 1)
            self.assertEqual(edge_findings[0].severity, "error")

    def test_record_and_safe_repair_flags_have_independent_side_effects(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Independent Diagnostic Actions")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")
            repo.create_fact(actor.entity_id, "location", "north", status="canon")
            repo.create_fact(actor.entity_id, "location", "south", status="proposed")
            empty_report = workspace / "reports" / "inbox" / "empty.html"
            empty_report.parent.mkdir(parents=True, exist_ok=True)
            empty_report.write_text("", encoding="utf-8")

            WorldManager(workspace).run_diagnostics(record_findings=True)
            with sqlite_connection(world_db_path(world.path)) as conn:
                recorded_before_repair = conn.execute(
                    "SELECT COUNT(*) FROM diagnostic_logs"
                ).fetchone()[0]
            self.assertTrue(empty_report.exists())
            self.assertGreater(recorded_before_repair, 0)

            WorldManager(workspace).run_diagnostics(repair_safe_artifacts=True)
            with sqlite_connection(world_db_path(world.path)) as conn:
                recorded_after_repair = conn.execute(
                    "SELECT COUNT(*) FROM diagnostic_logs"
                ).fetchone()[0]
            self.assertFalse(empty_report.exists())
            self.assertEqual(recorded_after_repair, recorded_before_repair)

    def test_fact_correction_is_preview_only(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Correction Preview World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")
            first = repo.create_fact(
                actor.entity_id,
                "location",
                "north",
                status="canon",
            )
            second = repo.create_fact(
                actor.entity_id,
                "location",
                "south",
                status="proposed",
            )

            findings = WorldManager(workspace).run_diagnostics()
            conflict = next(
                item
                for item in findings
                if item.finding_type == "explicit_contradiction"
            )

            self.assertEqual(conflict.severity, "error")
            self.assertIsNotNone(conflict.correction_preview)
            assert conflict.correction_preview is not None
            self.assertEqual(conflict.correction_preview["mode"], "proposal_only")
            self.assertEqual(
                len(conflict.correction_preview["options"]),
                2,
            )
            statuses = {fact.fact_id: fact.status for fact in repo.list_facts()}
            self.assertEqual(statuses[first.fact_id], "canon")
            self.assertEqual(statuses[second.fact_id], "proposed")
