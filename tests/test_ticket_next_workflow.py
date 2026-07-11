import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.cli import main
from wsa.repositories import WorldRepository
from wsa.tickets import create_pr_packet, review_ticket
from wsa.workspace import create_world


class TicketNextWorkflowTests(TestCase):
    def test_guided_flow_never_requires_copying_ticket_or_world_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Guided World")
            repo = WorldRepository(world.world_id, world.path)

            written = StringIO()
            with redirect_stdout(written):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "compose",
                            "--add-entity",
                            "character|Mina",
                            "--write-ticket",
                        ]
                    ),
                    0,
                )
            self.assertIn("ticket next --world 'Guided World'", written.getvalue())

            inspected = StringIO()
            with redirect_stdout(inspected):
                self.assertEqual(
                    main(["--workspace", str(workspace), "ticket", "next"]),
                    0,
                )
            self.assertIn("entity character: Mina", inspected.getvalue())
            self.assertNotIn("ticket_id:", inspected.getvalue())
            self.assertIn("ticket review-next", inspected.getvalue())

            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "review-next",
                        ]
                    ),
                    0,
                )
            self.assertEqual(repo.list_tickets()[0].status, "approved")

            after_review = StringIO()
            with redirect_stdout(after_review):
                self.assertEqual(
                    main(["--workspace", str(workspace), "ticket", "next"]),
                    0,
                )
            self.assertIn("ticket apply-next", after_review.getvalue())

            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "apply-next",
                        ]
                    ),
                    0,
                )
            self.assertEqual(repo.list_tickets()[0].status, "applied")
            self.assertEqual(repo.list_entities()[0].display_name, "Mina")

    def test_guided_transition_refuses_to_guess_between_multiple_tickets(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Ambiguous World")
            repo = WorldRepository(world.world_id, world.path)
            for name in ("Mina", "Sol"):
                create_pr_packet(
                    repo,
                    f"Add {name}",
                    [
                        {
                            "change_type": "add_entity",
                            "target_type": "entity",
                            "entity_type": "character",
                            "display_name": name,
                        }
                    ],
                )

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    ["--workspace", str(workspace), "ticket", "review-next"]
                )
            self.assertEqual(code, 1)
            self.assertIn("multiple tickets are eligible", output.getvalue())
            self.assertEqual(
                [ticket.status for ticket in repo.list_tickets()],
                ["proposed", "proposed"],
            )
            self.assertEqual(repo.list_entities(), [])

    def test_next_prioritizes_the_single_approved_ticket(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Priority World")
            repo = WorldRepository(world.world_id, world.path)
            approved = create_pr_packet(
                repo,
                "Approved change",
                [
                    {
                        "change_type": "add_entity",
                        "target_type": "entity",
                        "entity_type": "character",
                        "display_name": "Mina",
                    }
                ],
            )
            create_pr_packet(
                repo,
                "Proposed change",
                [
                    {
                        "change_type": "add_entity",
                        "target_type": "entity",
                        "entity_type": "character",
                        "display_name": "Sol",
                    }
                ],
            )
            review_ticket(repo, approved.ticket_id)

            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "next",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["ticket_id"], approved.ticket_id)
            self.assertEqual(payload["guided_action"], "apply")
