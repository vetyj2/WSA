from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .migrations.control import v1_to_v2 as control_v1_to_v2
from .migrations.world import v1_to_v2 as world_v1_to_v2
from .paths import safe_child_path
from .workspace import (
    CONTROL_SCHEMA_VERSION,
    WORLD_SCHEMA_VERSION,
    connect_sqlite,
    control_db_path,
    schema_version,
    world_db_path,
    world_root_path,
)


MIGRATION_PLAN_SCHEMA = "wsa.migration.plan.v1"
MIGRATION_RESULT_SCHEMA = "wsa.migration.result.v1"


class MigrationError(RuntimeError):
    """Raised when an explicit migration cannot be completed and verified."""


@dataclass(frozen=True)
class MigrationStep:
    store: str
    database: Path
    world_id: str | None
    from_version: int | None
    to_version: int
    status: str


@dataclass(frozen=True)
class MigrationPlan:
    workspace: Path
    steps: list[MigrationStep]

    @property
    def blocked(self) -> bool:
        return any(step.status in {"unsupported_newer", "unknown_version"} for step in self.steps)

    @property
    def upgrade_required(self) -> bool:
        return any(step.status == "upgrade_required" for step in self.steps)


@dataclass(frozen=True)
class MigrationResult:
    plan: MigrationPlan
    backup_path: Path | None
    applied: list[str]
    verified: list[str]


def plan_migrations(workspace: Path) -> MigrationPlan:
    workspace = workspace.resolve()
    control_path = control_db_path(workspace)
    if not control_path.exists():
        return MigrationPlan(workspace, [])
    control_version = _read_version(control_path, "control")
    steps = [
        MigrationStep(
            "control",
            control_path,
            None,
            control_version,
            CONTROL_SCHEMA_VERSION,
            _status(control_version, CONTROL_SCHEMA_VERSION),
        )
    ]
    for world_id, relative_path in _registered_worlds(control_path):
        expected = world_root_path(workspace, world_id)
        registered = Path(relative_path)
        resolved = (
            registered.resolve()
            if registered.is_absolute()
            else (workspace / registered).resolve()
        )
        if resolved != expected:
            raise MigrationError(f"unsafe registered world path for {world_id}: {relative_path}")
        database = world_db_path(expected)
        version = _read_version(database, "world") if database.exists() else None
        steps.append(
            MigrationStep(
                "world",
                database,
                world_id,
                version,
                WORLD_SCHEMA_VERSION,
                _status(version, WORLD_SCHEMA_VERSION),
            )
        )
    return MigrationPlan(workspace, steps)


