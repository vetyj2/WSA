from __future__ import annotations

import json
from pathlib import Path

from .repositories import WorldRepository
from .review_cleanup import (
    archive_callback_residue,
    format_cleanup_audit,
    format_review_triage,
    reject_pending_review,
    triage_review_queue,
)
from .application.review_service import ReviewInboxService, format_review_inbox
from .update import UpdateLockError, assert_update_unlocked
from .workspace import get_world


def run_report_inbox(
    workspace: Path,
    world_id: str,
    output_format: str,
    language: str = "ko",
) -> int:
    try:
        world = get_world(workspace, world_id)
        payload = ReviewInboxService(workspace, world).inbox()
    except (KeyError, ValueError) as exc:
        print("검토함: 차단" if language == "ko" else "review_inbox: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        _print_json(payload)
    else:
        for line in format_review_inbox(payload, language=language):
            print(line)
    return 0


def run_report_show(
    workspace: Path,
    world_id: str,
    item_id: str,
    output_format: str,
) -> int:
    try:
        world = get_world(workspace, world_id)
        payload = ReviewInboxService(workspace, world).show(item_id)
    except (KeyError, ValueError) as exc:
        print("review_item: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        _print_json(payload)
    else:
        item = payload["item"]
        print(f"review_item: {item['item_id']}")
        print(f"kind: {item['kind']}")
        print(f"status: {item['status']}")
        print(f"execution_mode: {item['execution_mode']}")
        print(f"title: {item['title']}")
        print(f"allowed_actions: {', '.join(item['allowed_actions'])}")
        print(json.dumps(payload["details"], ensure_ascii=False, indent=2, sort_keys=True))
        print(f"side_effect_status: {payload['side_effect_status']}")
    return 0


def run_report_decide(
    workspace: Path,
    world_id: str,
    item_id: str,
    decision: str,
    option: str | None,
    note: str | None,
    output_format: str,
) -> int:
    if not _guard_update_unlocked(workspace, "report.decide"):
        return 1
    try:
        world = get_world(workspace, world_id)
        payload = ReviewInboxService(workspace, world).decide(
            item_id,
            decision,
            option=option,
            note=note,
        )
    except (KeyError, ValueError) as exc:
        print("review_decision: blocked")
        print("side_effect_status: no_world_mutation")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        _print_json(payload)
    else:
        print(f"review_decision: {payload['decision']}")
        print(f"item_id: {payload['item_id']}")
        print(f"kind: {payload['kind']}")
        print(f"status: {payload['status']}")
        if payload.get("candidate_ticket_id"):
            print(f"candidate_ticket_id: {payload['candidate_ticket_id']}")
        if payload.get("next_action"):
            print(f"next_action: {payload['next_action']}")
        print(f"side_effect_status: {payload['side_effect_status']}")
    return 0


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
