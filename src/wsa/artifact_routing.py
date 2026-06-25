from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .workspace import utc_now


ARTIFACT_ROUTING_POLICY_SCHEMA = "wsa.artifact.routing_policy.v1"
ARTIFACT_ROUTING_RECOMMENDATION_SCHEMA = "wsa.artifact.routing_recommendation.v1"


def build_artifact_routing_policy() -> Dict[str, Any]:
    return {
        "schema": ARTIFACT_ROUTING_POLICY_SCHEMA,
        "purpose": (
            "Route WSA-related artifacts into bounded workspace locations before they are "
            "created, and require source-map metadata when a runtime must write outside "
            "the managed architecture."
        ),
        "default_policy": {
            "prefer_managed_workspace_roots": True,
            "external_paths_allowed_only_when_runtime_or_user_requires": True,
            "unknown_artifact_type": "route_as_custom_wsa_artifact_not_error",
            "external_runtime_namespace": "prefer_wsa_marker_in_directory_or_filename",
            "source_map_filename": "artifact_source_map.json",
            "do_not_create_files": True,
            "do_not_execute_cleanup": True,
        },
        "external_runtime_naming_policy": {
            "goal": "make WSA byproducts inside Hermes/runtime storage easy to find without deleting unrelated Hermes data",
            "preferred_directory_markers": ["wsa", "wsa-artifacts", "wsa-runtime"],
            "preferred_file_prefixes": ["wsa-", "wsa_"],
            "warning_when_external_path_lacks_wsa_marker": True,
            "source_map_still_required": True,
            "runtime_owned_cleanup": "Hermes doctor or equivalent runtime diagnostics should review these paths",
        },
        "classifications": [
            "source_of_truth",
            "source_log",
            "managed_artifact",
            "runtime_residue",
            "external_artifact",
            "runtime_owned",
        ],
        "artifact_families": [_route_public_entry(route) for route in _ROUTES.values()],
    }


def build_artifact_route_recommendation(
    workspace: Path,
    artifact_type: str,
    *,
    world_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    filename: str | None = None,
    date: str | None = None,
    external_path: str | None = None,
) -> Dict[str, Any]:
    del workspace
    now = utc_now()
    date_value = _safe_token(date or now[:10], default="YYYY-MM-DD")
    requested_type = artifact_type.strip() if artifact_type else "custom_wsa_artifact"
    canonical_type = _ALIASES.get(_normalize_type(requested_type), _normalize_type(requested_type))
    route = _ROUTES.get(canonical_type, _custom_route(canonical_type))
    values = {
        "world_id": _safe_token(world_id, default="{world_id}") if world_id else "{world_id}",
        "session_id": _safe_token(session_id, default="{session_id}") if session_id else "{session_id}",
        "run_id": _safe_token(run_id, default="{run_id}") if run_id else "{run_id}",
        "YYYY-MM-DD": date_value,
        "filename": _safe_filename(filename or route["default_filename"]),
    }
    relative_path_template = route["path_template"]
    workspace_relative_path = relative_path_template.format(**values)
    source_map_template = route.get("source_map_template") or (
        "worlds/{world_id}/artifacts/session_logs/{YYYY-MM-DD}/{session_id}/artifact_source_map.json"
    )
    source_map_ref = source_map_template.format(**values)
    unresolved = _unresolved_placeholders(workspace_relative_path)
    warnings = _warnings(route, world_id=world_id, session_id=session_id, run_id=run_id)
    namespace_target = external_path or workspace_relative_path
    wsa_namespace_recommended = route["classification"] in {"external_artifact", "runtime_owned"}
    wsa_namespace_detected = _has_wsa_marker(namespace_target)
    if external_path:
        warnings.append("external_path_supplied: write source-map entry before delivery or cleanup")
        if not _has_wsa_marker(external_path):
            warnings.append(
                "external_path_lacks_wsa_marker: prefer a wsa/ directory or wsa-* filename inside Hermes/runtime storage"
            )
    if route["route_kind"] == "external_runtime":
        warnings.append("external artifact is runtime-owned unless source-mapped into WSA session log")
        if not wsa_namespace_detected:
            warnings.append("external runtime artifact should include a visible wsa namespace marker")
    if route["route_kind"] == "runtime_owned":
        warnings.append("WSA should not delete Hermes runtime memory, skills, or provider-owned files")
        if not wsa_namespace_detected:
            warnings.append("runtime-owned references should use a visible wsa namespace marker when Hermes allows it")
    return {
        "schema": ARTIFACT_ROUTING_RECOMMENDATION_SCHEMA,
        "created_at": now,
        "side_effect_status": "read_only",
        "file_created": False,
        "delete_performed": False,
        "requested_artifact_type": requested_type,
        "artifact_type": route["artifact_type"],
        "classification": route["classification"],
        "route_kind": route["route_kind"],
        "managed_by": route["managed_by"],
        "preferred_path_template": relative_path_template,
        "workspace_relative_path": workspace_relative_path,
        "source_map_required": route["source_map_required"],
        "source_map_ref": source_map_ref if route["source_map_required"] else None,
        "safe_to_delete_with_session": route["safe_to_delete_with_session"],
        "cleanup_hint": route["cleanup_hint"],
        "retention_hint": route["retention_hint"],
        "external_path": external_path,
        "wsa_namespace_recommended": wsa_namespace_recommended,
        "wsa_namespace_detected": wsa_namespace_detected,
        "unresolved_placeholders": unresolved,
        "warnings": warnings,
        "runtime_boundary": {
            "wsa_creates_runtime_file": False,
            "hermes_runtime_may_create_file": True,
            "actual_delivery_owner": "user_hermes_runtime",
            "actual_cleanup_owner": route["managed_by"],
        },
    }


