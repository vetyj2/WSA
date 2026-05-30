#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TASK_SCHEMA = "wsa.hermes.task.v1"
CALLBACK_SCHEMA = "wsa.hermes.callback.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def workspace_root() -> Path:
    value = os.environ.get("WSA_WORKSPACE")
    if value:
        return Path(value).expanduser().resolve()
    return Path.cwd().resolve()


def safe_child_path(base: Path, path_ref: str) -> Path:
    candidate = Path(path_ref)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"path must stay under workspace root: {path_ref}")
    resolved = base.joinpath(candidate).resolve()
    resolved.relative_to(base.resolve())
    return resolved


def load_task(root: Path, task_ref: str) -> dict[str, Any]:
    path = safe_child_path(root, task_ref)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("task JSON must be an object")
    if value.get("schema") != TASK_SCHEMA:
        raise ValueError(f"unsupported task schema: {value.get('schema')}")
    return value


def write_callback(root: Path, task: dict[str, Any], status: str) -> Path:
    callback_id = f"hermes_callback_{uuid.uuid4().hex}"
    callbacks_dir = safe_child_path(root, task["paths"]["callbacks"])
    callbacks_dir.mkdir(parents=True, exist_ok=True)
    route = task["route"]
    task_payload = task["task"]
    summary = f"Reference wrapper completed task: {task_payload['title']}"
    callback = {
        "schema": CALLBACK_SCHEMA,
        "schema_version": task["schema_version"],
        "callback_id": callback_id,
        "task_id": task["task_id"],
        "workspace_id": task["workspace"]["workspace_id"],
        "created_at": utc_now(),
        "status": status,
        "message_type": "final_report",
        "route": route,
        "payload": {
            "summary": summary,
            "reference_wrapper": True,
        },
        "delivery": task.get("delivery", {}),
        "sensitivity": task.get("sensitivity", {}),
        "artifact_refs": [],
        "report": {
            "title": f"Reference Hermes callback: {task_payload['title']}",
            "purpose": "hermes_callback",
            "risk": "low",
            "status": "inbox",
            "delivery": task.get("delivery", {}),
            "sensitivity": task.get("sensitivity", {}),
            "payload": {
                "summary": summary,
                "task_id": task["task_id"],
                "reference_wrapper": True,
            },
        },
    }
    callback_path = callbacks_dir / f"{callback_id}.json"
    callback_path.write_text(
        json.dumps(callback, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return callback_path


def write_quarantine(root: Path, task_ref: str | None, error: Exception) -> Path:
    quarantine_dir = safe_child_path(root, "hermes/quarantine")
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    quarantine_id = f"quarantine_{uuid.uuid4().hex}"
    payload = {
        "schema": "wsa.hermes.reference_wrapper_quarantine.v1",
        "quarantine_id": quarantine_id,
        "created_at": utc_now(),
        "task_ref": task_ref,
        "error": str(error),
        "source": "examples/wsa_hermes_cli_reference.py",
    }
    path = quarantine_dir / f"{quarantine_id}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def run_task(args: argparse.Namespace) -> int:
    root = workspace_root()
    task = load_task(root, args.task_json)
    callback_path = write_callback(root, task, args.status)
    print(f"callback_path: {callback_path.relative_to(root).as_posix()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wsa-hermes-cli-reference",
        description="Safe reference wrapper for WSA Hermes task packets.",
    )
    subparsers = parser.add_subparsers(dest="command")
    run = subparsers.add_parser("run-task", help="Read a task JSON and write a callback JSON.")
    run.add_argument("task_json", help="Task JSON path relative to the workspace root.")
    run.add_argument(
        "--status",
        choices=("completed", "failed", "blocked"),
        default="completed",
        help="Callback status to write.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "run-task":
            return run_task(args)
        parser.print_help()
        return 0
    except Exception as exc:
        root = workspace_root()
        task_ref = getattr(args, "task_json", None)
        quarantine_path = write_quarantine(root, task_ref, exc)
        print(f"error: {exc}", file=sys.stderr)
        print(f"quarantine_path: {quarantine_path.relative_to(root).as_posix()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
