from __future__ import annotations

from typing import Any, Dict, List


WORKFLOW_PROFILE_SCHEMA = "wsa.orchestrator.workflow_profile.v1"

WORKFLOW_ALIASES = {
    "meeting": "meetup",
    "meetup": "meetup",
    "council": "meetup",
    "subsession": "meetup",
    "scene": "scene_generation",
    "scene_generation": "scene_generation",
    "scene-generation": "scene_generation",
    "scene_start": "scene_generation",
    "scene-start": "scene_generation",
    "scene_prep": "scene_generation",
    "scene-prep": "scene_generation",
}


def normalize_workflow(workflow: str) -> str:
    key = workflow.strip().casefold().replace(" ", "_")
    return WORKFLOW_ALIASES.get(key, key or "meetup")


def build_workflow_profile(workflow: str, skill_name: str) -> Dict[str, Any]:
    canonical = normalize_workflow(workflow)
    if canonical == "scene_generation":
        return _scene_generation_profile(workflow, skill_name)
    if canonical == "meetup":
        return _meetup_profile(workflow, skill_name)
    return _generic_profile(workflow, skill_name, canonical)


def default_participants_for_profile(profile: Dict[str, Any], workflow: str) -> List[str]:
    defaults = profile.get("default_participants")
    if isinstance(defaults, list) and defaults:
        return [str(item) for item in defaults]
    return ["canon_guardian", "conflict_diagnostician", f"{workflow}_proposal_builder"]


def profile_expected_output_fields(profile: Dict[str, Any]) -> List[str]:
    fields = profile.get("participant_output_schema", {}).get("required_fields", [])
    if isinstance(fields, list) and fields:
        return [str(item) for item in fields]
    return ["position", "objections", "proposals", "gaps", "uncertainty"]


def build_workflow_entrypoint_contracts() -> Dict[str, Any]:
    return {
        "schema": "wsa.orchestrator.workflow_entrypoints.v1",
        "entrypoints": {
            "meetup": {
                "manual_trigger": "/wsa_meetup or wsa orchestrator run --workflow meetup",
                "purpose": "Worldbuilding fact proposals, conflict diagnosis, scene-prep planning, or target-oriented representative meetings.",
                "runtime_boundary": "Hermes owns subagent execution; WSA owns state, prompt packets, audit, quality gates, and approval package.",
            },
            "scene_generation": {
                "manual_trigger": "/wsa_scene_start or wsa orchestrator run --workflow scene_generation --skill scene_start",
                "purpose": "Scene-prep decision collection, cross-verification, actor/session assignment, role isolation, and script-generation readiness.",
                "runtime_boundary": "Hermes owns actor/subagent calls and model selection; WSA records recommended packets, constraints, checks, and approval boundaries.",
            },
        },
        "shared_guards": [
            "proposal_only_until_author_approval",
            "hard_queue_and_call_limits_required",
            "ephemeral_sessions_must_close_or_mark_complete",
            "mock_or_simulated_modes_must_be_labeled",
        ],
    }


def _base_profile(
    requested_workflow: str,
    skill_name: str,
    canonical_workflow: str,
    title: str,
    purpose: str,
) -> Dict[str, Any]:
    return {
        "schema": WORKFLOW_PROFILE_SCHEMA,
        "requested_workflow": requested_workflow,
        "workflow": canonical_workflow,
        "skill": skill_name,
        "title": title,
        "purpose": purpose,
        "execution_boundary": {
            "wsa_owns": [
                "isolated_run_state",
                "floor_state",
                "turn_and_prompt_packets",
                "quality_gate_records",
                "synthesis_and_approval_package",
            ],
            "hermes_runtime_owns": [
                "subagent_invocation",
                "model_selection",
                "thinking_level_selection",
                "delivery_to_user",
                "cron_or_background_execution",
            ],
        },
        "terminal_hook_model": {
            "status": "prompt_packet_contract",
            "available_now": (
                "Round prompt packets include a wsa hermes task argv template and an expected callback route. "
                "Hermes may adapt those packets to its own subagent syntax."
            ),
            "future_resume_shape": [
                "wsa orchestrator next RUN_ID",
                "wsa orchestrator submit RUN_ID --turn-id TURN_ID --callback CALLBACK_JSON",
            ],
        },
    }


