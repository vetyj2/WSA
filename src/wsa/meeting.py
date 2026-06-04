from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .ids import slugify
from .paths import safe_child_path
from .reporting_contract import build_reporting_artifact_contract
from .reports import ReportMailbox
from .repositories import EntityRecord, TicketRecord, WorldRepository, new_id
from .transport import RuntimeTransport
from .workspace import WorldRecord, utc_now


MEETING_DECISIONS = {"approve", "retry", "hold"}


@dataclass(frozen=True)
class MeetingParticipant:
    label: str
    entity: EntityRecord | None
    session_id: str
    contribution: Dict[str, Any]


@dataclass(frozen=True)
class MeetingResult:
    meeting_id: str
    meeting_dir: Path
    transcript_path: Path
    report_id: str
    manager_session_id: str
    participant_session_ids: List[str]


@dataclass(frozen=True)
class MeetingDecisionResult:
    report_id: str
    decision: str
    report_status: str
    ticket: TicketRecord | None = None


class MeetingOrchestrator:
    """Run a non-mutating representative meeting for world diagnosis."""

    def __init__(self, workspace: Path, world: WorldRecord) -> None:
        self.workspace = workspace
        self.world = world
        self.repo = WorldRepository(world.world_id, world.path)
        self.transport = RuntimeTransport(workspace)
        self.mailbox = ReportMailbox(workspace)

    def run_meeting(
        self,
        topic: str,
        question: str,
        participants: Iterable[str],
    ) -> MeetingResult:
        labels = [item.strip() for item in participants if item.strip()]
        if not labels:
            labels = ["world_manager"]

        meeting_id = new_id("meeting")
        meeting_dir = safe_child_path(
            self.world.path,
            "meetings",
            f"{slugify(topic)}_{meeting_id[:14]}",
        )
        meeting_dir.mkdir(parents=True, exist_ok=True)

        agenda = {
            "meeting_id": meeting_id,
            "mode": "meeting",
            "topic": topic,
            "question": question,
            "apply_policy": {
                "world_mutation": "proposal_only",
                "creates_facts": False,
                "creates_tickets": False,
                "commits_scene_events": False,
            },
            "decision_options": ["approve", "retry", "hold"],
            "participants": labels,
        }
        manager_session_id = self.transport.start_session(
            role="meeting_manager",
            runtime_target="meeting:mock",
            world_id=self.world.world_id,
            payload=agenda,
        )
        agenda_envelope = self.transport.send(
            manager_session_id,
            "inbox",
            role="wsa",
            message_type="meeting_agenda",
            world_id=self.world.world_id,
            payload=agenda,
        )

        entity_index = {
            entity.display_name.casefold(): entity
            for entity in self.repo.list_entities(status="active")
        }
        participant_records: List[MeetingParticipant] = []
        for label in labels:
            entity = entity_index.get(label.casefold())
            session_id = self.transport.start_session(
                role="representative",
                runtime_target="meeting:mock",
                world_id=self.world.world_id,
                payload={
                    "meeting_id": meeting_id,
                    "represents": label,
                    "entity_id": entity.entity_id if entity else None,
                    "mode": "meeting",
                },
            )
            self.transport.send(
                session_id,
                "inbox",
                role="meeting_manager",
                message_type="meeting_agenda",
                world_id=self.world.world_id,
                payload=agenda,
                parent_message_id=agenda_envelope.message_id,
            )
            contribution = self._build_contribution(label, entity, topic, question)
            participant_records.append(
                MeetingParticipant(
                    label=label,
                    entity=entity,
                    session_id=session_id,
                    contribution=contribution,
                )
            )
            self.transport.send(
                session_id,
                "outbox",
                role="representative",
                message_type="meeting_contribution",
                world_id=self.world.world_id,
                payload=contribution,
                parent_message_id=agenda_envelope.message_id,
            )

        transcript = {
            "schema": "wsa.meeting.transcript.v1",
            "created_at": utc_now(),
            "world_id": self.world.world_id,
            "meeting_id": meeting_id,
            "topic": topic,
            "question": question,
            "apply_policy": agenda["apply_policy"],
            "decision_options": agenda["decision_options"],
            "reporting_artifact_contract": build_reporting_artifact_contract(
                workflow="meeting",
                skill="meeting",
            ),
            "manager_session_id": manager_session_id,
            "participants": [
                {
                    "label": item.label,
                    "entity_id": item.entity.entity_id if item.entity else None,
                    "session_id": item.session_id,
                    "contribution": item.contribution,
                }
                for item in participant_records
            ],
            "synthesis": self._synthesize(topic, question, participant_records),
        }
        transcript_path = safe_child_path(meeting_dir, "transcript.json")
        transcript_path.write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report = self.mailbox.create_world_report(
            self.repo,
            title=f"Meeting report: {topic}",
            purpose="meeting",
            risk="low",
            status="inbox",
            payload=transcript,
        )
        self.transport.send(
            manager_session_id,
            "outbox",
            role="meeting_manager",
            message_type="meeting_summary",
            world_id=self.world.world_id,
            payload={"meeting_id": meeting_id, "report_id": report.report_id},
            artifact_refs=[
                item
                for item in (str(transcript_path), report.artifact_ref)
                if item is not None
            ],
        )
        safe_child_path(meeting_dir, ".wsa_completed").write_text("completed\n", encoding="utf-8")

        return MeetingResult(
            meeting_id=meeting_id,
            meeting_dir=meeting_dir,
            transcript_path=transcript_path,
            report_id=report.report_id,
            manager_session_id=manager_session_id,
            participant_session_ids=[item.session_id for item in participant_records],
        )

    def decide_report(
        self,
        report_id: str,
        decision: str,
        note: str | None = None,
    ) -> MeetingDecisionResult:
        if decision not in MEETING_DECISIONS:
            raise ValueError(f"unsupported meeting decision: {decision}")

        report = self.repo.get_report(report_id)
        if report.purpose != "meeting":
            raise ValueError(f"report is not a meeting report: {report_id}")

        status = {
            "approve": "approved",
            "retry": "rejected",
            "hold": "pending_review",
        }[decision]
        transitioned = self.mailbox.transition_report(self.repo, report_id, status)
        decision_payload = {
            "report_id": report_id,
            "decision": decision,
            "note": note,
            "meeting_id": report.payload.get("meeting_id"),
            "topic": report.payload.get("topic"),
        }
        self.repo.create_diagnostic_log(
            "meeting_decision",
            decision,
            payload=decision_payload,
        )

        ticket = None
        if decision == "approve":
            ticket = self.repo.create_ticket(
                title=f"Meeting candidate: {report.payload.get('topic', report.title)}",
                ticket_type="meeting_candidate",
                status="proposed",
                risk="medium",
                payload={
                    **decision_payload,
                    "source_report_id": report_id,
                    "candidate": report.payload.get("synthesis", {}),
                    "transcript": report.payload,
                    "apply_policy": "requires_explicit_change_ticket",
                },
            )
            self.repo.append_commit(
                "meeting_candidate_created",
                "ticket",
                ticket.ticket_id,
                payload={
                    "source_report_id": report_id,
                    "decision": decision,
                },
            )

        return MeetingDecisionResult(
            report_id=report_id,
            decision=decision,
            report_status=transitioned.status,
            ticket=ticket,
        )

    def _build_contribution(
        self,
        label: str,
        entity: EntityRecord | None,
        topic: str,
        question: str,
    ) -> Dict[str, Any]:
        if entity is None:
            return {
                "represents": label,
                "representation_status": "unbound",
                "topic": topic,
                "question": question,
                "position": (
                    f"{label} is not yet registered in the world. Treat any claim "
                    "as a meeting proposal, not canon."
                ),
                "open_questions": [
                    f"What authority, motive, or constraint should {label} represent?",
                    "Which proposed details require user confirmation before canonization?",
                ],
                "proposals": [
                    f"Define {label}'s role before applying changes to the world state."
                ],
            }

        facts = self.repo.list_facts(entity.entity_id)
        anchors = [
            f"{fact.predicate}: {fact.object_value}"
            for fact in facts[:5]
            if fact.object_value is not None
        ]
        return {
            "represents": label,
            "representation_status": "bound",
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "topic": topic,
            "question": question,
            "canon_anchors": anchors,
            "position": (
                f"{label} should be evaluated against existing canon anchors."
                if anchors
                else f"{label} has no canon anchors yet; keep conclusions provisional."
            ),
            "open_questions": [
                "Which claims are grounded in existing facts?",
                "Which useful gaps should become review tickets later?",
            ],
            "proposals": [
                f"Capture {label}'s meeting stance as a proposal before changing canon."
            ],
        }

    def _synthesize(
        self,
        topic: str,
        question: str,
        participants: List[MeetingParticipant],
    ) -> Dict[str, Any]:
        return {
            "summary": f"Meeting gathered {len(participants)} representative perspectives.",
            "topic": topic,
            "question": question,
            "world_mutations": [],
            "recommended_next_steps": [
                "Review the meeting report with the user or Hermes manager.",
                "Convert accepted proposals into explicit tickets in a later step.",
                "Keep unresolved gaps outside canon until approved.",
            ],
        }
