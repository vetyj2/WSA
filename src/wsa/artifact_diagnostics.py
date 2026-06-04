from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .artifact_map import artifact_architecture_map_path, validate_artifact_architecture_map
from .paths import safe_child_path
from .reporting_contract import REPORTING_ARTIFACT_MANIFEST_SCHEMA
from .workspace import list_worlds, utc_now


ARTIFACT_SOURCE_MAP_DIAGNOSTIC_SCHEMA = "wsa.artifact.source_map_diagnostic.v1"
ARTIFACT_SOURCE_MAP_FILENAME = "artifact_source_map.json"
SOURCE_MAP_EXTERNAL_REQUIRED_FIELDS = {
    "artifact_id",
    "artifact_type",
    "originating_command_or_run_id",
    "absolute_or_runtime_path",
    "managed_by",
    "cleanup_hint",
    "safe_to_delete_with_session",
}


def diagnose_artifact_source_maps(workspace: Path) -> Dict[str, Any]:
    source_maps = sorted(workspace.glob(f"**/{ARTIFACT_SOURCE_MAP_FILENAME}"))
    findings: List[Dict[str, Any]] = []
    worlds = {world.world_id: world for world in list_worlds(workspace)}
    for path in source_maps:
        findings.extend(_validate_source_map(workspace, path, worlds))
    findings.extend(_find_orphan_exports(workspace, source_maps))
    map_issues = validate_artifact_architecture_map(workspace)
    for issue in map_issues:
        findings.append(
            _finding(
                "warn",
                "artifact_architecture_map_issue",
                issue,
                artifact_ref=_relative(workspace, artifact_architecture_map_path(workspace)),
            )
        )
    counts = {
        "source_maps": len(source_maps),
        "block": sum(1 for finding in findings if finding["severity"] == "block"),
        "warn": sum(1 for finding in findings if finding["severity"] == "warn"),
        "info": sum(1 for finding in findings if finding["severity"] == "info"),
        "orphan_exports": sum(1 for finding in findings if finding["code"] == "missing_source_map_for_export"),
    }
    status = "blocked" if counts["block"] else ("warn" if counts["warn"] else "pass")
    if not findings:
        findings.append(
            _finding(
                "info",
                "source_maps_valid",
                "artifact source maps are valid and no orphan exports were found",
            )
        )
        counts["info"] = 1
    return {
        "schema": ARTIFACT_SOURCE_MAP_DIAGNOSTIC_SCHEMA,
        "created_at": utc_now(),
        "workspace_ref": ".",
        "status": status,
        "side_effect_status": "read_only",
        "counts": counts,
        "findings": findings,
        "recommended_actions": _recommended_actions(findings),
    }


def format_artifact_source_map_diagnostic(payload: Dict[str, Any]) -> List[str]:
    lines = [
        f"artifact_source_maps: {payload['status']}",
        "side_effect_status: read_only",
        f"source_maps: {payload['counts']['source_maps']}",
        f"orphan_exports: {payload['counts']['orphan_exports']}",
        f"warnings: {payload['counts']['warn']}",
        f"blocks: {payload['counts']['block']}",
    ]
    for finding in payload["findings"]:
        fields = [finding["severity"], finding["code"], finding["message"]]
        if finding.get("artifact_ref"):
            fields.append(f"artifact_ref={finding['artifact_ref']}")
        if finding.get("source_map_ref"):
            fields.append(f"source_map_ref={finding['source_map_ref']}")
        lines.append("\t".join(fields))
    if payload.get("recommended_actions"):
        lines.append("recommended_actions:")
        lines.extend(f"\t{item}" for item in payload["recommended_actions"])
    return lines