def format_artifact_route_recommendation(payload: Dict[str, Any]) -> List[str]:
    lines = [
        f"artifact_route: {payload['artifact_type']}",
        f"classification: {payload['classification']}",
        f"route_kind: {payload['route_kind']}",
        f"managed_by: {payload['managed_by']}",
        f"side_effect_status: {payload['side_effect_status']}",
        f"file_created: {str(payload['file_created']).lower()}",
        f"delete_performed: {str(payload['delete_performed']).lower()}",
        f"workspace_relative_path: {payload['workspace_relative_path']}",
        f"source_map_required: {str(payload['source_map_required']).lower()}",
        f"wsa_namespace_recommended: {str(payload['wsa_namespace_recommended']).lower()}",
        f"wsa_namespace_detected: {str(payload['wsa_namespace_detected']).lower()}",
    ]
    if payload.get("source_map_ref"):
        lines.append(f"source_map_ref: {payload['source_map_ref']}")
    lines.append(f"cleanup_hint: {payload['cleanup_hint']}")
    lines.append(f"retention_hint: {payload['retention_hint']}")
    if payload.get("unresolved_placeholders"):
        lines.append("unresolved_placeholders:")
        lines.extend(f"\t{item}" for item in payload["unresolved_placeholders"])
    if payload.get("warnings"):
        lines.append("warnings:")
        lines.extend(f"\t{item}" for item in payload["warnings"])
    return lines


def _route_public_entry(route: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "artifact_type",
        "aliases",
        "classification",
        "route_kind",
        "managed_by",
        "path_template",
        "source_map_required",
        "safe_to_delete_with_session",
        "cleanup_hint",
        "retention_hint",
    )
    return {key: route[key] for key in keys if key in route}


def _route(
    artifact_type: str,
    path_template: str,
    classification: str,
    route_kind: str,
    managed_by: str,
    cleanup_hint: str,
    retention_hint: str,
    *,
    aliases: List[str] | None = None,
    default_filename: str = "{artifact_type}.txt",
    source_map_required: bool = False,
    safe_to_delete_with_session: bool = False,
    source_map_template: str | None = None,
    requires_world_id: bool = False,
    requires_session_id: bool = False,
    requires_run_id: bool = False,
) -> Dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "aliases": aliases or [],
        "path_template": path_template,
        "classification": classification,
        "route_kind": route_kind,
        "managed_by": managed_by,
        "cleanup_hint": cleanup_hint,
        "retention_hint": retention_hint,
        "default_filename": default_filename.replace("{artifact_type}", artifact_type),
        "source_map_required": source_map_required,
        "safe_to_delete_with_session": safe_to_delete_with_session,
        "source_map_template": source_map_template,
        "requires_world_id": requires_world_id,
        "requires_session_id": requires_session_id,
        "requires_run_id": requires_run_id,
    }


