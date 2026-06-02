from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .hermes_adapter import HERMES_CALLBACK_SCHEMA
from .orchestrator_turns import (
    build_actor_turn_record,
    build_manager_check_turn_records,
    build_orchestrator_turn_record,
    build_round_prompt_packet,
    update_floor_state,
)
from .paths import safe_child_path
from .repositories import ControlRepository, WorldRepository
from .reports import ReportMailbox
from .workspace import WorldRecord, list_worlds, utc_now


ORCHESTRATOR_NEXT_SCHEMA = "wsa.orchestrator.next.v1"
ORCHESTRATOR_SUBMIT_SCHEMA = "wsa.orchestrator.submit.v1"
BRIDGE_MODES = {"hermes-bridge", "hermes_bridge", "hermes-runtime", "hermes_runtime"}
MAX_CALLBACK_BYTES = 256 * 1024
MAX_TEXT_CHARS = 4000
MAX_LIST_ITEMS = 16
MAX_DICT_ITEMS = 24
ALLOWED_OUTPUT_FIELDS = {
    "answer",
    "canon_mutation",
    "confidence",
    "conflicts",
    "dependencies",
    "gaps",
    "new_claims",
    "next_actor_suggestion",
    "objections",
    "position",
    "proposals",
    "risk_flags",
    "source_refs",
    "stance",
    "uncertainty",
    "worldbuilding_use",
}


def is_hermes_bridge_mode(mode: str) -> bool:
    return mode.strip().casefold() in BRIDGE_MODES


def initialize_bridge_payload(payload: Dict[str, Any], world_id: str) -> None:
    participant_count = len(payload.get("context_packets", []))
    max_rounds = int(payload.get("queue_limits", {}).get("queue_turns_used") or 0)
    max_calls = int(payload.get("queue_limits", {}).get("planned_subsession_calls") or 0)
    payload["status"] = "awaiting_callback"
    payload["execution_status"] = "waiting_for_hermes"
    payload["subsession_execution_mode"] = "hermes_bridge_pending_callbacks"
    payload["real_subagent_execution"] = "pending_user_hermes_runtime_callbacks"
    payload["runtime_hook_packets"] = []
    payload["round_prompt_packets"] = []
    payload["pending_hooks"] = []
    payload["submitted_callbacks"] = []
    payload["rejected_callbacks"] = []
    payload["subsession_outputs"] = []
    payload["accepted_outputs_only"] = True
    payload["turn_records"] = [
        build_orchestrator_turn_record(
            payload["run_id"],
            1,
            payload.get("workflow_profile", {}),
            payload.get("floor_state", {}),
        )
    ]
    payload["compressed_context_snapshots"] = []
    payload["hermes_bridge"] = {
        "schema": "wsa.orchestrator.hermes_bridge.v1",
        "status": "waiting_for_hermes",
        "next_round": 1,
        "next_participant_index": 0,
        "participant_count": participant_count,
        "max_rounds": max_rounds,
        "max_actor_calls": max_calls,
        "completed_actor_calls": 0,
        "pending_turn_ids": [],
        "callback_policy": {
            "callback_dir": "hermes/callbacks",
            "external_callback_paths": False,
            "execution_owner": "user_hermes_runtime",
        },
    }
    payload["next_action"] = "run_next_hermes_hook"
    _append_next_hook(payload, world_id)