def _validate_source_map(
    workspace: Path,
    path: Path,
    worlds: Dict[str, Any],
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            _finding(
                "block",
                "invalid_source_map_json",
                f"source map is invalid JSON: {exc}",
                source_map_ref=_relative(workspace, path),
            )
        ]
    if payload.get("schema") != REPORTING_ARTIFACT_MANIFEST_SCHEMA:
        findings.append(
            _finding(
                "block",
                "invalid_source_map_schema",
                "source map has unexpected schema",
                source_map_ref=_relative(workspace, path),
            )
        )
    world = worlds.get(str(payload.get("world_id", "")))
    for field in ("world_id", "session_log_ref", "exports"):
        if field not in payload:
            findings.append(
                _finding(
                    "block",
                    "source_map_missing_field",
                    f"source map missing required field: {field}",
                    source_map_ref=_relative(workspace, path),
                )
            )
    exports = payload.get("exports", [])
    if not isinstance(exports, list):
        findings.append(
            _finding(
                "block",
                "source_map_exports_not_list",
                "source map exports field must be a list",
                source_map_ref=_relative(workspace, path),
            )
        )
        exports = []
    for item in exports:
        if not isinstance(item, dict):
            findings.append(
                _finding(
                    "block",
                    "source_map_export_not_object",
                    "source map export entry must be an object",
                    source_map_ref=_relative(workspace, path),
                )
            )
            continue
        for field in ("artifact_type", "path", "managed_by", "cleanup_hint", "safe_to_delete_with_session"):
            if field not in item:
                findings.append(
                    _finding(
                        "warn",
                        "source_map_export_missing_field",
                        f"source map export missing field: {field}",
                        source_map_ref=_relative(workspace, path),
                    )
                )
        if world is not None and item.get("path"):
            artifact_path = safe_child_path(world.path, str(item["path"]))
            if not artifact_path.exists():
                findings.append(
                    _finding(
                        "warn",
                        "mapped_export_missing",
                        "source map points to an export file that does not exist",
                        artifact_ref=str(item["path"]),
                        source_map_ref=_relative(workspace, path),
                    )
                )
    external_artifacts = payload.get("external_artifacts", [])
    if isinstance(external_artifacts, list):
        for item in external_artifacts:
            if not isinstance(item, dict):
                findings.append(
                    _finding(
                        "block",
                        "external_artifact_not_object",
                        "external artifact entry must be an object",
                        source_map_ref=_relative(workspace, path),
                    )
                )
                continue
            missing = sorted(SOURCE_MAP_EXTERNAL_REQUIRED_FIELDS - set(item.keys()))
            if missing:
                findings.append(
                    _finding(
                        "warn",
                        "external_artifact_missing_fields",
                        f"external artifact missing fields: {', '.join(missing)}",
                        source_map_ref=_relative(workspace, path),
                    )
                )
    return findings


def _find_orphan_exports(workspace: Path, source_maps: List[Path]) -> List[Dict[str, Any]]:
    source_map_dirs = {path.parent for path in source_maps}
    findings: List[Dict[str, Any]] = []
    for path in sorted(workspace.glob("worlds/*/artifacts/session_logs/**/exports/*")):
        if not path.is_file() or path.name == ARTIFACT_SOURCE_MAP_FILENAME:
            continue
        if path.suffix.lower() not in {".txt", ".html"}:
            continue
        if path.parent not in source_map_dirs:
            findings.append(
                _finding(
                    "warn",
                    "missing_source_map_for_export",
                    "export file has no artifact_source_map.json in its export directory",
                    artifact_ref=_relative(workspace, path),
                )
            )
    return findings


def _recommended_actions(findings: List[Dict[str, Any]]) -> List[str]:
    actions: List[str] = []
    if any(finding["code"] == "missing_source_map_for_export" for finding in findings):
        actions.append("regenerate or write a source map for orphan export files before uninstall or migration")
    if any(finding["severity"] == "block" for finding in findings):
        actions.append("fix invalid source-map JSON/schema before trusting cleanup diagnostics")
    if any(finding["code"] == "mapped_export_missing" for finding in findings):
        actions.append("remove stale manifest entries or restore the missing export artifact")
    return actions


def _finding(
    severity: str,
    code: str,
    message: str,
    artifact_ref: str | None = None,
    source_map_ref: str | None = None,
) -> Dict[str, Any]:
    payload = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if artifact_ref:
        payload["artifact_ref"] = artifact_ref
    if source_map_ref:
        payload["source_map_ref"] = source_map_ref
    return payload


def _relative(workspace: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)
