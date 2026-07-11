from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

from ..atomic_io import atomic_write_json
from ..orchestrator_bridge import OrchestratorBridge
from ..runtime_adapter import (
    DispatchPlan,
    RuntimeExecutionResult,
    StdioRuntimeAdapter,
)


RUNTIME_LOOP_RESULT_SCHEMA = "wsa.runtime_loop.result.v1"


class RuntimeLoopError(ValueError):
    """Raised when a guided runtime loop cannot safely continue."""


class RuntimeNotConfiguredError(RuntimeLoopError):
    """Raised when no runtime adapter was supplied by the caller."""


class PrepReviewRequiredError(RuntimeLoopError):
    """Raised before dispatch while the run still requires prep review."""


class NoExecutableHookError(RuntimeLoopError):
    """Raised when the bridge has no pending runtime hook."""


class StaleDispatchPlanError(RuntimeLoopError):
    """Raised when a reviewed plan no longer matches the pending hook."""


@dataclass(frozen=True)
class RuntimeLoopResult:
    status: str
    run_id: str
    turn_id: str
    dispatch_plan: DispatchPlan
    execution: RuntimeExecutionResult
    callback_path: Optional[Path] = None
    callback_ref: Optional[str] = None
    submission: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def accepted(self) -> bool:
        return bool(self.submission and self.submission.get("accepted") is True)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema": RUNTIME_LOOP_RESULT_SCHEMA,
            "status": self.status,
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "accepted": self.accepted,
            "dispatch_plan": self.dispatch_plan.to_dict(),
            "execution": self.execution.to_dict(),
            "callback_ref": self.callback_ref,
            "submission": self.submission,
            "side_effect": {
                "callback_atomically_written": self.callback_ref is not None,
                "bridge_submit_called": self.submission is not None,
                "canon_mutation_performed": False,
                "callback_auto_apply": "forbidden",
                "secret_values_recorded": False,
            },
            "side_effect_status": self._side_effect_status(),
        }
        if self.error_code is not None:
            payload["error"] = {
                "code": self.error_code,
                "message": self.error_message,
            }
        return payload

    def _side_effect_status(self) -> str:
        if self.submission is not None:
            return "callback_ingested_no_canon_mutation"
        if self.callback_ref is not None:
            return "callback_preserved_ingest_not_completed"
        if self.execution.process_started:
            return "runtime_process_only_no_workspace_callback_write"
        return "no_process_no_workspace_write"