def _meetup_profile(requested_workflow: str, skill_name: str) -> Dict[str, Any]:
    profile = _base_profile(
        requested_workflow,
        skill_name,
        "meetup",
        "Meetup lifecycle",
        (
            "Open a bounded representative meeting for world facts, startup candidates, "
            "scene-prep questions, or a specific worldbuilding objective."
        ),
    )
    profile.update(
        {
            "default_frame": (
                "Run a live-floor meetup. Expand groups into representative voices when useful, "
                "surface conflicts and gaps, challenge shallow consensus, and return approval choices "
                "without canon mutation."
            ),
            "default_participants": [
                "canon_guardian",
                "conflict_diagnostician",
                "stakeholder_representative",
                "proposal_builder",
            ],
            "phase_model": [
                _phase("planning", "Define topic, frame, participants, risks, artifacts, and limits."),
                _phase("participant_expansion", "Split groups/institutions into representative voices or components when needed."),
                _phase("multi_turn_floor", "Run positions, objections, grievances, rebuttals, compromises, and fault lines."),
                _phase("active_facilitation", "Focus, pause, challenge, interview, skip, or verify participants as the floor evolves."),
                _phase("synthesis", "Separate canon anchors, proposals, weak options, conflicts, gaps, and author questions."),
                _phase("approval_package", "Return approve/hold/retry/refine choices before any canon conversion."),
                _phase("downstream_handoff", "Prepare selected facts, tickets, actor choices, or scene-prep candidates after approval."),
            ],
            "floor_state_template": {
                "goal": "",
                "active_question": "",
                "accepted_constraints": [],
                "candidate_decisions": [],
                "conflicts": [],
                "gaps": [],
                "paused_actors": [],
                "verification_queue": [],
                "recent_turns": [],
                "conclusion_status": "open",
            },
            "dynamic_facilitation_hooks": [
                _hook("focus_actor", "actor owns the highest-value unresolved gap", "ask a focused 1:1 follow-up"),
                _hook("challenge_consensus", "participants agree too quickly", "extract the hidden cost or counterexample"),
                _hook("pause_for_manager_check", "claim is overconfident, lore-expanding, or likely contradictory", "pause the actor and schedule manager_check_turn"),
                _hook("skip_low_stake_actor", "actor has no live stake in the current subtopic", "skip until the floor changes"),
                _hook("promote_subtopic", "a repeated gap becomes more important than the original broad topic", "make it the active question for the next turn"),
            ],
            "participant_output_schema": {
                "required_fields": [
                    "position",
                    "stance",
                    "answer",
                    "new_claims",
                    "objections",
                    "dependencies",
                    "conflicts",
                    "worldbuilding_use",
                    "confidence",
                    "next_actor_suggestion",
                    "uncertainty",
                    "gaps",
                    "proposals",
                ],
                "reject_if": [
                    "empty_agreement",
                    "repetition_without_new_information",
                    "unbounded_lore_dump",
                    "unlabeled_uncertainty",
                    "canon_mutation_attempt",
                ],
            },
            "completion_criteria": [
                "review_package_ready",
                "stable_candidate_survives_challenge_turn",
                "author_boundary_reached",
                "hard_queue_or_call_limit_reached",
                "failure_or_retry_needed",
            ],
        }
    )
    return profile


