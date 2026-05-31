from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .ids import slugify
from .orchestrator_contract import (
    DEFAULT_CONTEXT_POLICY,
    DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
    DEFAULT_MAX_QUEUE_TURNS,
    DEFAULT_MAX_SUBSESSION_CALLS,
    DEFAULT_TERMINATION_POLICY,
    DEFAULT_UTTERANCE_TARGET,
    ORCHESTRATOR_DECISIONS,
    ORCHESTRATOR_RUN_SCHEMA,
    build_concurrency_policy,
    build_orchestrator_session_contract,
    build_plan_frame,
    build_session_cleanup_policy,
    build_start_preflight,
    build_termination_contract,
)
from .paths import safe_child_path
from .reports import ReportMailbox
from .repositories import EntityRecord, TicketRecord, WorldRepository, new_id
from .transport import RuntimeTransport
from .workspace import WorldRecord, list_worlds, utc_now


@dataclass(frozen=True)
class OrchestratorRunResult:
    run_id: str
    status: str
    run_dir: Path
    run_path: Path
    report_id: str
    manager_session_id: str
    subsession_session_ids: List[str]


@dataclass(frozen=True)
class OrchestratorDecisionResult:
    run_id: str
    decision: str
    report_id: str
    report_status: str
    ticket: TicketRecord | None = None


