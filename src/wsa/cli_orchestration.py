from __future__ import annotations

from pathlib import Path

from .autonomous_orchestrator import AutonomousOrchestrator, resolve_scene_filter_contract
from .orchestrator_bridge import OrchestratorBridge
from .run_store import ProjectionWriteError, RunStore
from .contract_registry import concise_run_view
from .meeting import MeetingOrchestrator
from .orchestrator import SceneOrchestrator
from .repositories import WorldRepository
from .workspace import (
    get_world,
)


from .cli_core import guard_update_unlocked, print_json

def run_scene_mock(workspace: Path, world_id: str, name: str, goal: str, actors: list[str]) -> int:
    if not guard_update_unlocked(workspace, "scene.mock"):
        return 1
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    actor_records = [
        repo.create_entity("character", actor_name, payload={"source": "scene_mock_cli"})
        for actor_name in (actors or ["Mock Actor"])
    ]
    result = SceneOrchestrator(workspace, world).run_mock_scene(name, goal, actor_records)
    print(f"scene_id: {result.scene_id}")
    print(f"scene_dir: {result.scene_dir}")
    print(f"prep_receipt: {result.prep_receipt}")
    print(f"progress_checkpoint: {result.progress_checkpoint}")
    print(f"ticket_id: {result.ticket_id}")
    print(f"report_id: {result.report_id}")
    return 0

def run_scene_start(
    workspace: Path,
    world_id: str,
    topic: str,
    question: str,
    rounds: int,
    max_queue_turns: int,
    max_concurrent_subsessions: int,
    max_subsession_calls: int,
    context_policy: str,
    frame_plan: str | None,
    termination_policy: str,
    time_scope: str | None,
    location_scope: str | None,
    viewpoint: str | None,
    conditions: list[str],
    participants: list[str],
    output_format: str,
    prep_review: bool,
    generation_mode: str,
) -> int:
    if not guard_update_unlocked(workspace, "scene.start"):
        return 1
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    scene_filter_contract = resolve_scene_filter_contract(
        repo,
        time_scope=time_scope,
        location_scope=location_scope,
        viewpoint=viewpoint,
        conditions=conditions,
    )
    try:
        result = AutonomousOrchestrator(workspace, world).run(
            workflow="scene_generation",
            topic=topic,
            question=question,
            participants=participants,
            rounds=rounds,
            skill="scene_start",
            mode="hermes-bridge",
            max_queue_turns=max_queue_turns,
            max_concurrent_subsessions=max_concurrent_subsessions,
            max_subsession_calls=max_subsession_calls,
            context_policy=context_policy,
            frame_plan=frame_plan,
            termination_policy=termination_policy,
            subsession_policy="ephemeral",
            canon_policy="proposal-only",
            approval="required",
            close_on="complete",
            scene_filter_contract=scene_filter_contract,
            prep_review=prep_review,
            scene_generation_mode=generation_mode,
        )
    except ValueError as exc:
        print("scene_start: blocked")
        print(f"detail: {exc}")
        return 1
    next_payload = OrchestratorBridge(workspace).next(result.run_id)
    if output_format == "json":
        print_json(
            {
                "scene_start_run_id": result.run_id,
                "orchestrator_status": result.status,
                "run_path": str(result.run_path),
                "report_id": result.report_id or None,
                "scene_filter_contract": scene_filter_contract,
                "scene_mode_disclosure": next_payload.get("scene_mode_disclosure", {}),
                "actor_contribution_summary": next_payload.get("actor_contribution_summary", {}),
                "next": next_payload,
            }
        )
        return 0
    print(f"scene_start_run_id: {result.run_id}")
    print(f"orchestrator_status: {result.status}")
    print("workflow: scene_generation")
    print("skill: scene_start")
    print("mode: hermes-bridge")
    print(f"run_path: {result.run_path}")
    print(f"report_id: {result.report_id or 'pending_hermes_completion'}")
    print(f"next_action: {next_payload.get('next_action')}")
    mode_disclosure = next_payload.get("scene_mode_disclosure", {})
    if mode_disclosure:
        print(f"scene_generation_mode: {mode_disclosure.get('resolved_mode')}")
        print(f"mode_resolution_source: {mode_disclosure.get('mode_resolution_source')}")
    hook = next_payload.get("hook")
    if hook:
        print(f"next_turn_id: {hook['turn_id']}")
        print(f"next_represents: {hook['represents']}")
    print("side_effect_status: proposal_only_no_scene_draft_no_canon_mutation")
    return 0


