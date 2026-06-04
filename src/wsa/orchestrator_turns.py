from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from .orchestrator_contract import DEFAULT_UTTERANCE_TARGET


ACTOR_STATE_SCHEMA = "wsa.orchestrator.actor_state.v1"


def build_initial_floor_state(
    workflow_profile: Dict[str, Any],
    topic: str,
    question: str,
    participants: List[Dict[str, Any]],
) -> Dict[str, Any]:
    template = dict(workflow_profile.get("floor_state_template", {}))
    template.update(
        {
            "schema": "wsa.orchestrator.floor_state.v1",
            "workflow": workflow_profile.get("workflow"),
            "topic": topic,
            "question": question,
            "participant_ids": [item["participant_id"] for item in participants],
            "floor_open": True,
            "turn_count": 0,
        }
    )
    return template


def build_initial_actor_states(
    participants: List[Dict[str, Any]],
    workflow_profile: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    return {
        item["participant_id"]: build_actor_state(item, workflow_profile)
        for item in participants
    }


def build_actor_state(
    participant: Dict[str, Any],
    workflow_profile: Dict[str, Any],
) -> Dict[str, Any]:
    workflow = str(workflow_profile.get("workflow") or participant.get("workflow_role") or "meetup")
    if workflow == "scene_generation":
        stable_mandate = [
            "protect viewpoint-safe scene context",
            "separate visible facts, hidden facts, and role memory",
            "return only scene-prep material until draft approval",
        ]
        scope_boundaries = [
            "do not draft script prose before the prep boundary",
            "do not leak hidden facts into the wrong viewpoint packet",
            "do not mutate canon or startup state",
        ]
    else:
        stable_mandate = [
            "represent the assigned stakeholder or viewpoint",
            "surface constraints, objections, dependencies, and candidate proposals",
            "keep generated material proposal-only until author approval",
        ]
        scope_boundaries = [
            "do not decide canon authority",
            "do not speak for unrelated participants",
            "do not convert workflow notes into in-world facts",
        ]
    return {
        "schema": ACTOR_STATE_SCHEMA,
        "actor_id": participant["participant_id"],
        "represents": participant["label"],
        "role_identity": participant.get("role", "representative_voice"),
        "workflow": workflow,
        "stable_mandate": stable_mandate,
        "scope_boundaries": scope_boundaries,
        "last_position": None,
        "last_answer": None,
        "last_claims": [],
        "accepted_claims": [],
        "rejected_claims": [],
        "objections_made": [],
        "objections_received": [],
        "unanswered_questions": [],
        "stance": None,
        "stance_changes": [],
        "confidence_history": [],
        "identity_drift_warnings": [],
        "low_value_turn_warnings": [],
        "next_required_response": "give an initial bounded position",
        "turn_count": 0,
        "last_turn_id": None,
    }


def compact_actor_state(actor_state: Dict[str, Any] | None) -> Dict[str, Any]:
    if not actor_state:
        return {}
    return {
        "actor_id": actor_state.get("actor_id"),
        "represents": actor_state.get("represents"),
        "role_identity": actor_state.get("role_identity"),
        "stable_mandate": _last_items(actor_state.get("stable_mandate", []), 3),
        "scope_boundaries": _last_items(actor_state.get("scope_boundaries", []), 3),
        "last_position": actor_state.get("last_position"),
        "last_answer": actor_state.get("last_answer"),
        "last_claims": _last_items(actor_state.get("last_claims", []), 4),
        "objections_made": _last_items(actor_state.get("objections_made", []), 4),
        "objections_received": _last_items(actor_state.get("objections_received", []), 4),
        "unanswered_questions": _last_items(actor_state.get("unanswered_questions", []), 4),
        "stance": actor_state.get("stance"),
        "stance_changes": _last_items(actor_state.get("stance_changes", []), 3),
        "confidence_history": _last_items(actor_state.get("confidence_history", []), 4),
        "identity_drift_warnings": _last_items(actor_state.get("identity_drift_warnings", []), 3),
        "next_required_response": actor_state.get("next_required_response"),
        "turn_count": actor_state.get("turn_count", 0),
    }


def build_scheduler_decision(
    context_packet: Dict[str, Any],
    round_index: int,
    actor_state: Dict[str, Any] | None,
    floor_state: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    floor_state = floor_state or {}
    actor_state = actor_state or {}
    participant_id = context_packet["participant_id"]
    verification_items = [
        item
        for item in floor_state.get("verification_queue", [])
        if item.get("participant_id") == participant_id
    ]
    if verification_items:
        reason = "actor_has_pending_verification_or_manager_check"
        action = "ask_actor_to_answer_only_after considering verification status"
    elif actor_state.get("objections_received"):
        reason = "actor_has_relevant_objections_to_answer"
        action = "ask_actor_to answer the strongest received objection"
    elif actor_state.get("unanswered_questions"):
        reason = "actor_owns_unanswered_question"
        action = "ask a focused follow-up instead of broad restatement"
    elif round_index == 1 or not actor_state.get("last_position"):
        reason = "initial_position_needed"
        action = "collect first bounded position"
    else:
        reason = "continuity_followup"
        action = "advance or revise prior position with one new constraint"
    return {
        "schema": "wsa.orchestrator.scheduler_decision.v1",
        "policy": "dynamic_turn_selection_contract",
        "round": round_index,
        "participant_id": participant_id,
        "called_because": reason,
        "recommended_action": action,
        "round_is_reporting_unit_only": True,
        "equal_airtime_not_required": True,
        "may_skip_when_low_stake": True,
        "verification_items": verification_items[:4],
    }


def build_round_prompt_packet(
    context_packet: Dict[str, Any],
    round_index: int,
    previous_snapshot: Dict[str, Any] | None,
    workflow_profile: Dict[str, Any],
    world_id: str,
    actor_state: Dict[str, Any] | None = None,
    scheduler_decision: Dict[str, Any] | None = None,
    floor_state: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    participant_id = context_packet["participant_id"]
    turn_id = f"{context_packet['run_id']}:{participant_id}:round-{round_index}"
    actor_state_summary = compact_actor_state(actor_state or context_packet.get("actor_state"))
    scheduler_decision = scheduler_decision or build_scheduler_decision(
        context_packet,
        round_index,
        actor_state_summary,
        floor_state,
    )
    prompt = build_runtime_prompt(
        context_packet,
        round_index,
        previous_snapshot,
        workflow_profile,
        actor_state_summary,
        scheduler_decision,
    )
    task_type = f"orchestrator_{workflow_profile.get('workflow', context_packet['workflow'])}_actor_turn"
    return {
        "schema": "wsa.orchestrator.round_prompt_packet.v1",
        "prompt_packet_id": turn_id,
        "turn_id": turn_id,
        "run_id": context_packet["run_id"],
        "participant_id": participant_id,
        "represents": context_packet["represents"],
        "session_id": context_packet.get("session_id"),
        "round": round_index,
        "turn_type": "actor_turn",
        "workflow": workflow_profile.get("workflow", context_packet["workflow"]),
        "execution_mode": "runtime_bridge_hook",
        "execution_owner": "external_agent_runtime",
        "actor_state": actor_state_summary,
        "scheduler_decision": scheduler_decision,
        "identity_continuity_contract": {
            "must_answer_relevant_prior_objections": True,
            "must_not_reset_actor_identity_between_turns": True,
            "must_report_stance_change_or_explicit_reaffirmation": True,
            "must_label_uncertainty": True,
        },
        "live_floor_state": {
            "floor_open": True,
            "chair_has_closed": False,
            "previous_compressed_snapshot": previous_snapshot,
            "verification_queue": (floor_state or {}).get("verification_queue", []),
            "recent_turns": (floor_state or {}).get("recent_turns", []),
        },
        "prompt": prompt,
        "terminal_command": {
            "owner": "user_hermes_runtime",
            "purpose": "Create a Hermes-owned task for this actor/subsession turn.",
            "argv": [
                "wsa",
                "hermes",
                "task",
                world_id,
                "--task-type",
                task_type,
                "--title",
                f"{context_packet['represents']} round {round_index}",
                "--instruction",
                prompt,
                "--session-id",
                str(context_packet.get("session_id", "")),
                "--skill",
                str(context_packet.get("skill", workflow_profile.get("workflow", "orchestrator"))),
                "--background",
            ],
            "callback_collection_shape": [
                "wsa",
                "hermes",
                "collect-callback",
                "hermes/callbacks/<callback>.json",
            ],
        },
        "instruction": (
            "Respond with only the requested bounded fields. Prefer one precise sentence "
            "for each field unless the expected value requires a list."
        ),
        "expected_response_shape": DEFAULT_UTTERANCE_TARGET,
        "expected_fields": context_packet.get("expected_output", []),
        "expected_callback_route": {
            "world_id": world_id,
            "session_id": context_packet.get("session_id"),
            "role": "orchestrator_subsession",
        },
        "quality_gate": {
            "accepted_only_if_complete": True,
            "missing_or_unbounded_output_requires_retry": True,
        },
    }


def build_runtime_prompt(
    context_packet: Dict[str, Any],
    round_index: int,
    previous_snapshot: Dict[str, Any] | None,
    workflow_profile: Dict[str, Any],
    actor_state: Dict[str, Any] | None = None,
    scheduler_decision: Dict[str, Any] | None = None,
) -> str:
    expected = ", ".join(context_packet.get("expected_output", []))
    snapshot = "none"
    if previous_snapshot:
        snapshot = str(previous_snapshot.get("summary") or "previous compressed snapshot available")
    hooks = ", ".join(
        str(item.get("hook_id"))
        for item in workflow_profile.get("dynamic_facilitation_hooks", [])[:4]
        if isinstance(item, dict)
    )
    actor_note = "no prior actor state"
    if actor_state:
        actor_note = (
            f"prior stance={actor_state.get('stance') or 'none'}; "
            f"last_position={actor_state.get('last_position') or 'none'}; "
            f"unanswered={actor_state.get('unanswered_questions') or []}; "
            f"objections_received={actor_state.get('objections_received') or []}"
        )
    schedule_note = "initial bounded turn"
    if scheduler_decision:
        schedule_note = (
            f"{scheduler_decision.get('called_because')}: "
            f"{scheduler_decision.get('recommended_action')}"
        )
    mode_contract = context_packet.get("scene_mode_contract") or {}
    mode_note = "no scene mode contract"
    if mode_contract:
        fields = mode_contract.get("recommended_output_fields", [])
        mode_note = (
            f"scene mode={mode_contract.get('mode')}; "
            f"recommended_mode_fields={fields[:8]}"
        )
    return (
        f"WSA {workflow_profile.get('workflow')} turn. Round {round_index}. "
        f"Represent: {context_packet['represents']}. Topic: {context_packet['topic']}. "
        f"Question: {context_packet['question']}. Previous floor summary: {snapshot}. "
        f"Your actor continuity: {actor_note}. Scheduler reason: {schedule_note}. "
        f"Mode contract: {mode_note}. "
        f"Return only these fields: {expected}. Keep each field bounded, label uncertainty, "
        "do not mutate canon, and suggest the next actor only if useful. "
        f"Orchestrator hooks in scope: {hooks or 'manager_check'}."
    )


def build_orchestrator_turn_record(
    run_id: str,
    round_index: int,
    workflow_profile: Dict[str, Any],
    floor_state: Dict[str, Any],
) -> Dict[str, Any]:
    hooks = workflow_profile.get("dynamic_facilitation_hooks", [])
    hook = hooks[(round_index - 1) % len(hooks)] if hooks else {}
    return {
        "schema": "wsa.orchestrator.turn_record.v1",
        "turn_id": f"{run_id}:orchestrator:round-{round_index}",
        "run_id": run_id,
        "round": round_index,
        "turn_type": "orchestrator_turn",
        "hook_id": hook.get("hook_id", "round_focus") if isinstance(hook, dict) else "round_focus",
        "action": hook.get("orchestrator_action", "choose next bounded actor prompt")
        if isinstance(hook, dict)
        else "choose next bounded actor prompt",
        "floor_summary_before": floor_state.get("conclusion_status", "open"),
        "actor_call_spent": False,
    }


def build_actor_turn_record(
    prompt_packet: Dict[str, Any],
    output: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema": "wsa.orchestrator.turn_record.v1",
        "turn_id": prompt_packet["turn_id"],
        "run_id": prompt_packet["run_id"],
        "round": prompt_packet["round"],
        "turn_type": "actor_turn",
        "participant_id": prompt_packet["participant_id"],
        "represents": prompt_packet["represents"],
        "prompt_packet_id": prompt_packet["prompt_packet_id"],
        "scheduler_decision": prompt_packet.get("scheduler_decision", {}),
        "actor_state_ref": {
            "actor_id": prompt_packet.get("actor_state", {}).get("actor_id"),
            "turn_count_before": prompt_packet.get("actor_state", {}).get("turn_count", 0),
        },
        "quality_gate": output.get("quality_gate", {}),
        "accepted": bool(output.get("quality_gate", {}).get("accepted")),
    }


def build_manager_check_turn_records(
    run_id: str,
    round_index: int,
    round_outputs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    records = []
    risky = [
        output
        for output in round_outputs
        if output.get("uncertainty") == "high" or output.get("risk_flags")
    ][:3]
    for index, output in enumerate(risky, start=1):
        records.append(
            {
                "schema": "wsa.orchestrator.turn_record.v1",
                "turn_id": f"{run_id}:manager-check:round-{round_index}:{index}",
                "run_id": run_id,
                "round": round_index,
                "turn_type": "manager_check_turn",
                "checks": [
                    "canon_contradiction",
                    "timeline_or_location_conflict",
                    "hidden_truth_exposure_policy",
                    "authoring_workflow_vs_world_canon_contamination",
                ],
                "source_participant_id": output["participant_id"],
                "status": "scheduled_for_hermes_or_manager_runtime",
            }
        )
    return records


def update_floor_state(
    floor_state: Dict[str, Any],
    round_index: int,
    round_outputs: List[Dict[str, Any]],
    turn_records: List[Dict[str, Any]],
    actor_states: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    updated = dict(floor_state)
    risky_outputs = [
        output
        for output in round_outputs
        if output.get("uncertainty") == "high" or output.get("risk_flags")
    ]
    updated["turn_count"] = len(turn_records)
    updated["recent_turns"] = [
        {
            "turn_id": item.get("turn_id"),
            "turn_type": item.get("turn_type"),
            "round": item.get("round"),
        }
        for item in turn_records[-10:]
    ]
    previous_queue = [
        item
        for item in updated.get("verification_queue", [])
        if isinstance(item, dict)
    ]
    new_queue = [
        {
            "participant_id": output["participant_id"],
            "reason": "high_uncertainty_or_risk_flag",
            "round": round_index,
            "status": "verification_or_manager_check_recommended",
            "pause_protocol": "do_not_treat_risky_claim_as_grounded_until_checked",
        }
        for output in risky_outputs[:8]
    ]
    updated["verification_queue"] = _dedupe_dicts(
        previous_queue + new_queue,
        keys=("participant_id", "round", "reason"),
        limit=16,
    )
    updated["gaps"] = [
        {
            "participant_id": output["participant_id"],
            "represents": output["represents"],
            "gap": "needs canon grounding or author decision",
        }
        for output in risky_outputs[:8]
    ]
    updated["paused_actors"] = [
        {
            "participant_id": output["participant_id"],
            "reason": "manager_check_recommended_before_claim_influences_next_turns",
            "round": round_index,
        }
        for output in risky_outputs[:8]
    ]
    if actor_states is not None:
        updated["actor_state_summary"] = {
            actor_id: {
                "represents": state.get("represents"),
                "turn_count": state.get("turn_count", 0),
                "stance": state.get("stance"),
                "last_position": state.get("last_position"),
                "unanswered_question_count": len(state.get("unanswered_questions", [])),
                "objection_count": len(state.get("objections_made", [])),
                "drift_warning_count": len(state.get("identity_drift_warnings", [])),
            }
            for actor_id, state in actor_states.items()
        }
    updated["scheduler_state"] = {
        "turn_based": True,
        "round_is_reporting_unit_only": True,
        "equal_airtime_not_required": True,
        "next_actor_should_be_selected_by": [
            "verification_need",
            "blocking_objection",
            "domain_ownership",
            "candidate_falsification_value",
            "unanswered_question",
        ],
    }
    updated["conclusion_status"] = (
        "author_review_ready" if round_outputs else "partial_no_accepted_outputs"
    )
    return updated


def update_actor_states(
    actor_states: Dict[str, Dict[str, Any]],
    prompt_packet: Dict[str, Any],
    output: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    updated = deepcopy(actor_states)
    actor_id = prompt_packet["participant_id"]
    state = dict(updated.get(actor_id) or prompt_packet.get("actor_state") or {})
    state.setdefault("schema", ACTOR_STATE_SCHEMA)
    state.setdefault("actor_id", actor_id)
    state.setdefault("represents", prompt_packet.get("represents"))
    turn_id = prompt_packet["turn_id"]
    state["turn_count"] = int(state.get("turn_count") or 0) + 1
    state["last_turn_id"] = turn_id
    if output.get("position"):
        state["last_position"] = str(output["position"])
    if output.get("answer"):
        state["last_answer"] = str(output["answer"])
    state["last_claims"] = _merge_recent(
        state.get("last_claims", []),
        _as_list(output.get("new_claims")),
        limit=8,
    )
    state["accepted_claims"] = _merge_recent(
        state.get("accepted_claims", []),
        _as_list(output.get("proposals")),
        limit=8,
    )
    state["objections_made"] = _merge_recent(
        state.get("objections_made", []),
        _as_list(output.get("objections")),
        limit=8,
    )
    state["unanswered_questions"] = _merge_recent(
        state.get("unanswered_questions", []),
        _as_list(output.get("gaps")),
        limit=8,
    )
    old_stance = state.get("stance")
    new_stance = output.get("stance")
    if isinstance(new_stance, str) and new_stance:
        if old_stance and old_stance != new_stance:
            state["stance_changes"] = _merge_recent(
                state.get("stance_changes", []),
                [
                    {
                        "turn_id": turn_id,
                        "from": old_stance,
                        "to": new_stance,
                    }
                ],
                limit=8,
            )
        state["stance"] = new_stance
    confidence = output.get("confidence")
    uncertainty = output.get("uncertainty")
    if confidence or uncertainty:
        state["confidence_history"] = _merge_recent(
            state.get("confidence_history", []),
            [
                {
                    "turn_id": turn_id,
                    "round": prompt_packet.get("round"),
                    "confidence": confidence,
                    "uncertainty": uncertainty,
                }
            ],
            limit=12,
        )
    warnings = []
    if output.get("canon_mutation"):
        warnings.append("canon_mutation_attempt")
    if _looks_like_empty_agreement(output):
        warnings.append("empty_agreement_or_no_new_constraint")
    if output.get("quality_gate", {}).get("low_value_warnings"):
        warnings.extend(output["quality_gate"]["low_value_warnings"])
    if warnings:
        state["low_value_turn_warnings"] = _merge_recent(
            state.get("low_value_turn_warnings", []),
            [{"turn_id": turn_id, "warnings": warnings}],
            limit=8,
        )
    state["next_required_response"] = _next_required_response(output)
    updated[actor_id] = state
    return updated


def _next_required_response(output: Dict[str, Any]) -> str:
    if output.get("uncertainty") == "high" or output.get("risk_flags"):
        return "answer the verification result or narrow the unsupported claim"
    if output.get("gaps"):
        return "resolve one listed gap with a bounded answer"
    if output.get("objections"):
        return "respond to the strongest live objection if called again"
    return "add one new constraint, concession, or explicit reaffirmation"


def _looks_like_empty_agreement(output: Dict[str, Any]) -> bool:
    text = " ".join(
        str(output.get(field) or "")
        for field in ("position", "stance", "answer")
    ).strip().casefold()
    empty_markers = {
        "agree",
        "i agree",
        "yes",
        "same",
        "no objection",
        "looks good",
        "동의",
        "찬성",
    }
    return text in empty_markers


def _as_list(value: Any) -> List[Any]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "", [])]
    return [value]


def _last_items(value: Any, limit: int) -> List[Any]:
    items = _as_list(value)
    return items[-limit:]


def _merge_recent(existing: Any, new_items: List[Any], limit: int) -> List[Any]:
    merged = _as_list(existing)
    for item in new_items:
        if item not in merged:
            merged.append(item)
    return merged[-limit:]


def _dedupe_dicts(
    items: List[Dict[str, Any]],
    keys: tuple[str, ...],
    limit: int,
) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        marker = tuple(item.get(key) for key in keys)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result[-limit:]
