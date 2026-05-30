from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .paths import safe_child_path
from .repositories import ReportRecord, WorldRepository


MAILBOX_STATES = {"inbox", "pending_review", "approved", "rejected", "archived", "telegram_queue"}


class InvalidReportStateError(ValueError):
    """Raised when a report state is outside the mailbox lifecycle."""


def validate_report_state(status: str) -> None:
    if status not in MAILBOX_STATES:
        raise InvalidReportStateError(f"invalid report state: {status}")


class ReportMailbox:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def ensure_mailbox(self) -> None:
        for status in MAILBOX_STATES:
            safe_child_path(self.workspace, "reports", status).mkdir(parents=True, exist_ok=True)

    def create_world_report(
        self,
        repo: WorldRepository,
        title: str,
        purpose: str,
        risk: str = "low",
        status: str = "inbox",
        payload: Optional[Dict[str, Any]] = None,
    ) -> ReportRecord:
        validate_report_state(status)
        self.ensure_mailbox()
        report = repo.create_report(
            title=title,
            purpose=purpose,
            risk=risk,
            status=status,
            payload=payload,
        )
        artifact_path = self.render_report(repo.world_id, report)
        repo.update_report_status(report.report_id, status, str(artifact_path))
        return repo.get_report(report.report_id)

    def render_report(self, world_id: str, report: ReportRecord) -> Path:
        validate_report_state(report.status)
        self.ensure_mailbox()
        path = safe_child_path(
            self.workspace,
            "reports",
            report.status,
            f"{report.report_id}.html",
        )
        path.write_text(self._html(world_id, report), encoding="utf-8")
        return path

    def transition_report(
        self,
        repo: WorldRepository,
        report_id: str,
        status: str,
    ) -> ReportRecord:
        validate_report_state(status)
        self.ensure_mailbox()
        report = repo.get_report(report_id)
        old_path = Path(report.artifact_ref) if report.artifact_ref else None
        updated = ReportRecord(
            report_id=report.report_id,
            purpose=report.purpose,
            title=report.title,
            risk=report.risk,
            status=status,
            payload=report.payload,
            artifact_ref=report.artifact_ref,
        )
        new_path = self.render_report(repo.world_id, updated)
        if (
            old_path
            and old_path.exists()
            and old_path != new_path
            and self._is_managed_report_path(old_path)
        ):
            old_path.unlink()
        repo.update_report_status(report_id, status, str(new_path))
        return repo.get_report(report_id)

    def _is_managed_report_path(self, path: Path) -> bool:
        reports_root = safe_child_path(self.workspace, "reports")
        try:
            resolved_path = path.resolve()
            resolved_root = reports_root.resolve()
            resolved_path.relative_to(resolved_root)
        except (OSError, ValueError):
            return False
        return resolved_path.suffix == ".html"

    def _html(self, world_id: str, report: ReportRecord) -> str:
        payload = html.escape(json.dumps(report.payload, ensure_ascii=False, indent=2, sort_keys=True))
        title = html.escape(report.title)
        return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 32px; color: #202124; }}
    main {{ max-width: 960px; margin: 0 auto; }}
    dl {{ display: grid; grid-template-columns: 160px 1fr; gap: 8px 16px; }}
    dt {{ font-weight: 700; }}
    pre {{ background: #f6f8fa; border: 1px solid #d0d7de; padding: 16px; overflow: auto; }}
  </style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <dl>
    <dt>report_id</dt><dd>{html.escape(report.report_id)}</dd>
    <dt>world_id</dt><dd>{html.escape(world_id)}</dd>
    <dt>purpose</dt><dd>{html.escape(report.purpose)}</dd>
    <dt>risk</dt><dd>{html.escape(report.risk)}</dd>
    <dt>status</dt><dd>{html.escape(report.status)}</dd>
  </dl>
  <h2>Payload</h2>
  <pre>{payload}</pre>
</main>
</body>
</html>
"""


def list_empty_mailbox_files(workspace: Path) -> List[Path]:
    reports_root = safe_child_path(workspace, "reports")
    if not reports_root.exists():
        return []
    return [
        path
        for path in sorted(reports_root.glob("*/*.html"))
        if path.is_file() and path.stat().st_size == 0
    ]


def remove_empty_mailbox_files(workspace: Path) -> int:
    removed = 0
    for path in list_empty_mailbox_files(workspace):
        path.unlink()
        removed += 1
    return removed
