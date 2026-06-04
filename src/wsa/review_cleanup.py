from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .paths import safe_child_path
from .reports import ReportMailbox
from .repositories import ReportRecord, WorldRepository
from .workspace import WorldRecord, utc_now


REVIEW_TRIAGE_SCHEMA = "wsa.review.triage.v1"
REVIEW_CLEANUP_AUDIT_SCHEMA = "wsa.review.cleanup_audit.v1"

PENDING_REPORT_STATUSES = {"inbox", "pending_review"}
REVIEWABLE_RUN_STATUSES = {"awaiting_author_review"}


def triage_review_queue(workspace: Path, world: WorldRecord) -> Dict[str, Any]:
    repo = WorldRepository(world.world_id, world.path)
    reports = repo.list_reports()
    pending_reports = [
        _report_summary(report)
        for report in reports
        if report.status in PENDING_REPORT_STATUSES
    ]
    approved_reports = [
        _report_summary(report)
        for report in reports
        if report.status == "approved"
    ]
    runs = _list_orchestrator_runs(world)
    reviewable_runs = [
        _run_summary(run)
        for run in runs
        if str(run.get("status", "")) in REVIEWABLE_RUN_STATUSES
    ]
    callback_files = _list_callback_files(workspace)
    return {
        "schema": REVIEW_TRIAGE_SCHEMA,
        "created_at": utc_now(),
        "world_id": world.world_id,
        "side_effect_status": "read_only",
        "pending_report_statuses": sorted(PENDING_REPORT_STATUSES),
        "reviewable_run_statuses": sorted(REVIEWABLE_RUN_STATUSES),
        "counts": {
            "pending_reports": len(pending_reports),
            "reviewable_runs": len(reviewable_runs),
            "approved_reports_excluded": len(approved_reports),
            "callback_residue_files": len(callback_files),
        },
        "pending_reports": pending_reports,
        "reviewable_runs": reviewable_runs,
        "callback_residue": [
            _relative_to_workspace(workspace, path)
            for path in callback_files
        ],
        "excluded_from_cleanup": {
            "approved_reports": [item["report_id"] for item in approved_reports],
            "canon_facts": "not_touched",
            "tickets": "not_touched",
            "world_database_schema": "not_changed",
        },
        "recommended_actions": _recommended_actions(
            pending_reports=pending_reports,
            reviewable_runs=reviewable_runs,
            callback_files=callback_files,
        ),
    }


def reject_pending_review(
    workspace: Path,
    world: WorldRecord,
    reason: str,
    archive_callbacks: bool = False,
) -> Dict[str, Any]:
    started_at = utc_now()
    repo = WorldRepository(world.world_id, world.path)
    mailbox = ReportMailbox(workspace)
    reports_transitioned: List[Dict[str, Any]] = []
    for report in repo.list_reports():
        if report.status not in PENDING_REPORT_STATUSES:
            continue
        before = _report_summary(report)
        updated = mailbox.transition_report(repo, report.report_id, "rejected")
        reports_transitioned.append(
            {
                "report_id": report.report_id,
                "previous_status": before["status"],
                "new_status": updated.status,
                "previous_artifact_ref": before.get("artifact_ref"),
                "new_artifact_ref": updated.artifact_ref,
                "purpose": updated.purpose,
                "title": updated.title,
            }
        )

    runs_transitioned = _reject_reviewable_runs(world, reason)
    callback_archive = (
        archive_callback_residue(workspace, world, reason=reason, write_audit=False)
        if archive_callbacks
        else _empty_callback_archive_summary()
    )
    audit = {
        "schema": REVIEW_CLEANUP_AUDIT_SCHEMA,
        "created_at": started_at,
        "completed_at": utc_now(),
        "world_id": world.world_id,
        "operation": "reject_pending_review",
        "reason": reason,
        "side_effect_status": "workspace_mutating",
        "canon_write_performed": False,
        "fact_write_performed": False,
        "ticket_mutation_performed": False,
        "startup_profile_write_performed": False,
        "reports_transitioned": reports_transitioned,
        "orchestrator_runs_transitioned": runs_transitioned,
        "callback_archive": callback_archive,
        "excluded_from_cleanup": {
            "approved_reports": [
                report.report_id
                for report in repo.list_reports(status="approved")
            ],
            "canon_facts": "not_touched",
            "tickets": "not_touched",
            "world_database_schema": "not_changed",
        },
    }
    return _write_audit(workspace, audit)


