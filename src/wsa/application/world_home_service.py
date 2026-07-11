from __future__ import annotations

from pathlib import Path
from typing import Any

from ..diagnostics import run_world_detectors
from ..repositories import WorldRepository
from ..run_store import RunStore
from ..startup import StartupProfileManager
from ..workspace import WorldRecord


ACTIVE_RUN_STATUSES = {
    "requested",
    "planned",
    "awaiting_prep_review",
    "awaiting_callback",
    "awaiting_author_review",
    "interrupted",
}
PENDING_REPORT_STATUSES = {"inbox", "pending_review"}
PENDING_TICKET_STATUSES = {"proposed", "approved"}


class WorldHomeService:
    def __init__(self, workspace: Path, world: WorldRecord) -> None:
        self.workspace = workspace.resolve()
        self.world = world
        self.repo = WorldRepository(world.world_id, world.path)

    def snapshot(self) -> dict[str, Any]:
        startup = StartupProfileManager(self.world).summary()
        tickets = [
            ticket
            for ticket in self.repo.list_tickets()
            if ticket.status in PENDING_TICKET_STATUSES
        ]
        runs = [
            record
            for record in RunStore(self.workspace).list(self.world.world_id)
            if record.status in ACTIVE_RUN_STATUSES
        ]
        active_run_ids = {record.run_id for record in runs}
        reports = [
            report
            for report in self.repo.list_reports()
            if report.status in PENDING_REPORT_STATUSES
            and not (
                report.purpose == "orchestrator_run"
                and report.payload.get("run_id") in active_run_ids
            )
        ]
        hard_conflicts = [
            finding
            for finding in run_world_detectors(self.repo)
            if finding.severity == "error"
        ]
        entities = self.repo.list_entities()
        facts = self.repo.list_facts()
        applied = [
            ticket for ticket in self.repo.list_tickets(status="applied")
        ]
        frame_ready = bool(
            startup.get("minimum_frame_ready", startup.get("startup_ready", False))
        )
        next_reason = self._next_reason(
            frame_ready=frame_ready,
            pending_reviews=len(reports) + len(tickets),
            active_runs=len(runs),
            hard_conflicts=len(hard_conflicts),
            world_items=len(entities) + len(facts),
        )
        return {
            "schema": "wsa.world.home.v1",
            "world": {
                "world_id": self.world.world_id,
                "display_name": self.world.display_name,
                "status": self.world.status,
            },
            "startup": {
                "minimum_frame_ready": frame_ready,
                "startup_ready": bool(startup.get("startup_ready", False)),
                "interview_progress_percent": startup.get(
                    "interview_progress_percent",
                    0,
                ),
                "unresolved_count": len(startup.get("unresolved", [])),
            },
            "counts": {
                "entities": len(entities),
                "facts": len(facts),
                "pending_reports": len(reports),
                "pending_tickets": len(tickets),
                "active_runs": len(runs),
                "hard_conflicts": len(hard_conflicts),
            },
            "pending": {
                "reports": [
                    {
                        "report_id": item.report_id,
                        "status": item.status,
                        "purpose": item.purpose,
                        "title": item.title,
                    }
                    for item in reports
                ],
                "tickets": [
                    {
                        "ticket_id": item.ticket_id,
                        "status": item.status,
                        "ticket_type": item.ticket_type,
                        "title": item.title,
                    }
                    for item in tickets
                ],
                "runs": [
                    {
                        "run_id": item.run_id,
                        "status": item.status,
                        "workflow": item.workflow,
                        "runner_type": item.runner_type,
                    }
                    for item in runs
                ],
            },
            "recent_application": (
                {
                    "ticket_id": applied[-1].ticket_id,
                    "title": applied[-1].title,
                }
                if applied
                else None
            ),
            "next_action": {
                "action": "continue_world_workflow",
                "reason": next_reason,
                "argv": [
                    "wsa",
                    "--workspace",
                    str(self.workspace),
                    "world",
                    "continue",
                    self.world.world_id,
                ],
                "side_effect": "read_only_until_explicit_follow_up",
            },
            "side_effect_status": "read_only_no_world_mutation",
        }

    @staticmethod
    def _next_reason(
        *,
        frame_ready: bool,
        pending_reviews: int,
        active_runs: int,
        hard_conflicts: int,
        world_items: int,
    ) -> str:
        if hard_conflicts:
            return "review_blocking_conflicts"
        if pending_reviews:
            return "review_pending_items"
        if active_runs:
            return "continue_or_review_active_run"
        if not frame_ready:
            return "complete_minimum_startup_frame"
        if not world_items:
            return "create_first_world_item"
        return "inspect_or_extend_world"


def format_world_home(payload: dict[str, Any], language: str = "ko") -> list[str]:
    world = payload["world"]
    counts = payload["counts"]
    startup = payload["startup"]
    next_action = payload["next_action"]
    if language == "en":
        labels = {
            "home": "world_home",
            "ready": "minimum_frame_ready",
            "progress": "startup_progress",
            "pending": "pending_review_items",
            "runs": "active_runs",
            "conflicts": "hard_conflicts",
            "next": "next_action",
            "side": "side_effect_status",
        }
    else:
        labels = {
            "home": "월드_홈",
            "ready": "최소_제작_프레임_준비",
            "progress": "스타트업_진행률",
            "pending": "검토_대기",
            "runs": "진행중_실행",
            "conflicts": "중요_충돌",
            "next": "다음_행동",
            "side": "변경_상태",
        }
    return [
        f"{labels['home']}: {world['display_name']} ({world['world_id']})",
        f"{labels['ready']}: {'yes' if startup['minimum_frame_ready'] else 'no'}",
        f"{labels['progress']}: {startup['interview_progress_percent']}%",
        f"{labels['pending']}: {counts['pending_reports'] + counts['pending_tickets']}",
        f"{labels['runs']}: {counts['active_runs']}",
        f"{labels['conflicts']}: {counts['hard_conflicts']}",
        f"{labels['next']}: {' '.join(next_action['argv'])}",
        f"{labels['side']}: {payload['side_effect_status']}",
    ]
