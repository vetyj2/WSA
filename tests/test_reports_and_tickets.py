from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.reports import ReportMailbox
from wsa.repositories import WorldRepository
from wsa.tickets import approve_ticket, create_pr_packet
from wsa.workspace import create_world


class ReportsAndTicketsTests(TestCase):
    def test_report_mailbox_renders_and_transitions_html(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Report World")
            repo = WorldRepository(world.world_id, world.path)
            mailbox = ReportMailbox(workspace)

            report = mailbox.create_world_report(
                repo,
                title="Prep Report",
                purpose="prep",
                payload={"action": "review"},
            )

            self.assertEqual(report.status, "inbox")
            self.assertTrue(Path(report.artifact_ref or "").exists())
            self.assertIn("/reports/inbox/", report.artifact_ref or "")

            approved = mailbox.transition_report(repo, report.report_id, "approved")

            self.assertEqual(approved.status, "approved")
            self.assertTrue(Path(approved.artifact_ref or "").exists())
            self.assertIn("/reports/approved/", approved.artifact_ref or "")
            self.assertFalse(Path(report.artifact_ref or "").exists())

    def test_report_transition_only_deletes_managed_report_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            external_path = Path(tmp) / "external.html"
            external_path.write_text("keep me", encoding="utf-8")
            world = create_world(workspace, "Report Safety World")
            repo = WorldRepository(world.world_id, world.path)
            mailbox = ReportMailbox(workspace)
            report = mailbox.create_world_report(
                repo,
                title="External Ref Report",
                purpose="prep",
            )
            repo.update_report_status(report.report_id, "inbox", str(external_path))

            mailbox.transition_report(repo, report.report_id, "approved")

            self.assertTrue(external_path.exists())

    def test_pr_packet_approval_applies_fact_and_commit(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Ticket World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ara")

            ticket = create_pr_packet(
                repo,
                "Add role fact",
                [
                    {
                        "change_type": "add_fact",
                        "target_type": "fact",
                        "subject_id": actor.entity_id,
                        "predicate": "has_role",
                        "object_value": "navigator",
                        "authority": "approved",
                        "status": "canon",
                    }
                ],
            )

            applied = approve_ticket(repo, ticket.ticket_id)
            facts = repo.list_facts(actor.entity_id)
            approved_ticket = repo.get_ticket(ticket.ticket_id)

            self.assertEqual(len(applied), 1)
            self.assertEqual(len(facts), 1)
            self.assertEqual(facts[0].object_value, "navigator")
            self.assertEqual(facts[0].status, "canon")
            self.assertEqual(approved_ticket.status, "approved")

    def test_pr_packet_approval_rolls_back_if_later_change_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Ticket Rollback World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ara")

            ticket = create_pr_packet(
                repo,
                "Mixed success ticket",
                [
                    {
                        "change_type": "add_fact",
                        "target_type": "fact",
                        "subject_id": actor.entity_id,
                        "predicate": "has_role",
                        "object_value": "navigator",
                    },
                    {
                        "change_type": "update_fact_status",
                        "target_type": "fact",
                        "target_id": "fact_missing",
                        "status": "rejected",
                    },
                ],
            )

            with self.assertRaises(KeyError):
                approve_ticket(repo, ticket.ticket_id)

            self.assertEqual(repo.list_facts(actor.entity_id), [])
            self.assertEqual(repo.get_ticket(ticket.ticket_id).status, "proposed")
