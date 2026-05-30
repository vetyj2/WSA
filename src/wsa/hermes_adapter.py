from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from .paths import safe_child_path
from .reports import ReportMailbox, validate_report_state
from .repositories import WorldRepository, new_id
from .runtime import RuntimeEnvelope
from .transport import RuntimeTransport
from .workspace import SCHEMA_VERSION, get_world, init_workspace, utc_now


DEFAULT_HERMES_ADAPTER_NAME = "example-hermes"
DEFAULT_HERMES_COMMAND = "wsa-hermes-cli"
HERMES_TASK_SCHEMA = "wsa.hermes.task.v1"
HERMES_CALLBACK_SCHEMA = "wsa.hermes.callback.v1"
HERMES_OPERATION_CONTRACT_SCHEMA = "wsa.hermes.operation_contract.v1"
ALLOWED_OPERATION_ACTIONS = {"version_control.snapshot"}
ALLOWED_OPERATION_MODES = ("none", "local_commit", "remote_push", "custom")


class HermesAdapterError(ValueError):
    """Raised when a Hermes adapter packet is malformed."""


class HermesAdapterRouteError(HermesAdapterError):
    """Raised when a Hermes callback route does not match its task."""


@dataclass(frozen=True)
class HermesTaskRecord:
    task_id: str
    task_path: Path
    session_id: str
    workspace_id: str
    world_id: str
    role: str
    runtime_envelope: RuntimeEnvelope


@dataclass(frozen=True)
class HermesCallbackRecord:
    callback_id: str
    callback_path: Path
    task_id: str
    session_id: str
    world_id: str
    status: str
    runtime_envelope: RuntimeEnvelope
    report_id: Optional[str] = None


