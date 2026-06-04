from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .paths import safe_child_path
from .reporting_contract import REPORTING_ARTIFACT_MANIFEST_SCHEMA
from .workspace import WorldRecord, init_workspace, list_worlds, utc_now


ARTIFACT_ARCHITECTURE_MAP_SCHEMA = "wsa.artifact_architecture_map.v1"
ARTIFACT_ARCHITECTURE_MAP_FILENAME = "artifact_architecture_map.json"
ARTIFACT_MAP_ROOT = ("manager", "artifact_map")


def artifact_map_root(workspace: Path) -> Path:
    return safe_child_path(workspace, *ARTIFACT_MAP_ROOT)


def artifact_architecture_map_path(workspace: Path) -> Path:
    return safe_child_path(workspace, *ARTIFACT_MAP_ROOT, ARTIFACT_ARCHITECTURE_MAP_FILENAME)


def build_artifact_architecture_map(workspace: Path) -> Dict[str, Any]:
    worlds = _safe_worlds(workspace)
    return {
        "schema": ARTIFACT_ARCHITECTURE_MAP_SCHEMA,
        "created_at": utc_now(),
        "workspace_ref": ".",
        "directory_base": "/".join(ARTIFACT_MAP_ROOT) + "/",
        "map_ref": "/".join((*ARTIFACT_MAP_ROOT, ARTIFACT_ARCHITECTURE_MAP_FILENAME)),
        "purpose": (
            "Bound WSA source-of-truth zones, managed artifact zones, runtime residue, "
            "and external artifact policy for export, maintenance, migration, and uninstall."
        ),
        "source_of_truth_zones": _source_of_truth_zones(),
        "managed_artifact_zones": _managed_artifact_zones(),
        "runtime_residue_zones": _runtime_residue_zones(),
        "external_artifact_boundary": {
            "automatic_delete": False,
            "source_map_required": True,
            "source_map_filename": "artifact_source_map.json",
            "source_map_schema": REPORTING_ARTIFACT_MANIFEST_SCHEMA,
            "default_action_without_source_map": "report_unknown_external_artifact_only",
            "required_fields": [
                "artifact_id",
                "artifact_type",
                "originating_command_or_run_id",
                "absolute_or_runtime_path",
                "managed_by",
                "cleanup_hint",
                "safe_to_delete_with_session",
            ],
        },
        "delete_and_uninstall_policy": {
            "default_mode": "dry_run",
            "preserve_by_default": [
                "control.sqlite",
                "worlds/{world_id}/world.sqlite",
                "worlds/{world_id}/startup/",
                "hermes/adapter_config/hermes_commands.local.json",
            ],
            "archive_before_delete": [
                "reports/",
                "hermes/task_archive/",
                "hermes/callback_archive/",
                "worlds/{world_id}/artifacts/session_logs/",
            ],
            "delete_candidates_only_after_saved_plan": [
                "rebuildable exports",
                "completed callback residue",
                "completed task residue",
                "diagnostic logs beyond retention policy",
            ],
        },
        "maintenance_policy": {
            "scan_strategy": "metadata_first_streaming",
            "large_workspace_rule": "summarize top-N and save plan before mutating",
            "source_logs_before_exports": True,
            "unknown_external_artifacts": "warn_only",
        },
        "concrete_worlds": [_world_entry(world) for world in worlds],
    }


def write_artifact_architecture_map(workspace: Path) -> Path:
    init_workspace(workspace)
    path = artifact_architecture_map_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_artifact_architecture_map(workspace)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_artifact_architecture_map(workspace: Path) -> Dict[str, Any] | None:
    path = artifact_architecture_map_path(workspace)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validate_artifact_architecture_map(workspace: Path) -> List[str]:
    path = artifact_architecture_map_path(workspace)
    if not path.exists():
        return ["artifact architecture map is missing"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"artifact architecture map is invalid JSON: {exc}"]
    if payload.get("schema") != ARTIFACT_ARCHITECTURE_MAP_SCHEMA:
        return ["artifact architecture map has unexpected schema"]
    if payload.get("directory_base") != "/".join(ARTIFACT_MAP_ROOT) + "/":
        return ["artifact architecture map has unexpected directory_base"]
    required = {
        "source_of_truth_zones",
        "managed_artifact_zones",
        "runtime_residue_zones",
        "external_artifact_boundary",
    }
    missing = sorted(required - payload.keys())
    if missing:
        return [f"artifact architecture map is missing fields: {', '.join(missing)}"]
    return []


def format_artifact_architecture_map(payload: Dict[str, Any], stored_path: Path | None = None) -> List[str]:
    lines = [
        f"artifact_map: {payload['schema']}",
        f"directory_base: {payload['directory_base']}",
        f"map_ref: {payload['map_ref']}",
        f"source_of_truth_zones: {len(payload['source_of_truth_zones'])}",
        f"managed_artifact_zones: {len(payload['managed_artifact_zones'])}",
        f"runtime_residue_zones: {len(payload['runtime_residue_zones'])}",
        f"concrete_worlds: {len(payload['concrete_worlds'])}",
        "external_artifacts: source_map_required",
        "default_delete_policy: dry_run",
    ]
    if stored_path is not None:
        lines.append(f"stored_path: {stored_path}")
    for zone in payload["source_of_truth_zones"]:
        lines.append(f"source\t{zone['zone_id']}\t{zone['path_template']}")
    for zone in payload["managed_artifact_zones"]:
        lines.append(f"artifact\t{zone['zone_id']}\t{zone['path_template']}")
    return lines


