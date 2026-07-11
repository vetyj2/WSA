from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


STDIO_RUNTIME_PROTOCOL_SCHEMA = "wsa.runtime_adapter.stdio.v1"
RUNTIME_ADAPTER_REQUEST_SCHEMA = "wsa.runtime_adapter.request.v1"
RUNTIME_CAPABILITY_RESPONSE_SCHEMA = "wsa.runtime_adapter.capability_response.v1"
SUPPORTED_CAPABILITIES = (
    "stdio_single_hook_json",
    "hermes_callback_json_v1",
    "orchestrator_dispatch_receipt_v1",
    "process_cancellation",
)
MAX_INPUT_BYTES = 256 * 1024
MINIMAL_ENV_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "WINDIR",
)


def _read_hook() -> Dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("hook input exceeds reference adapter limit")
    hook = json.loads(raw.decode("utf-8"))
    if not isinstance(hook, dict):
        raise ValueError("hook input must be one JSON object")
    if hook.get("schema") != "wsa.orchestrator.round_prompt_packet.v1":
        raise ValueError("unsupported hook schema")
    request = hook.get("runtime_adapter_request")
    if not isinstance(request, dict):
        raise ValueError("hook does not contain runtime adapter request")
    if request.get("schema") != RUNTIME_ADAPTER_REQUEST_SCHEMA:
        raise ValueError("unsupported runtime adapter request")
    if request.get("protocol") != STDIO_RUNTIME_PROTOCOL_SCHEMA:
        raise ValueError("unsupported stdio runtime protocol")
    required = request.get("required_capabilities")
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise ValueError("required capabilities must be an array of strings")
    return hook


def _minimal_environment(workspace: Path) -> Dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in MINIMAL_ENV_KEYS
        if key in os.environ
    }
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONPATH"] = str(source_root)
    environment["WSA_WORKSPACE"] = str(workspace)
    return environment


def _create_task(hook: Dict[str, Any], workspace: Path) -> Dict[str, Any]:
    terminal_command = hook.get("terminal_command")
    if not isinstance(terminal_command, dict):
        raise ValueError("hook does not contain terminal_command")
    argv = terminal_command.get("argv")
    if not isinstance(argv, list) or not argv or argv[0] != "wsa":
        raise ValueError("generated task command must be a wsa argv array")
    if any(not isinstance(item, str) for item in argv):
        raise ValueError("generated task argv must contain strings")

    command = [sys.executable, "-m", "wsa", *argv[1:]]
    completed = subprocess.run(
        command,
        cwd=workspace,
        env=_minimal_environment(workspace),
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError("generated WSA task command failed")
    task_ref = _task_ref(completed.stdout)
    task_path = (workspace / task_ref).resolve()
    try:
        task_path.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("generated task path escaped workspace") from exc
    task = json.loads(task_path.read_text(encoding="utf-8"))
    if not isinstance(task, dict):
        raise ValueError("generated task packet must be an object")
    return task


def _task_ref(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("task_path: "):
            return line.split(": ", 1)[1]
    raise ValueError("generated task command did not report task_path")


def _reference_output(hook: Dict[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {
        "position": "Reference runtime completed the bounded stdio hook.",
        "stance": "provisional",
        "answer": "Return this deterministic candidate for WSA validation.",
        "new_claims": [],
        "objections": ["Keep the result proposal-only."],
        "dependencies": ["Author review."],
        "conflicts": [],
        "worldbuilding_use": "reference integration candidate",
        "confidence": "medium",
        "next_actor_suggestion": "none",
        "proposals": ["Review the reference callback."],
        "gaps": ["No model or provider was called."],
        "uncertainty": "medium",
    }
    expected_fields = hook.get("expected_fields") or []
    if not isinstance(expected_fields, list):
        raise ValueError("hook expected_fields must be an array")
    for field in expected_fields:
        if not isinstance(field, str):
            raise ValueError("hook expected field names must be strings")
        output.setdefault(field, [] if field.endswith("s") else f"reference {field}")
    return output


def _build_callback(hook: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    receipt = task.get("dispatch_receipt")
    route = task.get("route")
    workspace = task.get("workspace")
    if not isinstance(receipt, dict):
        raise ValueError("generated task does not contain dispatch_receipt")
    if not isinstance(route, dict) or not isinstance(workspace, dict):
        raise ValueError("generated task route/workspace is malformed")
    request = hook["runtime_adapter_request"]
    required: List[str] = request["required_capabilities"]
    negotiated = [item for item in required if item in SUPPORTED_CAPABILITIES]
    return {
        "schema": "wsa.hermes.callback.v1",
        "callback_id": f"reference_{task['task_id']}",
        "task_id": task["task_id"],
        "workspace_id": workspace["workspace_id"],
        "created_at": task.get("created_at"),
        "status": "completed",
        "route": route,
        "dispatch_receipt": receipt,
        "payload": {
            "run_id": hook["run_id"],
            "turn_id": hook["turn_id"],
            "output": _reference_output(hook),
        },
        "artifact_refs": [],
        "runtime_adapter": {
            "schema": RUNTIME_CAPABILITY_RESPONSE_SCHEMA,
            "protocol": STDIO_RUNTIME_PROTOCOL_SCHEMA,
            "capabilities": list(SUPPORTED_CAPABILITIES),
            "negotiated_capabilities": negotiated,
            "provider": None,
            "secret_values_recorded": False,
            "canon_mutation_performed": False,
        },
    }


def main() -> int:
    try:
        hook = _read_hook()
        workspace = Path.cwd().resolve()
        callback = _build_callback(hook, _create_task(hook, workspace))
        json.dump(callback, sys.stdout, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0
    except Exception as exc:
        sys.stderr.write(f"reference stdio adapter failed: {type(exc).__name__}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
