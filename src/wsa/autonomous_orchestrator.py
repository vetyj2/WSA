from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .ids import slugify
from .orchestrator_bridge import initialize_bridge_payload, is_hermes_bridge_mode
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
from .orchestrator_turns import (
    build_actor_turn_record,
    build_initial_actor_states,
    build_initial_floor_state,
    build_manager_check_turn_records,
    build_orchestrator_turn_record,
    build_round_prompt_packet,
    build_scheduler_decision,
    update_actor_states,
    update_floor_state,
)
from .orchestrator_workflows import (
    build_workflow_profile,
    default_participants_for_profile,
    normalize_workflow,
    profile_expected_output_fields,
)
from .paths import safe_child_path
from .reports import ReportMailbox
from .repositories import EntityRecord, TicketRecord, WorldRepository, new_id
from .scene_modes import (
    build_actor_contribution_summary,
    build_scene_mode_disclosure,
    update_scene_mode_disclosure_for_outputs,
)
from .transport import RuntimeTransport
from .workspace import WorldRecord, list_worlds, utc_now


SCENE_FILTER_CONTRACT_SCHEMA = "wsa.scene.filter_contract.v1"


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


def build_scene_filter_contract(
    time_scope: str | None = None,
    location_scope: str | None = None,
    viewpoint: str | None = None,
    conditions: Iterable[str] | None = None,
    known_dimension_keys: Iterable[str] | None = None,
    selector_result: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a scene filter contract without requiring every dimension to exist."""

    condition_list = [
        item.strip()
        for item in (conditions or [])
        if isinstance(item, str) and item.strip()
    ]
    known_dimensions = {
        item.strip()
        for item in (known_dimension_keys or [])
        if isinstance(item, str) and item.strip()
    }
    parsed_dimensions = [
        item for item in (_condition_dimension_key(condition) for condition in condition_list) if item
    ]
    missing_dimensions = sorted(
        {dimension for dimension in parsed_dimensions if dimension not in known_dimensions}
    )
    requested = bool(time_scope or location_scope or viewpoint or condition_list)
    gap_diagnostics = []
    if condition_list and not known_dimensions:
        gap_diagnostics.append(
            {
                "gap_type": "dynamic_dimension_registry_empty_or_unavailable",
                "detail": (
                    "Scene conditions were recorded, but no registered dynamic "
                    "dimensions are available yet."
                ),
                "conditions": condition_list,
            }
        )
    if missing_dimensions:
        gap_diagnostics.append(
            {
                "gap_type": "missing_dynamic_dimensions",
                "detail": "Scene conditions reference dimensions that are not defined yet.",
                "dimension_keys": missing_dimensions,
            }
        )
    return {
        "schema": SCENE_FILTER_CONTRACT_SCHEMA,
        "status": "declared" if requested else "not_requested",
        "time_scope": time_scope.strip() if isinstance(time_scope, str) and time_scope.strip() else None,
        "location_scope": (
            location_scope.strip()
            if isinstance(location_scope, str) and location_scope.strip()
            else None
        ),
        "viewpoint": viewpoint.strip() if isinstance(viewpoint, str) and viewpoint.strip() else None,
        "conditions": condition_list,
        "parsed_dimension_keys": parsed_dimensions,
        "dynamic_dimension_policy": {
            "unknown_dimension_behavior": "report_gap_not_error",
            "missing_attribute_behavior": "return_scene_prep_gap",
            "canon_mutation": "not_allowed_by_filter_contract",
        },
        "dynamic_graph_contract": {
            "dimension_registry": "dimension_definitions",
            "attribute_source": "entity_attribute_spans",
            "relationship_source": "world_edges",
            "knowledge_source": "knowledge_attributions",
            "known_dimension_keys": sorted(known_dimensions),
            "missing_dimension_keys": missing_dimensions,
        },
        "resolution_policy": (
            "record_filter_intent_now; query temporal graph data when dimensions and spans exist"
        ),
        "selector_result": selector_result or {
            "status": "not_run",
            "matched_entity_ids": [],
            "matched_entities": [],
            "applied_conditions": [],
            "gap_diagnostics": [],
        },
        "gap_diagnostics": gap_diagnostics,
    }


def resolve_scene_filter_contract(
    repo: WorldRepository,
    time_scope: str | None = None,
    location_scope: str | None = None,
    viewpoint: str | None = None,
    conditions: Iterable[str] | None = None,
) -> Dict[str, Any]:
    known_dimensions = [item.dimension_key for item in repo.list_dimension_definitions()]
    selector_result = select_scene_entities(
        repo,
        time_scope=time_scope,
        location_scope=location_scope,
        conditions=conditions,
        known_dimension_keys=known_dimensions,
    )
    return build_scene_filter_contract(
        time_scope=time_scope,
        location_scope=location_scope,
        viewpoint=viewpoint,
        conditions=conditions,
        known_dimension_keys=known_dimensions,
        selector_result=selector_result,
    )


def select_scene_entities(
    repo: WorldRepository,
    time_scope: str | None = None,
    location_scope: str | None = None,
    conditions: Iterable[str] | None = None,
    known_dimension_keys: Iterable[str] | None = None,
    limit: int = 12,
) -> Dict[str, Any]:
    """Resolve simple scene filters against sparse temporal graph data."""

    known = set(known_dimension_keys or [])
    parsed = [_parse_scene_condition(item) for item in (conditions or [])]
    parsed = [item for item in parsed if item is not None]
    gap_diagnostics: List[Dict[str, Any]] = []
    applied_conditions: List[Dict[str, Any]] = []
    candidate_ids: set[str] | None = None

    for condition in parsed:
        key = condition["dimension_key"]
        if key not in known:
            continue
        spans = repo.query_entity_attribute_spans(
            dimension_key=key,
            as_of=time_scope,
        )
        matched_ids = {
            span.entity_id
            for span in spans
            if span.status not in {"rejected", "deprecated"}
            and _span_matches_condition(span, condition)
        }
        applied_conditions.append(
            {
                "condition": condition["raw"],
                "dimension_key": key,
                "operator": condition["operator"],
                "matched_count": len(matched_ids),
            }
        )
        candidate_ids = matched_ids if candidate_ids is None else candidate_ids & matched_ids

    if location_scope:
        location_ids = _location_candidate_ids(repo, location_scope, time_scope)
        if location_ids:
            applied_conditions.append(
                {
                    "condition": f"location_scope = {location_scope}",
                    "dimension_key": "current_location",
                    "operator": "=",
                    "matched_count": len(location_ids),
                }
            )
            candidate_ids = location_ids if candidate_ids is None else candidate_ids & location_ids
        else:
            gap_diagnostics.append(
                {
                    "gap_type": "location_scope_not_resolved",
                    "detail": "No current_location attribute matched the requested location scope.",
                    "location_scope": location_scope,
                }
            )

    unsupported = [
        item.strip()
        for item in (conditions or [])
        if isinstance(item, str) and item.strip() and _parse_scene_condition(item) is None
    ]
    if unsupported:
        gap_diagnostics.append(
            {
                "gap_type": "unsupported_scene_condition_syntax",
                "detail": "Only simple operator conditions are resolved locally.",
                "conditions": unsupported,
            }
        )

    if candidate_ids is None:
        candidate_ids = set()
    entities = [
        entity
        for entity in repo.list_entities(status="active")
        if entity.entity_id in candidate_ids
    ][:limit]
    return {
        "status": "resolved" if applied_conditions else "no_resolvable_conditions",
        "time_scope": time_scope,
        "location_scope": location_scope,
        "matched_entity_ids": [entity.entity_id for entity in entities],
        "matched_entities": [
            {
                "entity_id": entity.entity_id,
                "display_name": entity.display_name,
                "entity_type": entity.entity_type,
            }
            for entity in entities
        ],
        "candidate_count": len(candidate_ids),
        "result_limit": limit,
        "applied_conditions": applied_conditions,
        "gap_diagnostics": gap_diagnostics,
    }


def _condition_dimension_key(condition: str) -> str | None:
    operators = (">=", "<=", "==", "!=", ">", "<", "=")
    for operator in operators:
        if operator in condition:
            key = condition.split(operator, 1)[0].strip()
            return key.replace(" ", "_") if key else None
    return None


def _parse_scene_condition(condition: str) -> Dict[str, Any] | None:
    if not isinstance(condition, str):
        return None
    for operator in (">=", "<=", "==", "!=", ">", "<", "="):
        if operator in condition:
            key, raw_value = condition.split(operator, 1)
            key = key.strip().replace(" ", "_")
            raw_value = raw_value.strip()
            if not key or not raw_value:
                return None
            value_number = _as_number(raw_value)
            return {
                "raw": condition.strip(),
                "dimension_key": key,
                "operator": operator,
                "value_text": raw_value,
                "value_number": value_number,
            }
    return None


def _as_number(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _span_matches_condition(span: Any, condition: Dict[str, Any]) -> bool:
    operator = condition["operator"]
    if condition.get("value_number") is not None and span.value_number is not None:
        return _compare_numbers(span.value_number, condition["value_number"], operator)
    actual = span.value_text or span.value_ref_id
    expected = condition["value_text"]
    if actual is None:
        return False
    if operator in {"=", "=="}:
        return str(actual).casefold() == expected.casefold()
    if operator == "!=":
        return str(actual).casefold() != expected.casefold()
    return False


def _compare_numbers(actual: float, expected: float, operator: str) -> bool:
    if operator == ">=":
        return actual >= expected
    if operator == "<=":
        return actual <= expected
    if operator == ">":
        return actual > expected
    if operator == "<":
        return actual < expected
    if operator in {"=", "=="}:
        return actual == expected
    if operator == "!=":
        return actual != expected
    return False


def _location_candidate_ids(
    repo: WorldRepository,
    location_scope: str,
    time_scope: str | None,
) -> set[str]:
    location_entities = {
        entity.entity_id
        for entity in repo.list_entities(status="active")
        if entity.display_name.casefold() == location_scope.casefold()
    }
    matches = set()
    for span in repo.query_entity_attribute_spans(
        dimension_key="current_location",
        as_of=time_scope,
    ):
        if span.status in {"rejected", "deprecated"}:
            continue
        if span.value_text and span.value_text.casefold() == location_scope.casefold():
            matches.add(span.entity_id)
        if span.value_ref_id and span.value_ref_id in location_entities:
            matches.add(span.entity_id)
    return matches


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
        scene_filter_contract: Dict[str, Any] | None = None,
        prep_review: bool = True,
        scene_generation_mode: str | None = None,
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
        workflow_requested = workflow
        workflow = normalize_workflow(workflow)
        skill_name = skill or workflow
        workflow_profile = build_workflow_profile(workflow_requested, skill_name)
        if workflow == "scene_generation" and scene_filter_contract is None:
            scene_filter_contract = build_scene_filter_contract()
        scene_mode_disclosure = build_scene_mode_disclosure(
            workflow,
            skill_name,
            scene_generation_mode,
        )
        participant_plan = self._plan_participants(
            participants,
            topic,
            workflow,
            workflow_profile,
        )
        actor_states = build_initial_actor_states(participant_plan, workflow_profile)
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
        plan_frame = build_plan_frame(
            workflow,
            skill_name,
            topic,
            question,
            frame_plan,
            workflow_profile,
        )
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
            workflow_profile,
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
            "workflow_requested": workflow_requested,
            "skill": skill_name,
            "workflow_profile": workflow_profile,
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
            "progress_report_policy": session_contract["progress_report_policy"],
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
            "scene_mode_disclosure": scene_mode_disclosure,
            "actor_contribution_summary": build_actor_contribution_summary([]),
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
        if scene_filter_contract is not None:
            plan["scene_filter_contract"] = scene_filter_contract
        prep_review_policy = {
            "schema": "wsa.orchestrator.prep_review_policy.v1",
            "required": bool(prep_review),
            "default": "required",
            "opt_out": "--no-prep-review",
            "scope": "hermes_bridge_before_first_actor_turn",
            "purpose": (
                "Let Hermes/user inspect requirement parsing, selected context bundles, "
                "gaps, participants, and queue limits before spending actor/subagent calls."
            ),
        }
        plan["prep_review_policy"] = prep_review_policy
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
                workflow_profile,
                scene_filter_contract,
            )
            context_packet["actor_state"] = actor_states[participant["participant_id"]]
            context_packet["prompt_packet"]["actor_state_seed"] = context_packet["actor_state"]
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

        prep_report = self._prep_report(
            run_id,
            workflow,
            skill_name,
            topic,
            question,
            frame_plan,
            participant_plan,
            context_packets,
            scene_filter_contract,
            plan,
            prep_review_policy,
        )
        lifecycle.append({"state": "subsessions_running", "at": utc_now()})
        if is_hermes_bridge_mode(mode):
            floor_state = build_initial_floor_state(
                workflow_profile,
                topic,
                question,
                participant_plan,
            )
            lifecycle.append(
                {
                    "state": (
                        "awaiting_prep_review"
                        if prep_review_policy.get("required")
                        else "awaiting_hermes_callback"
                    ),
                    "at": utc_now(),
                }
            )
            run_payload = {
                "schema": ORCHESTRATOR_RUN_SCHEMA,
                "run_id": run_id,
                "status": "awaiting_callback",
                "world_id": self.world.world_id,
                "workflow": workflow,
                "workspace_id": "local",
                "workflow_requested": workflow_requested,
                "skill": skill_name,
                "workflow_profile": workflow_profile,
                "topic": topic,
                "question": question,
                "manual_trigger": True,
                "execution": "autonomous_until_boundary",
                "subsession_execution_mode": "hermes_bridge_pending_callbacks",
                "real_subagent_execution": "pending_user_hermes_runtime_callbacks",
                "execution_owner": "user_hermes_runtime",
                "wsa_role": "orchestration_contract_and_audit_artifacts_only",
                "plan_frame": plan_frame,
                "floor_state": floor_state,
                "actor_states": actor_states,
                "execution_provenance": _execution_provenance(
                    mode="hermes-bridge",
                    artifact_type="runtime_bridge_contract",
                    completed=False,
                ),
                "start_preflight": start_preflight,
                "session_contract": session_contract,
                "context_continuity": session_contract["context_continuity"],
                "floor_continuity": session_contract["floor_continuity"],
                "progress_report_policy": session_contract["progress_report_policy"],
                "prompt_coordination": session_contract["prompt_coordination"],
                "micro_turn_policy": session_contract["micro_turn_policy"],
                "quality_gate": session_contract["quality_gate"],
                "termination_policy": termination_contract,
                "session_cleanup": session_cleanup,
                "concurrency_policy": concurrency_policy,
                "queue_limits": plan["queue_limits"],
                "scene_filter_contract": scene_filter_contract,
                "scene_mode_disclosure": scene_mode_disclosure,
                "actor_contribution_summary": build_actor_contribution_summary([]),
                "prep_review_policy": prep_review_policy,
                "prep_report": prep_report,
                "lifecycle": lifecycle,
                "plan": plan,
                "context_packets": context_packets,
                "manager_session_id": manager_session_id,
                "subsession_session_ids": subsession_session_ids,
                "subagent_prompt_packets": [
                    context_packet["prompt_packet"] for context_packet in context_packets
                ],
                "closed_subsessions": [],
                "close_reason": None,
                "canon_policy": "proposal_only_until_author_approval",
                "world_mutations": [],
                "report_id": None,
            }
            initialize_bridge_payload(run_payload, self.world.world_id)
            run_path = safe_child_path(run_dir, "run.json")
            run_path.write_text(
                json.dumps(run_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.transport.send(
                manager_session_id,
                "outbox",
                role="orchestrator_manager",
                message_type="orchestrator_status",
                world_id=self.world.world_id,
                payload={
                    "run_id": run_id,
                    "status": run_payload["status"],
                    "execution_status": run_payload["execution_status"],
                },
                artifact_refs=[str(run_path)],
            )
            safe_child_path(run_dir, ".wsa_bridge").write_text(
                f"{run_payload['execution_status']}\n",
                encoding="utf-8",
            )
            return OrchestratorRunResult(
                run_id=run_id,
                status=run_payload["status"],
                run_dir=run_dir,
                run_path=run_path,
                report_id="",
                manager_session_id=manager_session_id,
                subsession_session_ids=subsession_session_ids,
            )

        compressed_context_snapshots = []
        round_prompt_packets = []
        turn_records = []
        floor_state = build_initial_floor_state(
            workflow_profile,
            topic,
            question,
            participant_plan,
        )
        for round_index in range(1, queue_turns + 1):
            if round_index > 1:
                lifecycle.append(
                    {
                        "state": "followup_round_running",
                        "at": utc_now(),
                        "round": round_index,
                    }
                )
            turn_records.append(
                build_orchestrator_turn_record(
                    run_id,
                    round_index,
                    workflow_profile,
                    floor_state,
                )
            )
            round_outputs = []
            for context_packet in context_packets:
                actor_state = actor_states.get(context_packet["participant_id"], {})
                scheduler_decision = build_scheduler_decision(
                    context_packet,
                    round_index,
                    actor_state,
                    floor_state,
                )
                round_prompt_packet = build_round_prompt_packet(
                    context_packet,
                    round_index,
                    compressed_context_snapshots[-1] if compressed_context_snapshots else None,
                    workflow_profile,
                    self.world.world_id,
                    actor_state=actor_state,
                    scheduler_decision=scheduler_decision,
                    floor_state=floor_state,
                )
                round_prompt_packets.append(round_prompt_packet)
                output = self._subsession_output(context_packet, round_index)
                output["prompt_packet_id"] = round_prompt_packet["prompt_packet_id"]
                output["quality_gate"] = self._quality_gate(output)
                if output["quality_gate"]["accepted"]:
                    subsession_outputs.append(output)
                    round_outputs.append(output)
                    actor_states = update_actor_states(actor_states, round_prompt_packet, output)
                turn_records.append(
                    build_actor_turn_record(round_prompt_packet, output)
                )
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
            turn_records.extend(
                build_manager_check_turn_records(run_id, round_index, round_outputs)
            )
            floor_state = update_floor_state(
                floor_state,
                round_index,
                round_outputs,
                turn_records,
                actor_states,
            )

        lifecycle.append({"state": "synthesizing", "at": utc_now()})
        synthesis = self._synthesize(
            topic,
            question,
            participant_plan,
            subsession_outputs,
            workflow_profile,
            scene_filter_contract,
        )
        lifecycle.append({"state": "diagnosing_conflicts", "at": utc_now()})
        diagnosis = self._diagnose_conflicts(
            subsession_outputs,
            budget_exhausted,
            budget_exhausted_reasons,
        )
        actor_contribution_summary = build_actor_contribution_summary(
            subsession_outputs,
            final_synthesizer="wsa_local_simulated_synthesis",
            actor_authorship_evidence=False,
        )
        scene_mode_disclosure = update_scene_mode_disclosure_for_outputs(
            scene_mode_disclosure,
            actor_contribution_summary,
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
            "workflow_requested": workflow_requested,
            "skill": skill_name,
            "workflow_profile": workflow_profile,
            "topic": topic,
            "question": question,
            "manual_trigger": True,
            "execution": "autonomous_until_boundary",
            "subsession_execution_mode": "local_simulated_outputs",
            "real_subagent_execution": "hermes_runtime_owned_not_performed_by_wsa_cli",
            "execution_owner": "user_hermes_runtime",
            "wsa_role": "orchestration_contract_and_audit_artifacts_only",
            "plan_frame": plan_frame,
            "floor_state": floor_state,
            "actor_states": actor_states,
            "execution_provenance": _execution_provenance(
                mode="local-simulated",
                artifact_type="wsa_local_simulated_proposal",
                completed=True,
            ),
            "start_preflight": start_preflight,
            "session_contract": session_contract,
            "context_continuity": session_contract["context_continuity"],
            "floor_continuity": session_contract["floor_continuity"],
            "progress_report_policy": session_contract["progress_report_policy"],
            "prompt_coordination": session_contract["prompt_coordination"],
            "micro_turn_policy": session_contract["micro_turn_policy"],
            "quality_gate": session_contract["quality_gate"],
            "termination_policy": termination_contract,
            "session_cleanup": session_cleanup,
            "concurrency_policy": concurrency_policy,
            "queue_limits": plan["queue_limits"],
            "scene_filter_contract": scene_filter_contract,
            "scene_mode_disclosure": scene_mode_disclosure,
            "actor_contribution_summary": actor_contribution_summary,
            "prep_review_policy": prep_review_policy,
            "prep_report": prep_report,
            "lifecycle": lifecycle,
            "plan": plan,
            "context_packets": context_packets,
            "subagent_prompt_packets": [
                context_packet["prompt_packet"] for context_packet in context_packets
            ],
            "round_prompt_packets": round_prompt_packets,
            "runtime_hook_packets": round_prompt_packets,
            "turn_records": turn_records,
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
        workflow_profile: Dict[str, Any],
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
            labels = default_participants_for_profile(workflow_profile, workflow)
        return [
            {
                "participant_id": f"P{index:03d}",
                "label": label,
                "role": "representative_voice",
                "scope": "topic_relevant_context_only",
                "workflow_role": workflow_profile.get("workflow", workflow),
            }
            for index, label in enumerate(labels, start=1)
        ]

    def _prep_report(
        self,
        run_id: str,
        workflow: str,
        skill_name: str,
        topic: str,
        question: str,
        frame_plan: str | None,
        participant_plan: List[Dict[str, Any]],
        context_packets: List[Dict[str, Any]],
        scene_filter_contract: Dict[str, Any] | None,
        plan: Dict[str, Any],
        prep_review_policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        selector = (
            scene_filter_contract.get("selector_result", {})
            if isinstance(scene_filter_contract, dict)
            else {}
        )
        graph_contract = (
            scene_filter_contract.get("dynamic_graph_contract", {})
            if isinstance(scene_filter_contract, dict)
            else {}
        )
        scene_gaps = (
            scene_filter_contract.get("gap_diagnostics", [])
            if isinstance(scene_filter_contract, dict)
            else []
        )
        selector_gaps = selector.get("gap_diagnostics", []) if isinstance(selector, dict) else []
        participant_bundles = [
            {
                "participant_id": packet["participant_id"],
                "represents": packet["represents"],
                "entity_id": packet.get("entity_id"),
                "canon_anchor_count": len(packet.get("canon_anchors", [])),
                "expected_output": packet.get("expected_output", []),
            }
            for packet in context_packets
        ]
        status = "ready"
        if scene_gaps or selector_gaps:
            status = "ready_with_gaps"
        if prep_review_policy.get("required"):
            status = f"{status}_pending_review"
        return {
            "schema": "wsa.orchestrator.prep_report.v1",
            "run_id": run_id,
            "status": status,
            "workflow": workflow,
            "skill": skill_name,
            "generated_at": utc_now(),
            "requirement_parse": {
                "topic": topic,
                "question": question,
                "frame_plan": frame_plan,
                "scene_time_scope": (
                    scene_filter_contract.get("time_scope")
                    if isinstance(scene_filter_contract, dict)
                    else None
                ),
                "scene_location_scope": (
                    scene_filter_contract.get("location_scope")
                    if isinstance(scene_filter_contract, dict)
                    else None
                ),
                "scene_viewpoint": (
                    scene_filter_contract.get("viewpoint")
                    if isinstance(scene_filter_contract, dict)
                    else None
                ),
                "conditions": (
                    scene_filter_contract.get("conditions", [])
                    if isinstance(scene_filter_contract, dict)
                    else []
                ),
                "parsed_dimension_keys": (
                    scene_filter_contract.get("parsed_dimension_keys", [])
                    if isinstance(scene_filter_contract, dict)
                    else []
                ),
            },
            "selected_context_bundles": {
                "participant_context": participant_bundles,
                "scene_selector": selector,
                "dynamic_graph_contract": graph_contract,
                "queue_limits": plan.get("queue_limits", {}),
            },
            "gap_diagnostics": scene_gaps + selector_gaps,
            "review_options": [
                "approve_prep_and_run",
                "hold_and_refine_request",
                "restart_with_more_participants_or_conditions",
                "opt_out_with_no_prep_review",
            ],
            "side_effect_status": "no_actor_calls_before_prep_approval_when_required",
        }

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
        workflow_profile: Dict[str, Any],
        scene_filter_contract: Dict[str, Any] | None = None,
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
        expected_fields = profile_expected_output_fields(workflow_profile)
        relevant_context = {
            "topic": topic,
            "question": question,
            "canon_anchors": anchors,
        }
        if scene_filter_contract is not None:
            relevant_context["scene_filter_contract"] = scene_filter_contract
        prompt_packet = {
            "schema": "wsa.orchestrator.subagent_prompt_packet.v1",
            "run_id": run_id,
            "skill": skill_name,
            "workflow": workflow,
            "workflow_profile": workflow_profile.get("workflow", workflow),
            "participant_id": participant["participant_id"],
            "represents": participant["label"],
            "execution_owner": "user_hermes_runtime",
            "role_instruction": (
                f"Represent {participant['label']} for this isolated WSA {skill_name} session. "
                "Stay within the relevant context, mark uncertain claims as provisional, "
                "and answer only the bounded fields requested by the orchestrator."
            ),
            "relevant_context": relevant_context,
            "floor_continuity": {
                "meeting_floor": "same_live_floor_until_chair_close_or_hard_limit",
                "context_mode": "compressed_floor_summary_plus_relevant_recent_outputs",
            },
            "expected_output": expected_fields,
            "workflow_phase_model": workflow_profile.get("phase_model", []),
            "facilitation_hooks": workflow_profile.get("dynamic_facilitation_hooks", []),
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
            "expected_output": expected_fields,
            "workflow_profile": {
                "workflow": workflow_profile.get("workflow", workflow),
                "title": workflow_profile.get("title"),
                "purpose": workflow_profile.get("purpose"),
            },
            "context_scope": "minimal_relevant_context",
            "context_continuity": {
                "policy": context_policy,
                "compression": "rolling_summary_plus_recent_outputs",
                "share_policy": "participant_relevant_context_only",
            },
            "canon_anchors": anchors,
            "scene_filter_contract": scene_filter_contract,
            "prompt_packet": prompt_packet,
            "proposal_policy": "do_not_mutate_canon",
        }

    def _subsession_output(self, context_packet: Dict[str, Any], round_index: int) -> Dict[str, Any]:
        label = context_packet["represents"]
        grounded = bool(context_packet.get("canon_anchors"))
        uncertainty = "medium" if grounded else "high"
        output = {
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
        workflow = context_packet.get("workflow_profile", {}).get("workflow")
        if workflow == "scene_generation":
            output.update(
                {
                    "scene_relevance": (
                        f"{label} identifies which facts or memories should affect the scene prep."
                    ),
                    "facts_to_include": [
                        "Use only facts that affect scene stakes, viewpoint, or causality."
                    ],
                    "facts_to_hide": [
                        "Keep hidden truths out of actor packets unless the viewpoint should know them."
                    ],
                    "memory_filter": "Separate character memory from author/workflow notes.",
                    "actor_assignment": f"Treat {label} as a bounded scene-prep role until casting is approved.",
                    "role_isolation": "If one session plays multiple roles, isolate voice, memory, and objectives per role.",
                    "viewpoint_constraints": "Do not reveal unavailable knowledge to the viewpoint actor.",
                    "scene_beat": f"Draft one provisional beat pressure for {label}.",
                    "model_thinking_recommendation": (
                        "Use higher thinking for canon or hidden-truth checks; use bounded turns for single-role actors."
                    ),
                    "risk_flags": [
                        "verify timeline/location before script drafting",
                        "avoid mixing multi-role memory",
                    ],
                    "confidence": "medium" if grounded else "low",
                }
            )
        else:
            output.update(
                {
                    "stance": "support_with_conditions" if grounded else "provisional",
                    "answer": (
                        f"{label} can contribute if its authority, needs, and constraints are explicit."
                    ),
                    "new_claims": [],
                    "dependencies": [
                        "author approval before canon conversion",
                        "manager check for unsupported claims",
                    ],
                    "conflicts": [],
                    "worldbuilding_use": "candidate meeting material only",
                    "confidence": "medium" if grounded else "low",
                    "next_actor_suggestion": "conflict_diagnostician"
                    if uncertainty == "high"
                    else "proposal_builder",
                }
            )
        for field in context_packet.get("expected_output", []):
            output.setdefault(field, [] if field.endswith("s") else "provisional")
        return output

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
            "rejects_empty_agreement": True,
            "rejects_unbounded_lore_dump": True,
            "rejects_unlabeled_uncertainty": True,
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
        workflow_profile: Dict[str, Any],
        scene_filter_contract: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        participant_labels = [item["label"] for item in participants]
        if workflow_profile.get("workflow") == "scene_generation":
            draft_options = [
                {
                    "option_id": "option-a",
                    "title": "Approve scene-prep package only",
                    "description": "Accept filtered facts, actor packets, role isolation notes, and stop before drafting.",
                },
                {
                    "option_id": "option-b",
                    "title": "Retry focused prep on risky actor assignments",
                    "description": "Run another pass on multi-role isolation, hidden information, or model/thinking allocation.",
                },
                {
                    "option_id": "option-c",
                    "title": "Hold for author scene direction",
                    "description": "Pause before actor/session calls until the author clarifies scene goal or viewpoint.",
                },
            ]
        else:
            draft_options = [
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
            ]
        synthesis = {
            "summary": (
                f"Autonomous orchestrator ran {len(outputs)} subsession outputs "
                f"for {len(participants)} participants in {workflow_profile.get('workflow')} mode."
            ),
            "topic": topic,
            "question": question,
            "workflow": workflow_profile.get("workflow"),
            "workflow_title": workflow_profile.get("title"),
            "participant_labels": participant_labels,
            "draft_options": draft_options,
            "structured_appendix": {
                "canon_anchors": "kept separate from generated proposals",
                "participant_proposals": "proposal_only_until_author_approval",
                "turn_record_count": "see turn_records",
                "workflow_phase_ids": [
                    item.get("phase_id")
                    for item in workflow_profile.get("phase_model", [])
                    if isinstance(item, dict)
                ],
            },
        }
        if workflow_profile.get("workflow") == "scene_generation":
            synthesis["scene_prep_package"] = self._scene_prep_package(
                outputs,
                scene_filter_contract,
            )
        return synthesis

    def _scene_prep_package(
        self,
        outputs: List[Dict[str, Any]],
        scene_filter_contract: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        return {
            "schema": "wsa.scene.prep_package.v1",
            "status": "awaiting_author_review",
            "side_effect_status": "proposal_only_no_scene_draft_no_canon_mutation",
            "scene_filter_contract": scene_filter_contract,
            "facts_to_include": _collect_output_values(outputs, "facts_to_include"),
            "facts_to_hide": _collect_output_values(outputs, "facts_to_hide"),
            "actor_assignments": _collect_output_values(outputs, "actor_assignment"),
            "role_isolation": _collect_output_values(outputs, "role_isolation"),
            "viewpoint_constraints": _collect_output_values(outputs, "viewpoint_constraints"),
            "scene_beats": _collect_output_values(outputs, "scene_beat"),
            "model_thinking_recommendations": _collect_output_values(
                outputs,
                "model_thinking_recommendation",
            ),
            "risk_flags": _collect_output_values(outputs, "risk_flags"),
            "prep_completion_check": {
                "status": "requires_author_or_hermes_review",
                "required_before_draft": [
                    "scene goal is explicit",
                    "actor packets are scoped",
                    "hidden facts are separated from viewpoint-visible facts",
                    "role isolation is defined for multi-role sessions",
                    "risk flags are reviewed",
                ],
            },
            "draft_boundary": "author_approval_required_before_script_draft_or_canon_mutation",
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


def _execution_provenance(
    mode: str,
    artifact_type: str,
    completed: bool,
) -> Dict[str, Any]:
    is_bridge = mode in {"hermes-bridge", "hermes_runtime", "hermes-runtime"}
    return {
        "schema": "wsa.orchestrator.execution_provenance.v1",
        "execution_mode": mode,
        "artifact_type": artifact_type,
        "wsa_direct_runtime_execution": False,
        "external_runtime_owner": "user_runtime",
        "real_actor_sessions_executed": (
            "external_runtime_callback_report_only" if is_bridge and completed else False
        ),
        "callback_execution_reported": bool(is_bridge and completed),
        "canon_write_performed": False,
        "startup_profile_write_performed": False,
        "world_mutation_performed": False,
        "requires_author_decision": True,
    }


def _report_id_for_run(repo: WorldRepository, run_id: str) -> str:
    for report in repo.list_reports():
        if report.purpose == "orchestrator_run" and report.payload.get("run_id") == run_id:
            return report.report_id
    raise KeyError(f"orchestrator report not found for run: {run_id}")


def _collect_output_values(
    outputs: List[Dict[str, Any]],
    field: str,
    limit: int = 12,
) -> List[Any]:
    values: List[Any] = []
    for output in outputs:
        value = output.get(field)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            values.extend(item for item in value if item not in (None, "", []))
        else:
            values.append(value)
        if len(values) >= limit:
            return values[:limit]
    return values
