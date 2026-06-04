from __future__ import annotations

import json
from pathlib import Path

from .artifact_map import (
    artifact_architecture_map_path,
    build_artifact_architecture_map,
    format_artifact_architecture_map,
    write_artifact_architecture_map,
)
from .artifact_diagnostics import (
    diagnose_artifact_source_maps,
    format_artifact_source_map_diagnostic,
)
from .maintenance import (
    build_maintenance_scan,
    format_maintenance_scan,
    write_maintenance_scan,
)
from .update import UpdateLockError, assert_update_unlocked
from .uninstall import (
    build_uninstall_dry_run_plan,
    format_uninstall_dry_run_plan,
    write_uninstall_dry_run_plan,
)


def _guard_update_unlocked(workspace: Path, operation: str) -> bool:
    try:
        assert_update_unlocked(workspace, operation)
    except UpdateLockError as exc:
        print("update_lock: blocked")
        print(f"operation: {operation}")
        print(f"detail: {exc}")
        return False
    return True


def run_artifact_map(workspace: Path, write: bool, output_format: str) -> int:
    stored_path = artifact_architecture_map_path(workspace)
    payload = build_artifact_architecture_map(workspace)
    output_path = stored_path if stored_path.exists() else None
    if write:
        if not _guard_update_unlocked(workspace, "artifact.map.write"):
            return 1
        output_path = write_artifact_architecture_map(workspace)
        payload = build_artifact_architecture_map(workspace)
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_artifact_architecture_map(payload, stored_path=output_path):
            print(line)
    return 0


def run_artifact_diagnose(workspace: Path, output_format: str) -> int:
    payload = diagnose_artifact_source_maps(workspace)
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_artifact_source_map_diagnostic(payload):
            print(line)
    return 0


def run_artifact_uninstall_plan(workspace: Path, write: bool, output_format: str) -> int:
    if write and not _guard_update_unlocked(workspace, "artifact.uninstall_plan.write"):
        return 1
    payload = (
        write_uninstall_dry_run_plan(workspace)
        if write
        else build_uninstall_dry_run_plan(workspace)
    )
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_uninstall_dry_run_plan(payload):
            print(line)
    return 0


def run_artifact_maintenance_scan(
    workspace: Path,
    write: bool,
    output_format: str,
    top: int,
) -> int:
    if write and not _guard_update_unlocked(workspace, "artifact.maintenance_scan.write"):
        return 1
    payload = (
        write_maintenance_scan(workspace, top=top)
        if write
        else build_maintenance_scan(workspace, top=top)
    )
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_maintenance_scan(payload):
            print(line)
    return 0