def archive_callback_residue(
    workspace: Path,
    world: WorldRecord,
    reason: str,
    write_audit: bool = True,
) -> Dict[str, Any]:
    callback_files = _list_callback_files(workspace)
    if not callback_files:
        archive_summary = _empty_callback_archive_summary()
    else:
        archive_dir = _unique_callback_archive_dir(workspace)
        archive_dir.mkdir(parents=True, exist_ok=False)
        moved: List[Dict[str, str]] = []
        for source in callback_files:
            destination = safe_child_path(archive_dir, source.name)
            source.rename(destination)
            moved.append(
                {
                    "from": _relative_to_workspace(workspace, source),
                    "to": _relative_to_workspace(workspace, destination),
                }
            )
        archive_summary = {
            "performed": True,
            "archive_dir": _relative_to_workspace(workspace, archive_dir),
            "archived_count": len(moved),
            "moved_files": moved,
        }
    if not write_audit:
        return archive_summary
    audit = {
        "schema": REVIEW_CLEANUP_AUDIT_SCHEMA,
        "created_at": utc_now(),
        "completed_at": utc_now(),
        "world_id": world.world_id,
        "operation": "archive_callback_residue",
        "reason": reason,
        "side_effect_status": "workspace_mutating",
        "canon_write_performed": False,
        "fact_write_performed": False,
        "ticket_mutation_performed": False,
        "startup_profile_write_performed": False,
        "reports_transitioned": [],
        "orchestrator_runs_transitioned": [],
        "callback_archive": archive_summary,
        "excluded_from_cleanup": {
            "approved_reports": "not_touched",
            "canon_facts": "not_touched",
            "tickets": "not_touched",
            "world_database_schema": "not_changed",
        },
    }
    return _write_audit(workspace, audit)


def format_review_triage(payload: Dict[str, Any]) -> List[str]:
    counts = payload["counts"]
    lines = [
        "review_queue: triage",
        f"world_id: {payload['world_id']}",
        "side_effect_status: read_only",
        f"pending_reports: {counts['pending_reports']}",
        f"reviewable_runs: {counts['reviewable_runs']}",
        f"callback_residue_files: {counts['callback_residue_files']}",
        f"approved_reports_excluded: {counts['approved_reports_excluded']}",
    ]
    for report in payload["pending_reports"]:
        lines.append(
            "\t".join(
                [
                    "report",
                    report["report_id"],
                    report["status"],
                    report["purpose"],
                    report["title"],
                ]
            )
        )
    for run in payload["reviewable_runs"]:
        lines.append(
            "\t".join(
                [
                    "orchestrator_run",
                    run["run_id"],
                    run["status"],
                    run.get("workflow", ""),
                    run.get("topic", ""),
                ]
            )
        )
    if payload["recommended_actions"]:
        lines.append("recommended_actions:")
        lines.extend(f"\t{item}" for item in payload["recommended_actions"])
    return lines


def format_cleanup_audit(payload: Dict[str, Any]) -> List[str]:
    callback_archive = payload["callback_archive"]
    lines = [
        f"review_cleanup: {payload['operation']}",
        f"world_id: {payload['world_id']}",
        f"side_effect_status: {payload['side_effect_status']}",
        f"canon_write_performed: {str(payload['canon_write_performed']).lower()}",
        f"fact_write_performed: {str(payload['fact_write_performed']).lower()}",
        f"ticket_mutation_performed: {str(payload['ticket_mutation_performed']).lower()}",
        f"reports_transitioned: {len(payload['reports_transitioned'])}",
        f"orchestrator_runs_transitioned: {len(payload['orchestrator_runs_transitioned'])}",
        f"callbacks_archived: {callback_archive['archived_count']}",
    ]
    if callback_archive.get("archive_dir"):
        lines.append(f"callback_archive_dir: {callback_archive['archive_dir']}")
    if payload.get("audit_artifact_ref"):
        lines.append(f"audit_artifact_ref: {payload['audit_artifact_ref']}")
    return lines


def _report_summary(report: ReportRecord) -> Dict[str, Any]:
    return {
        "report_id": report.report_id,
        "status": report.status,
        "risk": report.risk,
        "purpose": report.purpose,
        "title": report.title,
        "artifact_ref": report.artifact_ref,
        "requires_author_decision": report.status in PENDING_REPORT_STATUSES,
        "canon_write_performed": bool(report.payload.get("canon_write_performed", False)),
    }


