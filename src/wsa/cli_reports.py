from __future__ import annotations

import json
from pathlib import Path

from .reports import ReportMailbox
from .repositories import WorldRepository
from .review_cleanup import (
    archive_callback_residue,
    format_cleanup_audit,
    format_review_triage,
    reject_pending_review,
    triage_review_queue,
)
from .update import UpdateLockError, assert_update_unlocked
from .workspace import get_world


def _guard_update_unlocked(workspace: Path, operation: str) -> bool:
    try:
        assert_update_unlocked(workspace, operation)
    except UpdateLockError as exc:
        print("update_lock: blocked")
        print(f"operation: {operation}")
        print(f"detail: {exc}")
        return False
    return True


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def run_report_list(workspace: Path, world_id: str, status: str | None) -> int:
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    reports = repo.list_reports(status=status)
    if not reports:
        print("reports: none")
        return 0
    for report in reports:
        print(
            "\t".join(
                [
                    report.report_id,
                    report.status,
                    report.risk,
                    report.purpose,
                    report.title,
                    report.artifact_ref or "",
                ]
            )
        )
    return 0


def run_report_triage(workspace: Path, world_id: str, output_format: str) -> int:
    world = get_world(workspace, world_id)
    payload = triage_review_queue(workspace, world)
    if output_format == "json":
        _print_json(payload)
    else:
        for line in format_review_triage(payload):
            print(line)
    return 0


def run_report_reject_pending(
    workspace: Path,
    world_id: str,
    reason: str,
    archive_callbacks: bool,
    output_format: str,
) -> int:
    if not _guard_update_unlocked(workspace, "report.reject_pending"):
        return 1
    world = get_world(workspace, world_id)
    payload = reject_pending_review(
        workspace,
        world,
        reason=reason,
        archive_callbacks=archive_callbacks,
    )
    if output_format == "json":
        _print_json(payload)
    else:
        for line in format_cleanup_audit(payload):
            print(line)
    return 0


def run_report_archive_callbacks(
    workspace: Path,
    world_id: str,
    reason: str,
    output_format: str,
) -> int:
    if not _guard_update_unlocked(workspace, "report.archive_callbacks"):
        return 1
    world = get_world(workspace, world_id)
    payload = archive_callback_residue(workspace, world, reason=reason)
    if output_format == "json":
        _print_json(payload)
    else:
        for line in format_cleanup_audit(payload):
            print(line)
    return 0
