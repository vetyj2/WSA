import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.cli import main
from wsa.repositories import WorldRepository
from wsa.tickets import create_pr_packet
from wsa.workspace import create_world


class TicketRevisionCliTests(TestCase):
    def test_split_then_merge_is_preview_first_and_keeps_change_order(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Revision CLI World")
            repo = WorldRepository(world.world_id, world.path)
            source = create_pr_packet(
                repo,
                "Three actors",
                [self._entity_change(name) for name in ("Mina", "Sol", "Ren")],
            )

            preview_output = StringIO()
            with redirect_stdout(preview_output):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "split",
                            source.ticket_id,
                            "--part",
                            "1,3",
                            "--part",
                            "2",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            preview = json.loads(preview_output.getvalue())
            self.assertEqual(preview["change_index_groups"], [[1, 3], [2]])
            self.assertEqual(repo.get_ticket(source.ticket_id).status, "proposed")
            self.assertEqual(len(repo.list_tickets()), 1)

            split_output = StringIO()
            with redirect_stdout(split_output):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "split",
                            source.ticket_id,
                            "--part",
                            "1,3",
                            "--part",
                            "2",
                            "--write-ticket",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            split = json.loads(split_output.getvalue())
            child_ids = split["child_ticket_ids"]
            self.assertEqual(len(child_ids), 2)
            self.assertEqual(repo.get_ticket(source.ticket_id).status, "superseded")

            merge_preview_output = StringIO()
            with redirect_stdout(merge_preview_output):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "merge",
                            *child_ids,
                            "--title",
                            "Recombined actors",
                            "--format",
                            "json",
                        ]
                    ),
                    0,
                )
            merge_preview = json.loads(merge_preview_output.getvalue())
            self.assertEqual(
                [item["display_name"] for item in merge_preview["changes"]],
                ["Mina", "Ren", "Sol"],
            )
            self.assertTrue(
                all(repo.get_ticket(ticket_id).status == "proposed" for ticket_id in child_ids)
            )

            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "ticket",
                            "merge",
                            *child_ids,
                            "--title",
                            "Recombined actors",
                            "--write-ticket",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(["--workspace", str(workspace), "ticket", "review-next"]),
                    0,
                )
                self.assertEqual(
                    main(["--workspace", str(workspace), "ticket", "apply-next"]),
                    0,
                )
            self.assertEqual(
                [item.display_name for item in repo.list_entities()],
                ["Mina", "Ren", "Sol"],
            )
            self.assertTrue(
                all(
                    repo.get_ticket(ticket_id).status == "superseded"
                    for ticket_id in child_ids
                )
            )

    def test_invalid_split_cli_leaves_the_source_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Invalid Split CLI World")
            repo = WorldRepository(world.world_id, world.path)
            source = create_pr_packet(
                repo,
                "Two actors",
                [self._entity_change(name) for name in ("Mina", "Sol")],
            )

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "split",
                        source.ticket_id,
                        "--part",
                        "1",
                        "--part",
                        "1",
                        "--write-ticket",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertIn("appears in more than one group", output.getvalue())
            self.assertEqual(repo.get_ticket(source.ticket_id).status, "proposed")
            self.assertEqual(len(repo.list_tickets()), 1)

    def _entity_change(self, name: str) -> dict:
        return {
            "change_type": "add_entity",
            "target_type": "entity",
            "entity_type": "character",
            "display_name": name,
        }
