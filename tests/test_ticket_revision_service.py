from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.repositories import WorldRepository
from wsa.tickets import (
    InvalidTicketStateError,
    NonApplicableTicketError,
    TicketMergePreview,
    TicketRevisionService,
    TicketSplitPreview,
    UnsupportedTicketChangeError,
    create_pr_packet,
    review_ticket,
)
from wsa.workspace import create_world


class TicketRevisionServiceTests(TestCase):
    def test_split_preview_is_typed_and_has_zero_mutations(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "Split Preview World")
            source = self._ticket(
                repo,
                "Source",
                ["one", "two", "three"],
                source_ref="outline:7",
            )
            before = self._database_snapshot(repo)

            preview = TicketRevisionService(repo).preview_split(
                source.ticket_id,
                [[1, 3], [2]],
            )

            self.assertIsInstance(preview, TicketSplitPreview)
            self.assertEqual(preview.change_index_groups, [[1, 3], [2]])
            self.assertEqual(
                [change["display_name"] for change in preview.groups[0].changes],
                ["one", "three"],
            )
            payload = preview.to_dict()
            self.assertEqual(payload["schema"], "wsa.ticket_split.preview.v1")
            self.assertEqual(payload["mutation_count"], 0)
            self.assertIn("read_only_preview", payload["side_effect_status"])
            self.assertEqual(self._database_snapshot(repo), before)

    def test_split_preview_requires_an_exact_disjoint_partition(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "Split Partition World")
            source = self._ticket(repo, "Source", ["one", "two", "three"])
            service = TicketRevisionService(repo)
            before = self._database_snapshot(repo)
            invalid_groups = (
                [[1, 2, 3]],
                [[1, 2, 3], []],
                [[1, 2], [2, 3]],
                [[1], [2, 4]],
                [[1], [2]],
                [[1], [2, "3"]],
            )

            for groups in invalid_groups:
                with self.subTest(groups=groups):
                    with self.assertRaises(ValueError):
                        service.preview_split(source.ticket_id, groups)

            self.assertEqual(self._database_snapshot(repo), before)

    def test_split_write_preserves_source_and_builds_complete_lineage(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "Split Lineage World")
            source = self._ticket(
                repo,
                "Source",
                ["one", "two", "three"],
                source_ref="outline:11",
            )
            source_before = repo.get_ticket(source.ticket_id)
            changes_before = repo.list_ticket_changes(source.ticket_id)
            service = TicketRevisionService(repo)
            preview = service.preview_split(
                source.ticket_id,
                [[1, 3], [2]],
                titles=["Outer changes", "Middle change"],
            )

            result = service.write_split(preview)

            self.assertEqual(result.source_previous_status, "proposed")
            self.assertEqual(len(result.child_tickets), 2)
            self.assertEqual(result.to_dict()["schema"], "wsa.ticket_split.result.v1")
            source_after = repo.get_ticket(source.ticket_id)
            self.assertEqual(source_after.status, "superseded")
            self.assertEqual(source_after.payload["changes"], source_before.payload["changes"])
            self.assertEqual(source_after.payload["source_ref"], "outline:11")
            self.assertEqual(
                source_after.payload["superseded_by_ticket_ids"],
                result.child_ticket_ids,
            )
            self.assertEqual(source_after.payload["lineage"]["operation"], "split")
            self.assertEqual(
                source_after.payload["lineage"]["root_ticket_id"],
                source.ticket_id,
            )
            self.assertEqual(
                repo.list_ticket_changes(source.ticket_id),
                changes_before,
            )

            child_change_names = []
            for child in result.child_tickets:
                stored_child = repo.get_ticket(child.ticket_id)
                lineage = stored_child.payload["lineage"]
                self.assertEqual(stored_child.status, "proposed")
                self.assertEqual(stored_child.payload["source_ref"], "outline:11")
                self.assertEqual(lineage["operation"], "split")
                self.assertEqual(lineage["root_ticket_id"], source.ticket_id)
                self.assertEqual(lineage["parent_ticket_id"], source.ticket_id)
                self.assertEqual(lineage["revision_number"], 2)
                self.assertEqual(
                    lineage["sibling_ticket_ids"],
                    [
                        ticket_id
                        for ticket_id in result.child_ticket_ids
                        if ticket_id != child.ticket_id
                    ],
                )
                self.assertEqual(lineage["split_ticket_ids"], result.child_ticket_ids)
                child_change_names.append(
                    [
                        change.payload["display_name"]
                        for change in repo.list_ticket_changes(child.ticket_id)
                    ]
                )
            self.assertEqual(child_change_names, [["one", "three"], ["two"]])

    def test_merge_preview_and_write_preserve_caller_order_and_all_lineage(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "Merge Lineage World")
            first = self._ticket(
                repo,
                "First",
                ["first-a", "first-b"],
                source_ref="draft:first",
            )
            second = self._ticket(
                repo,
                "Second",
                ["second-a"],
                source_ref="draft:second",
            )
            first_changes = repo.list_ticket_changes(first.ticket_id)
            second_changes = repo.list_ticket_changes(second.ticket_id)
            service = TicketRevisionService(repo)
            before = self._database_snapshot(repo)

            preview = service.preview_merge(
                [second.ticket_id, first.ticket_id],
                title="Combined ticket",
            )

            self.assertIsInstance(preview, TicketMergePreview)
            self.assertEqual(
                [change["display_name"] for change in preview.changes],
                ["second-a", "first-a", "first-b"],
            )
            self.assertEqual(preview.to_dict()["schema"], "wsa.ticket_merge.preview.v1")
            self.assertEqual(self._database_snapshot(repo), before)

            result = service.write_merge(preview)

            merged = repo.get_ticket(result.merged_ticket_id)
            parent_ids = [second.ticket_id, first.ticket_id]
            self.assertEqual(merged.status, "proposed")
            self.assertEqual(merged.payload["lineage"]["operation"], "merge")
            self.assertEqual(merged.payload["lineage"]["parent_ticket_ids"], parent_ids)
            self.assertEqual(merged.payload["lineage"]["root_ticket_ids"], parent_ids)
            self.assertEqual(merged.payload["lineage"]["revision_number"], 2)
            self.assertEqual(merged.payload["source_refs"], ["draft:second", "draft:first"])
            self.assertEqual(
                [
                    change.payload["display_name"]
                    for change in repo.list_ticket_changes(merged.ticket_id)
                ],
                ["second-a", "first-a", "first-b"],
            )
            self.assertEqual(repo.list_ticket_changes(first.ticket_id), first_changes)
            self.assertEqual(repo.list_ticket_changes(second.ticket_id), second_changes)
            for source in (second, first):
                stored = repo.get_ticket(source.ticket_id)
                self.assertEqual(stored.status, "superseded")
                self.assertEqual(stored.payload["lineage"]["operation"], "merge")
                self.assertEqual(stored.payload["lineage"]["parent_ticket_ids"], parent_ids)
                self.assertEqual(stored.payload["lineage"]["root_ticket_ids"], parent_ids)
                self.assertEqual(
                    stored.payload["superseded_by_ticket_ids"],
                    [merged.ticket_id],
                )
            self.assertEqual(result.to_dict()["schema"], "wsa.ticket_merge.result.v1")

    def test_approved_sources_always_create_proposed_packets(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "Approved Revision World")
            split_source = self._ticket(repo, "Split", ["one", "two"])
            review_ticket(repo, split_source.ticket_id)
            service = TicketRevisionService(repo)

            split_result = service.write_split(
                service.preview_split(split_source.ticket_id, [[1], [2]])
            )

            self.assertEqual(split_result.source_previous_status, "approved")
            self.assertTrue(
                all(ticket.status == "proposed" for ticket in split_result.child_tickets)
            )
            self.assertTrue(
                all(
                    repo.get_ticket(ticket.ticket_id).status == "proposed"
                    for ticket in split_result.child_tickets
                )
            )

            merge_first = self._ticket(repo, "Merge first", ["first"])
            merge_second = self._ticket(repo, "Merge second", ["second"])
            review_ticket(repo, merge_first.ticket_id)
            review_ticket(repo, merge_second.ticket_id)
            merge_result = service.write_merge(
                service.preview_merge([merge_first.ticket_id, merge_second.ticket_id])
            )

            self.assertEqual(
                list(merge_result.source_previous_statuses.values()),
                ["approved", "approved"],
            )
            self.assertEqual(merge_result.merged_ticket.status, "proposed")
            self.assertEqual(
                repo.get_ticket(merge_result.merged_ticket_id).status,
                "proposed",
            )

    def test_candidate_invalid_status_and_non_distinct_sources_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "Rejected Sources World")
            concrete = self._ticket(repo, "Concrete", ["one", "two"])
            candidate = repo.create_ticket(
                title="Candidate",
                ticket_type="meeting_candidate",
                status="proposed",
                payload={"candidate": {"summary": "not concrete"}},
            )
            repo.add_ticket_change(
                candidate.ticket_id,
                change_type="add_entity",
                target_type="entity",
                payload=self._change("candidate-change"),
            )
            invalid = self._ticket(repo, "Applied", ["applied-change"])
            repo.update_ticket_status(invalid.ticket_id, "applied")
            service = TicketRevisionService(repo)
            before = self._database_snapshot(repo)

            with self.assertRaises(NonApplicableTicketError):
                service.preview_split(candidate.ticket_id, [[1], [1]])
            with self.assertRaises(NonApplicableTicketError):
                service.preview_merge([concrete.ticket_id, candidate.ticket_id])
            with self.assertRaises(InvalidTicketStateError):
                service.preview_split(invalid.ticket_id, [[1], [1]])
            with self.assertRaises(InvalidTicketStateError):
                service.preview_merge([concrete.ticket_id, invalid.ticket_id])
            with self.assertRaises(ValueError):
                service.preview_merge([concrete.ticket_id])
            with self.assertRaises(ValueError):
                service.preview_merge([concrete.ticket_id, concrete.ticket_id])

            self.assertEqual(self._database_snapshot(repo), before)

    def test_merge_preview_validates_the_combined_change_set(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "Merge Validation World")
            first = create_pr_packet(
                repo,
                "First portable source",
                [self._portable_change("portable_same", "first")],
            )
            second = create_pr_packet(
                repo,
                "Second portable source",
                [self._portable_change("portable_same", "second")],
            )
            before = self._database_snapshot(repo)

            with self.assertRaises(UnsupportedTicketChangeError):
                TicketRevisionService(repo).preview_merge(
                    [first.ticket_id, second.ticket_id]
                )

            self.assertEqual(self._database_snapshot(repo), before)

    def test_split_write_rolls_back_children_when_source_update_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "Split Rollback World")
            source = self._ticket(repo, "Source", ["one", "two"])
            service = TicketRevisionService(repo)
            preview = service.preview_split(source.ticket_id, [[1], [2]])
            self._install_supersede_failure_trigger(repo, "fail_split_supersede")
            before = self._database_snapshot(repo)

            with self.assertRaises(sqlite3.IntegrityError):
                service.write_split(preview)

            self.assertEqual(self._database_snapshot(repo), before)
            self.assertEqual(repo.get_ticket(source.ticket_id).status, "proposed")
            self.assertEqual(len(repo.list_tickets()), 1)

    def test_merge_write_rolls_back_new_packet_and_all_source_updates(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "Merge Rollback World")
            first = self._ticket(repo, "First", ["first"])
            second = self._ticket(repo, "Second", ["second"])
            service = TicketRevisionService(repo)
            preview = service.preview_merge([first.ticket_id, second.ticket_id])
            self._install_second_source_failure_trigger(repo, second.ticket_id)
            before = self._database_snapshot(repo)

            with self.assertRaises(sqlite3.IntegrityError):
                service.write_merge(preview)

            self.assertEqual(self._database_snapshot(repo), before)
            self.assertEqual(repo.get_ticket(first.ticket_id).status, "proposed")
            self.assertEqual(repo.get_ticket(second.ticket_id).status, "proposed")
            self.assertEqual(len(repo.list_tickets()), 2)

    def _repo(self, tmp: str, name: str) -> WorldRepository:
        world = create_world(Path(tmp) / "workspace", name)
        return WorldRepository(world.world_id, world.path)

    def _ticket(
        self,
        repo: WorldRepository,
        title: str,
        names: list[str],
        *,
        source_ref: str | None = None,
    ):
        return create_pr_packet(
            repo,
            title,
            [self._change(name) for name in names],
            source_ref=source_ref,
        )

    def _change(self, name: str) -> dict:
        return {
            "change_type": "add_entity",
            "target_type": "entity",
            "entity_type": "character",
            "display_name": name,
        }

    def _portable_change(self, portable_id: str, name: str) -> dict:
        return {
            **self._change(name),
            "portable_id": portable_id,
        }

    def _database_snapshot(self, repo: WorldRepository) -> tuple:
        with repo._connect() as conn:
            tickets = conn.execute(
                """
                SELECT ticket_id, status, payload
                FROM tickets
                ORDER BY ticket_id
                """
            ).fetchall()
            changes = conn.execute(
                """
                SELECT ticket_change_id, ticket_id, payload
                FROM ticket_changes
                ORDER BY ticket_change_id
                """
            ).fetchall()
            commits = conn.execute(
                """
                SELECT commit_id, action, target_id, payload
                FROM commit_log
                ORDER BY sequence
                """
            ).fetchall()
        return (
            tuple(tuple(row) for row in tickets),
            tuple(tuple(row) for row in changes),
            tuple(tuple(row) for row in commits),
        )

    def _install_supersede_failure_trigger(
        self,
        repo: WorldRepository,
        trigger_name: str,
    ) -> None:
        with repo._connect() as conn:
            conn.execute(
                f"""
                CREATE TRIGGER {trigger_name}
                BEFORE UPDATE OF status ON tickets
                WHEN NEW.status = 'superseded'
                BEGIN
                    SELECT RAISE(ABORT, 'forced supersede failure');
                END
                """
            )

    def _install_second_source_failure_trigger(
        self,
        repo: WorldRepository,
        ticket_id: str,
    ) -> None:
        with repo._connect() as conn:
            conn.execute(
                f"""
                CREATE TRIGGER fail_second_merge_source
                BEFORE UPDATE OF status ON tickets
                WHEN OLD.ticket_id = '{ticket_id}' AND NEW.status = 'superseded'
                BEGIN
                    SELECT RAISE(ABORT, 'forced second-source failure');
                END
                """
            )