class OrchestratorBridge:
    """Minimal next/submit bridge for Hermes-owned subagent execution."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def next(self, run_id: str) -> Dict[str, Any]:
        _, _, payload = find_bridge_run(self.workspace, run_id)
        pending = payload.get("pending_hooks", [])
        hook = pending[0] if pending else None
        next_action = "run_hermes_hook" if hook else payload.get("next_action", "author_review")
        return {
            "schema": ORCHESTRATOR_NEXT_SCHEMA,
            "run_id": run_id,
            "status": payload.get("status"),
            "execution_status": payload.get("execution_status"),
            "workflow": payload.get("workflow"),
            "skill": payload.get("skill"),
            "next_action": next_action,
            "hook": hook,
            "terminal_command": hook.get("terminal_command") if hook else None,
            "floor_state": payload.get("floor_state", {}),
            "progress_report_policy": payload.get("progress_report_policy", {}),
            "queue_limits": payload.get("queue_limits", {}),
            "hermes_bridge": payload.get("hermes_bridge", {}),
        }

    def submit(self, run_id: str, callback_path: Path) -> Dict[str, Any]:
        world, path, payload = find_bridge_run(self.workspace, run_id)
        callback_path = self._resolve_callback_path(callback_path)
        self._validate_callback_path_unique(callback_path, payload)
        callback = json.loads(callback_path.read_text(encoding="utf-8"))
        turn_payload = self._turn_payload(callback, payload)
        turn_id = turn_payload["turn_id"]
        pending_hooks = payload.get("pending_hooks", [])
        hook = self._pending_hook(pending_hooks, turn_id)
        self._validate_callback_binding(callback, hook)
        output = self._sanitize_output(dict(turn_payload["output"]), hook)
        output.update(
            {
                "run_id": run_id,
                "participant_id": hook["participant_id"],
                "represents": hook["represents"],
                "round": hook["round"],
                "prompt_packet_id": hook["prompt_packet_id"],
            }
        )
        output["quality_gate"] = quality_gate(output, hook.get("expected_fields", []))
        payload.setdefault("submitted_callbacks", []).append(
            self._callback_record(callback, callback_path, turn_id, output["quality_gate"])
        )
        if not output["quality_gate"]["accepted"]:
            return self._reject_callback(path, payload, callback_path, turn_id, output["quality_gate"])

        payload["pending_hooks"] = [
            item for item in pending_hooks if item.get("turn_id") != turn_id
        ]
        payload.setdefault("turn_records", []).append(build_actor_turn_record(hook, output))
        payload.setdefault("subsession_outputs", []).append(output)
        payload.setdefault("turn_records", []).extend(
            build_manager_check_turn_records(run_id, hook["round"], [output])
        )
        payload.setdefault("compressed_context_snapshots", []).append(
            _compressed_bridge_snapshot(payload, hook["round"], [output])
        )
        payload["floor_state"] = update_floor_state(
            payload.get("floor_state", {}),
            hook["round"],
            [output],
            payload.get("turn_records", []),
        )
        bridge = payload.setdefault("hermes_bridge", {})
        bridge["completed_actor_calls"] = int(bridge.get("completed_actor_calls") or 0) + 1
        bridge["pending_turn_ids"] = [
            item.get("turn_id") for item in payload.get("pending_hooks", [])
        ]

        _append_next_hook(payload, world.world_id)
        if not payload.get("pending_hooks"):
            _finalize_bridge_payload(self.workspace, world, path.parent, payload)
        else:
            payload["status"] = "awaiting_callback"
            payload["execution_status"] = "running_in_hermes"
            payload["next_action"] = "run_next_hermes_hook"
            bridge["status"] = "awaiting_callback"

        self._write_run_payload(path, payload)
        return {
            "schema": ORCHESTRATOR_SUBMIT_SCHEMA,
            "run_id": run_id,
            "turn_id": turn_id,
            "accepted": output["quality_gate"]["accepted"],
            "quality_gate": output["quality_gate"],
            "status": payload.get("status"),
            "execution_status": payload.get("execution_status"),
            "next_action": payload.get("next_action"),
            "pending_hook_count": len(payload.get("pending_hooks", [])),
            "report_id": payload.get("report_id"),
        }

    def _callback_record(
        self,
        callback: Dict[str, Any],
        callback_path: Path,
        turn_id: str,
        gate: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "callback_ref": self._workspace_relative(callback_path),
            "callback_id": callback.get("callback_id"),
            "task_id": callback.get("task_id"),
            "turn_id": turn_id,
            "submitted_at": utc_now(),
            "status": callback.get("status", "completed"),
            "accepted": gate["accepted"],
            "rejection_reasons": gate.get("rejection_reasons", []),
        }

    def _reject_callback(
        self,
        run_path: Path,
        payload: Dict[str, Any],
        callback_path: Path,
        turn_id: str,
        gate: Dict[str, Any],
    ) -> Dict[str, Any]:
        bridge = payload.setdefault("hermes_bridge", {})
        bridge["status"] = "callback_retry_required"
        bridge["rejected_callback_count"] = int(bridge.get("rejected_callback_count") or 0) + 1
        bridge["pending_turn_ids"] = [
            item.get("turn_id") for item in payload.get("pending_hooks", [])
        ]
        payload["status"] = "awaiting_callback"
        payload["execution_status"] = "callback_retry_required"
        payload["next_action"] = "retry_current_hermes_hook"
        payload.setdefault("rejected_callbacks", []).append(
            {
                "callback_ref": self._workspace_relative(callback_path),
                "turn_id": turn_id,
                "rejected_at": utc_now(),
                "quality_gate": gate,
            }
        )
        self._write_run_payload(run_path, payload)
        return {
            "schema": ORCHESTRATOR_SUBMIT_SCHEMA,
            "run_id": payload["run_id"],
            "turn_id": turn_id,
            "accepted": False,
            "quality_gate": gate,
            "status": payload.get("status"),
            "execution_status": payload.get("execution_status"),
            "next_action": payload.get("next_action"),
            "pending_hook_count": len(payload.get("pending_hooks", [])),
            "report_id": payload.get("report_id"),
        }

    def _write_run_payload(self, path: Path, payload: Dict[str, Any]) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        safe_child_path(path.parent, ".wsa_bridge").write_text(
            f"{payload.get('execution_status', payload.get('status'))}\n",
            encoding="utf-8",
        )

    def _resolve_callback_path(self, callback_path: Path) -> Path:
        callbacks_root = safe_child_path(self.workspace, "hermes", "callbacks")
        candidate = callback_path.expanduser()
        if not candidate.is_absolute():
            candidate = safe_child_path(self.workspace, str(candidate))
        resolved = candidate.resolve()
        try:
            resolved.relative_to(callbacks_root.resolve())
        except ValueError as exc:
            raise ValueError("callback path must be inside workspace/hermes/callbacks") from exc
        if not resolved.exists():
            raise FileNotFoundError(f"callback not found: {callback_path}")
        if resolved.stat().st_size > MAX_CALLBACK_BYTES:
            raise ValueError("callback exceeds maximum bridge callback size")
        return resolved

    def _workspace_relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.workspace.resolve()))
        except ValueError:
            return str(path)

    def _turn_payload(
        self,
        callback: Dict[str, Any],
        run_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if callback.get("schema") != HERMES_CALLBACK_SCHEMA:
            raise ValueError(f"unsupported callback schema: {callback.get('schema')}")
        if not isinstance(callback.get("callback_id"), str) or not callback["callback_id"]:
            raise ValueError("callback requires callback_id")
        if not isinstance(callback.get("task_id"), str) or not callback["task_id"]:
            raise ValueError("callback requires task_id")
        expected_workspace = run_payload.get("workspace_id", "local")
        if callback.get("workspace_id") != expected_workspace:
            raise ValueError("callback workspace_id does not match orchestrator run")
        self._validate_callback_unique(callback, run_payload)
        if callback.get("status", "completed") != "completed":
            raise ValueError("only completed callbacks can advance an orchestrator run")
        route = callback.get("route")
        if not isinstance(route, dict) or not route.get("world_id"):
            raise ValueError("callback route requires world_id")
        if route.get("world_id") != run_payload.get("world_id"):
            raise ValueError("callback world_id does not match orchestrator run")
        payload = callback.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("callback payload must be an object")
        output = payload.get("output", payload)
        if not isinstance(output, dict):
            raise ValueError("callback output must be an object")
        turn_id = payload.get("turn_id") or output.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("callback payload requires turn_id")
        if isinstance(output.get("turn_id"), str) and output["turn_id"] != turn_id:
            raise ValueError("callback output turn_id does not match payload turn_id")
        return {
            "turn_id": turn_id,
            "output": output,
        }

    def _validate_callback_unique(
        self,
        callback: Dict[str, Any],
        run_payload: Dict[str, Any],
    ) -> None:
        seen_ids = {
            item.get("callback_id")
            for item in run_payload.get("submitted_callbacks", [])
            if item.get("callback_id")
        }
        if callback["callback_id"] in seen_ids:
            raise ValueError("callback_id was already submitted for this run")

    def _validate_callback_path_unique(
        self,
        callback_path: Path,
        run_payload: Dict[str, Any],
    ) -> None:
        seen_refs = {
            item.get("callback_ref")
            for item in run_payload.get("submitted_callbacks", [])
            if item.get("callback_ref")
        }
        callback_ref = self._workspace_relative(callback_path)
        if callback_ref in seen_refs:
            raise ValueError("callback file was already submitted for this run")

    def _pending_hook(
        self,
        pending_hooks: List[Dict[str, Any]],
        turn_id: str,
    ) -> Dict[str, Any]:
        for hook in pending_hooks:
            if hook.get("turn_id") == turn_id:
                return hook
        raise ValueError(f"callback turn_id is not pending for this run: {turn_id}")

    def _validate_callback_binding(
        self,
        callback: Dict[str, Any],
        hook: Dict[str, Any],
    ) -> None:
        route = callback["route"]
        expected = hook.get("expected_callback_route", {})
        for key in ("world_id", "session_id", "role"):
            if expected.get(key) and route.get(key) != expected.get(key):
                raise ValueError(f"callback {key} does not match pending hook")

    def _sanitize_output(
        self,
        output: Dict[str, Any],
        hook: Dict[str, Any],
    ) -> Dict[str, Any]:
        allowed = set(ALLOWED_OUTPUT_FIELDS)
        allowed.update(str(field) for field in hook.get("expected_fields", []))
        sanitized = {}
        for key, value in output.items():
            if key in allowed:
                sanitized[key] = _bounded_value(value)
        return sanitized


def quality_gate(output: Dict[str, Any], expected_fields: List[str]) -> Dict[str, Any]:
    required = ["position", "objections", "proposals", "gaps", "uncertainty"]
    missing = [field for field in required if output.get(field) in (None, "", [])]
    expected_missing = [
        field for field in expected_fields if output.get(field) in (None, "", [])
    ]
    uncertainty_ok = output.get("uncertainty") in {"low", "medium", "high"}
    canon_attempt = bool(output.get("canon_mutation"))
    accepted = not missing and uncertainty_ok and not canon_attempt
    rejection_reasons = []
    if missing:
        rejection_reasons.append("missing_required_fields")
    if not uncertainty_ok:
        rejection_reasons.append("unlabeled_uncertainty")
    if canon_attempt:
        rejection_reasons.append("canon_mutation_attempt")
    return {
        "schema": "wsa.orchestrator.output_quality_gate.v1",
        "accepted": accepted,
        "missing_fields": missing,
        "missing_expected_fields": expected_missing,
        "uncertainty_labeled": uncertainty_ok,
        "canon_mutation_attempt": canon_attempt,
        "rejection_reasons": rejection_reasons,
        "accumulation_policy": "accepted_outputs_only",
        "rejects_empty_agreement": True,
        "rejects_unbounded_lore_dump": True,
        "rejects_unlabeled_uncertainty": True,
    }


def _bounded_value(value: Any, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_TEXT_CHARS]
    if isinstance(value, list):
        return [_bounded_value(item, depth + 1) for item in value[:MAX_LIST_ITEMS]]
    if isinstance(value, dict):
        if depth >= 2:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)[:MAX_TEXT_CHARS]
        return {
            str(key)[:80]: _bounded_value(item, depth + 1)
            for key, item in list(value.items())[:MAX_DICT_ITEMS]
        }
    return str(value)[:MAX_TEXT_CHARS]


def find_bridge_run(workspace: Path, run_id: str) -> tuple[WorldRecord, Path, Dict[str, Any]]:
    for world in list_worlds(workspace):
        root = safe_child_path(world.path, "orchestrator_runs")
        if not root.exists():
            continue
        for path in sorted(root.glob("*/run.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("run_id") == run_id:
                return world, path, payload
    raise KeyError(f"orchestrator run not found: {run_id}")


def _append_next_hook(payload: Dict[str, Any], world_id: str) -> bool:
    if payload.get("pending_hooks"):
        return False
    bridge = payload.get("hermes_bridge", {})
    if int(bridge.get("completed_actor_calls") or 0) >= int(bridge.get("max_actor_calls") or 0):
        payload["next_action"] = "author_review"
        return False
    round_index = int(bridge.get("next_round") or 1)
    max_rounds = int(bridge.get("max_rounds") or 0)
    if round_index > max_rounds:
        payload["next_action"] = "author_review"
        return False
    contexts = payload.get("context_packets", [])
    if not contexts:
        payload["next_action"] = "author_review"
        return False
    participant_index = int(bridge.get("next_participant_index") or 0)
    if participant_index == 0:
        _ensure_orchestrator_turn(payload, round_index)
    context_packet = contexts[participant_index]
    previous_snapshot = (
        payload.get("compressed_context_snapshots", [])[-1]
        if payload.get("compressed_context_snapshots")
        else None
    )
    hook = build_round_prompt_packet(
        context_packet,
        round_index,
        previous_snapshot,
        payload.get("workflow_profile", {}),
        world_id,
    )
    payload.setdefault("pending_hooks", []).append(hook)
    payload.setdefault("runtime_hook_packets", []).append(hook)
    payload.setdefault("round_prompt_packets", []).append(hook)
    participant_index += 1
    if participant_index >= len(contexts):
        participant_index = 0
        bridge["next_round"] = round_index + 1
    bridge["next_participant_index"] = participant_index
    bridge["pending_turn_ids"] = [hook["turn_id"]]
    bridge["status"] = "awaiting_callback"
    payload["next_action"] = "run_next_hermes_hook"
    return True


def _ensure_orchestrator_turn(payload: Dict[str, Any], round_index: int) -> None:
    turn_id = f"{payload['run_id']}:orchestrator:round-{round_index}"
    for record in payload.get("turn_records", []):
        if record.get("turn_id") == turn_id:
            return
    payload.setdefault("turn_records", []).append(
        build_orchestrator_turn_record(
            payload["run_id"],
            round_index,
            payload.get("workflow_profile", {}),
            payload.get("floor_state", {}),
        )
    )


def _finalize_bridge_payload(
    workspace: Path,
    world: WorldRecord,
    run_dir: Path,
    payload: Dict[str, Any],
) -> None:
    outputs = payload.get("subsession_outputs", [])
    payload["status"] = "awaiting_author_review"
    payload["execution_status"] = "completed_by_hermes"
    payload["next_action"] = "author_review"
    payload.setdefault("hermes_bridge", {})["status"] = "completed_by_hermes"
    control = ControlRepository(workspace)
    closed_subsessions = []
    for session_id in payload.get("subsession_session_ids", []):
        control.update_runtime_session_status(session_id, "closed")
        closed_subsessions.append(session_id)
    manager_session_id = payload.get("manager_session_id")
    if manager_session_id:
        control.update_runtime_session_status(manager_session_id, "awaiting_author_review")
    payload["closed_subsessions"] = closed_subsessions
    payload["close_reason"] = "subsessions_closed_after_bridge_review_package"
    payload["synthesis"] = {
        "summary": (
            f"Hermes bridge collected {len(outputs)} accepted outputs for "
            f"{len(payload.get('participants', []))} participants."
        ),
        "workflow": payload.get("workflow"),
        "topic": payload.get("topic"),
        "question": payload.get("question"),
        "participant_labels": [
            item.get("label") for item in payload.get("participants", [])
        ],
        "draft_options": [
            {
                "option_id": "option-a",
                "title": "Accept Hermes-collected review package as proposal",
                "description": "Convert selected output into candidate tickets only after author approval.",
            },
            {
                "option_id": "option-b",
                "title": "Retry focused Hermes pass",
                "description": "Run another bridge pass on high-uncertainty or missing participants.",
            },
            {
                "option_id": "option-c",
                "title": "Hold for author direction",
                "description": "Pause before canon, scene draft, or actor assignment changes.",
            },
        ],
    }
    high_uncertainty = [
        output for output in outputs if output.get("uncertainty") == "high"
    ]
    payload["conflict_gap_diagnosis"] = {
        "conflicts": [],
        "gaps": [
            {
                "participant_id": output.get("participant_id"),
                "represents": output.get("represents"),
                "detail": "Hermes output remains high-uncertainty.",
            }
            for output in high_uncertainty[:8]
        ],
        "weak_proposals": high_uncertainty[:8],
        "budget_exhausted": False,
        "requires_author_boundary": True,
        "author_boundary_reasons": ["hermes_bridge_review_complete"],
    }
    payload["draft_options"] = payload["synthesis"]["draft_options"]
    payload["approval_options"] = [
        "approve option-a",
        "hold for later",
        "retry focused Hermes pass",
    ]
    payload["proposed_tickets"] = [
        {
            "ticket_type": "orchestrator_candidate",
            "title": option["title"],
            "status": "draft_until_author_decision",
        }
        for option in payload["draft_options"]
    ]
    if not payload.get("report_id"):
        repo = WorldRepository(world.world_id, world.path)
        report = ReportMailbox(workspace).create_world_report(
            repo,
            title=f"Orchestrator Hermes bridge report: {payload.get('topic', payload['run_id'])}",
            purpose="orchestrator_run",
            risk="medium",
            status="inbox",
            payload=payload,
        )
        payload["report_id"] = report.report_id
    safe_child_path(run_dir, ".wsa_completed").write_text("completed\n", encoding="utf-8")


def _compressed_bridge_snapshot(
    payload: Dict[str, Any],
    round_index: int,
    round_outputs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    high_uncertainty = [
        output for output in round_outputs if output.get("uncertainty") == "high"
    ]
    return {
        "round": round_index,
        "policy": payload.get("context_continuity", {}).get("policy", "compressed-continuity"),
        "compression": "bridge_callback_summary_plus_recent_output",
        "summary": (
            f"Bridge round {round_index} accepted {len(round_outputs)} callback outputs; "
            f"{len(high_uncertainty)} remain high-uncertainty."
        ),
        "recent_output_refs": [
            {
                "participant_id": output.get("participant_id"),
                "represents": output.get("represents"),
                "uncertainty": output.get("uncertainty"),
            }
            for output in round_outputs[-8:]
        ],
    }
