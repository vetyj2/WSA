from __future__ import annotations

import json
import sqlite3
import subprocess
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from . import __version__
from .hermes_commands import (
    HERMES_COMMAND_REGISTRY_FILENAME,
    HERMES_LOCAL_COMMAND_REGISTRY_FILENAME,
    build_hermes_command_registry,
    validate_local_command_registry_report,
)
from .paths import safe_child_path
from .workspace import (
    CONTROL_SCHEMA_VERSION,
    SCHEMA_VERSION,
    WORLD_SCHEMA_VERSION,
    SchemaVersionError,
    WorkspacePathError,
    control_db_path,
    list_worlds,
    schema_version,
    sqlite_connection,
    world_db_path,
)


UPDATE_PREFLIGHT_SCHEMA = "wsa.update.preflight.v1"
UPDATE_BACKUP_SCHEMA = "wsa.update.backup.v1"
UPDATE_LOCK_FILENAME = "update.lock"
ACTIVE_TASK_STATUSES = {"queued", "running", "waiting_approval", "blocked"}
ACTIVE_JOB_STATUSES = {"active", "running", "queued", "enabled", "scheduled"}
PROTECTED_PATHS = [
    "control.sqlite",
    "artifacts/",
    "worlds/",
    "reports/",
    "user_profile/",
    "manager/",
    "hermes/adapter_config/hermes_commands.local.json",
    "hermes/adapter_config/*live*.json",
    "hermes/task_queue/",
    "hermes/task_archive/",
    "hermes/task_state/",
    "hermes/callbacks/",
    "hermes/callback_archive/",
    "hermes/reports_outbox/",
    "hermes/quarantine/",
    "hermes/maintenance/",
]


@dataclass(frozen=True)
class UpdateCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class UpdatePreflightReport:
    workspace: Path
    source_root: Path | None
    package_version: str
    schema_version: int
    checks: List[UpdateCheck]

    @property
    def blocked(self) -> bool:
        return any(check.status == "block" for check in self.checks)

    @property
    def warnings(self) -> bool:
        return any(check.status == "warn" for check in self.checks)


@dataclass(frozen=True)
class UpdateBackupResult:
    backup_path: Path
    workspace: Path
    sqlite_files: int
    copied_files: int
    metadata_path: Path


class UpdateLockError(RuntimeError):
    """Raised when a workspace mutation is attempted during an update lock."""


class UpdateBackupError(RuntimeError):
    """Raised when a workspace backup cannot be created safely."""


def update_lock_path(workspace: Path) -> Path:
    return safe_child_path(workspace, "hermes", "maintenance", UPDATE_LOCK_FILENAME)


def assert_update_unlocked(workspace: Path, operation: str) -> None:
    for path in (
        update_lock_path(workspace),
        safe_child_path(workspace, "hermes", "maintenance", "migration.lock"),
    ):
        if path.exists():
            raise UpdateLockError(f"{operation} blocked by workspace lock: {path}")


def run_update_preflight(
    workspace: Path,
    source_root: Path | None = None,
) -> UpdatePreflightReport:
    checks: List[UpdateCheck] = []
    checks.append(_workspace_check(workspace))
    checks.extend(_schema_checks(workspace))
    checks.append(_update_lock_check(workspace))
    checks.extend(_runtime_queue_checks(workspace))
    checks.append(_scheduler_check(workspace))
    checks.append(_command_overlay_check(workspace))
    checks.append(_generated_registry_check(workspace))
    checks.append(_live_config_check(workspace))
    checks.append(_backup_requirement_check(workspace))
    if source_root is not None:
        checks.append(_source_root_check(source_root))
    checks.append(
        UpdateCheck(
            "destructive_update_policy",
            "ok",
            "update automation must not run git clean -fdx, rm -rf, or recopy over protected workspace paths",
        )
    )
    return UpdatePreflightReport(
        workspace=workspace,
        source_root=source_root,
        package_version=__version__,
        schema_version=SCHEMA_VERSION,
        checks=checks,
    )


def update_preflight_to_dict(report: UpdatePreflightReport) -> dict[str, Any]:
    return {
        "schema": UPDATE_PREFLIGHT_SCHEMA,
        "package_version": report.package_version,
        "supported_schema_version": report.schema_version,
        "status": "blocked" if report.blocked else "pass",
        "blocked": report.blocked,
        "warnings": report.warnings,
        "workspace": str(report.workspace),
        "source_root": str(report.source_root) if report.source_root is not None else None,
        "checks": [
            {"name": check.name, "status": check.status, "detail": check.detail}
            for check in report.checks
        ],
        "protected_paths": PROTECTED_PATHS,
        "recommended_actions": recommended_update_actions(report),
    }


