from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_json
from .paths import safe_child_path
from .update import assert_update_unlocked
from .workspace import connect_sqlite, utc_now


RESTORE_PLAN_SCHEMA = "wsa.restore.plan.v1"
RESTORE_RECEIPT_SCHEMA = "wsa.restore.receipt.v1"
MIGRATION_BACKUP_SCHEMA = "wsa.migration.backup.v1"


class RestoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestoreWorld:
    world_id: str
    source: Path
    destination: Path


@dataclass(frozen=True)
class RestorePlan:
    workspace: Path
    backup_root: Path
    destination: Path
    control_source: Path
    control_destination: Path
    worlds: tuple[RestoreWorld, ...]
    verified_sources: tuple[str, ...]


def plan_restore_to_new_path(
    workspace: Path,
    backup_root: Path,
    destination: Path,
) -> RestorePlan:
    workspace = workspace.resolve()
    backup_root = backup_root.expanduser().resolve()
    destination = destination.expanduser().resolve()
    assert_update_unlocked(workspace, "restore.plan")
    _assert_runtime_idle(workspace)
    if not backup_root.is_dir():
        raise RestoreError(f"backup directory not found: {backup_root}")
    if destination.exists():
        raise RestoreError(f"restore destination must not already exist: {destination}")
    if _is_relative_to(destination, workspace):
        raise RestoreError("restore destination must be outside the live workspace")
    if _is_relative_to(destination, backup_root):
        raise RestoreError("restore destination must be outside the backup directory")

    manifest_path = safe_child_path(backup_root, "manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RestoreError(f"invalid migration backup manifest: {exc}") from exc
    if manifest.get("schema") != MIGRATION_BACKUP_SCHEMA:
        raise RestoreError(f"unsupported backup schema: {manifest.get('schema')}")
    declared = manifest.get("files")
    if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
        raise RestoreError("backup manifest files must be a string list")

    control_source = safe_child_path(backup_root, "control.sqlite")
    if "control.sqlite" not in declared or not control_source.is_file():
        raise RestoreError("backup is missing control.sqlite")
    verified = [_verify_sqlite(control_source, "control.sqlite")]
    registered = _registered_world_ids(control_source)
    worlds: list[RestoreWorld] = []
    for world_id in registered:
        filename = f"world-{world_id}.sqlite"
        source = safe_child_path(backup_root, filename)
        if filename not in declared or not source.is_file():
            raise RestoreError(f"backup is missing registered world database: {filename}")
        verified.append(_verify_sqlite(source, filename))
        worlds.append(
            RestoreWorld(
                world_id=world_id,
                source=source,
                destination=destination / "worlds" / world_id / "world.sqlite",
            )
        )
    return RestorePlan(
        workspace=workspace,
        backup_root=backup_root,
        destination=destination,
        control_source=control_source,
        control_destination=destination / "control.sqlite",
        worlds=tuple(worlds),
        verified_sources=tuple(verified),
    )


def restore_plan_to_dict(plan: RestorePlan) -> dict[str, Any]:
    return {
        "schema": RESTORE_PLAN_SCHEMA,
        "status": "ready",
        "source_workspace": str(plan.workspace),
        "backup_root": str(plan.backup_root),
        "destination": str(plan.destination),
        "overwrite_live_workspace": False,
        "control": {
            "source": str(plan.control_source),
            "destination": str(plan.control_destination),
        },
        "worlds": [
            {
                "world_id": item.world_id,
                "source": str(item.source),
                "destination": str(item.destination),
            }
            for item in plan.worlds
        ],
        "verified_sources": list(plan.verified_sources),
        "side_effect_status": "read_only_plan_no_restore_performed",
    }


def execute_restore_to_new_path(plan: RestorePlan) -> dict[str, Any]:
    if plan.destination.exists():
        raise RestoreError(f"restore destination must not already exist: {plan.destination}")
    assert_update_unlocked(plan.workspace, "restore.execute")
    _assert_runtime_idle(plan.workspace)
    plan.destination.mkdir(parents=True, exist_ok=False)
    _sqlite_copy(plan.control_source, plan.control_destination)
    for world in plan.worlds:
        world.destination.parent.mkdir(parents=True, exist_ok=False)
        _sqlite_copy(world.source, world.destination)
    _rewrite_world_paths(plan)

    verified = [_verify_sqlite(plan.control_destination, "restored control.sqlite")]
    source_counts = _control_counts(plan.control_source)
    destination_counts = _control_counts(plan.control_destination)
    if source_counts != destination_counts:
        raise RestoreError(
            f"restored control row counts differ: source={source_counts}, "
            f"destination={destination_counts}"
        )
    world_receipts = []
    for world in plan.worlds:
        verified.append(_verify_sqlite(world.destination, f"restored {world.world_id}"))
        source_world_counts = _world_counts(world.source)
        destination_world_counts = _world_counts(world.destination)
        if source_world_counts != destination_world_counts:
            raise RestoreError(
                f"restored world row counts differ for {world.world_id}: "
                f"source={source_world_counts}, destination={destination_world_counts}"
            )
        world_receipts.append(
            {
                "world_id": world.world_id,
                "database": str(world.destination),
                "row_counts": destination_world_counts,
            }
        )
    receipt = {
        "schema": RESTORE_RECEIPT_SCHEMA,
        "status": "restored_and_verified",
        "created_at": utc_now(),
        "backup_root": str(plan.backup_root),
        "destination": str(plan.destination),
        "overwrite_live_workspace": False,
        "control_row_counts": destination_counts,
        "worlds": world_receipts,
        "verified": verified,
        "side_effect_status": "new_destination_created_live_workspace_unchanged",
    }
    receipt_path = safe_child_path(plan.destination, "restore_receipt.json")
    atomic_write_json(receipt_path, receipt)
    return {**receipt, "receipt_path": str(receipt_path)}


def _assert_runtime_idle(workspace: Path) -> None:
    active: list[str] = []
    for relative in (
        ("hermes", "task_queue"),
        ("hermes", "callbacks"),
        ("hermes", "reports_outbox"),
    ):
        root = safe_child_path(workspace, *relative)
        if root.exists() and any(path.is_file() for path in root.glob("*.json")):
            active.append("/".join(relative))
    if active:
        raise RestoreError(f"restore blocked by active runtime files: {', '.join(active)}")


def _registered_world_ids(control_path: Path) -> list[str]:
    conn = connect_sqlite(control_path)
    try:
        rows = conn.execute("SELECT world_id FROM worlds ORDER BY created_at").fetchall()
        return [str(row["world_id"]) for row in rows]
    except sqlite3.Error as exc:
        raise RestoreError(f"backup control database has no readable world registry: {exc}") from exc
    finally:
        conn.close()


def _sqlite_copy(source: Path, destination: Path) -> None:
    source_conn = connect_sqlite(source)
    destination_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(destination_conn)
    finally:
        destination_conn.close()
        source_conn.close()


def _rewrite_world_paths(plan: RestorePlan) -> None:
    conn = connect_sqlite(plan.control_destination)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for world in plan.worlds:
            conn.execute(
                "UPDATE worlds SET path = ?, updated_at = ? WHERE world_id = ?",
                (str(world.destination.parent.resolve()), utc_now(), world.world_id),
            )
        conn.commit()
    finally:
        conn.close()


def _verify_sqlite(path: Path, label: str) -> str:
    conn = connect_sqlite(path)
    try:
        result = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    except sqlite3.Error as exc:
        raise RestoreError(f"SQLite verification failed for {label}: {exc}") from exc
    finally:
        conn.close()
    if result != "ok":
        raise RestoreError(f"SQLite integrity_check failed for {label}: {result}")
    return f"{label}:integrity_ok"


def _control_counts(path: Path) -> dict[str, int]:
    return _table_counts(path, ("worlds", "workflow_runs", "workflow_callback_receipts"))


def _world_counts(path: Path) -> dict[str, int]:
    return _table_counts(path, ("entities", "facts", "tickets", "ticket_changes", "commit_log"))


def _table_counts(path: Path, tables: tuple[str, ...]) -> dict[str, int]:
    conn = connect_sqlite(path)
    try:
        existing = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
            if table in existing
        }
    finally:
        conn.close()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