class RuntimeLoopService:
    """Coordinate one reviewed bridge hook through dispatch and callback ingest."""

    def __init__(
        self,
        workspace: Path,
        adapter: Optional[StdioRuntimeAdapter],
        *,
        bridge: Optional[OrchestratorBridge] = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.adapter = adapter
        self.bridge = bridge or OrchestratorBridge(self.workspace)

    def dispatch_plan(self, run_id: str) -> DispatchPlan:
        """Return a read-only plan; this method never starts a subprocess."""

        adapter = self._adapter()
        next_payload = self.bridge.next(run_id)
        hook = self._executable_hook(run_id, next_payload)
        return adapter.build_dispatch_plan(hook)

    def plan(self, run_id: str) -> DispatchPlan:
        return self.dispatch_plan(run_id)

    def prepare(self, run_id: str) -> DispatchPlan:
        return self.dispatch_plan(run_id)

    def execute(
        self,
        plan_or_run_id: Union[DispatchPlan, str],
        cancellation: Optional[Any] = None,
        *,
        cancel_token: Optional[Any] = None,
    ) -> RuntimeLoopResult:
        """Execute one hook, atomically persist its callback, and submit it."""

        if cancel_token is not None:
            if cancellation is not None:
                raise RuntimeLoopError("pass cancellation or cancel_token, not both")
            cancellation = cancel_token
        plan = (
            self.dispatch_plan(plan_or_run_id)
            if isinstance(plan_or_run_id, str)
            else plan_or_run_id
        )
        if not isinstance(plan, DispatchPlan):
            raise RuntimeLoopError("execute requires a run_id or DispatchPlan")

        adapter = self._adapter()
        self._assert_plan_is_current(plan)
        execution = adapter.execute(plan, cancellation)
        if not execution.ok:
            return RuntimeLoopResult(
                status=execution.status,
                run_id=plan.run_id,
                turn_id=plan.turn_id,
                dispatch_plan=plan,
                execution=execution,
                error_code=execution.error_code,
                error_message=execution.error_message,
            )

        callback = execution.callback
        if callback is None:
            raise RuntimeLoopError("completed runtime execution did not return a callback")
        callback_path = self._callback_path(plan, callback)
        callback_ref = callback_path.relative_to(self.workspace).as_posix()
        if callback_path.exists():
            return RuntimeLoopResult(
                status="callback_artifact_exists",
                run_id=plan.run_id,
                turn_id=plan.turn_id,
                dispatch_plan=plan,
                execution=execution,
                callback_path=callback_path,
                callback_ref=callback_ref,
                error_code="callback_artifact_exists",
                error_message="runtime callback artifact already exists and was not overwritten",
            )

        try:
            atomic_write_json(callback_path, callback)
        except OSError:
            return RuntimeLoopResult(
                status="callback_write_failed",
                run_id=plan.run_id,
                turn_id=plan.turn_id,
                dispatch_plan=plan,
                execution=execution,
                error_code="callback_write_failed",
                error_message="runtime callback could not be written atomically",
            )

        try:
            submission = self.bridge.submit(plan.run_id, callback_path)
        except (json.JSONDecodeError, KeyError, OSError, ValueError):
            return RuntimeLoopResult(
                status="ingest_failed",
                run_id=plan.run_id,
                turn_id=plan.turn_id,
                dispatch_plan=plan,
                execution=execution,
                callback_path=callback_path,
                callback_ref=callback_ref,
                error_code="ingest_failed",
                error_message="callback was preserved but bridge submission failed",
            )

        status = "submitted" if submission.get("accepted") is True else "callback_rejected"
        return RuntimeLoopResult(
            status=status,
            run_id=plan.run_id,
            turn_id=plan.turn_id,
            dispatch_plan=plan,
            execution=execution,
            callback_path=callback_path,
            callback_ref=callback_ref,
            submission=submission,
        )

    def execute_next(
        self,
        run_id: str,
        cancellation: Optional[Any] = None,
    ) -> RuntimeLoopResult:
        return self.execute(self.dispatch_plan(run_id), cancellation)

    def dispatch_and_ingest(
        self,
        run_id: str,
        cancellation: Optional[Any] = None,
    ) -> RuntimeLoopResult:
        return self.execute_next(run_id, cancellation)

    def _adapter(self) -> StdioRuntimeAdapter:
        if self.adapter is None:
            raise RuntimeNotConfiguredError(
                "runtime command and workdir must be supplied by the caller"
            )
        return self.adapter

    def _assert_plan_is_current(self, plan: DispatchPlan) -> None:
        next_payload = self.bridge.next(plan.run_id)
        hook = self._executable_hook(plan.run_id, next_payload)
        current_turn_id = hook.get("turn_id")
        current_digest = (hook.get("dispatch_contract") or {}).get("route_digest")
        if current_turn_id != plan.turn_id or current_digest != plan.route_digest:
            raise StaleDispatchPlanError(
                "dispatch plan no longer matches the bridge pending hook"
            )

    @staticmethod
    def _executable_hook(run_id: str, next_payload: Dict[str, Any]) -> Dict[str, Any]:
        prep_required = (
            next_payload.get("execution_status") == "prep_review_required"
            or next_payload.get("next_action") == "review_prep_report"
        )
        if prep_required:
            raise PrepReviewRequiredError(
                f"prep review must be approved before runtime execution: {run_id}"
            )
        hook = next_payload.get("hook")
        if not isinstance(hook, dict):
            raise NoExecutableHookError(f"orchestrator run has no executable hook: {run_id}")
        return hook

    def _callback_path(self, plan: DispatchPlan, callback: Dict[str, Any]) -> Path:
        callback_id = str(callback.get("callback_id") or "")
        receipt = callback.get("dispatch_receipt") or {}
        dispatch_id = str(receipt.get("dispatch_id") or "")
        identity = "\x00".join(
            (plan.run_id, plan.turn_id, callback_id, dispatch_id)
        ).encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()[:32]
        return self.workspace / "hermes" / "callbacks" / f"runtime_{digest}.json"