def _scene_generation_profile(requested_workflow: str, skill_name: str) -> Dict[str, Any]:
    profile = _base_profile(
        requested_workflow,
        skill_name,
        "scene_generation",
        "Scene generation prep lifecycle",
        (
            "Prepare a script-like scene by filtering facts, history, memory, viewpoints, "
            "actor assignments, role isolation, model/thinking guidance, and readiness checks."
        ),
    )
    profile.update(
        {
            "default_frame": (
                "Run scene prep before drafting. Gather and cross-check only scene-relevant facts, "
                "decide actor/session assignment and role isolation, recommend model/thinking levels, "
                "and stop at a prep-ready package unless the author approves drafting."
            ),
            "default_participants": [
                "scene_prep_director",
                "canon_filter",
                "continuity_checker",
                "actor_casting_director",
            ],
            "phase_model": [
                _phase("scene_frame", "Define scene goal, stakes, viewpoint, timeframe, location, and output boundary."),
                _phase("fact_memory_filter", "Collect relevant facts, history, character memory, behavior tendencies, and hidden information."),
                _phase("cross_verification", "Check contradictions, timeline/location conflicts, exposure policy, and missing prerequisites."),
                _phase("actor_assignment", "Assign actor sessions, multi-role bundles, narrator/crowd/extras, and role isolation rules."),
                _phase("runtime_allocation", "Recommend parallelism, model class, thinking level, and retry policy per actor/session."),
                _phase("scene_prep_package", "Produce scene beats, actor context packets, risk flags, and prep-complete criteria."),
                _phase("draft_boundary", "Wait for author/Hermes approval before script-like scene generation or canon mutation."),
            ],
            "floor_state_template": {
                "scene_goal": "",
                "active_scene_question": "",
                "facts_to_include": [],
                "facts_to_hide": [],
                "memory_filters": [],
                "actor_assignments": [],
                "role_isolation_notes": [],
                "verification_queue": [],
                "risk_flags": [],
                "recent_turns": [],
                "conclusion_status": "prep_open",
            },
            "dynamic_facilitation_hooks": [
                _hook("filter_irrelevant_context", "context does not affect the scene beat or actor decision", "exclude it from actor packets"),
                _hook("split_multi_role_actor", "one model/session must play multiple roles", "define role boundaries and forbidden cross-role memory"),
                _hook("assign_narrator_or_crowd", "crowd, extras, or narrator require broad synthesis", "bundle roles and recommend stronger model/thinking"),
                _hook("manager_check_scene_fact", "scene beat depends on uncertain fact/history/memory", "schedule manager_check_turn before drafting"),
                _hook("prep_completion_check", "actor packets and scene beats appear complete", "run readiness diagnosis before draft boundary"),
            ],
            "participant_output_schema": {
                "required_fields": [
                    "position",
                    "scene_relevance",
                    "facts_to_include",
                    "facts_to_hide",
                    "memory_filter",
                    "actor_assignment",
                    "role_isolation",
                    "viewpoint_constraints",
                    "scene_beat",
                    "model_thinking_recommendation",
                    "risk_flags",
                    "confidence",
                    "uncertainty",
                    "gaps",
                    "proposals",
                ],
                "reject_if": [
                    "drafts_scene_before_prep_boundary",
                    "leaks_hidden_truth_to_wrong_actor",
                    "mixes_multi_role_memory",
                    "ignores_scene_goal",
                    "canon_mutation_attempt",
                ],
            },
            "actor_session_policy": {
                "one_actor_one_role_preferred": True,
                "multi_role_allowed_when": [
                    "roles are extras, crowd, narrator, or low-conflict supporting voices",
                    "role memory can be explicitly isolated in the prompt packet",
                    "Hermes runtime has sufficient model/thinking budget",
                ],
                "parallelism_policy": "bounded_by_max_concurrent_subsessions",
                "model_guidance": {
                    "higher_capability": "narrator, crowd synthesis, multi-role bundles, canon-risk checks",
                    "standard_capability": "bounded single-role actor turns with clear context",
                    "higher_thinking": "timeline, memory, hidden-truth, or contradiction-sensitive turns",
                },
            },
            "completion_criteria": [
                "scene_prep_package_ready",
                "actor_context_packets_ready",
                "risk_flags_and_hidden_truth_policy_checked",
                "prep_quality_gate_passed",
                "author_boundary_reached",
                "hard_queue_or_call_limit_reached",
            ],
        }
    )
    return profile


def _generic_profile(
    requested_workflow: str,
    skill_name: str,
    canonical_workflow: str,
) -> Dict[str, Any]:
    profile = _base_profile(
        requested_workflow,
        skill_name,
        canonical_workflow,
        f"{canonical_workflow} lifecycle",
        "Run a bounded proposal-only orchestration pass with explicit review boundary.",
    )
    profile.update(
        {
            "default_frame": (
                "Run a bounded orchestration pass, collect proposals and risks, and return "
                "author approval choices without canon mutation."
            ),
            "default_participants": [
                "canon_guardian",
                "conflict_diagnostician",
                f"{canonical_workflow}_proposal_builder",
            ],
            "phase_model": [
                _phase("planning", "Define the frame, participants, artifacts, and limits."),
                _phase("bounded_turns", "Collect concise participant outputs."),
                _phase("synthesis", "Return proposals, conflicts, gaps, and approval choices."),
            ],
            "floor_state_template": {
                "goal": "",
                "active_question": "",
                "conflicts": [],
                "gaps": [],
                "recent_turns": [],
                "conclusion_status": "open",
            },
            "dynamic_facilitation_hooks": [
                _hook("manager_check", "a claim looks risky or unsupported", "schedule manager_check_turn"),
            ],
            "participant_output_schema": {
                "required_fields": [
                    "position",
                    "objections",
                    "proposals",
                    "gaps",
                    "uncertainty",
                ],
                "reject_if": [
                    "missing_required_field",
                    "unlabeled_uncertainty",
                    "canon_mutation_attempt",
                ],
            },
            "completion_criteria": [
                "approval_package_ready",
                "author_boundary_reached",
                "hard_queue_or_call_limit_reached",
            ],
        }
    )
    return profile


def _phase(phase_id: str, purpose: str) -> Dict[str, str]:
    return {"phase_id": phase_id, "purpose": purpose}


def _hook(hook_id: str, fires_when: str, action: str) -> Dict[str, str]:
    return {
        "hook_id": hook_id,
        "fires_when": fires_when,
        "orchestrator_action": action,
        "turn_policy": "may_spend_orchestrator_turn_without_actor_call",
    }
