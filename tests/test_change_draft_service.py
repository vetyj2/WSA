from pathlib import Path
from sqlite3 import IntegrityError
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.application.change_draft_service import (
    AmbiguousEntityNameError,
    ChangeDraftService,
)
from wsa.repositories import WorldRepository
from wsa.tickets import NonApplicableTicketError, create_pr_packet
from wsa.workspace import create_world, sqlite_connection, world_db_path


class ChangeDraftServiceTests(TestCase):
    def _repo(self, tmp: str) -> WorldRepository:
        world = create_world(Path(tmp) / "workspace", "Draft World")
        return WorldRepository(world.world_id, world.path)

    def test_composes_without_json_and_uses_change_refs(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            service = ChangeDraftService(repo)

            draft = service.compose(
                add_entity=["character|Mina", "location|Harbor"],
                add_fact=["Mina|home|@Harbor"],
                add_world_edge=["Mina|based_in|Harbor"],
                add_timeline_point=["Arrival|001"],
            )

            entities = [c for c in draft.changes if c["change_type"] == "add_entity"]
            fact = next(c for c in draft.changes if c["change_type"] == "add_fact")
            edge = next(c for c in draft.changes if c["change_type"] == "add_world_edge")
            self.assertEqual(fact["subject_change_ref"], entities[0]["change_ref"])
            self.assertEqual(fact["object_change_ref"], entities[1]["change_ref"])
            self.assertEqual(edge["subject_change_ref"], entities[0]["change_ref"])
            self.assertEqual(edge["object_change_ref"], entities[1]["change_ref"])
            self.assertEqual(draft.to_dict()["mutation_count"], 0)
            self.assertEqual(repo.list_tickets(), [])
            self.assertEqual(repo.list_entities(), [])

            ticket = service.write(draft)
            self.assertEqual(ticket.status, "proposed")
            self.assertEqual(repo.list_entities(), [])

    def test_ambiguous_existing_display_name_is_blocked(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            repo.create_entity("character", "Mina")
            repo.create_entity("character", "mina")

            with self.assertRaises(AmbiguousEntityNameError):
                ChangeDraftService(repo).compose(add_fact=["MINA|role|navigator"])

    def test_candidate_accepts_structured_lists_only(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            structured = {
                "change_type": "add_fact",
                "subject_id": repo.world_id,
                "predicate": "premise",
                "object_value": "A signal arrives.",
            }
            candidate = repo.create_ticket(
                "Candidate",
                ticket_type="meeting_candidate",
                payload={
                    "summary": "Add a different fact from this prose.",
                    "candidate_changes": [structured],
                    "candidate": {"changes": ["free-form suggestion"]},
                },
            )
            service = ChangeDraftService(repo)
            draft = service.compose(accept_candidate=candidate.ticket_id)

            self.assertEqual(len(draft.changes), 1)
            self.assertEqual(repo.get_ticket(candidate.ticket_id).status, "proposed")
            ticket = service.write(draft)
            self.assertEqual(repo.get_ticket(candidate.ticket_id).status, "converted")
            self.assertEqual(len(repo.list_ticket_changes(ticket.ticket_id)), 1)

            prose_only = repo.create_ticket(
                "Prose only",
                ticket_type="meeting_candidate",
                payload={"candidate": {"summary": "add_entity character Mina"}},
            )
            with self.assertRaises(NonApplicableTicketError):
                service.compose(accept_candidate=prose_only.ticket_id)

    def test_candidate_can_skip_and_replace_one_structured_change(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            actor = repo.create_entity("character", "Ara")
            candidate = repo.create_ticket(
                "Candidate edits",
                ticket_type="meeting_candidate",
                payload={
                    "candidate_changes": [
                        {
                            "change_type": "add_fact",
                            "subject_id": actor.entity_id,
                            "predicate": "role",
                            "object_value": "navigator",
                        },
                        {
                            "change_type": "add_fact",
                            "subject_id": actor.entity_id,
                            "predicate": "mood",
                            "object_value": "uncertain",
                        },
                    ]
                },
            )

            draft = ChangeDraftService(repo).compose(
                accept_candidate=candidate.ticket_id,
                skip_index=[2],
                add_fact=["Ara|mood|focused"],
            )

            self.assertEqual(draft.skipped_change_indexes, [2])
            self.assertEqual(
                [(item["predicate"], item["object_value"]) for item in draft.changes],
                [("role", "navigator"), ("mood", "focused")],
            )
            self.assertEqual(draft.to_dict()["diff"]["removed_count"], 1)
            self.assertEqual(draft.to_dict()["diff"]["added_count"], 1)

    def test_revision_lineage_and_failed_supersede_roll_back(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            actor = repo.create_entity("character", "Ara")
            source = create_pr_packet(
                repo,
                "Source",
                [
                    {
                        "change_type": "add_fact",
                        "subject_id": actor.entity_id,
                        "predicate": "role",
                        "object_value": "navigator",
                    },
                    {
                        "change_type": "add_fact",
                        "subject_id": actor.entity_id,
                        "predicate": "mood",
                        "object_value": "calm",
                    },
                ],
            )
            service = ChangeDraftService(repo)
            draft = service.compose(
                revise_ticket=source.ticket_id,
                skip_index=[1],
                add_fact=["Ara|mood|focused"],
            )
            replacement = service.write(draft)
            old = repo.get_ticket(source.ticket_id)
            self.assertEqual(old.status, "superseded")
            self.assertEqual(old.payload["superseded_by"], replacement.ticket_id)
            self.assertEqual(
                replacement.payload["lineage"]["parent_ticket_id"],
                source.ticket_id,
            )
            self.assertEqual(service.ticket_diff(source.ticket_id)["added_count"], 1)

            rollback_source = create_pr_packet(
                repo,
                "Rollback source",
                [
                    {
                        "change_type": "add_fact",
                        "subject_id": actor.entity_id,
                        "predicate": "role",
                        "object_value": "pilot",
                    }
                ],
            )
            rollback_draft = service.compose(
                revise_ticket=rollback_source.ticket_id,
                add_timeline_point=["Departure|002"],
            )
            ticket_count = len(repo.list_tickets())
            with sqlite_connection(world_db_path(repo.world_path)) as conn:
                conn.execute(
                    """
                    CREATE TRIGGER fail_supersede BEFORE UPDATE OF status ON tickets
                    WHEN NEW.status = 'superseded'
                    BEGIN SELECT RAISE(ABORT, 'forced failure'); END
                    """
                )
                conn.commit()
            with self.assertRaises(IntegrityError):
                service.write(rollback_draft)
            self.assertEqual(repo.get_ticket(rollback_source.ticket_id).status, "proposed")
            self.assertEqual(len(repo.list_tickets()), ticket_count)
