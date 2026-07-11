from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .atomic_io import atomic_write_json
from .contract_registry import compact_run_projection
from .paths import safe_child_path
from .workspace import (
    control_db_path,
    ensure_control_v2_tables,
    ensure_current_schema,
    get_world,
    init_workspace,
    sqlite_connection,
    utc_now,
)


RUN_STORE_SCHEMA = "wsa.workflow.run_store.v1"


class ConcurrentRunUpdateError(RuntimeError):
    """Raised when a stale workflow revision attempts to overwrite newer state."""


class ProjectionWriteError(RuntimeError):
    """Raised after DB state is durable but its JSON projection could not be written."""


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    world_id: str
    workflow: str
    runner_type: str
    status: str
    revision: int
    run_path: Path
    payload: Dict[str, Any]
    projection_status: str
    projection_error: str | None


class RunStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        init_workspace(self.workspace)
        self._ensure_schema()

    def _connect(self):
        return sqlite_connection(control_db_path(self.workspace), schema_name="control")

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            ensure_current_schema(conn, "control")
            ensure_control_v2_tables(conn)

    def register(
        self,
        payload: Dict[str, Any],
        run_path: Path,
        runner_type: Any,
        *,
        project: bool = True,
    ) -> RunRecord:
        clean = _clean_payload(payload)
        resolved_runner_type = str(getattr(runner_type, "runner_type", runner_type))
        run_id = _required(clean, "run_id")
        world_id = _required(clean, "world_id")
        workflow = _required(clean, "workflow")
        status = _required(clean, "status")
        relative_path = self._relative_path(run_path)
        now = utc_now()
        encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT revision FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError(f"workflow run already registered: {run_id}")
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, world_id, workflow, runner_type, status, revision,
                    run_path, payload, projection_status, projection_error,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    run_id,
                    world_id,
                    workflow,
                    resolved_runner_type,
                    status,
                    relative_path,
                    encoded,
                    "pending" if project else "not_requested",
                    now,
                    now,
                ),
            )
        if project:
            self._project(run_id, run_path, clean)
        return self.get(run_id)

    def get(self, run_id: str) -> RunRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, world_id, workflow, runner_type, status, revision,
                       run_path, payload, projection_status, projection_error
                FROM workflow_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"orchestrator run not found: {run_id}")
        return RunRecord(
            run_id=row["run_id"],
            world_id=row["world_id"],
            workflow=row["workflow"],
            runner_type=row["runner_type"],
            status=row["status"],
            revision=int(row["revision"]),
            run_path=self._absolute_path(row["run_path"]),
            payload=json.loads(row["payload"]),
            projection_status=row["projection_status"],
            projection_error=row["projection_error"],
        )

    def locate(self, run_id: str) -> tuple[Any, Path, Dict[str, Any]]:
        record = self.get(run_id)
        return get_world(self.workspace, record.world_id), record.run_path, record.payload

    def list(self, world_id: str | None = None, status: str | None = None) -> list[RunRecord]:
        sql = """
            SELECT run_id FROM workflow_runs
            WHERE 1 = 1
        """
        params: list[str] = []
        if world_id is not None:
            sql += " AND world_id = ?"
            params.append(world_id)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self.get(str(row["run_id"])) for row in rows]

    def save(
        self,
        run_id: str,
        payload: Dict[str, Any],
        *,
        expected_revision: int,
        project: bool = True,
    ) -> RunRecord:
        clean = _clean_payload(payload)
        if _required(clean, "run_id") != run_id:
            raise ValueError("run payload run_id does not match store key")
        status = _required(clean, "status")
        now = utc_now()
        encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT revision, run_path FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"orchestrator run not found: {run_id}")
            current_revision = int(row["revision"])
            if current_revision != expected_revision:
                raise ConcurrentRunUpdateError(
                    f"run {run_id} revision changed: expected {expected_revision}, "
                    f"current {current_revision}"
                )
            result = conn.execute(
                """
                UPDATE workflow_runs
                SET status = ?, revision = revision + 1, payload = ?,
                    projection_status = ?, projection_error = NULL, updated_at = ?
                WHERE run_id = ? AND revision = ?
                """,
                (
                    status,
                    encoded,
                    "pending" if project else "not_requested",
                    now,
                    run_id,
                    expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise ConcurrentRunUpdateError(f"run {run_id} changed during update")
            run_path = self._absolute_path(row["run_path"])
        if project:
            self._project(run_id, run_path, clean)
        return self.get(run_id)

    def repair_projection(self, run_id: str) -> RunRecord:
        record = self.get(run_id)
        self._project(run_id, record.run_path, record.payload)
        return self.get(run_id)

    def claim_callback(
        self,
        callback_id: str,
        callback_ref: str,
        run_id: str,
        turn_id: str,
        payload: Dict[str, Any],
    ) -> None:
        if not callback_id.strip():
            raise ValueError("callback_id is required for replay protection")
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        now = utc_now()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO workflow_callback_receipts (
                        callback_id, callback_ref, run_id, turn_id,
                        payload_digest, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'claimed', ?, ?)
                    """,
                    (callback_id, callback_ref, run_id, turn_id, digest, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"callback replay blocked: {callback_id}") from exc

    def complete_callback(self, callback_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workflow_callback_receipts
                SET status = ?, updated_at = ?
                WHERE callback_id = ?
                """,
                (status, utc_now(), callback_id),
            )

    def _project(self, run_id: str, run_path: Path, payload: Dict[str, Any]) -> None:
        try:
            atomic_write_json(run_path, compact_run_projection(payload))
        except Exception as exc:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE workflow_runs
                    SET projection_status = 'failed', projection_error = ?, updated_at = ?
                    WHERE run_id = ?
                    """,
                    (str(exc), utc_now(), run_id),
                )
            raise ProjectionWriteError(
                f"run {run_id} is durable in SQLite but JSON projection failed: {exc}"
            ) from exc
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET projection_status = 'current', projection_error = NULL, updated_at = ?
                WHERE run_id = ?
                """,
                (utc_now(), run_id),
            )

    def _relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.workspace).as_posix()
        except ValueError as exc:
            raise ValueError("run projection path must be inside the workspace") from exc

    def _absolute_path(self, value: str) -> Path:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"unsafe run projection path: {value}")
        return safe_child_path(self.workspace, *candidate.parts)


def _clean_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if not key.startswith("_store_")}


def _required(payload: Dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"workflow run payload requires {key}")
    return value
