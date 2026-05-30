from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from .reports import list_empty_mailbox_files, remove_empty_mailbox_files
from .repositories import WorldRepository
from .workspace import WorldRecord, list_worlds


@dataclass(frozen=True)
class DiagnosticFinding:
    world_id: str
    finding_type: str
    path: str | None
    detail: str


class WorldManager:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def worlds(self) -> List[WorldRecord]:
        return list_worlds(self.workspace)

    def run_diagnostics(self, fix: bool = False) -> List[DiagnosticFinding]:
        findings: List[DiagnosticFinding] = []
        empty_reports = list_empty_mailbox_files(self.workspace)
        if empty_reports:
            if fix:
                detail = (
                    f"removed {remove_empty_mailbox_files(self.workspace)} "
                    "empty report files"
                )
                finding_type = "empty_report_cleanup"
            else:
                detail = (
                    f"{len(empty_reports)} empty report files found; "
                    "rerun with --fix to remove"
                )
                finding_type = "empty_report_files"
            findings.append(
                DiagnosticFinding(
                    world_id="*",
                    finding_type=finding_type,
                    path=str(self.workspace / "reports"),
                    detail=detail,
                )
            )

        for world in self.worlds():
            repo = WorldRepository(world.world_id, world.path)
            pending = repo.list_tickets(status="proposed")
            if pending:
                finding = DiagnosticFinding(
                    world_id=world.world_id,
                    finding_type="pending_tickets",
                    path=str(world.path / "tickets"),
                    detail=f"{len(pending)} proposed tickets need policy action",
                )
                findings.append(finding)
                if fix:
                    repo.create_diagnostic_log(
                        "pending_tickets",
                        "open",
                        payload={
                            "count": len(pending),
                            "ticket_ids": [item.ticket_id for item in pending],
                        },
                    )

            for tmp_dir in (world.path / "scenes").glob("*/tmp"):
                if (
                    tmp_dir.is_dir()
                    and any(tmp_dir.iterdir())
                    and not (tmp_dir / ".wsa_completed").exists()
                ):
                    finding = DiagnosticFinding(
                        world_id=world.world_id,
                        finding_type="unfinished_scene_tmp",
                        path=str(tmp_dir),
                        detail="scene tmp contains unfinished artifacts",
                    )
                    findings.append(finding)
                    if fix:
                        repo.create_diagnostic_log(
                            "unfinished_scene_tmp",
                            "open",
                            payload={"path": str(tmp_dir)},
                        )
        return findings
