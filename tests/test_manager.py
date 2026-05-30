from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

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
            empty_report = workspace / "reports" / "inbox" / "empty.html"
            empty_report.parent.mkdir(parents=True)
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