_ROUTES: Dict[str, Dict[str, Any]] = {
    "session_log": _route(
        "session_log",
        "worlds/{world_id}/artifacts/session_logs/{YYYY-MM-DD}/{session_id}/",
        "source_log",
        "workspace_managed",
        "wsa_workspace",
        "archive or delete the session directory according to user runtime policy",
        "source log; retain until author exports, migrates, or intentionally discards",
        aliases=["session", "meeting_log", "scene_log"],
        source_map_required=False,
        safe_to_delete_with_session=True,
        requires_world_id=True,
        requires_session_id=True,
    ),
    "human_session_minutes": _route(
        "human_session_minutes",
        "worlds/{world_id}/artifacts/session_logs/{YYYY-MM-DD}/{session_id}/exports/{filename}",
        "managed_artifact",
        "workspace_managed",
        "wsa_workspace",
        "derivable export; delete with session log when runtime policy allows",
        "export on demand; do not store every format by default",
        aliases=["minutes", "meeting_minutes", "session_minutes"],
        default_filename="human_session_minutes.txt",
        source_map_required=True,
        safe_to_delete_with_session=True,
        requires_world_id=True,
        requires_session_id=True,
    ),
    "draft_output": _route(
        "draft_output",
        "worlds/{world_id}/artifacts/session_logs/{YYYY-MM-DD}/{session_id}/exports/{filename}",
        "managed_artifact",
        "workspace_managed",
        "wsa_workspace",
        "proposal draft; archive/delete with session after author decision",
        "not canon; retain only while useful for review",
        aliases=["draft", "scene_draft", "manuscript_draft"],
        default_filename="draft_output.txt",
        source_map_required=True,
        safe_to_delete_with_session=True,
        requires_world_id=True,
        requires_session_id=True,
    ),
    "round_orchestration_report": _route(
        "round_orchestration_report",
        "worlds/{world_id}/artifacts/session_logs/{YYYY-MM-DD}/{session_id}/exports/{filename}",
        "managed_artifact",
        "workspace_managed",
        "wsa_workspace",
        "debug/operator export; prune after approval or after source log is archived",
        "checkpoint report; keep compact and derivable from run/session state",
        aliases=["round_report", "orchestration_report"],
        default_filename="round_orchestration_report.txt",
        source_map_required=True,
        safe_to_delete_with_session=True,
        requires_world_id=True,
        requires_session_id=True,
    ),
    "meeting_artifact": _route(
        "meeting_artifact",
        "worlds/{world_id}/meetings/{YYYY-MM-DD}/{session_id}/{filename}",
        "managed_artifact",
        "workspace_managed",
        "wsa_workspace",
        "proposal-only meeting artifact; archive with world or session",
        "working artifact; keep out of canon DB until approval",
        aliases=["meetup_artifact", "meetup"],
        default_filename="meeting_artifact.json",
        source_map_required=True,
        safe_to_delete_with_session=True,
        requires_world_id=True,
        requires_session_id=True,
    ),
    "scene_artifact": _route(
        "scene_artifact",
        "worlds/{world_id}/scenes/{YYYY-MM-DD}/{session_id}/{filename}",
        "managed_artifact",
        "workspace_managed",
        "wsa_workspace",
        "scene prep/temp artifact; archive accepted outputs and prune completed tmp by plan",
        "scene work directory; separate from world DB facts",
        aliases=["scene", "scene_prep", "scene_output"],
        default_filename="scene_artifact.json",
        source_map_required=True,
        safe_to_delete_with_session=True,
        requires_world_id=True,
        requires_session_id=True,
    ),
    "orchestrator_run": _route(
        "orchestrator_run",
        "worlds/{world_id}/orchestrator_runs/{run_id}/run.json",
        "source_log",
        "workspace_managed",
        "wsa_workspace",
        "durable audit state; archive rather than delete unless user discards the run",
        "source log for bridge, meetup, scene, and callback-derived state",
        aliases=["run_log", "orun"],
        default_filename="run.json",
        source_map_required=False,
        safe_to_delete_with_session=False,
        requires_world_id=True,
        requires_run_id=True,
    ),
    "hermes_task": _route(
        "hermes_task",
        "hermes/task_queue/{filename}",
        "runtime_residue",
        "workspace_managed_runtime_residue",
        "wsa_workspace_and_user_hermes_runtime",
        "do not delete while pending; archive after callback ingestion or rejection",
        "short-lived runtime packet",
        aliases=["task_packet", "subagent_task"],
        default_filename="task.json",
        source_map_required=False,
        safe_to_delete_with_session=False,
    ),
    "hermes_callback": _route(
        "hermes_callback",
        "hermes/callbacks/{filename}",
        "runtime_residue",
        "workspace_managed_runtime_residue",
        "wsa_workspace_and_user_hermes_runtime",
        "ingest, reject, or archive; pending callbacks may block update/backup",
        "short-lived callback packet",
        aliases=["callback", "callback_packet"],
        default_filename="callback.json",
        source_map_required=False,
        safe_to_delete_with_session=False,
    ),
    "runtime_delivery": _route(
        "runtime_delivery",
        "hermes/reports_outbox/{filename}",
        "managed_artifact",
        "workspace_managed_runtime_delivery",
        "user_hermes_runtime",
        "archive after delivery according to Hermes profile",
        "delivery-ready artifact; WSA does not send chat messages",
        aliases=["delivery", "chat_delivery", "telegram_report"],
        default_filename="runtime_delivery.txt",
        source_map_required=True,
        safe_to_delete_with_session=True,
    ),
    "maintenance_plan": _route(
        "maintenance_plan",
        "manager/maintenance_plans/{filename}",
        "managed_artifact",
        "workspace_managed",
        "wsa_workspace",
        "operator review artifact; preserve until user discards",
        "planning artifact, not executable cleanup",
        aliases=["storage_scan", "cleanup_plan"],
        default_filename="maintenance-plan.json",
        source_map_required=False,
        safe_to_delete_with_session=False,
    ),
    "uninstall_plan": _route(
        "uninstall_plan",
        "manager/uninstall_plans/{filename}",
        "managed_artifact",
        "workspace_managed",
        "wsa_workspace",
        "operator review artifact; preserve until uninstall decision is complete",
        "planning artifact, not executable delete",
        aliases=["uninstall_discovery", "delete_report"],
        default_filename="uninstall-plan.json",
        source_map_required=False,
        safe_to_delete_with_session=False,
    ),
    "external_runtime_artifact": _route(
        "external_runtime_artifact",
        "external:{filename}",
        "external_artifact",
        "external_runtime_path",
        "user_hermes_runtime",
        "write artifact_source_map entry; report to user before uninstall/migration",
        "external only when runtime/user explicitly needs the location",
        aliases=["external", "external_artifact", "media_attachment"],
        default_filename="wsa-external-runtime-artifact",
        source_map_required=True,
        safe_to_delete_with_session=False,
    ),
    "runtime_owned_memory_or_skill": _route(
        "runtime_owned_memory_or_skill",
        "runtime-owned:{filename}",
        "runtime_owned",
        "runtime_owned",
        "user_hermes_runtime",
        "WSA reports references only; Hermes doctor/user approval owns cleanup",
        "outside WSA workspace ownership",
        aliases=["runtime_memory", "runtime_skill", "hermes_skill", "hermes_memory"],
        default_filename="wsa-runtime-owned-reference",
        source_map_required=False,
        safe_to_delete_with_session=False,
    ),
}