def format_update_preflight(report: UpdatePreflightReport) -> List[str]:
    lines = [
        f"update_preflight: {'blocked' if report.blocked else 'pass'}",
        f"package_version: {report.package_version}",
        f"supported_schema_version: {report.schema_version}",
        f"workspace: {report.workspace}",
    ]
    if report.source_root is not None:
        lines.append(f"source_root: {report.source_root}")
    lines.extend(
        "\t".join([check.status, check.name, check.detail])
        for check in report.checks
    )
    lines.append("protected_paths:")
    lines.extend(f"\t{item}" for item in PROTECTED_PATHS)
    lines.append("recommended_actions:")
    lines.extend(f"\t{item}" for item in recommended_update_actions(report))
    return lines


def backup_workspace(
    workspace: Path,
    output_dir: Path,
    source_root: Path | None = None,
) -> UpdateBackupResult:
    report = run_update_preflight(workspace, source_root=source_root)
    blocking = [
        check
        for check in report.checks
        if check.status == "block" and check.name != "update_lock"
    ]
    if blocking:
        details = "; ".join(f"{check.name}: {check.detail}" for check in blocking)
        raise UpdateBackupError(f"update backup blocked: {details}")
    if not workspace.exists() or not workspace.is_dir():
        raise UpdateBackupError("workspace directory is required for backup")

    output_dir = output_dir.expanduser().resolve()
    workspace_resolved = workspace.resolve()
    if _is_relative_to(output_dir, workspace_resolved):
        raise UpdateBackupError("backup output directory must be outside the workspace")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = output_dir / f"{workspace_resolved.name}-wsa-backup-{timestamp}"
    if backup_root.exists():
        raise UpdateBackupError(f"backup path already exists: {backup_root}")
    backup_root.mkdir(parents=True)

    copied_files = 0
    sqlite_files = 0
    for path in sorted(workspace_resolved.rglob("*")):
        rel = path.relative_to(workspace_resolved)
        target = backup_root / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if _is_sqlite_runtime_file(path):
            continue
        if path.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied_files += 1

    for path in sorted(workspace_resolved.rglob("*.sqlite")):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace_resolved)
        target = backup_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _backup_sqlite(path, target)
        sqlite_files += 1

    metadata_path = backup_root / "wsa_backup_manifest.json"
    result = UpdateBackupResult(
        backup_path=backup_root,
        workspace=workspace_resolved,
        sqlite_files=sqlite_files,
        copied_files=copied_files,
        metadata_path=metadata_path,
    )
    metadata_path.write_text(
        json.dumps(backup_result_to_dict(result), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return result


def backup_result_to_dict(result: UpdateBackupResult) -> dict[str, Any]:
    return {
        "schema": UPDATE_BACKUP_SCHEMA,
        "backup_path": str(result.backup_path),
        "workspace": str(result.workspace),
        "sqlite_files": result.sqlite_files,
        "copied_files": result.copied_files,
        "metadata_path": str(result.metadata_path),
        "protected_paths": PROTECTED_PATHS,
    }


def format_backup_result(result: UpdateBackupResult) -> List[str]:
    return [
        f"update_backup: {result.backup_path}",
        f"workspace: {result.workspace}",
        f"sqlite_files: {result.sqlite_files}",
        f"copied_files: {result.copied_files}",
        f"metadata_path: {result.metadata_path}",
    ]


def recommended_update_actions(report: UpdatePreflightReport) -> List[str]:
    actions = [
        "pause Hermes task intake, callbacks, and cron jobs before source update",
        "create a backup snapshot of the workspace outside the source checkout before update",
        "update only the source/package layer; do not delete or recopy the live workspace",
        "refresh generated base command registry after update, preserving hermes_commands.local.json",
        "validate local Hermes command overlay before and after update; report collision risk to the user",
        "run update preflight again, then wsa doctor and manager diagnose before resuming Hermes",
    ]
    local_overlay = next(
        (check for check in report.checks if check.name == "local_command_overlay"),
        None,
    )
    if local_overlay is not None:
        if local_overlay.status == "block":
            actions.insert(
                0,
                "rename or remove colliding local Hermes commands before updating or resuming live use",
            )
        elif local_overlay.status == "warn":
            actions.insert(
                0,
                "review local Hermes mutating-command metadata and brief the user before side effects",
            )
    if report.blocked:
        actions.insert(0, "do not update until block checks are resolved")
    return actions


def _workspace_check(workspace: Path) -> UpdateCheck:
    if not workspace.exists():
        return UpdateCheck(
            "workspace_exists",
            "warn",
            "workspace does not exist yet; no live WSA data detected",
        )
    if not workspace.is_dir():
        return UpdateCheck("workspace_exists", "block", "workspace path is not a directory")
    return UpdateCheck("workspace_exists", "ok", "workspace directory exists")


def _schema_checks(workspace: Path) -> List[UpdateCheck]:
    db_path = control_db_path(workspace)
    if not db_path.exists():
        return [UpdateCheck("schema_supported", "ok", "control.sqlite is absent")]
    checks: List[UpdateCheck] = []
    try:
        with sqlite_connection(db_path, schema_name="control") as conn:
            control_version = schema_version(conn, "control")
        worlds = list_worlds(workspace)
        checks.append(
            UpdateCheck(
                "control_schema_supported",
                "ok" if control_version == CONTROL_SCHEMA_VERSION else "block",
                (
                    f"control schema {control_version if control_version is not None else 'unknown'}; "
                    f"supported={CONTROL_SCHEMA_VERSION}; worlds={len(worlds)}"
                    + ("; run wsa migrate --apply" if control_version != CONTROL_SCHEMA_VERSION else "")
                ),
            )
        )
        for world in worlds:
            with sqlite_connection(world_db_path(world.path), schema_name="world") as conn:
                world_version = schema_version(conn, "world")
            checks.append(
                UpdateCheck(
                    f"world_schema_supported:{world.world_id}",
                    "ok" if world_version == WORLD_SCHEMA_VERSION else "block",
                    (
                        f"world schema {world_version if world_version is not None else 'unknown'}; "
                        f"supported={WORLD_SCHEMA_VERSION}"
                        + ("; run wsa migrate --apply" if world_version != WORLD_SCHEMA_VERSION else "")
                    ),
                )
            )
    except (SchemaVersionError, WorkspacePathError, sqlite3.Error) as exc:
        return [UpdateCheck("schema_supported", "block", str(exc))]
    return checks


def _update_lock_check(workspace: Path) -> UpdateCheck:
    lock_path = safe_child_path(workspace, "hermes", "maintenance", "update.lock")
    if lock_path.exists():
        return UpdateCheck("update_lock", "block", f"existing update lock: {lock_path}")
    return UpdateCheck("update_lock", "ok", "no update lock")


def _runtime_queue_checks(workspace: Path) -> List[UpdateCheck]:
    checks: List[UpdateCheck] = []
    for name in ("task_queue", "callbacks", "reports_outbox"):
        path = safe_child_path(workspace, "hermes", name)
        files = _json_files(path)
        status = "block" if files else "ok"
        detail = f"{len(files)} pending files" if files else "no pending files"
        checks.append(UpdateCheck(f"{name}_empty", status, detail))

    state_dir = safe_child_path(workspace, "hermes", "task_state")
    active = []
    unreadable = []
    for path in _json_files(state_dir):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            unreadable.append(path.name)
            continue
        if str(payload.get("status", "")).lower() in ACTIVE_TASK_STATUSES:
            active.append(path.name)
    if active:
        checks.append(
            UpdateCheck(
                "task_state_active",
                "block",
                f"active task state files: {', '.join(active[:5])}",
            )
        )
    elif unreadable:
        checks.append(
            UpdateCheck(
                "task_state_active",
                "warn",
                f"unreadable task state files: {', '.join(unreadable[:5])}",
            )
        )
    else:
        checks.append(UpdateCheck("task_state_active", "ok", "no active task states"))
    return checks


def _scheduler_check(workspace: Path) -> UpdateCheck:
    db_path = control_db_path(workspace)
    if not db_path.exists():
        return UpdateCheck("scheduler_quiesced", "ok", "control.sqlite is absent")
    try:
        with sqlite_connection(db_path, schema_name="control") as conn:
            rows = conn.execute("SELECT status FROM scheduler_jobs").fetchall()
    except (SchemaVersionError, sqlite3.Error) as exc:
        return UpdateCheck("scheduler_quiesced", "block", str(exc))
    active_count = sum(1 for row in rows if str(row["status"]).lower() in ACTIVE_JOB_STATUSES)
    if active_count:
        return UpdateCheck("scheduler_quiesced", "block", f"{active_count} active scheduler jobs")
    return UpdateCheck("scheduler_quiesced", "ok", "no active scheduler jobs")


def _command_overlay_check(workspace: Path) -> UpdateCheck:
    path = safe_child_path(
        workspace,
        "hermes",
        "adapter_config",
        HERMES_LOCAL_COMMAND_REGISTRY_FILENAME,
    )
    if not path.exists():
        return UpdateCheck("local_command_overlay", "ok", "no local command overlay")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return UpdateCheck("local_command_overlay", "block", f"invalid local overlay JSON: {exc}")
    report = validate_local_command_registry_report(payload, build_hermes_command_registry(), path)
    if report["blocked"]:
        findings = [
            f"{item['code']}: {item['message']}"
            for item in report["findings"]
            if item["severity"] == "block"
        ]
        actions = "; ".join(report.get("recommended_actions", []))
        detail = "; ".join(findings[:5])
        if actions:
            detail = f"{detail}; recommended: {actions}"
        return UpdateCheck("local_command_overlay", "block", detail)
    if report["warnings"]:
        findings = [
            f"{item['code']}: {item['message']}"
            for item in report["findings"]
            if item["severity"] == "warn"
        ]
        actions = "; ".join(report.get("recommended_actions", []))
        detail = "; ".join(findings[:5])
        if actions:
            detail = f"{detail}; recommended: {actions}"
        return UpdateCheck("local_command_overlay", "warn", detail)
    count = len(payload.get("commands", []))
    return UpdateCheck("local_command_overlay", "ok", f"{count} local commands preserved by overlay")


def _generated_registry_check(workspace: Path) -> UpdateCheck:
    path = safe_child_path(
        workspace,
        "hermes",
        "adapter_config",
        HERMES_COMMAND_REGISTRY_FILENAME,
    )
    if not path.exists():
        return UpdateCheck(
            "generated_command_registry",
            "warn",
            "generated base registry is missing; recreate after update",
        )
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return UpdateCheck("generated_command_registry", "block", f"invalid generated registry: {exc}")
    generated = build_hermes_command_registry()
    status = "ok" if current == generated else "warn"
    detail = (
        "generated registry matches current package"
        if status == "ok"
        else "generated registry differs from current package; safe to refresh generated file only"
    )
    return UpdateCheck("generated_command_registry", status, detail)


def _live_config_check(workspace: Path) -> UpdateCheck:
    config_dir = safe_child_path(workspace, "hermes", "adapter_config")
    if not config_dir.exists():
        return UpdateCheck("live_adapter_config", "ok", "adapter_config is absent")
    live_files = [
        path.name
        for path in sorted(config_dir.iterdir())
        if path.is_file()
        and ".example." not in path.name
        and path.name != HERMES_COMMAND_REGISTRY_FILENAME
        and path.name != HERMES_LOCAL_COMMAND_REGISTRY_FILENAME
    ]
    if live_files:
        return UpdateCheck(
            "live_adapter_config",
            "warn",
            f"preserve local runtime config files: {', '.join(live_files[:5])}",
        )
    return UpdateCheck("live_adapter_config", "ok", "no extra live adapter config files")


def _backup_requirement_check(workspace: Path) -> UpdateCheck:
    live_paths = []
    for name in ("control.sqlite", "worlds", "reports", "manager", "hermes"):
        path = workspace / name
        if path.exists():
            live_paths.append(name)
    if live_paths:
        return UpdateCheck(
            "backup_required",
            "warn",
            f"live workspace state detected: {', '.join(live_paths)}",
        )
    return UpdateCheck("backup_required", "ok", "no live workspace state detected")


def _source_root_check(source_root: Path) -> UpdateCheck:
    if not source_root.exists():
        return UpdateCheck("source_root", "warn", "source root does not exist")
    git_dir = source_root / ".git"
    if not git_dir.exists():
        return UpdateCheck("source_root", "warn", "source root is not a Git checkout")
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return UpdateCheck("source_root", "warn", f"could not inspect Git status: {exc}")
    if result.stdout.strip():
        return UpdateCheck("source_root", "warn", "source checkout has local changes")
    return UpdateCheck("source_root", "ok", "source checkout is clean")


def _json_files(path: Path) -> List[Path]:
    if not path.exists() or not path.is_dir():
        return []
    return sorted(item for item in path.iterdir() if item.is_file() and item.suffix == ".json")


def _backup_sqlite(source: Path, target: Path) -> None:
    source_conn = sqlite3.connect(source)
    try:
        target_conn = sqlite3.connect(target)
        try:
            source_conn.backup(target_conn)
            target_conn.commit()
        finally:
            target_conn.close()
    finally:
        source_conn.close()


def _is_sqlite_runtime_file(path: Path) -> bool:
    name = path.name
    return (
        name.endswith(".sqlite")
        or name.endswith(".sqlite-wal")
        or name.endswith(".sqlite-shm")
        or name.endswith(".db")
        or name.endswith(".db-wal")
        or name.endswith(".db-shm")
    )


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True
