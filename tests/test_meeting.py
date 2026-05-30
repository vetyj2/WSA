import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.meeting import MeetingOrchestrator
from wsa.repositories import WorldRepository
from wsa.transport import RuntimeTransport
from wsa.workspace import create_world


class MeetingTests(TestCase):
    def test_meeting_creates_non_mutating_transcript_and_report(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Meeting World")
            repo = WorldRepository(world.world_id, world.path)
            faction = repo.create_entity("faction", "Harbor Guild")
            repo.create_fact(
                faction.entity_id,
                "controls",
                "old harbor",
                authority="user_explicit",
                status="canon",
            )

            result = MeetingOrchestrator(workspace, world).run_meeting(
                topic="Harbor succession",
                question="Who should diagnose the power gap?",
                participants=["Harbor Guild", "Unregistered Council"],
            )

            transcript = json.loads(result.transcript_path.read_text(encoding="utf-8"))
            report = repo.get_report(result.report_id)
            manager_outbox = RuntimeTransport(workspace).list_envelopes(
                result.manager_session_id,
                "outbox",
            )

            self.assertTrue((result.meeting_dir / ".wsa_completed").exists())
            self.assertEqual(report.purpose, "meeting")
            self.assertEqual(transcript["apply_policy"]["world_mutation"], "proposal_only")
            self.assertEqual(transcript["synthesis"]["world_mutations"], [])
            self.assertEqual(len(result.participant_session_ids), 2)
            self.assertEqual([item.message_type for item in manager_outbox], ["meeting_summary"])
            self.assertEqual(repo.list_tickets(), [])
            self.assertEqual(len(repo.list_facts()), 1)

    def test_approve_meeting_report_creates_candidate_ticket_without_world_mutation(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Meeting Decision World")
            repo = WorldRepository(world.world_id, world.path)
            orchestrator = MeetingOrchestrator(workspace, world)
            result = orchestrator.run_meeting(
                topic="New district sketch",
                question="What should be proposed?",
                participants=["Market Families"],
            )

            decision = orchestrator.decide_report(
                result.report_id,
                "approve",
                note="Promote to candidate review.",
            )

            tickets = repo.list_tickets()
            approved_report = repo.get_report(result.report_id)

            self.assertEqual(decision.report_status, "approved")
            self.assertEqual(decision.ticket, tickets[0])
            self.assertEqual(approved_report.status, "approved")
            self.assertEqual(tickets[0].ticket_type, "meeting_candidate")
            self.assertEqual(tickets[0].payload["apply_policy"], "requires_explicit_change_ticket")
            self.assertEqual(repo.list_facts(), [])

    def test_hold_and_retry_meeting_report_do_not_create_ticket(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Meeting Hold World")
            repo = WorldRepository(world.world_id, world.path)
            orchestrator = MeetingOrchestrator(workspace, world)

            hold_result = orchestrator.run_meeting(
                topic="Hold topic",
                question="Hold?",
                participants=["Archivist"],
            )
            hold_decision = orchestrator.decide_report(hold_result.report_id, "hold")

            retry_result = orchestrator.run_meeting(
                topic="Retry topic",
                question="Retry?",
                participants=["Archivist"],
            )
            retry_decision = orchestrator.decide_report(retry_result.report_id, "retry")

            self.assertEqual(hold_decision.report_status, "pending_review")
            self.assertEqual(retry_decision.report_status, "rejected")
            self.assertEqual(repo.list_tickets(), [])