def _list_orchestrator_runs(world: WorldRecord) -> List[Dict[str, Any]]:
    runs_root = safe_child_path(world.path, "orchestrator_runs")
    if not runs_root.exists():
        return []
    runs: List[Dict[str, Any]] = []
    for path in sorted(runs_root.glob("*/run.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            payload = {
                "run_id": path.parent.name,
                "status": "unreadable",
                "error": str(exc),
            }
        payload["_run_json_path"] = str(path)
        runs.append(payload)
    return runs


def _run_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "run_id": str(run.get("run_id") or Path(str(run.get("_run_json_path", ""))).parent.name),
        "status": str(run.get("status", "unknown")),
        "workflow": str(run.get("workflow", "")),
        "topic": str(run.get("topic", "")),
        "execution_mode": str(run.get("execution_mode", run.get("subsession_execution_mode", ""))),
        "report_id": run.get("report_id"),
        "run_json_ref": run.get("_run_json_path"),
    }


def _reject_reviewable_runs(world: WorldRecord, reason: str) -> List[Dict[str, Any]]:
    transitioned: List[Dict[str, Any]] = []
    for run in _list_orchestrator_runs(world):
        if str(run.get("status", "")) not in REVIEWABLE_RUN_STATUSES:
            continue
        path = Path(str(run.get("_run_json_path", "")))
        previous_status = str(run.get("status", "unknown"))
        previous_close_reason = run.get("close_reason")
        run.pop("_run_json_path", None)
        run["status"] = "rejected"
        run["close_reason"] = "bulk_reject_pending_review"
        run["closed_at"] = utc_now()
        run["author_decision"] = {
            "decision": "reject",
            "reason": reason,
            "decided_at": utc_now(),
            "source": "wsa report reject-pending",
        }
        run["side_effect_status"] = "proposal_rejected_no_canon_mutation"
        path.write_text(
            json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        transitioned.append(
            {
                "run_id": str(run.get("run_id", path.parent.name)),
                "previous_status": previous_status,
                "new_status": "rejected",
                "previous_close_reason": previous_close_reason,
                "new_close_reason": run["close_reason"],
                "run_json_ref": str(path),
            }
        )
    return transitioned


def _list_callback_files(workspace: Path) -> List[Path]:
    callbacks_dir = safe_child_path(workspace, "hermes", "callbacks")
    if not callbacks_dir.exists():
        return []
    return [
        path
        for path in sorted(callbacks_dir.glob("*.json"))
        if path.is_file()
    ]


def _recommended_actions(
    pending_reports: List[Dict[str, Any]],
    reviewable_runs: List[Dict[str, Any]],
    callback_files: List[Path],
) -> List[str]:
    actions: List[str] = []
    if pending_reports or reviewable_runs:
        actions.append(
            "Run wsa report reject-pending WORLD_ID --reason ... after explicit author intent."
        )
    if callback_files:
        actions.append(
            "Run wsa report archive-callbacks WORLD_ID after confirming callbacks are residue."
        )
    if not actions:
        actions.append("No pending review cleanup needed.")
    return actions


def _empty_callback_archive_summary() -> Dict[str, Any]:
    return {
        "performed": False,
        "archive_dir": None,
        "archived_count": 0,
        "moved_files": [],
    }


def _write_audit(workspace: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    audit_path = safe_child_path(
        workspace,
        "reports",
        "archived",
        f"review-cleanup-{_compact_timestamp()}.json",
    )
    if audit_path.exists():
        audit_path = safe_child_path(
            workspace,
            "reports",
            "archived",
            f"review-cleanup-{_compact_timestamp()}-{len(list(audit_path.parent.glob('review-cleanup-*.json')))}.json",
        )
    payload["audit_artifact_ref"] = _relative_to_workspace(workspace, audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _unique_callback_archive_dir(workspace: Path) -> Path:
    prefix = f"{_compact_timestamp()}-residue"
    for index in range(1000):
        suffix = "" if index == 0 else f"-{index}"
        candidate = safe_child_path(
            workspace,
            "hermes",
            "callback_archive",
            f"{prefix}{suffix}",
        )
        if not candidate.exists():
            return candidate
    raise FileExistsError("could not allocate a callback archive directory")


def _compact_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _relative_to_workspace(workspace: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)