def apply_migrations(workspace: Path) -> MigrationResult:
    plan = plan_migrations(workspace)
    if plan.blocked:
        raise MigrationError("migration plan is blocked by an unknown or newer schema")
    if not plan.steps:
        raise MigrationError("workspace is not initialized; run wsa init first")
    if not plan.upgrade_required:
        return MigrationResult(plan, None, [], _verify_plan(plan))

    backup_path = _backup_databases(plan)
    lock_path = safe_child_path(plan.workspace, "hermes", "maintenance", "migration.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {"schema": MIGRATION_RESULT_SCHEMA, "backup_path": str(backup_path)},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    applied: list[str] = []
    try:
        for step in plan.steps:
            if step.status != "upgrade_required":
                continue
            if step.from_version != 1 or step.to_version != 2:
                raise MigrationError(
                    f"no ordered migration for {step.store} {step.from_version} -> {step.to_version}"
                )
            conn = connect_sqlite(step.database)
            try:
                if step.store == "control":
                    control_v1_to_v2.apply(conn)
                    applied.append(control_v1_to_v2.MIGRATION_ID)
                else:
                    display_name = _world_display_name(conn, step.world_id or "")
                    world_v1_to_v2.apply(conn, step.world_id or "", display_name)
                    applied.append(f"{world_v1_to_v2.MIGRATION_ID}:{step.world_id}")
            finally:
                conn.close()
        verified = _verify_plan(plan_migrations(plan.workspace))
    except Exception as exc:
        raise MigrationError(
            f"migration failed; original backups remain at {backup_path}: {exc}"
        ) from exc
    finally:
        lock_path.unlink(missing_ok=True)
    return MigrationResult(plan, backup_path, applied, verified)


def migration_plan_to_dict(plan: MigrationPlan) -> dict[str, Any]:
    return {
        "schema": MIGRATION_PLAN_SCHEMA,
        "workspace": str(plan.workspace),
        "status": "blocked" if plan.blocked else "upgrade_required" if plan.upgrade_required else "current",
        "backup_required": plan.upgrade_required,
        "downgrade_supported": False,
        "steps": [
            {
                "store": step.store,
                "database": str(step.database),
                "world_id": step.world_id,
                "from_version": step.from_version,
                "to_version": step.to_version,
                "status": step.status,
                "destructive": False,
            }
            for step in plan.steps
        ],
    }


def migration_result_to_dict(result: MigrationResult) -> dict[str, Any]:
    return {
        "schema": MIGRATION_RESULT_SCHEMA,
        "status": "applied_and_verified" if result.applied else "already_current",
        "backup_path": str(result.backup_path) if result.backup_path else None,
        "applied": result.applied,
        "verified": result.verified,
        "plan": migration_plan_to_dict(result.plan),
        "downgrade_supported": False,
        "recovery": (
            "Stop WSA and restore SQLite files from backup_path if post-migration verification fails."
            if result.backup_path
            else "No migration writes were required."
        ),
    }


def _status(version: int | None, target: int) -> str:
    if version is None:
        return "unknown_version"
    if version > target:
        return "unsupported_newer"
    if version < target:
        return "upgrade_required"
    return "current"


def _read_version(path: Path, store: str) -> int | None:
    conn = connect_sqlite(path)
    try:
        return schema_version(conn, store)
    finally:
        conn.close()


def _registered_worlds(control_path: Path) -> list[tuple[str, str]]:
    conn = connect_sqlite(control_path)
    try:
        rows = conn.execute("SELECT world_id, path FROM worlds ORDER BY created_at").fetchall()
        return [(str(row["world_id"]), str(row["path"])) for row in rows]
    finally:
        conn.close()


def _world_display_name(conn: sqlite3.Connection, world_id: str) -> str:
    row = conn.execute(
        "SELECT display_name FROM world_metadata WHERE world_id = ?",
        (world_id,),
    ).fetchone()
    return str(row["display_name"]) if row is not None else world_id


def _backup_databases(plan: MigrationPlan) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = safe_child_path(plan.workspace, ".wsa_migration_backups", timestamp)
    backup_root.mkdir(parents=True, exist_ok=False)
    for step in plan.steps:
        if not step.database.exists():
            continue
        name = "control.sqlite" if step.store == "control" else f"world-{step.world_id}.sqlite"
        target = safe_child_path(backup_root, name)
        source_conn = connect_sqlite(step.database)
        target_conn = sqlite3.connect(target)
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
            source_conn.close()
    manifest = {
        "schema": "wsa.migration.backup.v1",
        "workspace": str(plan.workspace),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(path.name for path in backup_root.glob("*.sqlite")),
    }
    safe_child_path(backup_root, "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return backup_root


def _verify_plan(plan: MigrationPlan) -> list[str]:
    verified: list[str] = []
    for step in plan.steps:
        if step.status != "current":
            raise MigrationError(
                f"migration verification failed for {step.store} {step.world_id or ''}: {step.status}"
            )
        conn = connect_sqlite(step.database)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise MigrationError(f"integrity_check failed for {step.database}: {integrity}")
        finally:
            conn.close()
        verified.append(f"{step.store}:{step.world_id or 'workspace'}:v{step.to_version}")
    return verified
