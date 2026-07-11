import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.repositories import WorldRepository
from wsa.review_cleanup import archive_callback_residue, triage_review_queue
from wsa.tickets import (
    InvalidTicketStateError,
    apply_ticket,
    create_pr_packet,
    review_ticket,
)
from wsa.workspace import create_world


class Phase0ReviewSafetyTests(TestCase):
    def test_callback_triage_and_archive_are_scoped_to_requested_world(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            first_world = create_world(workspace, "First Callback World")
            second_world = create_world(workspace, "Second Callback World")
            callbacks_dir = workspace / "hermes" / "callbacks"
            first_callback = callbacks_dir / "first.json"
            second_callback = callbacks_dir / "second.json"
            _write_callback(first_callback, "callback-first", first_world.world_id, "run-first")
            _write_callback(second_callback, "callback-second", second_world.world_id, "run-second")

            triage = triage_review_queue(workspace, first_world)

            self.assertEqual(triage["counts"]["callback_files_scanned"], 2)
            self.assertEqual(triage["counts"]["callback_residue_files"], 1)
            self.assertEqual(triage["counts"]["other_world_callback_files"], 1)
            self.assertEqual(
                triage["callback_residue"],
                ["hermes/callbacks/first.json"],
            )
            self.assertEqual(
                triage["callback_residue_details"][0]["run_id"],
                "run-first",
            )
            self.assertEqual(
                triage["unscoped_callback_residue"]["items"][0]["classification"],
                "different_world",
            )

            audit = archive_callback_residue(
                workspace,
                first_world,
                reason="archive first-world residue",
            )
            archive = audit["callback_archive"]

            self.assertFalse(first_callback.exists())
            self.assertTrue(second_callback.exists())
            self.assertEqual(archive["archived_count"], 1)
            receipt = archive["archive_receipts"][0]
            self.assertEqual(
                {
                    key: receipt[key]
                    for key in (
                        "callback_id",
                        "world_id",
                        "run_id",
                        "source",
                    )
                },
                {
                    "callback_id": "callback-first",
                    "world_id": first_world.world_id,
                    "run_id": "run-first",
                    "source": "hermes/callbacks/first.json",
                },
            )
            self.assertTrue((workspace / receipt["destination"]).exists())
            self.assertEqual(
                archive["unscoped_callback_residue"]["counts"]["different_world"],
                1,
            )
            second_triage = triage_review_queue(workspace, second_world)
            self.assertEqual(
                second_triage["callback_residue"],
                ["hermes/callbacks/second.json"],
            )
            self.assertEqual(
                second_triage["unscoped_callback_residue"]["count"],
                0,
            )

    def test_malformed_and_unbound_callbacks_are_quarantine_only(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Malformed Callback World")
            callbacks_dir = workspace / "hermes" / "callbacks"
            malformed = callbacks_dir / "malformed.json"
            malformed.write_text('{"callback_id":', encoding="utf-8")
            unbound = callbacks_dir / "unbound.json"
            unbound.write_text(
                json.dumps(
                    {
                        "callback_id": "callback-unbound",
                        "route": {"world_id": world.world_id},
                    }
                ),
                encoding="utf-8",
            )

            triage = triage_review_queue(workspace, world)

            self.assertEqual(triage["counts"]["callback_residue_files"], 0)
            self.assertEqual(triage["counts"]["callback_quarantine_only_files"], 2)
            self.assertEqual(
                {
                    item["classification"]
                    for item in triage["unscoped_callback_residue"]["items"]
                },
                {"malformed", "unbound"},
            )

            audit = archive_callback_residue(
                workspace,
                world,
                reason="attempt malformed cleanup",
            )
            archive = audit["callback_archive"]

            self.assertFalse(archive["performed"])
            self.assertEqual(archive["archived_count"], 0)
            self.assertEqual(archive["archive_receipts"], [])
            self.assertEqual(archive["unscoped_callback_residue"]["count"], 2)
            self.assertTrue(malformed.exists())
            self.assertTrue(unbound.exists())

    def test_proposed_ticket_requires_review_unless_compat_is_explicit(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Ticket Review Safety World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ara")
            ticket = _create_role_ticket(repo, actor.entity_id, "navigator")

            with self.assertRaisesRegex(
                InvalidTicketStateError,
                "reviewed and approved",
            ):
                apply_ticket(repo, ticket.ticket_id)

            self.assertEqual(repo.get_ticket(ticket.ticket_id).status, "proposed")
            self.assertEqual(repo.list_facts(actor.entity_id), [])
            with repo._connect() as conn:
                receipt_count = conn.execute(
                    "SELECT COUNT(*) FROM ticket_applications WHERE ticket_id = ?",
                    (ticket.ticket_id,),
                ).fetchone()[0]
            self.assertEqual(receipt_count, 0)

            reviewed = review_ticket(repo, ticket.ticket_id)
            self.assertEqual(reviewed.status, "approved")
            self.assertEqual(
                reviewed.side_effect_status,
                "approved_for_application_no_world_mutation",
            )
            applied = apply_ticket(repo, ticket.ticket_id)
            self.assertEqual(applied.previous_status, "approved")
            self.assertEqual(applied.side_effect_status, "world_changes_applied")
            reapplied = apply_ticket(repo, ticket.ticket_id)
            self.assertEqual(reapplied.applied_ids, [])
            self.assertEqual(
                reapplied.side_effect_status,
                "already_applied_no_new_world_mutation",
            )

            compat_ticket = _create_role_ticket(repo, actor.entity_id, "scout")
            with self.assertWarnsRegex(DeprecationWarning, "deprecated"):
                compat_applied = apply_ticket(
                    repo,
                    compat_ticket.ticket_id,
                    allow_proposed_compat=True,
                )
            self.assertEqual(
                compat_applied.compatibility_mode,
                "allow_proposed_compat",
            )
            self.assertIn("deprecated", compat_applied.side_effect_status)
            self.assertIn("deprecated", compat_applied.deprecation_warning or "")


def _write_callback(
    path: Path,
    callback_id: str,
    world_id: str,
    run_id: str,
) -> None:
    path.write_text(
        json.dumps(
            {
                "callback_id": callback_id,
                "route": {
                    "world_id": world_id,
                    "run_id": run_id,
                },
            }
        ),
        encoding="utf-8",
    )


def _create_role_ticket(
    repo: WorldRepository,
    subject_id: str,
    role: str,
):
    return create_pr_packet(
        repo,
        f"Add {role} role",
        [
            {
                "change_type": "add_fact",
                "subject_id": subject_id,
                "predicate": "has_role",
                "object_value": role,
            }
        ],
    )
