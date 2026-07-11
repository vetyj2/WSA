import json
from io import StringIO
from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.application.proposal_service import (
    candidate_materialization_preview,
    entity_proposal_preview,
    portable_import_preview,
    startup_proposal_preview,
    write_materialized_candidate_ticket,
    write_proposal_ticket,
)
from wsa.application.world_service import WorldInspectionService
from wsa.cli import main
from wsa.meeting import MeetingOrchestrator
from wsa.repositories import WorldRepository
from wsa.startup import StartupProfileManager
from wsa.tickets import apply_ticket, review_ticket
from wsa.workspace import create_world, sqlite_connection, world_db_path


class WorldApplicationTests(TestCase):
    def test_meeting_candidate_materialize_review_apply_golden_path(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Candidate Materialization World")
            repo = WorldRepository(world.world_id, world.path)
            meeting = MeetingOrchestrator(workspace, world)
            meeting_result = meeting.run_meeting(
                topic="Choose an opening premise",
                question="What premise should be reviewed?",
                participants=["world_manager"],
            )
            decision = meeting.decide_report(meeting_result.report_id, "approve")
            candidate = decision.ticket
            self.assertIsNotNone(candidate)
            assert candidate is not None

            changes = [
                {
                    "change_type": "add_fact",
                    "target_type": "fact",
                    "subject_id": world.world_id,
                    "predicate": "opening_premise",
                    "object_value": "A disputed signal arrives at dawn.",
                    "authority": "user_explicit",
                    "status": "canon",
                }
            ]
            preview = candidate_materialization_preview(
                repo,
                candidate.ticket_id,
                changes,
            )

            self.assertEqual(repo.get_ticket(candidate.ticket_id).status, "proposed")
            self.assertEqual(repo.list_facts(), [])

            ticket = write_materialized_candidate_ticket(
                repo,
                candidate.ticket_id,
                preview,
            )
            self.assertEqual(repo.get_ticket(candidate.ticket_id).status, "converted")
            self.assertEqual(ticket.payload["source_ref"], f"ticket:{candidate.ticket_id}")
            self.assertEqual(repo.list_facts(), [])

            reviewed = review_ticket(repo, ticket.ticket_id)
            self.assertEqual(reviewed.status, "approved")
            self.assertEqual(reviewed.applied_ids, [])
            self.assertEqual(repo.list_facts(), [])

            review_ticket(repo, ticket.ticket_id)
            applied = apply_ticket(repo, ticket.ticket_id)
            self.assertEqual(applied.status, "applied")
            self.assertEqual(len(repo.list_facts(world.world_id)), 1)

    def test_cli_candidate_materialization_preview_and_write(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Candidate World")
            repo = WorldRepository(world.world_id, world.path)
            candidate = repo.create_ticket(
                "Candidate",
                ticket_type="meeting_candidate",
                payload={"candidate": {"summary": "review"}},
            )
            changes_path = Path(tmp) / "changes.json"
            changes_path.write_text(
                json.dumps(
                    {
                        "changes": [
                            {
                                "change_type": "add_entity",
                                "target_type": "entity",
                                "entity_type": "character",
                                "display_name": "Mina",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            preview_stdout = StringIO()
            with patch("sys.stdout", preview_stdout):
                preview_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "materialize",
                        world.world_id,
                        candidate.ticket_id,
                        str(changes_path),
                        "--format",
                        "json",
                    ]
                )
            preview_payload = json.loads(preview_stdout.getvalue())
            self.assertEqual(preview_code, 0)
            self.assertEqual(preview_payload["change_count"], 1)
            self.assertEqual(repo.get_ticket(candidate.ticket_id).status, "proposed")
            self.assertEqual(repo.list_entities(), [])

            write_stdout = StringIO()
            with patch("sys.stdout", write_stdout):
                write_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "materialize",
                        world.world_id,
                        candidate.ticket_id,
                        str(changes_path),
                        "--write-ticket",
                        "--format",
                        "json",
                    ]
                )
            write_payload = json.loads(write_stdout.getvalue())
            self.assertEqual(write_code, 0)
            self.assertEqual(repo.get_ticket(candidate.ticket_id).status, "converted")
            self.assertEqual(repo.list_entities(), [])
            self.assertIn("ticket review", write_payload["next_action"])

    def test_candidate_materialization_rolls_back_as_one_transaction(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Materialization Rollback World")
            repo = WorldRepository(world.world_id, world.path)
            candidate = repo.create_ticket(
                "Candidate",
                ticket_type="meeting_candidate",
                payload={"candidate": {"summary": "review"}},
            )
            preview = candidate_materialization_preview(
                repo,
                candidate.ticket_id,
                [
                    {
                        "change_type": "add_entity",
                        "entity_type": "character",
                        "display_name": "Mina",
                    }
                ],
            )
            with sqlite_connection(world_db_path(world.path)) as conn:
                conn.execute(
                    """
                    CREATE TRIGGER fail_materialized_change
                    BEFORE INSERT ON ticket_changes
                    BEGIN
                        SELECT RAISE(ABORT, 'forced materialization failure');
                    END
                    """
                )
                conn.commit()

            with self.assertRaises(IntegrityError):
                write_materialized_candidate_ticket(
                    repo,
                    candidate.ticket_id,
                    preview,
                )

            self.assertEqual(repo.get_ticket(candidate.ticket_id).status, "proposed")
            self.assertEqual(len(repo.list_tickets()), 1)

    def test_entity_preview_ticket_apply_and_inspection(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Application World")
            repo = WorldRepository(world.world_id, world.path)
            preview = entity_proposal_preview(world, "Mina", "character")

            self.assertEqual(repo.list_entities(), [])
            ticket = write_proposal_ticket(repo, preview)
            self.assertEqual(repo.list_entities(), [])

            review_ticket(repo, ticket.ticket_id)
            applied = apply_ticket(repo, ticket.ticket_id)
            payload = WorldInspectionService(world).entities()

            self.assertEqual(applied.status, "applied")
            self.assertEqual(len(applied.applied_ids), 1)
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["items"][0]["display_name"], "Mina")

    def test_startup_intent_is_not_materialized_as_world_canon(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Startup Materialization World")
            manager = StartupProfileManager(world)
            manager.answer("0001", "Organize an existing world reference.")
            manager.answer("0002", "Existing notes and a place sketch.")
            repo = WorldRepository(world.world_id, world.path)

            preview = startup_proposal_preview(world)
            self.assertEqual(preview.changes, [])
            self.assertEqual(repo.list_facts(), [])
            with self.assertRaisesRegex(ValueError, "no concrete changes"):
                write_proposal_ticket(repo, preview)

    def test_cli_golden_path_preview_apply_and_export(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Application World")
            preview_stdout = StringIO()
            with patch("sys.stdout", preview_stdout):
                preview_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "proposal",
                        "entity",
                        world.world_id,
                        "--name",
                        "Sol",
                        "--type",
                        "character",
                        "--write-ticket",
                        "--format",
                        "json",
                    ]
                )
            preview_payload = json.loads(preview_stdout.getvalue())
            ticket_id = preview_payload["ticket"]["ticket_id"]

            review_stdout = StringIO()
            with patch("sys.stdout", review_stdout):
                review_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "review",
                        world.world_id,
                        ticket_id,
                    ]
                )
            apply_stdout = StringIO()
            with patch("sys.stdout", apply_stdout):
                apply_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "apply",
                        world.world_id,
                        ticket_id,
                    ]
                )

            show_stdout = StringIO()
            with patch("sys.stdout", show_stdout):
                show_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "entity",
                        "list",
                        world.world_id,
                        "--format",
                        "json",
                    ]
                )

            export_stdout = StringIO()
            with patch("sys.stdout", export_stdout):
                export_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "export",
                        world.world_id,
                        "--format",
                        "json",
                    ]
                )

            entities = json.loads(show_stdout.getvalue())
            export = json.loads(export_stdout.getvalue())
            self.assertEqual(preview_code, 0)
            self.assertEqual(review_code, 0)
            self.assertEqual(apply_code, 0)
            self.assertEqual(show_code, 0)
            self.assertEqual(export_code, 0)
            self.assertEqual(entities["items"][0]["display_name"], "Sol")
            self.assertEqual(export["entities"][0]["display_name"], "Sol")
            self.assertNotIn("runtime_messages", export)

    def test_portable_export_import_preview_preserves_internal_references(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            source = create_world(workspace, "Portable Source")
            source_repo = WorldRepository(source.world_id, source.path)
            first = source_repo.create_entity("character", "First")
            second = source_repo.create_entity("place", "Second")
            source_repo.create_fact(
                first.entity_id,
                "visits",
                object_ref_id=second.entity_id,
                authority="user_explicit",
                status="canon",
            )
            source_repo.add_world_edge(
                "entity",
                first.entity_id,
                "located_at",
                "entity",
                object_id=second.entity_id,
                authority="user_explicit",
                status="canon",
            )
            exported = WorldInspectionService(source).export_data()
            destination = create_world(workspace, "Portable Destination")
            destination_repo = WorldRepository(destination.world_id, destination.path)

            preview = portable_import_preview(destination, exported)
            ticket = write_proposal_ticket(destination_repo, preview)
            review_ticket(destination_repo, ticket.ticket_id)
            apply_ticket(destination_repo, ticket.ticket_id)

            entities = destination_repo.list_entities()
            by_name = {item.display_name: item for item in entities}
            facts = destination_repo.list_facts(by_name["First"].entity_id)
            edges = destination_repo.query_world_edges(
                subject_id=by_name["First"].entity_id
            )
            self.assertEqual(facts[0].object_ref_id, by_name["Second"].entity_id)
            self.assertEqual(edges[0].object_id, by_name["Second"].entity_id)
            self.assertEqual(facts[0].payload["provenance"], "portable_import")
