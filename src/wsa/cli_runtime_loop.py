from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from .application.runtime_loop_service import RuntimeLoopService
from .runtime_adapter import DispatchPlan, StdioRuntimeAdapter


def _argv(values: Sequence[str]) -> list[str]:
    result = list(values)
    if result and result[0] == "--":
        result.pop(0)
    return result


def _plan_payload(plan: DispatchPlan) -> dict:
    return {
        "schema": "wsa.runtime_dispatch_cli.v1",
        "status": "planned",
        "plan": plan.to_dict(),
        "provider_credentials": "not_read_or_stored_by_wsa",
        "side_effect_status": "read_only_no_process_started",
    }


def _print_plan(plan: DispatchPlan, *, language: str) -> None:
    payload = plan.to_dict()
    print("런타임 실행 계획" if language == "ko" else "runtime dispatch plan")
    print(f"run_id: {payload['run_id']}")
    print(f"turn_id: {payload['turn_id']}")
    print(f"dispatch_status: {payload['dispatch_status']}")
    print(f"command: {json.dumps(payload['argv'], ensure_ascii=False)}")
    print(f"workdir: {payload['workdir']}")
    print(f"timeout_seconds: {payload['timeout_seconds']}")
    print(f"route_digest: {payload['route_digest']}")
    print("provider_credentials: not_read_or_stored_by_wsa")
    print(f"side_effect_status: {payload['side_effect_status']}")


def run_orchestrator_runtime_dispatch(
    workspace: Path,
    run_id: str,
    runtime_argv: Sequence[str],
    *,
    workdir: Path | None = None,
    timeout_seconds: float = 120.0,
    execute: bool = False,
    confirmed: bool = False,
    output_format: str = "text",
    language: str = "ko",
) -> int:
    adapter = StdioRuntimeAdapter(
        _argv(runtime_argv),
        workdir or workspace,
        timeout_seconds=timeout_seconds,
    )
    service = RuntimeLoopService(workspace, adapter)
    plan = service.dispatch_plan(run_id)

    if not execute:
        if output_format == "json":
            print(json.dumps(_plan_payload(plan), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            _print_plan(plan, language=language)
            print("next_action: repeat with orchestrator dispatch and --confirm")
        return 0

    if not confirmed:
        payload = _plan_payload(plan)
        payload["status"] = "confirmation_required"
        payload["next_action"] = "review command/workdir and repeat with --confirm"
        if output_format == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            _print_plan(plan, language=language)
            print("dispatch: blocked")
            print("status: confirmation_required")
            print("next_action: review command/workdir and repeat with --confirm")
        return 1

    if output_format == "text":
        _print_plan(plan, language=language)
        print("dispatch: starting_one_confirmed_process", flush=True)
    result = service.execute(plan)
    payload = result.to_dict()
    payload["provider_credentials"] = "not_read_or_stored_by_wsa"
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"dispatch_result: {payload['status']}")
        print(f"accepted: {str(payload['accepted']).lower()}")
        if payload.get("callback_ref"):
            print(f"callback_ref: {payload['callback_ref']}")
        if payload.get("error"):
            print(f"error: {payload['error']['code']}: {payload['error']['message']}")
        print(f"side_effect_status: {payload['side_effect_status']}")
    return 0 if result.accepted else 1
