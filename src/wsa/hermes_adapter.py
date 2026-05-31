from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from .autonomy import discretion_scale_contract, fill_the_rest_contract
from .hermes_commands import HERMES_COMMAND_REGISTRY_FILENAME
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
CALLBACK_STATUSES = ("completed", "failed", "blocked", "quarantined", "waiting_approval")
DELIVERY_TARGETS = ("origin", "local", "telegram", "discord", "none")
SENSITIVITY_LEVELS = ("public", "internal", "sensitive")
SESSION_MODES = ("callback_only", "gateway_origin", "cli", "cron", "background")


class HermesAdapterError(ValueError):
    """Raised when a Hermes adapter packet is malformed."""


class HermesAdapterRouteError(HermesAdapterError):
    """Raised when a Hermes callback route does not match its task."""


@dataclass(frozen=True)
class HermesTaskRecord:
    task_id: str
    task_path: Path
    task_ref: str
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
        runtime_target: Optional[Dict[str, Any]] = None,
        delivery: Optional[Dict[str, Any]] = None,
        sensitivity: Optional[Dict[str, Any]] = None,
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

    def task_state_dir(self) -> Path:
        return safe_child_path(self.workspace, "hermes", "task_state")

    def callbacks_dir(self) -> Path:
        return safe_child_path(self.workspace, "hermes", "callbacks")

    def quarantine_dir(self) -> Path:
        return safe_child_path(self.workspace, "hermes", "quarantine")

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
            "command_registry": f"hermes/adapter_config/{HERMES_COMMAND_REGISTRY_FILENAME}",
            "workspace": {
                "root": ".",
                "env": "WSA_WORKSPACE",
                "path_policy": "relative_to_workspace_root",
            },
            "task_queue": "hermes/task_queue",
            "task_state": "hermes/task_state",
            "callbacks": "hermes/callbacks",
            "reports_outbox": "hermes/reports_outbox",
            "quarantine": "hermes/quarantine",
            "maintenance": "hermes/maintenance",
            "agent_harness": build_agent_harness_contract(),
            "runtime_target": build_runtime_target(),
            "delivery": build_delivery_contract(),
            "sensitivity": build_sensitivity_contract(),
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
        runtime_target: Optional[Dict[str, Any]] = None,
        delivery: Optional[Dict[str, Any]] = None,
        sensitivity: Optional[Dict[str, Any]] = None,
    ) -> HermesTaskRecord:
        self.ensure_layout()
        world = get_world(self.workspace, world_id)
        runtime_target = runtime_target or build_runtime_target()
        delivery = delivery or build_delivery_contract()
        sensitivity = sensitivity or build_sensitivity_contract()
        if session_id is None:
            session_id = self.transport.start_session(
                role=role,
                runtime_target=f"hermes:{self.adapter_name}",
                world_id=world.world_id,
                payload={
                    "adapter": "cli",
                    "adapter_name": self.adapter_name,
                    "runtime_target": runtime_target,
                },
            )

        task_payload = {
            "task_type": task_type,
            "title": title,
            "instruction": instruction,
            "input": payload or {},
            "sensitivity": sensitivity,
            "delivery": delivery,
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
        task_ref = self._workspace_relative(task_path)
        packet = {
            "schema": HERMES_TASK_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "created_at": utc_now(),
            "adapter": {
                "type": "cli",
                "name": self.adapter_name,
                "command": self.command,
                "command_preview": [self.command, "run-task", task_ref],
            },
            "workspace": {
                "workspace_id": self.workspace_id,
                "workspace_root": ".",
                "path_policy": "relative_to_workspace_root",
            },
            "route": {
                "world_id": world.world_id,
                "scene_id": None,
                "session_id": session_id,
                "role": role,
            },
            "task": task_payload,
            "runtime_envelope": envelope.to_dict(),
            "runtime_target": runtime_target,
            "delivery": delivery,
            "sensitivity": sensitivity,
            "paths": {
                "task_queue": "hermes/task_queue",
                "task_state": "hermes/task_state",
                "callbacks": "hermes/callbacks",
                "reports_outbox": "hermes/reports_outbox",
                "quarantine": "hermes/quarantine",
                "maintenance": "hermes/maintenance",
            },
            "agent_harness": build_agent_harness_contract(),
            "operation_contract": build_operation_contract(),
        }
        task_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._write_task_state(
            task_id,
            "queued",
            {
                "task_ref": task_ref,
                "session_id": session_id,
                "world_id": world.world_id,
                "runtime_target": runtime_target,
            },
        )
        return HermesTaskRecord(
            task_id=task_id,
            task_path=task_path,
            task_ref=task_ref,
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
        try:
            callback = self._load_json(callback_path)
            task_id = self._required_str(callback, "task_id")
            task = self._load_task(task_id)
            self._validate_callback_shape(callback)
            self._validate_callback_route(task, callback)
        except HermesAdapterError as exc:
            self._quarantine_callback(callback_path, exc)
            raise

        route = callback["route"]
        payload = dict(callback.get("payload") or {})
        delivery = self._delivery_if_any(callback)
        sensitivity = self._sensitivity_if_any(callback)
        if delivery:
            payload["delivery"] = delivery
        if sensitivity:
            payload["sensitivity"] = sensitivity
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
        self._write_task_state(
            task_id,
            status,
            {
                "callback_id": self._required_str(callback, "callback_id"),
                "callback_ref": self._workspace_relative(callback_path),
                "message_id": envelope.message_id,
                "report_id": report_id,
            },
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
        payload = dict(report_payload.get("payload") or {})
        delivery = self._delivery_if_any(report_payload) or self._delivery_if_any(callback)
        sensitivity = self._sensitivity_if_any(report_payload) or self._sensitivity_if_any(callback)
        if delivery:
            payload["delivery"] = delivery
        if sensitivity:
            payload["sensitivity"] = sensitivity
        report = self.mailbox.create_world_report(
            repo,
            title=str(report_payload.get("title") or "Hermes report"),
            purpose=str(report_payload.get("purpose") or "hermes_callback"),
            risk=str(report_payload.get("risk") or "low"),
            status=status,
            payload=payload,
        )
        return report.report_id

    def _load_task(self, task_id: str) -> Dict[str, Any]:
        task_path = safe_child_path(self.task_queue_dir(), f"{task_id}.json")
        return self._load_json(task_path)

    def _resolve_callback_path(self, path: Path, allow_external_path: bool) -> Path:
        expanded = path.expanduser()
        if expanded.is_absolute():
            resolved = expanded.resolve()
        else:
            resolved = safe_child_path(self.workspace, expanded.as_posix())
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

    def _workspace_relative(self, path: Path) -> str:
        resolved_workspace = self.workspace.resolve()
        resolved_path = path.resolve()
        try:
            return resolved_path.relative_to(resolved_workspace).as_posix()
        except ValueError:
            return str(resolved_path)

    def _load_json(self, path: Path) -> Dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except json.JSONDecodeError as exc:
            raise HermesAdapterError(f"invalid JSON: {path}") from exc
        except OSError as exc:
            raise HermesAdapterError(f"cannot read JSON: {path}") from exc
        if not isinstance(value, dict):
            raise HermesAdapterError(f"expected JSON object: {path}")
        return value

    def _write_task_state(self, task_id: str, status: str, payload: Dict[str, Any]) -> Path:
        self.task_state_dir().mkdir(parents=True, exist_ok=True)
        path = safe_child_path(self.task_state_dir(), f"{task_id}.json")
        value = {
            "schema": "wsa.hermes.task_state.v1",
            "task_id": task_id,
            "status": status,
            "updated_at": utc_now(),
            "payload": payload,
        }
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def _quarantine_callback(self, callback_path: Path, error: Exception) -> Path:
        self.quarantine_dir().mkdir(parents=True, exist_ok=True)
        task_id = self._task_id_from_untrusted_callback(callback_path)
        quarantine_id = new_id("quarantine")
        path = safe_child_path(self.quarantine_dir(), f"{quarantine_id}.json")
        value = {
            "schema": "wsa.hermes.callback_quarantine.v1",
            "quarantine_id": quarantine_id,
            "created_at": utc_now(),
            "callback_ref": self._workspace_relative(callback_path),
            "task_id": task_id,
            "error": str(error),
        }
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if task_id:
            self._write_task_state(
                task_id,
                "quarantined",
                {
                    "callback_ref": value["callback_ref"],
                    "quarantine_ref": self._workspace_relative(path),
                    "error": str(error),
                },
            )
        return path

    def _task_id_from_untrusted_callback(self, callback_path: Path) -> str | None:
        try:
            value = json.loads(callback_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(value, dict) and isinstance(value.get("task_id"), str):
            return value["task_id"]
        return None

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

    def _validate_callback_shape(self, callback: Dict[str, Any]) -> None:
        status = str(callback.get("status") or "completed")
        if status not in CALLBACK_STATUSES:
            raise HermesAdapterError(f"unsupported callback status: {status}")
        payload = callback.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise HermesAdapterError("callback payload must be an object")
        artifact_refs = callback.get("artifact_refs")
        if artifact_refs is not None:
            self._validate_string_list(artifact_refs, "artifact_refs")
        self._delivery_if_any(callback)
        self._sensitivity_if_any(callback)

        report = callback.get("report")
        if report is not None:
            if not isinstance(report, dict):
                raise HermesAdapterError("report must be an object")
            report_payload = report.get("payload")
            if report_payload is not None and not isinstance(report_payload, dict):
                raise HermesAdapterError("report payload must be an object")
            self._delivery_if_any(report)
            self._sensitivity_if_any(report)

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
            approval_prompt = item.get("approval_prompt")
            if approval_prompt is not None:
                self._validate_approval_prompt(approval_prompt)
            requests.append(dict(item))
        return requests

    def _validate_approval_prompt(self, value: Any) -> None:
        if not isinstance(value, dict):
            raise HermesAdapterError("approval_prompt must be an object")
        for key in ("exact_command", "meaning", "why_needed", "rollback"):
            if key in value and not isinstance(value[key], str):
                raise HermesAdapterError(f"approval_prompt.{key} must be a string")
        if "risks" in value:
            self._validate_string_list(value["risks"], "approval_prompt.risks")

    def _delivery_if_any(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        value = packet.get("delivery")
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise HermesAdapterError("delivery must be an object")
        target = value.get("target", "origin")
        if target not in DELIVERY_TARGETS:
            raise HermesAdapterError(f"unsupported delivery target: {target}")
        if "requires_human_approval" in value and not isinstance(
            value["requires_human_approval"], bool
        ):
            raise HermesAdapterError("delivery.requires_human_approval must be a boolean")
        if "safe_for_chat" in value and not isinstance(value["safe_for_chat"], bool):
            raise HermesAdapterError("delivery.safe_for_chat must be a boolean")
        return dict(value)

    def _sensitivity_if_any(self, packet: Dict[str, Any]) -> Dict[str, Any]:
        value = packet.get("sensitivity")
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise HermesAdapterError("sensitivity must be an object")
        level = value.get("level", "internal")
        if level not in SENSITIVITY_LEVELS:
            raise HermesAdapterError(f"unsupported sensitivity level: {level}")
        return dict(value)

    def _validate_string_list(self, value: Any, name: str) -> None:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise HermesAdapterError(f"{name} must be a list of strings")


def build_operation_contract() -> Dict[str, Any]:
    return {
        "schema": HERMES_OPERATION_CONTRACT_SCHEMA,
        "owner": "hermes_runtime",
        "approval": "user_required",
        "action_request_format": {
            "message_type": "operation_request",
            "required_fields": ["action", "mode", "summary"],
            "optional_fields": ["payload", "dry_run", "approval_prompt"],
            "approval_prompt_fields": [
                "exact_command",
                "meaning",
                "why_needed",
                "risks",
                "rollback",
            ],
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


def build_runtime_target(
    profile: str = "default",
    source: str = "cli",
    session_mode: str = "callback_only",
    workdir: str = ".",
    interactive: bool = False,
    background: bool = False,
    toolsets: Optional[List[str]] = None,
    skills: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if session_mode not in SESSION_MODES:
        raise HermesAdapterError(f"unsupported session_mode: {session_mode}")
    return {
        "schema": "wsa.hermes.runtime_target.v1",
        "profile": profile,
        "source": source,
        "session_mode": session_mode,
        "workdir": workdir,
        "interactive": interactive,
        "background": background,
        "toolsets": toolsets or [],
        "skills": skills or [],
        "callback_policy": {
            "required": True,
            "callback_dir": "hermes/callbacks",
            "quarantine_dir": "hermes/quarantine",
            "external_callback_paths": False,
        },
    }


def build_delivery_contract(
    target: str = "origin",
    safe_for_chat: bool = False,
    requires_human_approval: bool = True,
) -> Dict[str, Any]:
    if target not in DELIVERY_TARGETS:
        raise HermesAdapterError(f"unsupported delivery target: {target}")
    return {
        "schema": "wsa.delivery.v1",
        "target": target,
        "safe_for_chat": safe_for_chat,
        "requires_human_approval": requires_human_approval,
        "chat_summary": "allowed",
        "full_artifact": "local_report_or_file_attachment",
    }


def build_sensitivity_contract(
    level: str = "internal",
    contains_workspace_payloads: bool = True,
) -> Dict[str, Any]:
    if level not in SENSITIVITY_LEVELS:
        raise HermesAdapterError(f"unsupported sensitivity level: {level}")
    return {
        "schema": "wsa.sensitivity.v1",
        "level": level,
        "contains_workspace_payloads": contains_workspace_payloads,
    }


def build_agent_harness_contract() -> Dict[str, Any]:
    return {
        "schema": "wsa.hermes.agent_harness.v1",
        "expected_cwd": "workspace_root",
        "path_policy": "relative_to_workspace_root",
        "autonomy_policy": {
            "owner": "user_hermes_runtime_dialogue",
            "enforcement": "guidance_only",
            "range": {"min": 0, "max": 100},
            "discretion_customizable": True,
            "discretion_scale": discretion_scale_contract(),
            "fill_the_rest": fill_the_rest_contract(),
            "fully_autonomous_generation_allowed": True,
            "checkpoint_policy": {
                "natural_language_allowed": True,
                "recommended": True,
                "examples": [
                    "until 100 characters exist",
                    "until three regions have factions, conflicts, and opening hooks",
                    "until the first academy year has enough institutions for scene play",
                ],
                "on_checkpoint": "summarize candidates and request user decision",
            },
            "canon_policy": (
                "Autonomous generation may produce candidates; canon mutation still follows "
                "the user's Hermes runtime policy and WSA ticket or callback review flow."
            ),
        },
        "read_roots": [
            ".",
        ],
        "write_roots": [
            "hermes/callbacks",
            "hermes/reports_outbox",
            "hermes/maintenance",
            "hermes/task_state",
            "hermes/quarantine",
            "manager/runtime_sessions",
        ],
        "world_state_policy": {
            "direct_db_writes": False,
            "direct_world_file_mutation": False,
            "use_tickets_or_callbacks_for_changes": True,
        },
        "meeting_mode": {
            "purpose": "representative diagnosis and proposal gathering",
            "world_mutation": "proposal_only",
        },
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
        "delivery": build_delivery_contract(),
        "sensitivity": build_sensitivity_contract(),
        "artifact_refs": [],
        "report": {
            "title": title,
            "purpose": "hermes_callback",
            "risk": "low",
            "status": "inbox",
            "delivery": build_delivery_contract(),
            "sensitivity": build_sensitivity_contract(),
            "payload": {
                "summary": summary,
                "task_id": task.task_id,
            },
        },
    }
