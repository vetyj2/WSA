from __future__ import annotations

from typing import Any, Dict

from .orchestrator_workflows import build_workflow_entrypoint_contracts


ORCHESTRATOR_RUN_SCHEMA = "wsa.orchestrator.run.v1"
ORCHESTRATOR_SESSION_CONTRACT_SCHEMA = "wsa.orchestrator.session_contract.v1"
HERMES_ORCHESTRATOR_RUNTIME_CONTRACT_SCHEMA = "wsa.hermes.orchestrator_runtime_contract.v1"
ORCHESTRATOR_PROGRESS_REPORT_POLICY_SCHEMA = "wsa.orchestrator.progress_report_policy.v1"

DEFAULT_CONTEXT_POLICY = "compressed-continuity"
DEFAULT_MAX_QUEUE_TURNS = 12
DEFAULT_MAX_CONCURRENT_SUBSESSIONS = 4
DEFAULT_MAX_SUBSESSION_CALLS = 48
DEFAULT_TERMINATION_POLICY = "chair_or_conclusion_or_queue_limit"
DEFAULT_UTTERANCE_TARGET = "one_sentence_or_requested_fields"

ORCHESTRATOR_DECISIONS = {"approve", "retry", "hold"}


def build_plan_frame(
    workflow: str,
    skill_name: str,
    topic: str,
    question: str,
    frame_plan: str | None,
    workflow_profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if frame_plan and frame_plan.strip():
        source = "user_defined"
        content = frame_plan.strip()
    else:
        source = "default_guardrail"
        profile_frame = ""
        if workflow_profile:
            profile_frame = str(workflow_profile.get("default_frame") or "").strip()
        if profile_frame:
            content = (
                f"{profile_frame} Topic: '{topic}'. Controlling question: {question}. "
                "Keep all generated material proposal-only, require clear uncertainty labels, "
                "and return to the author before canon mutation."
            )
        else:
            content = (
                f"Run a conservative {skill_name}/{workflow} pass on '{topic}'. "
                f"Answer the controlling question: {question}. Keep all generated material "
                "proposal-only, require clear uncertainty labels, and return to the author "
                "before canon mutation."
            )
    return {
        "schema": "wsa.orchestrator.plan_frame.v1",
        "source": source,
        "content": content,
        "required_before_start": True,
        "guardrails": [
            "proposal_only_until_author_approval",
            "participant_relevant_context_only",
            "no_unbounded_session_growth",
            "close_or_mark_all_ephemeral_sessions_at_boundary",
        ],
        "workflow_profile": workflow_profile.get("workflow") if workflow_profile else workflow,
    }


def build_termination_contract(
    termination_policy: str,
    max_queue_turns: int,
    max_subsession_calls: int,
) -> Dict[str, Any]:
    return {
        "schema": "wsa.orchestrator.termination_policy.v1",
        "policy": termination_policy,
        "chair_authority": "author_or_authorized_hermes_runtime",
        "chair_close_phrase": "today_session_closed",
        "conclusion_reached_criteria": [
            "approval_package_has_2_to_4_actionable_options",
            "conflicts_and_gaps_are_explicitly_listed",
            "uncertainty_is_labeled",
        ],
        "hard_limits": {
            "max_queue_turns": max_queue_turns,
            "max_subsession_calls": max_subsession_calls,
        },
        "fallback_when_no_conclusion": (
            "stop_at_hard_limit_summarize_partial_results_close_ephemeral_sessions"
        ),
    }


def build_session_cleanup_policy(close_on: str) -> Dict[str, Any]:
    return {
        "schema": "wsa.orchestrator.session_cleanup.v1",
        "close_on": close_on,
        "cleanup_required": True,
        "close_unfinished_on_boundary": True,
        "close_reason_required": True,
        "durable_artifact_after_close": "synthesis_report_and_audit_trail",
        "ephemeral_session_policy": "no_abandoned_open_subsessions",
    }


def build_concurrency_policy(
    participant_plan: list[Dict[str, Any]],
    max_concurrent_subsessions: int,
) -> Dict[str, Any]:
    batches = [
        [item["participant_id"] for item in participant_plan[index : index + max_concurrent_subsessions]]
        for index in range(0, len(participant_plan), max_concurrent_subsessions)
    ]
    return {
        "schema": "wsa.orchestrator.concurrency_policy.v1",
        "max_concurrent_subsessions": max_concurrent_subsessions,
        "participant_count": len(participant_plan),
        "batching_required": len(participant_plan) > max_concurrent_subsessions,
        "batches": batches,
        "diagnosis": (
            "batched_to_limit_parallel_context_pressure"
            if len(participant_plan) > max_concurrent_subsessions
            else "within_limit"
        ),
    }


def build_progress_report_policy(
    max_rounds: int,
    max_subsession_calls: int,
) -> Dict[str, Any]:
    return {
        "schema": ORCHESTRATOR_PROGRESS_REPORT_POLICY_SCHEMA,
        "availability": "optional_runtime_opt_in",
        "enabled_by_default": False,
        "delivery_owner": "user_hermes_runtime",
        "wsa_role": "declare_policy_only_no_user_delivery",
        "policy": "round_boundary_only",
        "allow_mid_round_report": False,
        "templates": {
            "ko": "라운드 {round}/{max_rounds} 현황 — {summary}",
            "en": "Round {round}/{max_rounds} status — {summary}",
            "with_turn_ko": "라운드 {round}/{max_rounds}, 턴 {turn}/{max_turns} 현황 — {summary}",
            "with_turn_en": "Round {round}/{max_rounds}, turn {turn}/{max_turns} status — {summary}",
        },
        "round_state": {
            "max_rounds": max_rounds,
            "max_turns": max_subsession_calls,
            "if_rounds_unavailable": (
                "compute_stable_checkpoint_or_state_no_round_state_exists"
            ),
        },
        "interim_report_rules": [
            "send_only_at_explicit_round_or_checkpoint_boundary",
            "include_current_round_and_max_rounds_when_available",
            "include_current_turn_and_max_turns_when_turns_are_reported",
            "avoid_unlabelled_in_progress_messages",
        ],
        "allowed_mid_round_exceptions": [
            "user_interrupt_or_stop_signal",
            "runtime_error",
            "approval_or_canon_boundary",
            "background_process_completion",
            "background_process_failure",
        ],
        "final_report_required_fields": [
            "stop_reason",
            "side_effect_status",
        ],
        "stop_reason_values": [
            "conclusion_reached",
            "author_boundary",
            "max_round_or_turn_budget",
            "error_or_interruption",
        ],
        "side_effect_status_values": [
            "proposal_only_no_world_mutation",
            "awaiting_author_approval",
            "approved_ticket_created_only",
        ],
    }


def build_start_preflight(
    plan_frame: Dict[str, Any],
    termination_contract: Dict[str, Any],
    session_cleanup: Dict[str, Any],
    concurrency_policy: Dict[str, Any],
) -> Dict[str, Any]:
    checks = {
        "plan_frame_defined": bool(plan_frame.get("content")),
        "termination_defined": bool(termination_contract.get("policy")),
        "queue_limits_defined": bool(termination_contract.get("hard_limits")),
        "cleanup_policy_defined": bool(session_cleanup.get("cleanup_required")),
        "concurrency_limit_defined": bool(
            concurrency_policy.get("max_concurrent_subsessions")
        ),
    }
    ready = all(checks.values())
    return {
        "schema": "wsa.orchestrator.start_preflight.v1",
        "status": "ready" if ready else "blocked",
        "frame_source": plan_frame["source"],
        "checks": checks,
        "start_recommendation": (
            "allowed_with_user_frame"
            if plan_frame["source"] == "user_defined"
            else "allowed_with_conservative_default_guardrails"
        )
        if ready
        else "do_not_start_until_plan_frame_and_limits_are_defined",
    }


def build_orchestrator_session_contract(
    run_id: str,
    world_id: str,
    workflow: str,
    skill_name: str,
    mode: str,
    max_queue_turns: int,
    max_concurrent_subsessions: int,
    max_subsession_calls: int,
    context_policy: str,
    plan_frame: Dict[str, Any],
    termination_contract: Dict[str, Any],
    session_cleanup: Dict[str, Any],
    workflow_profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = {
        "schema": ORCHESTRATOR_SESSION_CONTRACT_SCHEMA,
        "execution_owner": "user_hermes_runtime",
        "wsa_role": "orchestration_contract_and_audit_artifacts_only",
        "hermes_runtime_role": (
            "Owns subagent invocation, prompt execution, external delivery, "
            "approval UX, scheduling, and process management."
        ),
        "wsa_cli_execution_note": (
            "The template CLI records prompt packets and deterministic simulated outputs. "
            "Real subagent execution is owned by the user's Hermes runtime."
        ),
        "orchestrator_role": {
            "summary": (
                "Maintain one isolated meeting-like work session after a manual trigger, "
                "compressing shared context and coordinating subagent prompt packets until "
                "a review boundary or queue limit is reached."
            ),
            "responsibilities": [
                "keep the meeting floor open until the chair/author boundary or a hard limit",
                "plan temporary representative subsessions",
                "prepare participant-relevant context packets",
                "carry forward compressed meeting memory between queue turns",
                "adjust follow-up prompts from collected outputs",
                "ask short targeted prompts and accumulate only quality-gated outputs",
                "synthesize a review package before any canon mutation",
                "close or mark temporary subsessions complete after the package is produced",
            ],
        },
        "plan_frame": plan_frame,
        "skill_scope": {
            "skill": skill_name,
            "workflow": workflow,
            "mode": mode,
            "run_id": run_id,
            "world_id": world_id,
            "isolation": "per_orchestrator_run",
            "memory_scope": "orchestrator_run_only",
        },
        "context_continuity": {
            "policy": context_policy,
            "compression": "rolling_summary_plus_recent_outputs",
            "carry_forward_between_queue_turns": True,
            "share_policy": "participant_relevant_context_only",
            "subsession_context_is_pruned": True,
        },
        "floor_continuity": {
            "model": "live_meeting_floor",
            "floor_stays_open_until": [
                "chair_or_author_closes_session",
                "conclusion_reached",
                "max_queue_turns_reached",
                "max_subsession_calls_reached",
                "safety_or_authority_boundary",
            ],
            "all_participants_receive_continuity": True,
            "continuity_payload": "compressed_floor_summary_plus_relevant_recent_outputs",
            "chair_role": "author_or_authorized_hermes_runtime",
        },
        "progress_report_policy": build_progress_report_policy(
            max_rounds=max_queue_turns,
            max_subsession_calls=max_subsession_calls,
        ),
        "prompt_coordination": {
            "owner": "orchestrator_manager",
            "hermes_executes_subagent_calls": True,
            "subagent_invocation_owner": "user_hermes_runtime",
            "prompt_packets": (
                "WSA records desired role, context, constraints, and expected output. "
                "Hermes adapts these packets to its own subagent/session syntax."
            ),
            "user_babysitting": "not_required_until_author_boundary",
        },
        "runtime_bridge_contract": {
            "schema": "wsa.runtime_bridge.contract.v1",
            "runner_agnostic": True,
            "wsa_owns": [
                "run_state",
                "actor_state",
                "floor_state",
                "hook_packet_generation",
                "callback_validation",
                "quality_gate_records",
                "approval_package",
            ],
            "external_runtime_owns": [
                "actor_or_subagent_invocation",
                "model_provider_selection",
                "process_or_session_lifecycle",
                "delivery_to_user",
                "interrupt_execution",
                "cleanup_execution",
            ],
            "callback_contract": {
                "turn_id_required": True,
                "route_must_match_pending_hook": True,
                "callback_dir": "hermes/callbacks",
                "canon_mutation_forbidden": True,
            },
        },
        "actor_state_policy": {
            "schema": "wsa.orchestrator.actor_state_policy.v1",
            "durable_per_actor": True,
            "carried_into_later_prompts": True,
            "tracks": [
                "role_identity",
                "stable_mandate",
                "scope_boundaries",
                "last_claims",
                "objections_made",
                "objections_received",
                "unanswered_questions",
                "stance_changes",
                "confidence_history",
                "identity_drift_warnings",
            ],
        },
        "scheduler_policy": {
            "turn_based": True,
            "round_is_reporting_unit_only": True,
            "equal_airtime_not_required": True,
            "actor_selection_reasons_required": True,
            "priority_order": [
                "manager_check_for_risky_claim",
                "orchestrator_focus_turn_for_messy_floor",
                "blocking_objection_owner",
                "candidate_falsification_actor",
                "focused_followup_actor",
                "small_parallel_read_only_batch",
            ],
        },
        "micro_turn_policy": {
            "utterance_target": DEFAULT_UTTERANCE_TARGET,
            "prompt_budget_posture": "minimal_precise_subsession_calls",
            "instruction_style": (
                "Ask for one sentence or a clearly bounded expected field whenever possible."
            ),
            "subsubsessions": "allowed_only_when_needed_and_same_budget_rules_apply",
        },
        "quality_gate": {
            "accumulate_only_accepted_outputs": True,
            "required_fields": [
                "position",
                "objections",
                "proposals",
                "gaps",
                "uncertainty",
            ],
            "reject_or_retry_if": [
                "missing_required_field",
                "uncertainty_unlabeled",
                "empty_agreement",
                "repetition_without_new_information",
                "unbounded_lore_dump",
                "canon_mutation_attempt",
            ],
            "deepening_hook": (
                "if consensus is shallow, ask who pays, who loses, where the rule fails, "
                "which edge case breaks it, or which region/class/institution experiences it differently"
            ),
        },
        "termination_policy": termination_contract,
        "session_cleanup": session_cleanup,
        "queue_limits": {
            "default_max_queue_turns": DEFAULT_MAX_QUEUE_TURNS,
            "max_queue_turns": max_queue_turns,
            "default_max_concurrent_subsessions": DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
            "max_concurrent_subsessions": max_concurrent_subsessions,
            "default_max_subsession_calls": DEFAULT_MAX_SUBSESSION_CALLS,
            "max_subsession_calls": max_subsession_calls,
            "infinite_loop_guard": True,
            "termination_on_max_queue_turns": True,
        },
    }
    if workflow_profile is not None:
        payload["workflow_profile_summary"] = {
            "workflow": workflow_profile.get("workflow"),
            "title": workflow_profile.get("title"),
            "purpose": workflow_profile.get("purpose"),
            "phase_ids": [
                item.get("phase_id")
                for item in workflow_profile.get("phase_model", [])
                if isinstance(item, dict)
            ],
            "completion_criteria": workflow_profile.get("completion_criteria", []),
        }
        payload["active_facilitation"] = {
            "orchestrator_is_not_stenographer": True,
            "may_spend_turn_without_actor_call": True,
            "may_pause_actor_for_manager_check": True,
            "may_focus_skip_challenge_or_interview": True,
            "dynamic_hooks": workflow_profile.get("dynamic_facilitation_hooks", []),
        }
        payload["participant_output_schema"] = workflow_profile.get(
            "participant_output_schema",
            {},
        )
    return payload


def build_hermes_orchestrator_runtime_contract() -> Dict[str, Any]:
    return {
        "schema": HERMES_ORCHESTRATOR_RUNTIME_CONTRACT_SCHEMA,
        "execution_owner": "user_hermes_runtime",
        "wsa_role": "orchestration_contract_and_audit_artifacts_only",
        "subagent_invocation_owner": "user_hermes_runtime",
        "manual_trigger": True,
        "execution": "autonomous_until_boundary",
        "isolation": "per_orchestrator_run",
        "context_continuity": {
            "default_policy": DEFAULT_CONTEXT_POLICY,
            "compression": "rolling_summary_plus_recent_outputs",
            "memory_scope": "orchestrator_run_only",
            "share_policy": "participant_relevant_context_only",
        },
        "prompt_coordination": {
            "owner": "orchestrator_manager",
            "hermes_adapts_prompt_packets_to_subagent_syntax": True,
            "user_babysitting": "not_required_until_author_boundary",
        },
        "runtime_bridge_contract": {
            "schema": "wsa.runtime_bridge.contract.v1",
            "runner_agnostic": True,
            "compatible_runtime_families": [
                "hermes",
                "codex_or_local_cli_agent",
                "custom_external_actor_runtime",
            ],
            "wsa_does_not_start_runtime": True,
            "external_runtime_executes_actor_calls": True,
        },
        "actor_state_policy": {
            "durable_per_actor": True,
            "carried_into_later_prompts": True,
            "tracks_identity_claims_objections_and_stance_changes": True,
        },
        "scheduler_policy": {
            "turn_based": True,
            "round_is_reporting_unit_only": True,
            "equal_airtime_not_required": True,
            "manager_check_can_pause_risky_claims": True,
        },
        "queue_limits": {
            "default_max_queue_turns": DEFAULT_MAX_QUEUE_TURNS,
            "default_max_concurrent_subsessions": DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
            "default_max_subsession_calls": DEFAULT_MAX_SUBSESSION_CALLS,
            "infinite_loop_guard": True,
            "termination_on_max_queue_turns": True,
        },
        "floor_continuity": {
            "model": "live_meeting_floor",
            "all_participants_receive_compressed_context_until_close": True,
            "chair_closes_floor_or_hard_limit_stops": True,
        },
        "progress_report_policy": build_progress_report_policy(
            max_rounds=DEFAULT_MAX_QUEUE_TURNS,
            max_subsession_calls=DEFAULT_MAX_SUBSESSION_CALLS,
        ),
        "plan_frame_policy": {
            "required_before_start": True,
            "default_guardrail_allowed_when_user_frame_missing": True,
            "start_without_frame_recommendation": "do_not_start",
        },
        "micro_turn_policy": {
            "utterance_target": DEFAULT_UTTERANCE_TARGET,
            "accumulate_only_quality_gated_outputs": True,
            "prompt_budget_posture": "minimal_precise_subsession_calls",
        },
        "session_cleanup": {
            "cleanup_required": True,
            "no_abandoned_open_subsessions": True,
        },
        "side_effect_policy": "proposal_only_until_author_approval",
        "bridge_loop": {
            "schema": "wsa.hermes.orchestrator_bridge_loop.v1",
            "mode": "hermes-bridge",
            "purpose": (
                "Let Hermes execute real subagent or actor calls while WSA owns run state, "
                "quality gates, callback ingestion, and approval boundaries."
            ),
            "start_template": [
                "wsa",
                "orchestrator",
                "run",
                "{world_id}",
                "--workflow",
                "{workflow}",
                "--topic",
                "{topic}",
                "--mode",
                "hermes-bridge",
            ],
            "next_template": [
                "wsa",
                "orchestrator",
                "next",
                "{run_id}",
                "--format",
                "json",
            ],
            "submit_template": [
                "wsa",
                "orchestrator",
                "submit",
                "{run_id}",
                "--callback",
                "{callback_path}",
                "--format",
                "json",
            ],
            "callback_path_policy": "workspace/hermes/callbacks_only",
            "no_new_user_visible_command_required": True,
        },
        "workflow_entrypoints": build_workflow_entrypoint_contracts(),
    }
