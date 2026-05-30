from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.orchestrator import SceneOrchestrator
from wsa.repositories import WorldRepository
from wsa.transport import RuntimeTransport
from wsa.workspace import create_world


class SceneOrchestratorTests(TestCase):
    def test_mock_scene_vertical_slice_creates_artifacts_and_messages(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Scene World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Iris")

            result = SceneOrchestrator(workspace, world).run_mock_scene(
                "Opening Scene",
                "Reach the door",
                [actor],
            )

            self.assertTrue(result.prep_receipt.exists())
            self.assertTrue(result.progress_checkpoint.exists())
            self.assertEqual(repo.get_ticket(result.ticket_id).status, "proposed")
            self.assertTrue(repo.get_report(result.report_id).artifact_ref)

            transport = RuntimeTransport(workspace)
            outbox = transport.list_envelopes(result.orchestrator_session_id, "outbox")
            message_types = [item.message_type for item in outbox]

            self.assertIn("progress_summary", message_types)
            self.assertIn("pr_packet_request", message_types)
            self.assertIn("final_report", message_types)
            self.assertEqual(len(result.actor_session_ids), 1)