def run_meeting(
    workspace: Path,
    world_id: str,
    topic: str,
    question: str,
    participants: list[str],
) -> int:
    if not guard_update_unlocked(workspace, "meeting.run"):
        return 1
    world = get_world(workspace, world_id)
    result = MeetingOrchestrator(workspace, world).run_meeting(
        topic,
        question,
        participants,
    )
    print(f"execution_mode: {result.execution_mode}")
    print("real_agent_execution: false")
    print("execution_owner: wsa_local_deterministic_runner")
    print(f"meeting_id: {result.meeting_id}")
    print(f"meeting_dir: {result.meeting_dir}")
    print(f"transcript_path: {result.transcript_path}")
    print(f"report_id: {result.report_id}")
    print(f"manager_session_id: {result.manager_session_id}")
    for session_id in result.participant_session_ids:
        print(f"participant_session_id: {session_id}")
    return 0


def run_meeting_decide(
    workspace: Path,
    world_id: str,
    report_id: str,
    decision: str,
    note: str | None,
) -> int:
    if not guard_update_unlocked(workspace, "meeting.decide"):
        return 1
    world = get_world(workspace, world_id)
    result = MeetingOrchestrator(workspace, world).decide_report(
        report_id,
        decision,
        note=note,
    )
    print(f"meeting_decision: {result.decision}")
    print(f"report_id: {result.report_id}")
    print(f"report_status: {result.report_status}")
    if result.ticket is not None:
        print(f"ticket_id: {result.ticket.ticket_id}")
        print(f"ticket_type: {result.ticket.ticket_type}")
    return 0


def run_orchestrator(
    workspace: Path,
    world_id: str,
    workflow: str,
    skill: str | None,
    topic: str,
    question: str,
    mode: str,
    rounds: int,
    max_queue_turns: int,
    max_concurrent_subsessions: int,
    max_subsession_calls: int,
    context_policy: str,
    frame_plan: str | None,
    termination_policy: str,
    participants: list[str],
    subsession_policy: str,
    canon_policy: str,
    approval: str,
    close_on: str,
    prep_review: bool,
) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.run"):
        return 1
    world = get_world(workspace, world_id)
    try:
        result = AutonomousOrchestrator(workspace, world).run(
            workflow=workflow,
            topic=topic,
            question=question,
            participants=participants,
            rounds=rounds,
            skill=skill,
            mode=mode,
            max_queue_turns=max_queue_turns,
            max_concurrent_subsessions=max_concurrent_subsessions,
            max_subsession_calls=max_subsession_calls,
            context_policy=context_policy,
            frame_plan=frame_plan,
            termination_policy=termination_policy,
            subsession_policy=subsession_policy,
            canon_policy=canon_policy,
            approval=approval,
            close_on=close_on,
            prep_review=prep_review,
        )
    except ValueError as exc:
        print("orchestrator_run: blocked")
        print(f"detail: {exc}")
        return 1
    print(f"orchestrator_run_id: {result.run_id}")
    print(f"orchestrator_status: {result.status}")
    print(f"execution_mode: {result.execution_mode}")
    print(
        "real_agent_execution: "
        f"{'true' if result.execution_provenance.get('external_runtime_confirmed') else 'false'}"
    )
    print(
        "execution_owner: "
        f"{result.execution_provenance.get('actual_execution_owner', 'unknown')}"
    )
    print(f"run_dir: {result.run_dir}")
    print(f"run_path: {result.run_path}")
    print(f"report_id: {result.report_id or 'pending_hermes_completion'}")
    print(f"manager_session_id: {result.manager_session_id}")
    for session_id in result.subsession_session_ids:
        print(f"subsession_session_id: {session_id}")
    return 0


