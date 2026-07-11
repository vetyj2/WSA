from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.application.world_home_service import WorldHomeService, format_world_home
from wsa.repositories import WorldRepository
from wsa.workspace import create_world


class WorldHomeServiceTests(TestCase):
    def test_blank_world_points_to_single_continue_command_without_mutation(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Home World")
            repo = WorldRepository(world.world_id, world.path)

            payload = WorldHomeService(workspace, world).snapshot()

            self.assertEqual(payload["next_action"]["reason"], "complete_minimum_startup_frame")
            self.assertEqual(payload["next_action"]["argv"][-2:], ["continue", world.world_id])
            self.assertEqual(repo.list_tickets(), [])
            self.assertEqual(repo.list_facts(), [])
            self.assertIn("월드_홈", format_world_home(payload)[0])

    def test_pending_ticket_becomes_canonical_next_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Review Home")
            repo = WorldRepository(world.world_id, world.path)
            repo.create_ticket("Review me", ticket_type="meeting_candidate")

            payload = WorldHomeService(workspace, world).snapshot()

            self.assertEqual(payload["counts"]["pending_tickets"], 1)
            self.assertEqual(payload["next_action"]["reason"], "review_pending_items")
            self.assertEqual(payload["side_effect_status"], "read_only_no_world_mutation")
