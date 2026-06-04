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