class RuntimeAdapter(Protocol):
    def create_task(
        self,
        world_id: str,
        title: str,
        instruction: str,
        task_type: str = "manager_diagnostic",
        role: str = "world_manager",
        session_id: str | None = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> HermesTaskRecord:
        ...

    def collect_callback(self, callback_path: Path) -> HermesCallbackRecord:
        ...


class HermesCliTemplateAdapter:
    """CLI-first Hermes adapter template.

    The template writes file-contract packets and collects callbacks. It does
    not start Docker, Telegram, sockets, or real Hermes processes.
    """

    def __init__(
        self,
        workspace: Path,
        workspace_id: str = "local",
        adapter_name: str = DEFAULT_HERMES_ADAPTER_NAME,
        command: str = DEFAULT_HERMES_COMMAND,
    ) -> None:
        self.workspace = workspace
        self.workspace_id = workspace_id
        self.adapter_name = adapter_name
        self.command = command
        self.transport = RuntimeTransport(workspace, workspace_id)
        self.mailbox = ReportMailbox(workspace)

    def ensure_layout(self) -> None:
        init_workspace(self.workspace)

    def task_queue_dir(self) -> Path:
        return safe_child_path(self.workspace, "hermes", "task_queue")

    def callbacks_dir(self) -> Path:
        return safe_child_path(self.workspace, "hermes", "callbacks")

    def reports_outbox_dir(self) -> Path:
        return safe_child_path(self.workspace, "hermes", "reports_outbox")

    def adapter_config_dir(self) -> Path:
        return safe_child_path(self.workspace, "hermes", "adapter_config")

    def write_example_config(self, overwrite: bool = False) -> Path:
        self.ensure_layout()
        path = safe_child_path(
            self.adapter_config_dir(),
            "hermes_cli.example.json",
        )
        if path.exists() and not overwrite:
            return path

        payload = {
            "schema": "wsa.hermes.cli_config.example.v1",
            "adapter": "cli",
            "name": self.adapter_name,
            "command": self.command,
            "cwd": ".",
            "task_queue": "hermes/task_queue",
            "callbacks": "hermes/callbacks",
            "reports_outbox": "hermes/reports_outbox",
            "maintenance": "hermes/maintenance",
            "timeout_seconds": 300,
            "operation_contract": build_operation_contract(),
            "secret_env": [
                "HERMES_BOT_TOKEN",
                "OPENAI_API_KEY",
            ],
            "notes": [
                "Template only. Do not put raw secret values in this file.",
                "WSA writes task JSON; the Hermes CLI wrapper reads it and writes callback JSON.",
            ],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def create_task(
        self,
        world_id: str,
        title: str,
        instruction: str,
        task_type: str = "manager_diagnostic",
        role: str = "world_manager",
        session_id: str | None = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> HermesTaskRecord:
        self.ensure_layout()
        world = get_world(self.workspace, world_id)
        if session_id is None:
            session_id = self.transport.start_session(
                role=role,
                runtime_target=f"hermes:{self.adapter_name}",
                world_id=world.world_id,
                payload={"adapter": "cli", "adapter_name": self.adapter_name},
            )

        task_payload = {
            "task_type": task_type,
            "title": title,
            "instruction": instruction,
            "input": payload or {},
        }
        envelope = self.transport.send(
            session_id=session_id,
            direction="inbox",
            role="wsa",
            message_type="intent_request",
            world_id=world.world_id,
            payload=task_payload,
        )
        task_id = new_id("hermes_task")
        task_path = safe_child_path(self.task_queue_dir(), f"{task_id}.json")
        packet = {
            "schema": HERMES_TASK_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "created_at": utc_now(),
            "adapter": {
                "type": "cli",
                "name": self.adapter_name,
                "command": self.command,
                "command_preview": [self.command, "run-task", str(task_path)],
            },
            "workspace": {
                "workspace_id": self.workspace_id,
                "workspace_root_hint": str(self.workspace),
            },
            "route": {
                "world_id": world.world_id,
                "scene_id": None,
                "session_id": session_id,
                "role": role,
            },
            "task": task_payload,
            "runtime_envelope": envelope.to_dict(),
            "paths": {
                "task_queue": "hermes/task_queue",
                "callbacks": "hermes/callbacks",
                "reports_outbox": "hermes/reports_outbox",
                "maintenance": "hermes/maintenance",
            },
            "operation_contract": build_operation_contract(),
        }
        task_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return HermesTaskRecord(
            task_id=task_id,
            task_path=task_path,
            session_id=session_id,
            workspace_id=self.workspace_id,
            world_id=world.world_id,
            role=role,
            runtime_envelope=envelope,
        )

    def collect_callback(
        self,
        callback_path: Path,
        allow_external_path: bool = False,
    ) -> HermesCallbackRecord:
        self.ensure_layout()
        callback_path = self._resolve_callback_path(callback_path, allow_external_path)
        callback = self._load_json(callback_path)
        task_id = self._required_str(callback, "task_id")
        task = self._load_task(task_id)
        self._validate_callback_route(task, callback)

        route = callback["route"]
        payload = dict(callback.get("payload") or {})
        operation_requests = self._operation_requests_if_any(callback)
        if operation_requests:
            payload["operation_requests"] = operation_requests
        artifact_refs = list(callback.get("artifact_refs") or [])
        message_type = str(callback.get("message_type") or "final_report")
        status = str(callback.get("status") or "completed")
        report_id = self._create_report_if_requested(route["world_id"], callback)
        if report_id is not None:
            payload["report_id"] = report_id

        envelope = self.transport.send(
            session_id=route["session_id"],
            direction="outbox",
            role=route["role"],
            message_type=message_type,
            world_id=route["world_id"],
            scene_id=route.get("scene_id"),
            payload=payload,
            artifact_refs=artifact_refs,
            status=status,
        )
        return HermesCallbackRecord(
            callback_id=self._required_str(callback, "callback_id"),
            callback_path=callback_path,
            task_id=task_id,
            session_id=route["session_id"],
            world_id=route["world_id"],
            status=status,
            runtime_envelope=envelope,
            report_id=report_id,
        )

    def _create_report_if_requested(
        self,
        world_id: str,
        callback: Dict[str, Any],
    ) -> str | None:
        report_payload = callback.get("report")
        if report_payload is None:
            return None
        if not isinstance(report_payload, dict):
            raise HermesAdapterError("report must be an object")

        status = str(report_payload.get("status") or "inbox")
        validate_report_state(status)
        world = get_world(self.workspace, world_id)
        repo = WorldRepository(world.world_id, world.path)
        report = self.mailbox.create_world_report(
            repo,
            title=str(report_payload.get("title") or "Hermes report"),
            purpose=str(report_payload.get("purpose") or "hermes_callback"),
            risk=str(report_payload.get("risk") or "low"),
            status=status,
            payload=dict(report_payload.get("payload") or {}),
        )
        return report.report_id

    def _load_task(self, task_id: str) -> Dict[str, Any]:
        task_path = safe_child_path(self.task_queue_dir(), f"{task_id}.json")
        return self._load_json(task_path)

    def _resolve_callback_path(self, path: Path, allow_external_path: bool) -> Path:
        resolved = path.expanduser().resolve()
        if allow_external_path:
            return resolved

        callbacks_root = self.callbacks_dir().resolve()
        try:
            resolved.relative_to(callbacks_root)
        except ValueError as exc:
            raise HermesAdapterError(
                "callback_path must be inside hermes/callbacks unless external paths are allowed"
            ) from exc
        return resolved

    def _load_json(self, path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise HermesAdapterError(f"expected JSON object: {path}")
        return value

    def _validate_callback_route(
        self,
        task: Dict[str, Any],
        callback: Dict[str, Any],
    ) -> None:
        if callback.get("schema") != HERMES_CALLBACK_SCHEMA:
            raise HermesAdapterError(f"unsupported callback schema: {callback.get('schema')}")
        task_route = task.get("route")
        callback_route = callback.get("route")
        if not isinstance(task_route, dict) or not isinstance(callback_route, dict):
            raise HermesAdapterError("task and callback require route objects")

        for key in ("world_id", "scene_id", "session_id", "role"):
            if callback_route.get(key) != task_route.get(key):
                raise HermesAdapterRouteError(f"callback {key} does not match task route")

        if callback.get("workspace_id") != task.get("workspace", {}).get("workspace_id"):
            raise HermesAdapterRouteError("callback workspace_id does not match task")

    def _required_str(self, packet: Dict[str, Any], key: str) -> str:
        value = packet.get(key)
        if not isinstance(value, str) or not value:
            raise HermesAdapterError(f"{key} is required")
        return value

    def _operation_requests_if_any(self, callback: Dict[str, Any]) -> List[Dict[str, Any]]:
        value = callback.get("operation_requests")
        if value is None:
            return []
        if not isinstance(value, list):
            raise HermesAdapterError("operation_requests must be a list")

        requests: List[Dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                raise HermesAdapterError("operation request must be an object")
            action = item.get("action")
            mode = item.get("mode")
            summary = item.get("summary")
            if not isinstance(action, str) or not action:
                raise HermesAdapterError("operation request action is required")
            if not isinstance(mode, str) or not mode:
                raise HermesAdapterError("operation request mode is required")
            if not isinstance(summary, str) or not summary:
                raise HermesAdapterError("operation request summary is required")
            if action not in ALLOWED_OPERATION_ACTIONS:
                raise HermesAdapterError(f"unsupported operation request action: {action}")
            if mode not in ALLOWED_OPERATION_MODES:
                raise HermesAdapterError(f"unsupported operation request mode: {mode}")
            requests.append(dict(item))
        return requests


def build_operation_contract() -> Dict[str, Any]:
    return {
        "schema": HERMES_OPERATION_CONTRACT_SCHEMA,
        "owner": "hermes_runtime",
        "approval": "user_required",
        "action_request_format": {
            "message_type": "operation_request",
            "required_fields": ["action", "mode", "summary"],
            "optional_fields": ["payload", "dry_run"],
        },
        "actions": [
            {
                "action": "version_control.snapshot",
                "modes": list(ALLOWED_OPERATION_MODES),
                "executor": "user_hermes_adapter",
                "notes": [
                    "The WSA template declares intent only.",
                    "Each Hermes runtime maps this action to its own local policy.",
                    "Remote push, local commit, and disabled modes are all valid.",
                ],
            }
        ],
    }


def build_template_callback(
    task: HermesTaskRecord,
    title: str = "Hermes template callback",
    summary: str = "Template Hermes callback completed.",
    status: str = "completed",
) -> Dict[str, Any]:
    return {
        "schema": HERMES_CALLBACK_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "callback_id": new_id("hermes_callback"),
        "task_id": task.task_id,
        "workspace_id": task.workspace_id,
        "created_at": utc_now(),
        "status": status,
        "message_type": "final_report",
        "route": {
            "world_id": task.world_id,
            "scene_id": None,
            "session_id": task.session_id,
            "role": task.role,
        },
        "payload": {
            "summary": summary,
        },
        "artifact_refs": [],
        "report": {
            "title": title,
            "purpose": "hermes_callback",
            "risk": "low",
            "status": "inbox",
            "payload": {
                "summary": summary,
                "task_id": task.task_id,
            },
        },
    }