class AutonomousOrchestrator:
    """Manual-trigger, autonomous-until-boundary orchestration workflow."""

    def __init__(self, workspace: Path, world: WorldRecord) -> None:
        self.workspace = workspace
        self.world = world
        self.repo = WorldRepository(world.world_id, world.path)
        self.transport = RuntimeTransport(workspace)
        self.mailbox = ReportMailbox(workspace)

    def run(
        self,
        workflow: str,
        topic: str,
        question: str,
        participants: Iterable[str],
        rounds: int = 2,
        skill: str | None = None,
        mode: str = "agent",
        max_queue_turns: int = DEFAULT_MAX_QUEUE_TURNS,
        max_concurrent_subsessions: int = DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
        max_subsession_calls: int = DEFAULT_MAX_SUBSESSION_CALLS,
        context_policy: str = DEFAULT_CONTEXT_POLICY,
        frame_plan: str | None = None,
        termination_policy: str = DEFAULT_TERMINATION_POLICY,
        subsession_policy: str = "ephemeral",
        canon_policy: str = "proposal-only",
        approval: str = "required",
        close_on: str = "complete",
    ) -> OrchestratorRunResult:
        if rounds <= 0:
            raise ValueError("rounds must be positive")
        if max_queue_turns <= 0:
            raise ValueError("max_queue_turns must be positive")
        if max_concurrent_subsessions <= 0:
            raise ValueError("max_concurrent_subsessions must be positive")
        if max_subsession_calls <= 0:
            raise ValueError("max_subsession_calls must be positive")
        if subsession_policy != "ephemeral":
            raise ValueError("only ephemeral subsession policy is supported")
        if canon_policy != "proposal-only":
            raise ValueError("only proposal-only canon policy is supported")
        if approval != "required":
            raise ValueError("approval must be required for this MVP workflow")

        run_id = new_id("orun")
        skill_name = skill or workflow
        participant_plan = self._plan_participants(participants, topic, workflow)
        if len(participant_plan) > max_subsession_calls:
            raise ValueError(
                "max_subsession_calls must be at least the participant count "
                f"({len(participant_plan)})"
            )
        call_budget_turns = max_subsession_calls // max(1, len(participant_plan))
        queue_turns = min(rounds, max_queue_turns, call_budget_turns)
        planned_subsession_calls = len(participant_plan) * queue_turns
        budget_exhausted_reasons = []
        if rounds > max_queue_turns:
            budget_exhausted_reasons.append("max_queue_turns_reached_before_requested_rounds")
        if rounds > call_budget_turns:
            budget_exhausted_reasons.append("max_subsession_calls_reached_before_requested_rounds")
        budget_exhausted = bool(budget_exhausted_reasons)
        plan_frame = build_plan_frame(workflow, skill_name, topic, question, frame_plan)
        concurrency_policy = build_concurrency_policy(
            participant_plan,
            max_concurrent_subsessions,
        )
        termination_contract = build_termination_contract(
            termination_policy,
            max_queue_turns,
            max_subsession_calls,
        )
        session_cleanup = build_session_cleanup_policy(close_on)
        start_preflight = build_start_preflight(
            plan_frame,
            termination_contract,
            session_cleanup,
            concurrency_policy,
        )
        session_contract = build_orchestrator_session_contract(
            run_id,
            self.world.world_id,
            workflow,
            skill_name,
            mode,
            max_queue_turns,
            max_concurrent_subsessions,
            max_subsession_calls,
            context_policy,
            plan_frame,
            termination_contract,
            session_cleanup,
        )
        run_dir = safe_child_path(
            self.world.path,
            "orchestrator_runs",
            f"{slugify(workflow)}_{slugify(topic)}_{run_id[:14]}",
        )
        run_dir.mkdir(parents=True, exist_ok=True)

        lifecycle = [{"state": "requested", "at": utc_now()}]
        manager_session_id = self.transport.start_session(
            role="orchestrator_manager",
            runtime_target=f"orchestrator:{mode}",
            world_id=self.world.world_id,
            payload={
                "run_id": run_id,
                "workflow": workflow,
                "skill": skill_name,
                "topic": topic,
                "execution": "autonomous_until_boundary",
                "execution_owner": "user_hermes_runtime",
                "wsa_role": "orchestration_contract_and_audit_artifacts_only",
            },
        )
        plan = {
            "run_id": run_id,
            "workflow": workflow,
            "skill": skill_name,
            "world_id": self.world.world_id,
            "topic": topic,
            "question": question,
            "trigger": {
                "source": "manual_user_request",
                "created_at": utc_now(),
            },
            "execution": "autonomous_until_boundary",
            "subsession_execution_mode": "local_simulated_outputs",
            "real_subagent_execution": "hermes_runtime_owned_not_performed_by_wsa_cli",
            "execution_owner": "user_hermes_runtime",
            "wsa_role": "orchestration_contract_and_audit_artifacts_only",
            "mode": mode,
            "round_budget": rounds,
            "rounds_scheduled": queue_turns,
            "plan_frame": plan_frame,
            "start_preflight": start_preflight,
            "session_contract": session_contract,
            "context_continuity": session_contract["context_continuity"],
            "floor_continuity": session_contract["floor_continuity"],
            "prompt_coordination": session_contract["prompt_coordination"],
            "micro_turn_policy": session_contract["micro_turn_policy"],
            "quality_gate": session_contract["quality_gate"],
            "termination_policy": termination_contract,
            "session_cleanup": session_cleanup,
            "concurrency_policy": concurrency_policy,
            "queue_limits": {
                "max_queue_turns": max_queue_turns,
                "queue_turns_used": queue_turns,
                "rounds_requested": rounds,
                "max_subsession_calls": max_subsession_calls,
                "planned_subsession_calls": planned_subsession_calls,
                "budget_exhausted": budget_exhausted,
                "budget_exhausted_reasons": budget_exhausted_reasons,
                "infinite_loop_guard": True,
                "termination_on_max_queue_turns": True,
            },
            "subsession_policy": subsession_policy,
            "canon_policy": canon_policy,
            "approval": approval,
            "close_on": close_on,
            "participants": participant_plan,
            "termination_conditions": [
                "planned_rounds_complete",
                "approval_required",
                "unresolved_conflict_requires_author",
                "chair_closes_floor",
                "conclusion_reached",
                "max_queue_turns_reached",
                "max_subsession_calls_reached",
                "budget_exhausted",
                "failure",
            ],
        }
        plan_path = safe_child_path(run_dir, "plan.json")
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        plan_envelope = self.transport.send(
            manager_session_id,
            "inbox",
            role="wsa",
            message_type="orchestrator_plan",
            world_id=self.world.world_id,
            payload=plan,
            artifact_refs=[str(plan_path)],
        )
        lifecycle.append({"state": "planned", "at": utc_now()})
        lifecycle.append({"state": "subsessions_spawning", "at": utc_now()})

        context_packets = []
        subsession_outputs = []
        subsession_session_ids = []
        entity_index = {
            entity.display_name.casefold(): entity
            for entity in self.repo.list_entities(status="active")
        }
        for participant in participant_plan:
            entity = entity_index.get(participant["label"].casefold())
            session_id = self.transport.start_session(
                role="orchestrator_subsession",
                runtime_target=f"orchestrator:{mode}:ephemeral",
                world_id=self.world.world_id,
                payload={
                    "run_id": run_id,
                    "participant_id": participant["participant_id"],
                    "represents": participant["label"],
                    "ephemeral": True,
                },
            )
            subsession_session_ids.append(session_id)
            context_packet = self._context_packet(
                run_id,
                participant,
                entity,
                workflow,
                skill_name,
                topic,
                question,
                queue_turns,
                context_policy,
            )
            context_packets.append({**context_packet, "session_id": session_id})
            self.transport.send(
                session_id,
                "inbox",
                role="orchestrator_manager",
                message_type="subsession_context",
                world_id=self.world.world_id,
                payload=context_packet,
                parent_message_id=plan_envelope.message_id,
            )

        lifecycle.append({"state": "subsessions_running", "at": utc_now()})
        compressed_context_snapshots = []
        round_prompt_packets = []
        for round_index in range(1, queue_turns + 1):
            if round_index > 1:
                lifecycle.append(
                    {
                        "state": "followup_round_running",
                        "at": utc_now(),
                        "round": round_index,
                    }
                )
            round_outputs = []
            for context_packet in context_packets:
                round_prompt_packet = self._round_prompt_packet(
                    context_packet,
                    round_index,
                    compressed_context_snapshots[-1] if compressed_context_snapshots else None,
                )
                round_prompt_packets.append(round_prompt_packet)
                output = self._subsession_output(context_packet, round_index)
                output["prompt_packet_id"] = round_prompt_packet["prompt_packet_id"]
                output["quality_gate"] = self._quality_gate(output)
                if output["quality_gate"]["accepted"]:
                    subsession_outputs.append(output)
                    round_outputs.append(output)
                self.transport.send(
                    str(context_packet["session_id"]),
                    "outbox",
                    role="orchestrator_subsession",
                    message_type="subsession_output",
                    world_id=self.world.world_id,
                    payload=output,
                    parent_message_id=plan_envelope.message_id,
                )
            compressed_context_snapshots.append(
                self._compressed_context_snapshot(round_index, round_outputs, context_policy)
            )

        lifecycle.append({"state": "synthesizing", "at": utc_now()})
        synthesis = self._synthesize(topic, question, participant_plan, subsession_outputs)
        lifecycle.append({"state": "diagnosing_conflicts", "at": utc_now()})
        diagnosis = self._diagnose_conflicts(
            subsession_outputs,
            budget_exhausted,
            budget_exhausted_reasons,
        )
        approval_package = self._approval_package(synthesis, diagnosis)
        lifecycle.append({"state": "awaiting_author_review", "at": utc_now()})
        for session_id in subsession_session_ids:
            self.transport.close_session(session_id, status="closed")

        run_payload = {
            "schema": ORCHESTRATOR_RUN_SCHEMA,
            "run_id": run_id,
            "status": "awaiting_author_review",
            "world_id": self.world.world_id,
            "workflow": workflow,
            "skill": skill_name,
            "topic": topic,
            "question": question,
            "manual_trigger": True,
            "execution": "autonomous_until_boundary",
            "subsession_execution_mode": "local_simulated_outputs",
            "real_subagent_execution": "hermes_runtime_owned_not_performed_by_wsa_cli",
            "execution_owner": "user_hermes_runtime",
            "wsa_role": "orchestration_contract_and_audit_artifacts_only",
            "plan_frame": plan_frame,
            "start_preflight": start_preflight,
            "session_contract": session_contract,
            "context_continuity": session_contract["context_continuity"],
            "floor_continuity": session_contract["floor_continuity"],
            "prompt_coordination": session_contract["prompt_coordination"],
            "micro_turn_policy": session_contract["micro_turn_policy"],
            "quality_gate": session_contract["quality_gate"],
            "termination_policy": termination_contract,
            "session_cleanup": session_cleanup,
            "concurrency_policy": concurrency_policy,
            "queue_limits": plan["queue_limits"],
            "lifecycle": lifecycle,
            "plan": plan,
            "context_packets": context_packets,
            "subagent_prompt_packets": [
                context_packet["prompt_packet"] for context_packet in context_packets
            ],
            "round_prompt_packets": round_prompt_packets,
            "subsession_outputs": subsession_outputs,
            "accepted_outputs_only": True,
            "followup_questions": self._followup_questions(subsession_outputs),
            "compressed_context_snapshots": compressed_context_snapshots,
            "synthesis": synthesis,
            "conflict_gap_diagnosis": diagnosis,
            "draft_options": synthesis["draft_options"],
            "proposed_tickets": approval_package["proposed_tickets"],
            "approval_options": approval_package["approval_options"],
            "closed_subsessions": subsession_session_ids,
            "close_reason": "subsessions_closed_after_review_package",
            "canon_policy": "proposal_only_until_author_approval",
            "world_mutations": [],
        }
        run_path = safe_child_path(run_dir, "run.json")
        run_path.write_text(
            json.dumps(run_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report = self.mailbox.create_world_report(
            self.repo,
            title=f"Orchestrator report: {topic}",
            purpose="orchestrator_run",
            risk="medium" if diagnosis["requires_author_boundary"] else "low",
            status="inbox",
            payload=run_payload,
        )
        self.transport.send(
            manager_session_id,
            "outbox",
            role="orchestrator_manager",
            message_type="orchestrator_synthesis",
            world_id=self.world.world_id,
            payload={
                "run_id": run_id,
                "report_id": report.report_id,
                "status": "awaiting_author_review",
            },
            artifact_refs=(
                [str(run_path), report.artifact_ref]
                if report.artifact_ref
                else [str(run_path)]
            ),
        )
        self.transport.close_session(manager_session_id, status="awaiting_author_review")
        safe_child_path(run_dir, ".wsa_completed").write_text("completed\n", encoding="utf-8")
        return OrchestratorRunResult(
            run_id=run_id,
            status="awaiting_author_review",
            run_dir=run_dir,
            run_path=run_path,
            report_id=report.report_id,
            manager_session_id=manager_session_id,
            subsession_session_ids=subsession_session_ids,
        )

    @staticmethod
    def load_run(workspace: Path, run_id: str) -> Dict[str, Any]:
        _, _, payload = find_orchestrator_run(workspace, run_id)
        return payload

    @staticmethod
    def report_path(workspace: Path, run_id: str) -> Path:
        _, path, _ = find_orchestrator_run(workspace, run_id)
        return path

    @staticmethod
    def decide(
        workspace: Path,
        run_id: str,
        decision: str,
        option: str | None = None,
        note: str | None = None,
    ) -> OrchestratorDecisionResult:
        if decision not in ORCHESTRATOR_DECISIONS:
            raise ValueError(f"unsupported orchestrator decision: {decision}")
        world, path, payload = find_orchestrator_run(workspace, run_id)
        if decision == "approve":
            allowed_options = {
                item.get("option_id")
                for item in payload.get("draft_options", [])
                if isinstance(item, dict)
            }
            if not option:
                raise ValueError("approve decision requires an option")
            if option not in allowed_options:
                raise ValueError(f"unknown orchestrator option: {option}")
        repo = WorldRepository(world.world_id, world.path)
        mailbox = ReportMailbox(workspace)
        report_id = _report_id_for_run(repo, run_id)
        status = {
            "approve": "approved",
            "retry": "rejected",
            "hold": "pending_review",
        }[decision]
        transitioned = mailbox.transition_report(repo, report_id, status)
        payload["status"] = {
            "approve": "canonization_pending",
            "retry": "retry_requested",
            "hold": "awaiting_author_review",
        }[decision]
        payload["decision"] = {
            "decision": decision,
            "option": option,
            "note": note,
            "decided_at": utc_now(),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        ticket = None
        if decision == "approve":
            ticket = repo.create_ticket(
                title=f"Orchestrator candidate: {payload.get('topic', run_id)}",
                ticket_type="orchestrator_candidate",
                status="proposed",
                risk="medium",
                payload={
                    "run_id": run_id,
                    "source_report_id": report_id,
                    "approved_option": option,
                    "note": note,
                    "synthesis": payload.get("synthesis", {}),
                    "conflict_gap_diagnosis": payload.get("conflict_gap_diagnosis", {}),
                    "apply_policy": "requires_explicit_change_ticket",
                },
            )
        return OrchestratorDecisionResult(
            run_id=run_id,
            decision=decision,
            report_id=report_id,
            report_status=transitioned.status,
            ticket=ticket,
        )

    @staticmethod
    def close(workspace: Path, run_id: str, reason: str | None = None) -> Dict[str, Any]:
        _, path, payload = find_orchestrator_run(workspace, run_id)
        payload["status"] = "closed"
        payload["close_reason"] = reason or "closed_by_user_or_runtime"
        payload["closed_at"] = utc_now()
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return payload

    def _plan_participants(
        self,
        participants: Iterable[str],
        topic: str,
        workflow: str,
    ) -> List[Dict[str, Any]]:
        labels = [item.strip() for item in participants if item.strip()]
        if not labels:
            entity_labels = [
                entity.display_name
                for entity in self.repo.list_entities(status="active")
                if entity.display_name.casefold() in topic.casefold()
            ]
            labels = entity_labels[:8]
        if not labels:
            labels = [
                "canon_guardian",
                "conflict_diagnostician",
                f"{workflow}_proposal_builder",
            ]
        return [
            {
                "participant_id": f"P{index:03d}",
                "label": label,
                "role": "representative_voice",
                "scope": "topic_relevant_context_only",
            }
            for index, label in enumerate(labels, start=1)
        ]

    def _context_packet(
        self,
        run_id: str,
        participant: Dict[str, Any],
        entity: EntityRecord | None,
        workflow: str,
        skill_name: str,
        topic: str,
        question: str,
        rounds: int,
        context_policy: str,
    ) -> Dict[str, Any]:
        anchors = []
        if entity is not None:
            anchors = [
                {
                    "predicate": fact.predicate,
                    "object_value": fact.object_value,
                    "status": fact.status,
                }
                for fact in self.repo.list_facts(entity.entity_id)[:8]
            ]
        prompt_packet = {
            "schema": "wsa.orchestrator.subagent_prompt_packet.v1",
            "run_id": run_id,
            "skill": skill_name,
            "workflow": workflow,
            "participant_id": participant["participant_id"],
            "represents": participant["label"],
            "execution_owner": "user_hermes_runtime",
            "role_instruction": (
                f"Represent {participant['label']} for this isolated WSA {skill_name} session. "
                "Stay within the relevant context and mark uncertain claims as provisional."
            ),
            "relevant_context": {
                "topic": topic,
                "question": question,
                "canon_anchors": anchors,
            },
            "floor_continuity": {
                "meeting_floor": "same_live_floor_until_chair_close_or_hard_limit",
                "context_mode": "compressed_floor_summary_plus_relevant_recent_outputs",
            },
            "expected_output": [
                "position",
                "objections",
                "proposals",
                "gaps",
                "uncertainty",
            ],
            "response_shape": {
                "utterance_target": DEFAULT_UTTERANCE_TARGET,
                "prefer_one_sentence": True,
                "avoid_lore_dump": True,
            },
            "constraints": [
                "proposal_only_until_author_approval",
                "do_not_mutate_canon",
                "do_not_require_user_babysitting_before_boundary",
                "return_structured_output_for_orchestrator_synthesis",
                "keep_response_minimal_and_exact",
            ],
        }
        return {
            "run_id": run_id,
            "participant_id": participant["participant_id"],
            "represents": participant["label"],
            "entity_id": entity.entity_id if entity else None,
            "skill": skill_name,
            "workflow": workflow,
            "topic": topic,
            "question": question,
            "round_budget": rounds,
            "context_scope": "minimal_relevant_context",
            "context_continuity": {
                "policy": context_policy,
                "compression": "rolling_summary_plus_recent_outputs",
                "share_policy": "participant_relevant_context_only",
            },
            "canon_anchors": anchors,
            "prompt_packet": prompt_packet,
            "proposal_policy": "do_not_mutate_canon",
        }

    def _round_prompt_packet(
        self,
        context_packet: Dict[str, Any],
        round_index: int,
        previous_snapshot: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        participant_id = context_packet["participant_id"]
        return {
            "schema": "wsa.orchestrator.round_prompt_packet.v1",
            "prompt_packet_id": f"{context_packet['run_id']}:{participant_id}:round-{round_index}",
            "run_id": context_packet["run_id"],
            "participant_id": participant_id,
            "represents": context_packet["represents"],
            "round": round_index,
            "live_floor_state": {
                "floor_open": True,
                "chair_has_closed": False,
                "previous_compressed_snapshot": previous_snapshot,
            },
            "instruction": (
                "Respond with only the requested bounded fields. Prefer one precise sentence "
                "for each field unless the expected value requires a list."
            ),
            "expected_response_shape": DEFAULT_UTTERANCE_TARGET,
            "quality_gate": {
                "accepted_only_if_complete": True,
                "missing_or_unbounded_output_requires_retry": True,
            },
        }

    def _subsession_output(self, context_packet: Dict[str, Any], round_index: int) -> Dict[str, Any]:
        label = context_packet["represents"]
        grounded = bool(context_packet.get("canon_anchors"))
        uncertainty = "medium" if grounded else "high"
        return {
            "run_id": context_packet["run_id"],
            "participant_id": context_packet["participant_id"],
            "represents": label,
            "round": round_index,
            "position": (
                f"{label} evaluates the topic through existing canon anchors."
                if grounded
                else f"{label} is not sufficiently grounded in canon yet and should stay provisional."
            ),
            "objections": [
                "Do not canonize generated detail without author approval.",
                "Separate useful candidate structure from unsupported assertions.",
            ],
            "proposals": [
                f"Draft a candidate role or pressure line for {label} in round {round_index}."
            ],
            "gaps": [
                f"Clarify what authority or constraint {label} represents."
                if not grounded
                else f"Check whether {label}'s anchors conflict with other participants."
            ],
            "uncertainty": uncertainty,
        }

    def _quality_gate(self, output: Dict[str, Any]) -> Dict[str, Any]:
        required = ["position", "objections", "proposals", "gaps", "uncertainty"]
        missing = [field for field in required if output.get(field) in (None, "", [])]
        uncertainty_ok = output.get("uncertainty") in {"low", "medium", "high"}
        canon_attempt = bool(output.get("canon_mutation"))
        accepted = not missing and uncertainty_ok and not canon_attempt
        return {
            "schema": "wsa.orchestrator.output_quality_gate.v1",
            "accepted": accepted,
            "missing_fields": missing,
            "uncertainty_labeled": uncertainty_ok,
            "canon_mutation_attempt": canon_attempt,
            "accumulation_policy": "accepted_outputs_only",
        }

    def _compressed_context_snapshot(
        self,
        round_index: int,
        round_outputs: List[Dict[str, Any]],
        context_policy: str,
    ) -> Dict[str, Any]:
        high_uncertainty = [
            output for output in round_outputs if output.get("uncertainty") == "high"
        ]
        return {
            "round": round_index,
            "policy": context_policy,
            "compression": "rolling_summary_plus_recent_outputs",
            "summary": (
                f"Round {round_index} carried {len(round_outputs)} outputs forward; "
                f"{len(high_uncertainty)} outputs remain high-uncertainty."
            ),
            "recent_output_refs": [
                {
                    "participant_id": output["participant_id"],
                    "represents": output["represents"],
                    "uncertainty": output["uncertainty"],
                }
                for output in round_outputs[-8:]
            ],
        }

    def _followup_questions(self, outputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        questions = []
        for output in outputs:
            if output["uncertainty"] == "high":
                questions.append(
                    {
                        "participant_id": output["participant_id"],
                        "round": output["round"],
                        "question": f"What must be true before {output['represents']} can become canon-grounded?",
                    }
                )
        return questions

    def _synthesize(
        self,
        topic: str,
        question: str,
        participants: List[Dict[str, Any]],
        outputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        participant_labels = [item["label"] for item in participants]
        return {
            "summary": (
                f"Autonomous orchestrator ran {len(outputs)} subsession outputs "
                f"for {len(participants)} participants."
            ),
            "topic": topic,
            "question": question,
            "participant_labels": participant_labels,
            "draft_options": [
                {
                    "option_id": "option-a",
                    "title": "Conservative canon-grounded structure",
                    "description": "Use only anchored claims and keep unbound voices as open questions.",
                },
                {
                    "option_id": "option-b",
                    "title": "Expanded proposal structure",
                    "description": "Accept provisional roles as candidate tickets before canon conversion.",
                },
                {
                    "option_id": "option-c",
                    "title": "Retry with narrower participants",
                    "description": "Run another pass focused on the highest-uncertainty voices.",
                },
            ],
        }

    def _diagnose_conflicts(
        self,
        outputs: List[Dict[str, Any]],
        budget_exhausted: bool = False,
        budget_exhausted_reasons: List[str] | None = None,
    ) -> Dict[str, Any]:
        high_uncertainty = [output for output in outputs if output["uncertainty"] == "high"]
        author_boundary_reasons = []
        if high_uncertainty:
            author_boundary_reasons.append("unresolved high-uncertainty participant representation")
        if budget_exhausted:
            author_boundary_reasons.extend(budget_exhausted_reasons or ["budget_exhausted"])
        return {
            "conflicts": [],
            "gaps": [
                {
                    "participant_id": output["participant_id"],
                    "represents": output["represents"],
                    "detail": "Participant lacks canon anchors.",
                }
                for output in high_uncertainty[:8]
            ],
            "weak_proposals": [
                output
                for output in outputs
                if output["uncertainty"] == "high" and output["round"] == 1
            ][:8],
            "budget_exhausted": budget_exhausted,
            "requires_author_boundary": bool(author_boundary_reasons),
            "author_boundary_reasons": author_boundary_reasons,
        }

    def _approval_package(
        self,
        synthesis: Dict[str, Any],
        diagnosis: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "approval_options": [
                "approve option-a",
                "approve option-b",
                "hold for later",
                "retry focused pass",
            ],
            "proposed_tickets": [
                {
                    "ticket_type": "orchestrator_candidate",
                    "title": option["title"],
                    "status": "draft_until_author_decision",
                }
                for option in synthesis["draft_options"]
            ],
            "requires_author_boundary": diagnosis["requires_author_boundary"],
        }


def find_orchestrator_run(workspace: Path, run_id: str) -> tuple[WorldRecord, Path, Dict[str, Any]]:
    for world in list_worlds(workspace):
        root = safe_child_path(world.path, "orchestrator_runs")
        if not root.exists():
            continue
        for path in sorted(root.glob("*/run.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("run_id") == run_id:
                return world, path, payload
    raise KeyError(f"orchestrator run not found: {run_id}")


def _report_id_for_run(repo: WorldRepository, run_id: str) -> str:
    for report in repo.list_reports():
        if report.purpose == "orchestrator_run" and report.payload.get("run_id") == run_id:
            return report.report_id
    raise KeyError(f"orchestrator report not found for run: {run_id}")
