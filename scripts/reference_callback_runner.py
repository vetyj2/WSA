from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic no-network reference runtime for one WSA bridge hook."
    )
    parser.add_argument("--next-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workspace", type=Path)
    return parser


def _workspace_for(next_json: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    env_value = os.environ.get("WSA_WORKSPACE")
    if env_value:
        return Path(env_value).expanduser().resolve()
    resolved = next_json.expanduser().resolve()
    if resolved.parent.name == "hermes":
        return resolved.parent.parent
    raise ValueError("--workspace is required when next JSON is not under workspace/hermes")


def _run_wsa(argv: list[str], workspace: Path) -> str:
    if not argv or argv[0] != "wsa":
        raise ValueError("generated command must start with wsa")
    command = argv if shutil.which("wsa") else [sys.executable, "-m", "wsa", *argv[1:]]
    env = dict(os.environ)
    env["WSA_WORKSPACE"] = str(workspace)
    source_root = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(source_root), env.get("PYTHONPATH", "")) if item
    )
    result = subprocess.run(
        command,
        cwd=workspace,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _task_ref(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("task_path: "):
            return line.split(": ", 1)[1]
    raise ValueError("generated Hermes task command did not report task_path")


def main() -> int:
    args = build_parser().parse_args()
    next_payload = json.loads(args.next_json.read_text(encoding="utf-8"))
    hook = next_payload.get("hook")
    if not isinstance(hook, dict):
        raise ValueError("next JSON does not contain an executable hook")
    workspace = _workspace_for(args.next_json, args.workspace)
    terminal_command = hook.get("terminal_command") or {}
    task_stdout = _run_wsa(list(terminal_command.get("argv") or []), workspace)
    task_ref = _task_ref(task_stdout)
    task_path = workspace / task_ref
    task = json.loads(task_path.read_text(encoding="utf-8"))
    output = {
        "position": "Reference runtime completed the bounded hook.",
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
    for field in hook.get("expected_fields", []):
        output.setdefault(field, [] if field.endswith("s") else f"reference {field}")
    route = dict(task.get("route") or {})
    dispatch_receipt = task.get("dispatch_receipt")
    if not isinstance(dispatch_receipt, dict):
        raise ValueError("generated bridge task does not contain dispatch_receipt")
    callback = {
        "schema": "wsa.hermes.callback.v1",
        "callback_id": f"reference_{task['task_id']}",
        "task_id": task["task_id"],
        "workspace_id": task["workspace"]["workspace_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "route": route,
        "dispatch_receipt": dispatch_receipt,
        "payload": {
            "run_id": hook["run_id"],
            "turn_id": hook["turn_id"],
            "output": output,
        },
        "artifact_refs": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(callback, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    callback_ref = args.output.resolve().relative_to(workspace).as_posix()
    collection_argv = [
        callback_ref if value == "hermes/callbacks/<callback>.json" else value
        for value in terminal_command.get("callback_collection_shape", [])
    ]
    _run_wsa(collection_argv, workspace)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
