from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Protocol

from .run_store import RunRecord, RunStore
from .workspace import utc_now


RUN_STATES = {
    "awaiting_prep_review",
    "awaiting_callback",
    "awaiting_author_review",
    "canonization_pending",
    "retry_requested",
    "interrupted",
    "rejected",
    "closed",
}

ALLOWED_TRANSITIONS = {
    "awaiting_prep_review": {"awaiting_callback", "interrupted", "closed"},
    "awaiting_callback": {"awaiting_callback", "awaiting_author_review", "interrupted", "closed"},
    "awaiting_author_review": {
        "awaiting_author_review",
        "canonization_pending",
        "retry_requested",
        "interrupted",
        "rejected",
        "closed",
    },
    "canonization_pending": {"closed"},
    "retry_requested": {"awaiting_callback", "interrupted", "closed"},
    "interrupted": RUN_STATES - {"interrupted"},
    "rejected": set(),
    "closed": set(),
}


class WorkflowRunner(Protocol):
    @property
    def runner_type(self) -> str: ...

    def next_action(self, payload: Dict[str, Any]) -> str: ...


@dataclass(frozen=True)
class DeterministicMockRunner:
    runner_type: str = "deterministic_mock"

    def next_action(self, payload: Dict[str, Any]) -> str:
        return "author_review" if payload.get("status") == "awaiting_author_review" else "closed"


@dataclass(frozen=True)
class ExternalCallbackRunner:
    runner_type: str = "external_callback"

    def next_action(self, payload: Dict[str, Any]) -> str:
        if payload.get("status") == "awaiting_prep_review":
            return "review_prep_report"
        if payload.get("status") == "awaiting_callback":
            return "run_next_hermes_hook"
        if payload.get("status") == "awaiting_author_review":
            return "author_review"
        return str(payload.get("next_action") or "none")


class WorkflowEngine:
    def __init__(self, workspace: Path) -> None:
        self.store = RunStore(workspace)

    def register(
        self,
        payload: Dict[str, Any],
        run_path: Path,
        runner: WorkflowRunner,
    ) -> RunRecord:
        self._validate_state(str(payload.get("status") or ""))
        payload["workflow_state"] = {
            "schema": "wsa.workflow.state.v1",
            "runner_type": runner.runner_type,
            "state": payload["status"],
            "next_action": runner.next_action(payload),
        }
        return self.store.register(payload, run_path, runner.runner_type)

    def update(
        self,
        payload: Dict[str, Any],
        *,
        expected_revision: int,
    ) -> RunRecord:
        run_id = str(payload.get("run_id") or "")
        current = self.store.get(run_id)
        self._validate_transition(current.status, str(payload.get("status") or ""))
        state = payload.setdefault("workflow_state", {})
        state.update(
            {
                "schema": "wsa.workflow.state.v1",
                "runner_type": current.runner_type,
                "state": payload["status"],
                "updated_at": utc_now(),
            }
        )
        return self.store.save(
            run_id,
            payload,
            expected_revision=expected_revision,
        )

    def interrupt(self, run_id: str, reason: str | None = None) -> RunRecord:
        record = self.store.get(run_id)
        self._validate_transition(record.status, "interrupted")
        payload = dict(record.payload)
        payload["interrupted_from"] = record.status
        payload["status"] = "interrupted"
        payload["next_action"] = "resume"
        payload["interruption"] = {
            "reason": reason or "interrupted_by_user_or_runtime",
            "at": utc_now(),
        }
        return self.update(payload, expected_revision=record.revision)

    def resume(self, run_id: str) -> RunRecord:
        record = self.store.get(run_id)
        if record.status != "interrupted":
            return record
        payload = dict(record.payload)
        resumed_state = str(payload.get("interrupted_from") or "awaiting_callback")
        self._validate_transition("interrupted", resumed_state)
        payload["status"] = resumed_state
        payload["next_action"] = _runner(record.runner_type).next_action(payload)
        payload["resumed_at"] = utc_now()
        return self.update(payload, expected_revision=record.revision)

    def close(self, run_id: str, reason: str | None = None) -> RunRecord:
        record = self.store.get(run_id)
        if record.status == "closed":
            return record
        self._validate_transition(record.status, "closed")
        payload = dict(record.payload)
        payload["status"] = "closed"
        payload["next_action"] = "none"
        payload["close_reason"] = reason or "closed_by_user_or_runtime"
        payload["closed_at"] = utc_now()
        return self.update(payload, expected_revision=record.revision)

    def _validate_state(self, state: str) -> None:
        if state not in RUN_STATES:
            raise ValueError(f"unsupported workflow state: {state}")

    def _validate_transition(self, previous: str, target: str) -> None:
        self._validate_state(previous)
        self._validate_state(target)
        if target != previous and target not in ALLOWED_TRANSITIONS[previous]:
            raise ValueError(f"invalid workflow transition: {previous} -> {target}")


def _runner(runner_type: str) -> WorkflowRunner:
    if runner_type == "external_callback":
        return ExternalCallbackRunner()
    return DeterministicMockRunner()
