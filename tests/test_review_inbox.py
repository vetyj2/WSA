import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.application.review_service import ReviewInboxService
from wsa.cli import main
from wsa.repositories import WorldRepository
from wsa.tickets import create_pr_packet
from wsa.workspace import create_world


class ReviewInboxTests(TestCase):
    def test_inbox_unifies_candidate_and_concrete_ticket_without_mutation(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Review World")
            repo = WorldRepository(world.world_id, world.path)
            candidate = repo.create_ticket("Candidate", ticket_type="meeting_candidate")
            actor = repo.create_entity("character", "Mina")
            concrete = create_pr_packet(
                repo,
                "Concrete",
                [{
                    "change_type": "add_fact",
                    "subject_id": actor.entity_id,
                    "predicate": "role",
                    "object_value": "navigator",
                }],
            )

            payload = ReviewInboxService(workspace, world).inbox()

            by_id = {item["item_id"]: item for item in payload["items"]}
            self.assertEqual(by_id[candidate.ticket_id]["kind"], "candidate")
            self.assertNotIn("approve", by_id[candidate.ticket_id]["allowed_actions"])
            self.assertIn("approve", by_id[concrete.ticket_id]["allowed_actions"])
            self.assertEqual(repo.get_ticket(concrete.ticket_id).status, "proposed")

    def test_cli_show_displays_concrete_diff_read_only(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Show World")
            repo = WorldRepository(world.world_id, world.path)
            ticket = create_pr_packet(
                repo,
                "Add entity",
                [{
                    "change_type": "add_entity",
                    "entity_type": "character",
                    "display_name": "Mina",
                }],
            )
            output = StringIO()

            with patch("sys.stdout", output):
                code = main([
                    "--workspace",
                    str(workspace),
                    "report",
                    "show",
                    world.world_id,
                    ticket.ticket_id,
                    "--format",
                    "json",
                ])

            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["details"]["changes"][0]["change_type"], "add_entity")
            self.assertEqual(repo.get_ticket(ticket.ticket_id).status, "proposed")

    def test_unified_decision_approves_then_applies_ticket_with_distinct_effects(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Decision World")
            repo = WorldRepository(world.world_id, world.path)
            ticket = create_pr_packet(
                repo,
                "Add entity",
                [{
                    "change_type": "add_entity",
                    "entity_type": "character",
                    "display_name": "Mina",
                }],
            )
            service = ReviewInboxService(workspace, world)

            approved = service.decide(ticket.ticket_id, "approve")
            self.assertEqual(approved["status"], "approved")
            self.assertEqual(repo.list_entities(), [])

            applied = service.decide(ticket.ticket_id, "apply")
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(len(repo.list_entities()), 1)
