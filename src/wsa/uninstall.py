from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from .artifact_diagnostics import diagnose_artifact_source_maps
from .artifact_map import build_artifact_architecture_map
from .paths import safe_child_path
from .workspace import init_workspace, list_worlds, utc_now


UNINSTALL_DRY_RUN_SCHEMA = "wsa.uninstall.dry_run_plan.v1"
UNINSTALL_DISCOVERY_SCHEMA = "wsa.uninstall.discovery_manifest.v1"
UNINSTALL_PLAN_ROOT = ("manager", "uninstall_plans")
WSA_NAME_MARKERS = ("wsa", "world-scene-actors")
RUNTIME_OWNED_MARKERS = ("skills", "skill", "memory", "memories")
SOURCE_CONFIDENCE = "high"
WORKSPACE_CONFIDENCE = "high"
NAME_CONFIDENCE = "medium"
RUNTIME_CONFIDENCE = "medium"
UNKNOWN_CONFIDENCE = "low"


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
            "after any future uninstall apply, run Hermes doctor or equivalent runtime diagnostics to detect stale shortcuts, overlays, callback routes, and runtime-owned WSA memory",
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


def build_uninstall_discovery_manifest(
    workspace: Path,
    scan_roots: List[Path],
    exclude_roots: List[Path] | None = None,
    max_depth: int = 4,
    max_candidates: int = 500,
) -> Dict[str, Any]:
    """Find WSA-adjacent paths outside the managed architecture without deleting them."""

    excludes = [_resolve_loose(path) for path in (exclude_roots or [])]
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for root in scan_roots:
        resolved_root = _resolve_loose(root)
        if _is_under_any(resolved_root, excludes):
            _append_candidate(
                candidates,
                seen,
                _candidate(
                    resolved_root,
                    resolved_root,
                    "excluded_root",
                    "preserve",
                    SOURCE_CONFIDENCE,
                    ["path_is_under_exclude_root"],
                    deletion_allowed=False,
                ),
                max_candidates,
            )
            continue
        if not resolved_root.exists():
            _append_candidate(
                candidates,
                seen,
                _candidate(
                    resolved_root,
                    resolved_root,
                    "missing_scan_root",
                    "ignore",
                    UNKNOWN_CONFIDENCE,
                    ["scan_root_missing"],
                    deletion_allowed=False,
                ),
                max_candidates,
            )
            continue
        _scan_path(
            resolved_root,
            resolved_root,
            excludes,
            max_depth=max(0, max_depth),
            max_candidates=max(1, max_candidates),
            candidates=candidates,
            seen=seen,
        )
        if len(candidates) >= max_candidates:
            break
    counts = _discovery_counts(candidates)
    return {
        "schema": UNINSTALL_DISCOVERY_SCHEMA,
        "created_at": utc_now(),
        "workspace_ref": ".",
        "side_effect_status": "read_only",
        "delete_performed": False,
        "archive_performed": False,
        "scan_policy": {
            "scan_roots": [str(_resolve_loose(path)) for path in scan_roots],
            "exclude_roots": [str(path) for path in excludes],
            "max_depth": max_depth,
            "max_candidates": max_candidates,
            "symlink_policy": "do_not_follow",
            "unknown_candidate_policy": "ask_user",
        },
        "counts": counts,
        "candidates": candidates,
        "requires_user_review": True,
        "deletion_manifest_ready": False,
        "recommended_next_step": [
            "review discovery candidates with the user",
            "move exact approved paths into an uninstall plan manifest",
            "keep backup_preserve and runtime_owned_review items out of automatic deletion",
            "run dry-run apply before any execute-capable delete command exists",
            "after any future uninstall apply, run Hermes doctor or equivalent runtime diagnostics to detect stale shortcuts, overlays, callback routes, and runtime-owned WSA memory",
        ],
    }