def run_orchestrator_status(
    workspace: Path,
    run_id: str,
    output_format: str,
    expand_contracts: bool = False,
) -> int:
    payload = AutonomousOrchestrator.load_run(workspace, run_id)
    if output_format == "json":
        print_json(payload if expand_contracts else concise_run_view(payload))
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"orchestrator_status: {payload['status']}")
    print(f"execution_mode: {payload.get('execution_mode', 'unknown')}")
    provenance = payload.get("execution_provenance", {})
    print(
        "real_agent_execution: "
        f"{'true' if provenance.get('external_runtime_confirmed') else 'false'}"
    )
    if payload.get("execution_summary"):
        print(f"execution_summary: {payload['execution_summary'].get('statement')}")
    print(f"workflow: {payload['workflow']}")
    if payload.get("workflow_requested") and payload.get("workflow_requested") != payload["workflow"]:
        print(f"workflow_requested: {payload['workflow_requested']}")
    print(f"skill: {payload.get('skill', payload['workflow'])}")
    print(f"topic: {payload['topic']}")
    print(f"execution: {payload['execution']}")
    print(f"round_budget: {payload['plan']['round_budget']}")
    queue_limits = payload.get("queue_limits", {})
    if queue_limits:
        print(
            "queue_turns: "
            f"{queue_limits.get('queue_turns_used')}/{queue_limits.get('max_queue_turns')}"
        )
        print(
            "subsession_calls: "
            f"{queue_limits.get('planned_subsession_calls')}/"
            f"{queue_limits.get('max_subsession_calls')}"
        )
    print(f"frame_source: {payload.get('plan_frame', {}).get('source', 'unknown')}")
    print(
        "max_concurrent_subsessions: "
        f"{payload.get('concurrency_policy', {}).get('max_concurrent_subsessions', 'unknown')}"
    )
    print(f"closed_subsessions: {len(payload.get('closed_subsessions', []))}")
    print(f"approval_options: {', '.join(payload.get('approval_options', []))}")
    return 0


def run_orchestrator_report(
    workspace: Path,
    run_id: str,
    output_format: str,
    expand_contracts: bool = False,
) -> int:
    payload = AutonomousOrchestrator.load_run(workspace, run_id)
    path = AutonomousOrchestrator.report_path(workspace, run_id)
    if output_format == "json":
        print_json(
            {
                "run_path": str(path),
                "run": payload if expand_contracts else concise_run_view(payload),
            }
        )
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"run_path: {path}")
    print(f"execution_mode: {payload.get('execution_mode', 'unknown')}")
    print(
        "real_agent_execution: "
        f"{'true' if payload.get('execution_provenance', {}).get('external_runtime_confirmed') else 'false'}"
    )
    if payload.get("execution_summary"):
        print(f"execution_summary: {payload['execution_summary'].get('statement')}")
    print(f"summary: {payload['synthesis']['summary']}")
    print(f"requires_author_boundary: {payload['conflict_gap_diagnosis']['requires_author_boundary']}")
    for option in payload.get("draft_options", []):
        print(f"draft_option: {option['option_id']}\t{option['title']}")
    return 0


def run_orchestrator_hooks(workspace: Path, run_id: str, output_format: str) -> int:
    payload = AutonomousOrchestrator.load_run(workspace, run_id)
    hooks = payload.get("runtime_hook_packets", payload.get("round_prompt_packets", []))
    result = {
        "run_id": run_id,
        "workflow": payload.get("workflow"),
        "skill": payload.get("skill"),
        "subsession_execution_mode": payload.get("subsession_execution_mode"),
        "execution_mode": payload.get("execution_mode"),
        "hook_count": len(hooks),
        "hooks": hooks,
    }
    if output_format == "json":
        print_json(result)
        return 0
    print(f"orchestrator_run_id: {run_id}")
    print(f"workflow: {result['workflow']}")
    print(f"subsession_execution_mode: {result['subsession_execution_mode']}")
    print(f"execution_mode: {result['execution_mode']}")
    print(f"hook_count: {len(hooks)}")
    for hook in hooks:
        command = hook.get("terminal_command", {}).get("argv", [])
        print(f"hook: {hook.get('turn_id', hook.get('prompt_packet_id'))}")
        print(f"turn_type: {hook.get('turn_type')}")
        if command:
            print(f"terminal_command: {' '.join(str(item) for item in command[:8])} ...")
    return 0


def run_orchestrator_next(workspace: Path, run_id: str, output_format: str) -> int:
    payload = OrchestratorBridge(workspace).next(run_id)
    if output_format == "json":
        print_json(payload)
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"status: {payload['status']}")
    print(f"execution_status: {payload['execution_status']}")
    print(f"next_action: {payload['next_action']}")
    hook = payload.get("hook")
    if hook:
        print(f"turn_id: {hook['turn_id']}")
        print(f"turn_type: {hook['turn_type']}")
        print(f"represents: {hook['represents']}")
    prep_report = payload.get("prep_report")
    if prep_report:
        print(f"prep_report_status: {prep_report.get('status')}")
        print(f"prep_review_options: {', '.join(prep_report.get('review_options', []))}")
    return 0