def _custom_route(artifact_type: str) -> Dict[str, Any]:
    return _route(
        "custom_wsa_artifact",
        "worlds/{world_id}/artifacts/misc/{YYYY-MM-DD}/{session_id}/{filename}",
        "managed_artifact",
        "workspace_managed_custom",
        "wsa_workspace",
        "custom artifact; keep source-mapped and prune only by session/user policy",
        "custom user/Hermes artifact; do not promote to official command surface by default",
        aliases=[],
        default_filename=f"{artifact_type or 'custom_wsa_artifact'}.txt",
        source_map_required=True,
        safe_to_delete_with_session=True,
        requires_world_id=True,
        requires_session_id=True,
    )


def _warnings(
    route: Dict[str, Any],
    *,
    world_id: str | None,
    session_id: str | None,
    run_id: str | None,
) -> List[str]:
    warnings: List[str] = []
    if route["requires_world_id"] and not world_id:
        warnings.append("world_id missing: keep placeholder or resolve active world before writing")
    if route["requires_session_id"] and not session_id:
        warnings.append("session_id missing: create or reuse a date-scoped session id before writing")
    if route["requires_run_id"] and not run_id:
        warnings.append("run_id missing: route should be tied to an orchestrator run before writing")
    return warnings


def _unresolved_placeholders(value: str) -> List[str]:
    return sorted(set(re.findall(r"\{[^{}]+\}", value)))


def _normalize_type(value: str) -> str:
    lowered = value.strip().lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "", lowered) or "custom_wsa_artifact"


def _safe_token(value: str, *, default: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", value.strip())
    return cleaned.strip("._") or default


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", name)
    return cleaned.strip("._") or "artifact"


def _has_wsa_marker(value: str) -> bool:
    lowered = value.lower()
    parts = re.split(r"[/\\:_ .-]+", lowered)
    return "wsa" in parts or lowered.startswith("wsa-") or lowered.startswith("wsa_") or "/wsa" in lowered


_ALIASES: Dict[str, str] = {}
for _canonical, _route_payload in _ROUTES.items():
    _ALIASES[_normalize_type(_canonical)] = _canonical
    for _alias in _route_payload.get("aliases", []):
        _ALIASES[_normalize_type(_alias)] = _canonical