def write_uninstall_discovery_manifest(
    workspace: Path,
    scan_roots: List[Path],
    exclude_roots: List[Path] | None = None,
    max_depth: int = 4,
    max_candidates: int = 500,
) -> Dict[str, Any]:
    init_workspace(workspace)
    payload = build_uninstall_discovery_manifest(
        workspace,
        scan_roots,
        exclude_roots=exclude_roots,
        max_depth=max_depth,
        max_candidates=max_candidates,
    )
    root = safe_child_path(workspace, *UNINSTALL_PLAN_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    path = safe_child_path(
        root,
        f"uninstall-discovery-{_timestamp_for_filename(payload['created_at'])}.json",
    )
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload["side_effect_status"] = "workspace_mutating_manifest_written"
    payload["discovery_ref"] = _relative(workspace, path)
    return payload


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


def format_uninstall_discovery_manifest(payload: Dict[str, Any]) -> List[str]:
    counts = payload["counts"]
    lines = [
        "uninstall_discovery: read_only",
        f"side_effect_status: {payload['side_effect_status']}",
        f"delete_performed: {str(payload['delete_performed']).lower()}",
        f"scan_roots: {len(payload['scan_policy']['scan_roots'])}",
        f"exclude_roots: {len(payload['scan_policy']['exclude_roots'])}",
        f"candidates: {counts['total']}",
        f"ask_user_archive_or_delete: {counts['recommended_actions'].get('ask_user_archive_or_delete', 0)}",
        f"runtime_owned_review: {counts['classifications'].get('runtime_overlay', 0)}",
        f"backup_preserve: {counts['classifications'].get('backup_preserve', 0)}",
        f"unknown_candidate: {counts['classifications'].get('unknown_candidate', 0)}",
        f"deletion_manifest_ready: {str(payload['deletion_manifest_ready']).lower()}",
    ]
    if payload.get("discovery_ref"):
        lines.append(f"discovery_ref: {payload['discovery_ref']}")
    lines.append("candidates:")
    for item in payload["candidates"][:50]:
        evidence = ",".join(item["evidence"][:4])
        lines.append(
            "\t".join(
                [
                    item["classification"],
                    item["recommended_action"],
                    item["confidence"],
                    item["path"],
                    f"evidence={evidence}",
                ]
            )
        )
    if len(payload["candidates"]) > 50:
        lines.append(f"... {len(payload['candidates']) - 50} more candidates omitted")
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


def _scan_path(
    path: Path,
    scan_root: Path,
    excludes: List[Path],
    max_depth: int,
    max_candidates: int,
    candidates: List[Dict[str, Any]],
    seen: set[str],
) -> None:
    if len(candidates) >= max_candidates:
        return
    path = _resolve_loose(path)
    if _is_under_any(path, excludes):
        _append_candidate(
            candidates,
            seen,
            _candidate(
                path,
                scan_root,
                "excluded_root",
                "preserve",
                SOURCE_CONFIDENCE,
                ["path_is_under_exclude_root"],
                deletion_allowed=False,
            ),
            max_candidates,
        )
        return
    classified = _classify_path(path)
    if classified is not None:
        _append_candidate(
            candidates,
            seen,
            _candidate(path, scan_root, *classified),
            max_candidates,
        )
        if classified[0] in {"source_checkout", "wsa_workspace", "backup_preserve", "runtime_overlay"}:
            return
    if max_depth <= 0 or not path.is_dir() or path.is_symlink():
        return
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        _append_candidate(
            candidates,
            seen,
            _candidate(
                path,
                scan_root,
                "unknown_candidate",
                "ask_user",
                UNKNOWN_CONFIDENCE,
                ["scan_permission_or_io_error"],
                deletion_allowed=False,
            ),
            max_candidates,
        )
        return
    wsa_named_children = [
        child
        for child in children
        if _has_wsa_name_marker(child) and not _is_under_any(_resolve_loose(child), excludes)
    ]
    if len(wsa_named_children) >= 3:
        _append_candidate(
            candidates,
            seen,
            _candidate(
                path,
                scan_root,
                "external_artifact_collection",
                "ask_user_archive_or_delete",
                NAME_CONFIDENCE,
                [f"wsa_named_child_count:{len(wsa_named_children)}"],
                deletion_allowed=False,
            ),
            max_candidates,
        )
    for child in children:
        if len(candidates) >= max_candidates:
            return
        if child.is_symlink():
            if _has_wsa_name_marker(child):
                _append_candidate(
                    candidates,
                    seen,
                    _candidate(
                        child,
                        scan_root,
                        "unknown_candidate",
                        "ask_user",
                        UNKNOWN_CONFIDENCE,
                        ["symlink_not_followed", "name_contains_wsa_marker"],
                        deletion_allowed=False,
                    ),
                    max_candidates,
                )
            continue
        if child.is_file():
            classified_child = _classify_path(child)
            if classified_child is not None:
                _append_candidate(
                    candidates,
                    seen,
                    _candidate(child, scan_root, *classified_child),
                    max_candidates,
                )
            continue
        if child.is_dir():
            _scan_path(
                child,
                scan_root,
                excludes,
                max_depth=max_depth - 1,
                max_candidates=max_candidates,
                candidates=candidates,
                seen=seen,
            )


def _classify_path(path: Path) -> tuple[str, str, str, List[str], bool] | None:
    evidence: List[str] = []
    if _looks_like_wsa_source(path, evidence):
        return (
            "source_checkout",
            "ask_user_delete_or_preserve",
            SOURCE_CONFIDENCE,
            evidence,
            False,
        )
    evidence = []
    if _looks_like_wsa_workspace(path, evidence):
        return (
            "wsa_workspace",
            "ask_user_archive_or_delete",
            WORKSPACE_CONFIDENCE,
            evidence,
            False,
        )
    evidence = []
    if _looks_like_backup(path, evidence):
        return (
            "backup_preserve",
            "preserve",
            NAME_CONFIDENCE,
            evidence,
            False,
        )
    evidence = []
    if _looks_runtime_owned(path, evidence):
        return (
            "runtime_overlay",
            "runtime_owned_review",
            RUNTIME_CONFIDENCE,
            evidence,
            False,
        )
    evidence = []
    if _has_wsa_name_marker(path):
        evidence.append("name_contains_wsa_marker")
        return (
            "external_artifact",
            "ask_user_archive_or_delete",
            NAME_CONFIDENCE,
            evidence,
            False,
        )
    return None


def _looks_like_wsa_source(path: Path, evidence: List[str]) -> bool:
    if not path.is_dir():
        return False
    pyproject = path / "pyproject.toml"
    package = path / "src" / "wsa"
    matched = False
    if package.exists():
        evidence.append("contains_src_wsa_package")
        matched = True
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if "world-scene-actors" in text or "wsa.cli:main" in text:
            evidence.append("pyproject_declares_world_scene_actors")
            matched = True
    if (path / ".git").exists() and matched:
        evidence.append("contains_git_checkout")
    return matched


def _looks_like_wsa_workspace(path: Path, evidence: List[str]) -> bool:
    if not path.is_dir():
        return False
    control_db = path / "control.sqlite"
    worlds_root = path / "worlds"
    artifact_map = path / "manager" / "artifact_map" / "artifact_architecture_map.json"
    matched = False
    if control_db.exists():
        evidence.append("contains_control_sqlite")
        matched = True
    if worlds_root.exists() and any(
        (world / "world.sqlite").exists()
        for world in worlds_root.iterdir()
        if world.is_dir()
    ):
        evidence.append("contains_world_sqlite")
        matched = True
    if artifact_map.exists():
        evidence.append("contains_artifact_architecture_map")
        matched = True
    if (path / "hermes" / "adapter_config").exists():
        evidence.append("contains_hermes_adapter_config")
    return matched


def _looks_like_backup(path: Path, evidence: List[str]) -> bool:
    lowered = str(path).lower()
    if "backup" not in lowered and "backups" not in lowered:
        return False
    if _has_wsa_name_marker(path):
        evidence.append("backup_name_contains_wsa_marker")
        return True
    return False


def _looks_runtime_owned(path: Path, evidence: List[str]) -> bool:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    if not parts.intersection(RUNTIME_OWNED_MARKERS):
        return False
    if _has_wsa_name_marker(path):
        evidence.append("runtime_path_name_contains_wsa_marker")
        return True
    if path.is_file() and name.endswith((".md", ".json", ".txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:4096].lower()
        except OSError:
            text = ""
        if "wsa" in text or "world scene actors" in text:
            evidence.append("runtime_file_content_mentions_wsa")
            return True
    return False


def _candidate(
    path: Path,
    scan_root: Path,
    classification: str,
    recommended_action: str,
    confidence: str,
    evidence: List[str],
    deletion_allowed: bool,
) -> Dict[str, Any]:
    resolved = _resolve_loose(path)
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    return {
        "candidate_id": f"ucand_{digest}",
        "path": str(resolved),
        "relative_to_scan_root": _relative(scan_root, resolved),
        "classification": classification,
        "recommended_action": recommended_action,
        "confidence": confidence,
        "evidence": evidence,
        "deletion_allowed_without_explicit_manifest": deletion_allowed,
        "requires_user_review": recommended_action not in {"ignore"},
    }


def _append_candidate(
    candidates: List[Dict[str, Any]],
    seen: set[str],
    candidate: Dict[str, Any],
    max_candidates: int,
) -> None:
    if len(candidates) >= max_candidates:
        return
    key = candidate["path"]
    if key in seen:
        return
    seen.add(key)
    candidates.append(candidate)


def _discovery_counts(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    classifications: Dict[str, int] = {}
    actions: Dict[str, int] = {}
    for item in candidates:
        classifications[item["classification"]] = classifications.get(item["classification"], 0) + 1
        actions[item["recommended_action"]] = actions.get(item["recommended_action"], 0) + 1
    return {
        "total": len(candidates),
        "classifications": classifications,
        "recommended_actions": actions,
    }


def _has_wsa_name_marker(path: Path) -> bool:
    name = path.name.lower()
    return any(marker in name for marker in WSA_NAME_MARKERS)


def _is_under_any(path: Path, roots: List[Path]) -> bool:
    resolved = _resolve_loose(path)
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _resolve_loose(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()


def _entry(kind: str, path: str, reason: str) -> Dict[str, str]:
    return {"kind": kind, "path": path, "reason": reason}


def _timestamp_for_filename(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())[:14] or "unknown-time"


def _relative(workspace: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)
