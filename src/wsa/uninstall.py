from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .artifact_diagnostics import diagnose_artifact_source_maps
from .artifact_map import build_artifact_architecture_map
from .paths import safe_child_path
from .workspace import init_workspace, list_worlds, utc_now


UNINSTALL_DRY_RUN_SCHEMA = "wsa.uninstall.dry_run_plan.v1"
UNINSTALL_PLAN_ROOT = ("manager", "uninstall_plans")


def build_uninstall_dry_run_plan(workspace: Path) -> Dict[str, Any]:
    artifact_map = build_artifact_architecture_map(workspace)
    source_map_diagnostic = diagnose_artifact_source_maps(workspace)
    worlds = list_worlds(workspace)
    return {
        "schema": UNINSTALL_DRY_RUN_SCHEMA,
        "created_at": utc_now(),
        "workspace_ref": ".",
        "mode": "dry_run",
        "side_effect_status": "read_only",
        "automatic_delete_performed": False,
        "requires_explicit_user_approval_for_delete": True,
        "backup_recommended_before_any_cleanup": True,
        "artifact_source_map_status": source_map_diagnostic["status"],
        "artifact_orphan_exports": source_map_diagnostic["counts"]["orphan_exports"],
        "preserve": _preserve_entries(workspace, worlds),
        "archive_candidates": _archive_candidates(workspace, worlds),
        "delete_candidates_after_archive": _delete_candidates_after_archive(workspace, worlds),
        "external_artifact_policy": artifact_map["external_artifact_boundary"],
        "blocked_until_review": _blocked_until_review(source_map_diagnostic),
        "recommended_order": [
            "run wsa doctor and wsa artifact diagnose",
            "create an operator backup outside the workspace",
            "review preserve/archive/delete candidate sections",
            "fix source-map warnings before touching external or derived artifacts",
            "archive derived artifacts before any deletion",
            "remove source checkout/package only after user data is preserved",
        ],
    }


def write_uninstall_dry_run_plan(workspace: Path) -> Dict[str, Any]:
    init_workspace(workspace)
    plan = build_uninstall_dry_run_plan(workspace)
    root = safe_child_path(workspace, *UNINSTALL_PLAN_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    path = safe_child_path(root, f"uninstall-dry-run-{_timestamp_for_filename(plan['created_at'])}.json")
    path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    plan["side_effect_status"] = "workspace_mutating_plan_written"
    plan["plan_ref"] = _relative(workspace, path)
    return plan


def format_uninstall_dry_run_plan(payload: Dict[str, Any]) -> List[str]:
    lines = [
        f"uninstall_plan: {payload['mode']}",
        f"side_effect_status: {payload['side_effect_status']}",
        f"automatic_delete_performed: {str(payload['automatic_delete_performed']).lower()}",
        f"requires_explicit_user_approval_for_delete: {str(payload['requires_explicit_user_approval_for_delete']).lower()}",
        f"artifact_source_map_status: {payload['artifact_source_map_status']}",
        f"artifact_orphan_exports: {payload['artifact_orphan_exports']}",
        f"preserve_count: {len(payload['preserve'])}",
        f"archive_candidate_count: {len(payload['archive_candidates'])}",
        f"delete_candidate_count: {len(payload['delete_candidates_after_archive'])}",
        f"blocked_until_review_count: {len(payload['blocked_until_review'])}",
    ]
    if payload.get("plan_ref"):
        lines.append(f"plan_ref: {payload['plan_ref']}")
    if payload["blocked_until_review"]:
        lines.append("blocked_until_review:")
        for item in payload["blocked_until_review"]:
            lines.append(f"\t{item['code']}: {item['message']}")
    lines.append("preserve:")
    for item in payload["preserve"][:20]:
        lines.append(f"\t{item['kind']}\t{item['path']}\t{item['reason']}")
    lines.append("archive_candidates:")
    for item in payload["archive_candidates"][:20]:
        lines.append(f"\t{item['kind']}\t{item['path']}\t{item['reason']}")
    return lines


def _preserve_entries(workspace: Path, worlds: List[Any]) -> List[Dict[str, Any]]:
    entries = [
        _entry("source_of_truth", "control.sqlite", "workspace registry and runtime/session metadata"),
        _entry("local_overlay", "hermes/adapter_config/hermes_commands.local.json", "runtime-owned custom commands"),
    ]
    for world in worlds:
        entries.extend(
            [
                _entry("world_database", _relative(workspace, safe_child_path(world.path, "world.sqlite")), "world canon/proposal database"),
                _entry("startup_profile", _relative(workspace, safe_child_path(world.path, "startup")), "author startup answers and profile choices"),
            ]
        )
    return entries


def _archive_candidates(workspace: Path, worlds: List[Any]) -> List[Dict[str, Any]]:
    entries = [
        _entry("report_mailbox", "reports/", "workspace report mailboxes and cleanup audits"),
        _entry("task_archive", "hermes/task_archive/", "completed task packets"),
        _entry("callback_archive", "hermes/callback_archive/", "completed callback packets"),
    ]
    for world in worlds:
        entries.extend(
            [
                _entry("session_logs", _relative(workspace, safe_child_path(world.path, "artifacts", "session_logs")), "date-scoped source logs and derived exports"),
                _entry("orchestrator_runs", _relative(workspace, safe_child_path(world.path, "orchestrator_runs")), "durable run JSON and audit state"),
                _entry("meetings", _relative(workspace, safe_child_path(world.path, "meetings")), "meeting artifacts"),
                _entry("scenes", _relative(workspace, safe_child_path(world.path, "scenes")), "scene prep and temp artifacts"),
            ]
        )
    return entries


def _delete_candidates_after_archive(workspace: Path, worlds: List[Any]) -> List[Dict[str, Any]]:
    entries = [
        _entry("runtime_residue", "hermes/task_queue/", "only after tasks are completed/cancelled and archived"),
        _entry("runtime_residue", "hermes/callbacks/", "only after callbacks are ingested/rejected and archived"),
    ]
    for world in worlds:
        entries.append(
            _entry("derived_exports", _relative(workspace, safe_child_path(world.path, "artifacts", "session_logs")), "only derived exports with valid source maps, after archive")
        )
    return entries


def _blocked_until_review(source_map_diagnostic: Dict[str, Any]) -> List[Dict[str, str]]:
    blocked: List[Dict[str, str]] = []
    if source_map_diagnostic["status"] == "blocked":
        blocked.append(
            {
                "code": "invalid_source_map",
                "message": "invalid source-map JSON/schema must be fixed before uninstall cleanup",
            }
        )
    if source_map_diagnostic["counts"]["orphan_exports"]:
        blocked.append(
            {
                "code": "orphan_exports",
                "message": "source-map-less exports should be mapped, archived, or explicitly ignored before cleanup",
            }
        )
    return blocked


def _entry(kind: str, path: str, reason: str) -> Dict[str, str]:
    return {"kind": kind, "path": path, "reason": reason}


def _timestamp_for_filename(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())[:14] or "unknown-time"


def _relative(workspace: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)
