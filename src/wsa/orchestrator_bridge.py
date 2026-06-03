from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .hermes_adapter import HERMES_CALLBACK_SCHEMA
from .orchestrator_turns import (
    build_actor_turn_record,
    build_initial_actor_states,
    build_manager_check_turn_records,
    build_orchestrator_turn_record,
    build_round_prompt_packet,
    build_scheduler_decision,
    update_actor_states,
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
MAX_CALLBACK_REJECTIONS_PER_TURN = 3
ALLOWED_OUTPUT_FIELDS = {
    "actor_assignment",
    "answer",
    "canon_mutation",
    "confidence",
    "conflicts",
    "dependencies",
    "draft_boundary",
    "facts_to_hide",
    "facts_to_include",
    "gaps",
    "location_scope",
    "memory_filter",
    "model_thinking_recommendation",
    "new_claims",
    "next_actor_suggestion",
    "objections",
    "position",
    "prep_completion_check",
    "proposals",
    "risk_flags",
    "role_isolation",
    "scene_beat",
    "scene_frame",
    "scene_relevance",
    "source_refs",
    "stance",
    "time_scope",
    "uncertainty",
    "viewpoint_constraints",
    "viewpoint_scope",
    "worldbuilding_use",
}


def is_hermes_bridge_mode(mode: str) -> bool:
    return mode.strip().casefold() in BRIDGE_MODES


def initialize_bridge_payload(payload: Dict[str, Any], world_id: str) -> None:
    participant_count = len(payload.get("context_packets", []))
    max_rounds = int(payload.get("queue_limits", {}).get("queue_turns_used") or 0)
    max_calls = int(payload.get("queue_limits", {}).get("planned_subsession_calls") or 0)
    prep_required = bool(payload.get("prep_review_policy", {}).get("required", True))
    payload["status"] = "awaiting_prep_review" if prep_required else "awaiting_callback"
    payload["execution_status"] = "prep_review_required" if prep_required else "waiting_for_hermes"
    payload["subsession_execution_mode"] = "hermes_bridge_pending_callbacks"
    payload["real_subagent_execution"] = "pending_user_hermes_runtime_callbacks"
    payload["runtime_hook_packets"] = []
    payload["round_prompt_packets"] = []
    payload["pending_hooks"] = []
    payload["submitted_callbacks"] = []
    payload["rejected_callbacks"] = []
    payload["subsession_outputs"] = []
    payload["accepted_outputs_only"] = True
    payload["actor_states"] = payload.get("actor_states") or build_initial_actor_states(
        [
            {
                "participant_id": item["participant_id"],
                "label": item["represents"],
                "role": "representative_voice",
                "workflow_role": item.get("workflow", payload.get("workflow", "meetup")),
            }
            for item in payload.get("context_packets", [])
        ],
        payload.get("workflow_profile", {}),
    )
    payload["execution_provenance"] = {
        "schema": "wsa.orchestrator.execution_provenance.v1",
        "execution_mode": "runtime-bridge",
        "artifact_type": "external_runtime_bridge_contract",
        "wsa_direct_runtime_execution": False,
        "external_runtime_owner": "user_runtime",
        "real_actor_sessions_executed": "pending_external_runtime_callback",
        "callback_execution_reported": False,
        "canon_write_performed": False,
        "startup_profile_write_performed": False,
        "world_mutation_performed": False,
        "requires_author_decision": True,
    }
    payload["runtime_bridge_contract"] = _runtime_bridge_contract(payload)
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
        "status": "prep_review_required" if prep_required else "waiting_for_hermes",
        "next_round": 1,
        "next_participant_index": 0,
        "participant_count": participant_count,
        "max_rounds": max_rounds,
        "max_actor_calls": max_calls,
        "completed_actor_calls": 0,
        "pending_turn_ids": [],
        "retry_policy": {
            "max_rejections_per_turn": MAX_CALLBACK_REJECTIONS_PER_TURN,
            "on_retry_limit": "stop_and_return_partial_review_package",
        },
        "turn_retry_counts": {},
        "callback_policy": {
            "callback_dir": "hermes/callbacks",
            "external_callback_paths": False,
            "execution_owner": "external_agent_runtime",
        },
        "runtime_capability_manifest": _default_runtime_capability_manifest(),
        "scheduler_policy": {
            "turn_based": True,
            "round_is_reporting_unit_only": True,
            "equal_airtime_not_required": True,
            "actor_selection_reasons_required": True,
        },
    }
    if prep_required:
        payload["next_action"] = "review_prep_report"
        payload.setdefault("prep_report", {})["status"] = "ready_pending_review"
    else:
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
        prep_report = payload.get("prep_report") if next_action == "review_prep_report" else None
        prep_command = (
            {
                "argv": ["wsa", "orchestrator", "prep-approve", run_id, "--format", "json"],
                "purpose": "Approve prepared context bundles before first Hermes actor call.",
                "execution_owner": "user_hermes_runtime",
            }
            if prep_report
            else None
        )
        return {
            "schema": ORCHESTRATOR_NEXT_SCHEMA,
            "run_id": run_id,
            "status": payload.get("status"),
            "execution_status": payload.get("execution_status"),
            "workflow": payload.get("workflow"),
            "skill": payload.get("skill"),
            "next_action": next_action,
            "hook": hook,
            "terminal_command": hook.get("terminal_command") if hook else prep_command,
            "prep_report": prep_report,
            "prep_review_policy": payload.get("prep_review_policy", {}),
            "floor_state": payload.get("floor_state", {}),
            "active_actor_state": hook.get("actor_state") if hook else None,
            "actor_states": payload.get("actor_states", {}),
            "execution_provenance": payload.get("execution_provenance", {}),
            "runtime_bridge_contract": payload.get("runtime_bridge_contract", {}),
            "progress_report_policy": payload.get("progress_report_policy", {}),
            "queue_limits": payload.get("queue_limits", {}),
            "hermes_bridge": payload.get("hermes_bridge", {}),
        }

    def approve_prep(self, run_id: str) -> Dict[str, Any]:
        world, path, payload = find_bridge_run(self.workspace, run_id)
        if payload.get("next_action") != "review_prep_report":
            return self.next(run_id)
        payload["status"] = "awaiting_callback"
        payload["execution_status"] = "waiting_for_hermes"
        payload["next_action"] = "run_next_hermes_hook"
        payload.setdefault("lifecycle", []).append(
            {"state": "prep_review_approved", "at": utc_now()}
        )
        prep_report = payload.setdefault("prep_report", {})
        prep_report["status"] = "approved_for_actor_calls"
        prep_report["reviewed_at"] = utc_now()
        payload.setdefault("hermes_bridge", {})["status"] = "waiting_for_hermes"
        _append_next_hook(payload, world.world_id)
        self._write_run_payload(path, payload)
        next_payload = self.next(run_id)
        next_payload["prep_approved"] = True
        return next_payload

    def submit(self, run_id: str, callback_path: Path) -> Dict[str, Any]:
        world, path, payload = find_bridge_run(self.workspace, run_id)
        if payload.get("next_action") == "review_prep_report":
            raise ValueError("prep review must be approved before submitting actor callbacks")
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
        actor_states = payload.setdefault("actor_states", {})
        actor_state = actor_states.get(hook["participant_id"], hook.get("actor_state", {}))
        output["quality_gate"] = quality_gate(
            output,
            hook.get("expected_fields", []),
            actor_state=actor_state,
        )
        payload.setdefault("submitted_callbacks", []).append(
            self._callback_record(callback, callback_path, turn_id, output["quality_gate"])
        )
        if not output["quality_gate"]["accepted"]:
            return self._reject_callback(
                world,
                path,
                payload,
                callback_path,
                turn_id,
                output["quality_gate"],
            )

        payload["pending_hooks"] = [
            item for item in pending_hooks if item.get("turn_id") != turn_id
        ]
        payload.setdefault("turn_records", []).append(build_actor_turn_record(hook, output))
        payload.setdefault("subsession_outputs", []).append(output)
        payload["actor_states"] = update_actor_states(actor_states, hook, output)
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
            payload.get("actor_states", {}),
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
        world: WorldRecord,
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
        retry_counts = bridge.setdefault("turn_retry_counts", {})
        retry_counts[turn_id] = int(retry_counts.get(turn_id) or 0) + 1
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
        retry_limit = int(
            bridge.get("retry_policy", {}).get(
                "max_rejections_per_turn",
                MAX_CALLBACK_REJECTIONS_PER_TURN,
            )
            or MAX_CALLBACK_REJECTIONS_PER_TURN
        )
        retry_limit_reached = retry_counts[turn_id] >= retry_limit
        if retry_limit_reached:
            _finalize_bridge_retry_limit(
                self.workspace,
                world,
                run_path.parent,
                payload,
                turn_id,
                gate,
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
            "retry_limit_reached": retry_limit_reached,
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


def quality_gate(
    output: Dict[str, Any],
    expected_fields: List[str],
    actor_state: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    required = ["position", "objections", "proposals", "gaps", "uncertainty"]
    missing = [field for field in required if output.get(field) in (None, "", [])]
    expected_missing = [
        field
        for field in expected_fields
        if field not in output or output.get(field) in (None, "")
    ]
    uncertainty_ok = output.get("uncertainty") in {"low", "medium", "high"}
    canon_attempt = bool(output.get("canon_mutation"))
    accepted = not missing and not expected_missing and uncertainty_ok and not canon_attempt
    rejection_reasons = []
    if missing:
        rejection_reasons.append("missing_required_fields")
    if expected_missing:
        rejection_reasons.append("missing_workflow_expected_fields")
    if not uncertainty_ok:
        rejection_reasons.append("unlabeled_uncertainty")
    if canon_attempt:
        rejection_reasons.append("canon_mutation_attempt")
    low_value_warnings = []
    if _looks_like_empty_agreement(output):
        low_value_warnings.append("empty_agreement_or_no_new_constraint")
    if (
        actor_state
        and output.get("position") not in (None, "")
        and actor_state.get("last_position") not in (None, "")
        and output.get("position") == actor_state.get("last_position")
    ):
        low_value_warnings.append("repeated_prior_position")
    if (
        actor_state
        and output.get("answer") not in (None, "")
        and actor_state.get("last_answer") not in (None, "")
        and output.get("answer") == actor_state.get("last_answer")
    ):
        low_value_warnings.append("repeated_prior_answer")
    return {
        "schema": "wsa.orchestrator.output_quality_gate.v1",
        "accepted": accepted,
        "missing_fields": missing,
        "missing_expected_fields": expected_missing,
        "uncertainty_labeled": uncertainty_ok,
        "canon_mutation_attempt": canon_attempt,
        "rejection_reasons": rejection_reasons,
        "low_value_warnings": low_value_warnings,
        "anti_repetition_checked": True,
        "deepening_recommended_if_low_value": bool(low_value_warnings),
        "accumulation_policy": "accepted_outputs_only",
        "rejects_empty_agreement": True,
        "rejects_unbounded_lore_dump": True,
        "rejects_unlabeled_uncertainty": True,
    }


def _looks_like_empty_agreement(output: Dict[str, Any]) -> bool:
    text = " ".join(
        str(output.get(field) or "")
        for field in ("position", "stance", "answer")
    ).strip().casefold()
    return text in {
        "agree",
        "i agree",
        "yes",
        "same",
        "no objection",
        "looks good",
        "동의",
        "찬성",
    }


def _runtime_bridge_contract(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": "wsa.runtime_bridge.contract.v1",
        "mode": "runtime-bridge",
        "runner_agnostic": True,
        "compatible_runtime_families": [
            "hermes",
            "codex_or_local_cli_agent",
            "custom_external_actor_runtime",
        ],
        "wsa_owns": [
            "isolated_run_state",
            "actor_state",
            "floor_state",
            "hook_packet_generation",
            "callback_validation",
            "quality_gate_records",
            "report_and_approval_package",
        ],
        "external_runtime_owns": [
            "actor_or_subagent_invocation",
            "model_provider_selection",
            "process_or_session_lifecycle",
            "delivery_to_user",
            "interrupt_execution",
            "cleanup_execution",
        ],
        "required_callback_contract": {
            "callback_dir": "hermes/callbacks",
            "route_must_match_pending_hook": True,
            "turn_id_required": True,
            "structured_output_required": True,
            "canon_mutation_forbidden": True,
        },
        "state_continuity": {
            "actor_state_required": True,
            "floor_state_required": True,
            "later_prompts_include_prior_actor_state": True,
            "round_is_reporting_unit_only": True,
        },
        "workflow": payload.get("workflow"),
        "skill": payload.get("skill"),
    }


def _default_runtime_capability_manifest() -> Dict[str, Any]:
    return {
        "schema": "wsa.runtime_bridge.capability_manifest.v1",
        "source": "wsa_default_assumption_until_runtime_reports_capabilities",
        "supports_actor_callbacks": True,
        "supports_parallel_actor_calls": "runtime_declared_or_operator_limited",
        "supports_interrupt": "runtime_owned",
        "supports_cleanup_report": "runtime_owned",
        "supports_streaming": False,
        "max_recommended_concurrency": 3,
        "secret_owner": "external_runtime",
        "delivery_owner": "external_runtime",
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
    actor_state = payload.get("actor_states", {}).get(
        context_packet["participant_id"],
        context_packet.get("actor_state", {}),
    )
    scheduler_decision = build_scheduler_decision(
        context_packet,
        round_index,
        actor_state,
        payload.get("floor_state", {}),
    )
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
        actor_state=actor_state,
        scheduler_decision=scheduler_decision,
        floor_state=payload.get("floor_state", {}),
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
    payload.setdefault("execution_provenance", {}).update(
        {
            "real_actor_sessions_executed": "external_runtime_callback_report_only",
            "callback_execution_reported": True,
            "artifact_type": "external_runtime_callback_review_package",
        }
    )
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
    if payload.get("workflow") == "scene_generation":
        payload["synthesis"]["scene_prep_package"] = _scene_bridge_prep_package(
            payload,
            outputs,
        )
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


def _finalize_bridge_retry_limit(
    workspace: Path,
    world: WorldRecord,
    run_dir: Path,
    payload: Dict[str, Any],
    turn_id: str,
    gate: Dict[str, Any],
) -> None:
    payload["status"] = "awaiting_author_review"
    payload["execution_status"] = "callback_retry_limit_reached"
    payload["next_action"] = "author_review"
    bridge = payload.setdefault("hermes_bridge", {})
    bridge["status"] = "callback_retry_limit_reached"
    bridge["retry_limit_turn_id"] = turn_id
    payload.setdefault("execution_provenance", {}).update(
        {
            "real_actor_sessions_executed": "external_runtime_callback_report_only",
            "callback_execution_reported": bool(payload.get("submitted_callbacks")),
            "artifact_type": "external_runtime_partial_review_package",
            "requires_author_decision": True,
        }
    )
    control = ControlRepository(workspace)
    closed_subsessions = []
    for session_id in payload.get("subsession_session_ids", []):
        control.update_runtime_session_status(session_id, "closed")
        closed_subsessions.append(session_id)
    manager_session_id = payload.get("manager_session_id")
    if manager_session_id:
        control.update_runtime_session_status(manager_session_id, "awaiting_author_review")
    payload["closed_subsessions"] = closed_subsessions
    payload["close_reason"] = "callback_retry_limit_reached_partial_review"
    payload["synthesis"] = {
        "summary": (
            "Hermes bridge stopped before completion because a callback turn failed "
            "the WSA quality gate too many times."
        ),
        "workflow": payload.get("workflow"),
        "topic": payload.get("topic"),
        "question": payload.get("question"),
        "draft_options": [
            {
                "option_id": "option-a",
                "title": "Retry current Hermes turn with corrected output schema",
                "description": "Keep the same run context and resubmit a bounded callback.",
            },
            {
                "option_id": "option-b",
                "title": "Hold run for author or operator inspection",
                "description": "Pause before spending more actor/subagent calls.",
            },
        ],
    }
    if payload.get("workflow") == "scene_generation":
        payload["synthesis"]["scene_prep_package"] = _scene_bridge_prep_package(
            payload,
            payload.get("subsession_outputs", []),
        )
    payload["conflict_gap_diagnosis"] = {
        "conflicts": [],
        "gaps": [
            {
                "turn_id": turn_id,
                "detail": "callback output did not satisfy the required WSA quality gate",
                "quality_gate": gate,
            }
        ],
        "weak_proposals": [],
        "budget_exhausted": True,
        "requires_author_boundary": True,
        "author_boundary_reasons": ["callback_retry_limit_reached"],
    }
    payload["draft_options"] = payload["synthesis"]["draft_options"]
    payload["approval_options"] = [
        "retry current Hermes turn",
        "hold for later",
    ]
    payload["proposed_tickets"] = []
    if not payload.get("report_id"):
        repo = WorldRepository(world.world_id, world.path)
        report = ReportMailbox(workspace).create_world_report(
            repo,
            title=f"Orchestrator bridge retry-limit report: {payload.get('topic', payload['run_id'])}",
            purpose="orchestrator_run",
            risk="medium",
            status="inbox",
            payload=payload,
        )
        payload["report_id"] = report.report_id
    safe_child_path(run_dir, ".wsa_completed").write_text("retry_limit\n", encoding="utf-8")


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


def _scene_bridge_prep_package(
    payload: Dict[str, Any],
    outputs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "schema": "wsa.scene.prep_package.v1",
        "status": "awaiting_author_review",
        "side_effect_status": "proposal_only_no_scene_draft_no_canon_mutation",
        "scene_filter_contract": payload.get("scene_filter_contract"),
        "facts_to_include": _collect_output_values(outputs, "facts_to_include"),
        "facts_to_hide": _collect_output_values(outputs, "facts_to_hide"),
        "actor_assignments": _collect_output_values(outputs, "actor_assignment"),
        "role_isolation": _collect_output_values(outputs, "role_isolation"),
        "viewpoint_constraints": _collect_output_values(outputs, "viewpoint_constraints"),
        "scene_beats": _collect_output_values(outputs, "scene_beat"),
        "model_thinking_recommendations": _collect_output_values(
            outputs,
            "model_thinking_recommendation",
        ),
        "risk_flags": _collect_output_values(outputs, "risk_flags"),
        "prep_completion_check": {
            "status": "requires_author_or_hermes_review",
            "required_before_draft": [
                "scene goal is explicit",
                "actor packets are scoped",
                "hidden facts are separated from viewpoint-visible facts",
                "role isolation is defined for multi-role sessions",
                "risk flags are reviewed",
            ],
        },
        "draft_boundary": "author_approval_required_before_script_draft_or_canon_mutation",
    }


def _collect_output_values(
    outputs: List[Dict[str, Any]],
    field: str,
    limit: int = 12,
) -> List[Any]:
    values: List[Any] = []
    for output in outputs:
        value = output.get(field)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            values.extend(item for item in value if item not in (None, "", []))
        else:
            values.append(value)
        if len(values) >= limit:
            return values[:limit]
    return values
