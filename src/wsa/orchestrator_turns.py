from __future__ import annotations

from typing import Any, Dict, List

from .orchestrator_contract import DEFAULT_UTTERANCE_TARGET


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


def build_round_prompt_packet(
    context_packet: Dict[str, Any],
    round_index: int,
    previous_snapshot: Dict[str, Any] | None,
    workflow_profile: Dict[str, Any],
    world_id: str,
) -> Dict[str, Any]:
    participant_id = context_packet["participant_id"]
    turn_id = f"{context_packet['run_id']}:{participant_id}:round-{round_index}"
    prompt = build_runtime_prompt(
        context_packet,
        round_index,
        previous_snapshot,
        workflow_profile,
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
        "live_floor_state": {
            "floor_open": True,
            "chair_has_closed": False,
            "previous_compressed_snapshot": previous_snapshot,
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
    return (
        f"WSA {workflow_profile.get('workflow')} turn. Round {round_index}. "
        f"Represent: {context_packet['represents']}. Topic: {context_packet['topic']}. "
        f"Question: {context_packet['question']}. Previous floor summary: {snapshot}. "
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
) -> Dict[str, Any]:
    updated = dict(floor_state)
    high_uncertainty = [
        output for output in round_outputs if output.get("uncertainty") == "high"
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
    updated["verification_queue"] = [
        {
            "participant_id": output["participant_id"],
            "reason": "high_uncertainty_or_risk_flag",
            "round": round_index,
        }
        for output in high_uncertainty[:8]
    ]
    updated["gaps"] = [
        {
            "participant_id": output["participant_id"],
            "represents": output["represents"],
            "gap": "needs canon grounding or author decision",
        }
        for output in high_uncertainty[:8]
    ]
    updated["conclusion_status"] = (
        "author_review_ready" if round_outputs else "partial_no_accepted_outputs"
    )
    return updated
