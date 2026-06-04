from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .artifact_diagnostics import diagnose_artifact_source_maps
from .paths import safe_child_path
from .workspace import init_workspace, list_worlds, utc_now


MAINTENANCE_SCAN_SCHEMA = "wsa.maintenance.storage_scan.v1"
MAINTENANCE_PLAN_ROOT = ("manager", "maintenance_plans")


def build_maintenance_scan(workspace: Path, top: int = 10) -> Dict[str, Any]:
    top = max(1, top)
    roots = _scan_roots(workspace)
    scanned = [_root_entry(workspace, root_id, path, reason) for root_id, path, reason in roots]
    totals = {
        "files": sum(item["file_count"] for item in scanned),
        "bytes": sum(item["byte_count"] for item in scanned),
        "existing_roots": sum(1 for item in scanned if item["exists"]),
        "missing_roots": sum(1 for item in scanned if not item["exists"]),
    }
    source_maps = diagnose_artifact_source_maps(workspace)
    largest = sorted(
        [item for item in scanned if item["exists"]],
        key=lambda item: (item["byte_count"], item["file_count"], item["path"]),
        reverse=True,
    )[:top]
    recommended = _recommended_actions(scanned, source_maps)
    return {
        "schema": MAINTENANCE_SCAN_SCHEMA,
        "created_at": utc_now(),
        "workspace_ref": ".",
        "side_effect_status": "read_only",
        "delete_performed": False,
        "archive_performed": False,
        "scan_strategy": "metadata_first_bounded_roots",
        "top_limit": top,
        "totals": totals,
        "source_map_status": source_maps["status"],
        "orphan_exports": source_maps["counts"]["orphan_exports"],
        "roots": scanned,
        "largest_roots": largest,
        "recommended_actions": recommended,
    }


def write_maintenance_scan(workspace: Path, top: int = 10) -> Dict[str, Any]:
    init_workspace(workspace)
    payload = build_maintenance_scan(workspace, top=top)
    root = safe_child_path(workspace, *MAINTENANCE_PLAN_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    path = safe_child_path(root, f"maintenance-scan-{_timestamp_for_filename(payload['created_at'])}.json")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload["side_effect_status"] = "workspace_mutating_scan_written"
    payload["scan_ref"] = _relative(workspace, path)
    return payload


def format_maintenance_scan(payload: Dict[str, Any]) -> List[str]:
    lines = [
        "maintenance_scan: storage_hygiene",
        f"side_effect_status: {payload['side_effect_status']}",
        f"delete_performed: {str(payload['delete_performed']).lower()}",
        f"archive_performed: {str(payload['archive_performed']).lower()}",
        f"total_files: {payload['totals']['files']}",
        f"total_bytes: {payload['totals']['bytes']}",
        f"existing_roots: {payload['totals']['existing_roots']}",
        f"source_map_status: {payload['source_map_status']}",
        f"orphan_exports: {payload['orphan_exports']}",
    ]
    if payload.get("scan_ref"):
        lines.append(f"scan_ref: {payload['scan_ref']}")
    lines.append("largest_roots:")
    for item in payload["largest_roots"]:
        lines.append(
            f"\t{item['root_id']}\tfiles={item['file_count']}\tbytes={item['byte_count']}\t{item['path']}"
        )
    if payload.get("recommended_actions"):
        lines.append("recommended_actions:")
        lines.extend(f"\t{item}" for item in payload["recommended_actions"])
    return lines


def _scan_roots(workspace: Path) -> List[tuple[str, Path, str]]:
    roots: List[tuple[str, Path, str]] = [
        ("reports", safe_child_path(workspace, "reports"), "workspace report mailboxes"),
        ("hermes_task_queue", safe_child_path(workspace, "hermes", "task_queue"), "pending task packets"),
        ("hermes_callbacks", safe_child_path(workspace, "hermes", "callbacks"), "pending callback packets"),
        ("hermes_task_archive", safe_child_path(workspace, "hermes", "task_archive"), "completed task packets"),
        ("hermes_callback_archive", safe_child_path(workspace, "hermes", "callback_archive"), "completed callback packets"),
        ("hermes_reports_outbox", safe_child_path(workspace, "hermes", "reports_outbox"), "runtime-delivery report artifacts"),
    ]
    for world in list_worlds(workspace):
        roots.extend(
            [
                (
                    f"{world.world_id}:session_logs",
                    safe_child_path(world.path, "artifacts", "session_logs"),
                    "date-scoped session logs and exports",
                ),
                (
                    f"{world.world_id}:orchestrator_runs",
                    safe_child_path(world.path, "orchestrator_runs"),
                    "durable orchestrator run JSON",
                ),
                (
                    f"{world.world_id}:scenes",
                    safe_child_path(world.path, "scenes"),
                    "scene prep and temp artifacts",
                ),
                (
                    f"{world.world_id}:meetings",
                    safe_child_path(world.path, "meetings"),
                    "meeting artifacts",
                ),
                (
                    f"{world.world_id}:world_artifacts",
                    safe_child_path(world.path, "artifacts"),
                    "world-scoped managed artifacts",
                ),
            ]
        )
    return roots


def _root_entry(workspace: Path, root_id: str, path: Path, reason: str) -> Dict[str, Any]:
    stats = _path_stats(path)
    return {
        "root_id": root_id,
        "path": _relative(workspace, path),
        "reason": reason,
        "exists": path.exists(),
        "file_count": stats["files"],
        "byte_count": stats["bytes"],
    }


def _path_stats(path: Path) -> Dict[str, int]:
    if not path.exists():
        return {"files": 0, "bytes": 0}
    files = 0
    bytes_ = 0
    for item in _iter_files(path):
        files += 1
        try:
            bytes_ += item.stat().st_size
        except OSError:
            continue
    return {"files": files, "bytes": bytes_}


def _iter_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    for item in path.rglob("*"):
        if item.is_file():
            yield item


def _recommended_actions(
    roots: List[Dict[str, Any]],
    source_maps: Dict[str, Any],
) -> List[str]:
    actions: List[str] = []
    by_id = {item["root_id"]: item for item in roots}
    if by_id.get("hermes_task_queue", {}).get("file_count", 0):
        actions.append("review pending Hermes task queue before update, uninstall, or backup")
    if by_id.get("hermes_callbacks", {}).get("file_count", 0):
        actions.append("ingest, reject, or archive pending Hermes callbacks before cleanup")
    if source_maps["counts"]["orphan_exports"]:
        actions.append("run wsa artifact diagnose and map/archive orphan exports before uninstall")
    archive_files = sum(
        item["file_count"]
        for item in roots
        if "archive" in item["root_id"] and item["file_count"] >= 100
    )
    if archive_files:
        actions.append("large archive roots detected; write a maintenance scan before pruning by retention policy")
    if not actions:
        actions.append("no immediate storage hygiene action required")
    return actions


def _timestamp_for_filename(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())[:14] or "unknown-time"


def _relative(workspace: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)