def _source_of_truth_zones() -> List[Dict[str, Any]]:
    return [
        _zone(
            "workspace_registry",
            "control.sqlite",
            "source_of_truth",
            "WSA workspace registry, runtime sessions, scheduler metadata, and manager memory.",
            "preserve",
        ),
        _zone(
            "world_database",
            "worlds/{world_id}/world.sqlite",
            "source_of_truth",
            "Per-world canon/proposal facts, reports, tickets, temporal graph, context packets, and commit log.",
            "preserve",
        ),
        _zone(
            "startup_profile",
            "worlds/{world_id}/startup/",
            "source_of_truth",
            "Author startup answers, interview state, and profile decisions.",
            "preserve",
        ),
        _zone(
            "orchestrator_run_log",
            "worlds/{world_id}/orchestrator_runs/{run_id}/run.json",
            "source_log",
            "Durable orchestration state and callback-derived floor/actor state.",
            "preserve_or_archive",
        ),
        _zone(
            "session_log",
            "worlds/{world_id}/artifacts/session_logs/{YYYY-MM-DD}/{session_id}/",
            "source_log",
            "Date-scoped source log for optional human-facing exports.",
            "preserve_or_archive",
        ),
    ]


def _managed_artifact_zones() -> List[Dict[str, Any]]:
    return [
        _zone(
            "workspace_report_mailbox",
            "reports/{inbox|pending_review|approved|rejected|archived|telegram_queue}/",
            "managed_artifact",
            "Rendered review report artifacts and cleanup audits.",
            "mailbox_transition_or_archive",
        ),
        _zone(
            "world_artifacts",
            "worlds/{world_id}/artifacts/",
            "managed_artifact",
            "World-scoped artifacts, source logs, generated exports, and source maps.",
            "source_map_or_session_policy",
        ),
        _zone(
            "world_meetings",
            "worlds/{world_id}/meetings/",
            "managed_artifact",
            "Meeting transcripts and proposal-only working artifacts.",
            "archive_with_world",
        ),
        _zone(
            "world_scenes",
            "worlds/{world_id}/scenes/",
            "managed_artifact",
            "Scene work directories, temp artifacts, and scene prep records.",
            "archive_or_prune_completed_tmp",
        ),
        _zone(
            "hermes_reports_outbox",
            "hermes/reports_outbox/",
            "managed_artifact",
            "Runtime-delivery-ready reports that WSA still treats as local artifacts.",
            "archive_after_delivery_policy",
        ),
        _zone(
            "uninstall_plans",
            "manager/uninstall_plans/",
            "managed_artifact",
            "Dry-run uninstall plans written for operator review.",
            "preserve_until_operator_discards",
        ),
        _zone(
            "maintenance_plans",
            "manager/maintenance_plans/",
            "managed_artifact",
            "Storage hygiene scans and cleanup planning artifacts.",
            "preserve_until_operator_discards",
        ),
    ]


def _runtime_residue_zones() -> List[Dict[str, Any]]:
    return [
        _zone(
            "hermes_task_queue",
            "hermes/task_queue/",
            "runtime_residue",
            "Pending task packets; not safe to delete while active.",
            "block_update_when_nonempty",
        ),
        _zone(
            "hermes_task_archive",
            "hermes/task_archive/",
            "runtime_residue",
            "Completed task packets retained for audit or cleanup policy.",
            "archive_or_prune_by_plan",
        ),
        _zone(
            "hermes_callbacks",
            "hermes/callbacks/",
            "runtime_residue",
            "Pending callback JSON files awaiting ingestion.",
            "block_update_when_nonempty",
        ),
        _zone(
            "hermes_callback_archive",
            "hermes/callback_archive/",
            "runtime_residue",
            "Completed or discarded callback JSON files retained for audit.",
            "archive_or_prune_by_plan",
        ),
        _zone(
            "hermes_quarantine",
            "hermes/quarantine/",
            "runtime_residue",
            "Rejected callback metadata and validation errors.",
            "review_before_prune",
        ),
    ]


def _world_entry(world: WorldRecord) -> Dict[str, Any]:
    return {
        "world_id": world.world_id,
        "display_name": world.display_name,
        "world_root": f"worlds/{world.world_id}/",
        "source_of_truth": {
            "database": f"worlds/{world.world_id}/world.sqlite",
            "startup": f"worlds/{world.world_id}/startup/",
            "orchestrator_runs": f"worlds/{world.world_id}/orchestrator_runs/",
        },
        "managed_artifacts": [
            f"worlds/{world.world_id}/artifacts/",
            f"worlds/{world.world_id}/meetings/",
            f"worlds/{world.world_id}/scenes/",
            f"worlds/{world.world_id}/reports/",
            f"worlds/{world.world_id}/diagnostics/",
        ],
    }


def _zone(
    zone_id: str,
    path_template: str,
    zone_type: str,
    purpose: str,
    cleanup_policy: str,
) -> Dict[str, Any]:
    return {
        "zone_id": zone_id,
        "path_template": path_template,
        "zone_type": zone_type,
        "purpose": purpose,
        "cleanup_policy": cleanup_policy,
    }


def _safe_worlds(workspace: Path) -> List[WorldRecord]:
    try:
        return list_worlds(workspace)
    except Exception:
        return []