def run_orchestrator_prep_approve(workspace: Path, run_id: str, output_format: str) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.prep-approve"):
        return 1
    try:
        payload = OrchestratorBridge(workspace).approve_prep(run_id)
    except KeyError as exc:
        print("orchestrator_prep_approve: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        print_json(payload)
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"prep_approved: {str(payload.get('prep_approved', False)).lower()}")
    print(f"status: {payload['status']}")
    print(f"execution_status: {payload['execution_status']}")
    print(f"next_action: {payload['next_action']}")
    hook = payload.get("hook")
    if hook:
        print(f"turn_id: {hook['turn_id']}")
        print(f"represents: {hook['represents']}")
    return 0


def run_orchestrator_submit(
    workspace: Path,
    run_id: str,
    callback_path: str,
    output_format: str,
) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.submit"):
        return 1
    try:
        payload = OrchestratorBridge(workspace).submit(run_id, Path(callback_path))
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print("orchestrator_submit: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        print_json(payload)
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"turn_id: {payload['turn_id']}")
    print(f"accepted: {str(payload['accepted']).lower()}")
    print(f"status: {payload['status']}")
    print(f"execution_status: {payload['execution_status']}")
    print(f"next_action: {payload['next_action']}")
    if payload.get("report_id"):
        print(f"report_id: {payload['report_id']}")
    return 0


def run_orchestrator_decide(
    workspace: Path,
    run_id: str,
    decision: str,
    option: str | None,
    note: str | None,
) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.decide"):
        return 1
    try:
        result = AutonomousOrchestrator.decide(
            workspace,
            run_id,
            decision=decision,
            option=option,
            note=note,
        )
    except ValueError as exc:
        print("orchestrator_decision: blocked")
        print(f"detail: {exc}")
        return 1
    print(f"orchestrator_decision: {result.decision}")
    print(f"orchestrator_run_id: {result.run_id}")
    print(f"report_id: {result.report_id}")
    print(f"report_status: {result.report_status}")
    if result.ticket is not None:
        print(f"ticket_id: {result.ticket.ticket_id}")
        print(f"ticket_type: {result.ticket.ticket_type}")
    return 0


def run_orchestrator_close(workspace: Path, run_id: str, reason: str | None) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.close"):
        return 1
    payload = AutonomousOrchestrator.close(workspace, run_id, reason=reason)
    print(f"orchestrator_closed: {payload['run_id']}")
    print(f"orchestrator_status: {payload['status']}")
    print(f"close_reason: {payload['close_reason']}")
    return 0


def run_orchestrator_interrupt(workspace: Path, run_id: str, reason: str | None) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.interrupt"):
        return 1
    try:
        payload = AutonomousOrchestrator.interrupt(workspace, run_id, reason=reason)
    except (KeyError, ValueError) as exc:
        print("orchestrator_interrupt: blocked")
        print(f"detail: {exc}")
        return 1
    print(f"orchestrator_interrupted: {payload['run_id']}")
    print(f"orchestrator_status: {payload['status']}")
    print(f"interrupted_from: {payload['interrupted_from']}")
    return 0


def run_orchestrator_resume(workspace: Path, run_id: str, output_format: str) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.resume"):
        return 1
    try:
        payload = AutonomousOrchestrator.resume(workspace, run_id)
    except (KeyError, ValueError) as exc:
        print("orchestrator_resume: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        print_json(payload)
        return 0
    print(f"orchestrator_resumed: {payload['run_id']}")
    print(f"orchestrator_status: {payload['status']}")
    print(f"next_action: {payload.get('next_action', 'none')}")
    return 0


def run_orchestrator_repair_projection(workspace: Path, run_id: str) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.repair-projection"):
        return 1
    try:
        record = RunStore(workspace).repair_projection(run_id)
    except (KeyError, ProjectionWriteError, ValueError) as exc:
        print("orchestrator_projection_repair: blocked")
        print(f"detail: {exc}")
        return 1
    print(f"orchestrator_projection_repaired: {record.run_id}")
    print(f"run_path: {record.run_path}")
    print(f"projection_status: {record.projection_status}")
    return 0
