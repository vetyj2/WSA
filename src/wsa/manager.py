from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .artifact_map import (
    artifact_architecture_map_path,
    validate_artifact_architecture_map,
    write_artifact_architecture_map,
)
from .diagnostics import (
    ConflictFinding,
    persist_conflict_finding,
    run_world_detectors,
)
from .diagnostics_policy import load_diagnostics_policy
from .reports import list_empty_mailbox_files, remove_empty_mailbox_files
from .repositories import WorldRepository
from .workspace import WorldRecord, list_worlds


@dataclass(frozen=True)
class DiagnosticFinding:
    world_id: str
    finding_type: str
    path: str | None
    detail: str
    severity: str = "warning"
    correction_preview: Dict[str, Any] | None = None
    record_ids: tuple[str, ...] = ()
    why_it_matters: str = (
        "This finding can affect reliable world or workspace operation."
    )
    suggested_action: str = "Review the finding and choose an explicit follow-up."
    policy_source: str = "builtin:world_manager"
    fingerprint: str | None = None
    summary: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "world_id": self.world_id,
            "finding_type": self.finding_type,
            "severity": self.severity,
            "path": self.path,
            "detail": self.detail,
            "record_ids": list(self.record_ids),
            "why_it_matters": self.why_it_matters,
            "suggested_action": self.suggested_action,
            "policy_source": self.policy_source,
            "fingerprint": self.fingerprint,
            "summary": self.summary or self.detail,
        }
        if self.correction_preview is not None:
            payload["correction_preview"] = self.correction_preview
        return payload


class WorldManager:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def worlds(self) -> List[WorldRecord]:
        return list_worlds(self.workspace)

    def run_diagnostics(
        self,
        fix: bool = False,
        record_findings: bool = False,
        repair_safe_artifacts: bool = False,
    ) -> List[DiagnosticFinding]:
        if fix:
            record_findings = True
            repair_safe_artifacts = True

        findings: List[DiagnosticFinding] = []
        findings.extend(self._artifact_findings(repair_safe_artifacts))

        for world in self.worlds():
            policy_result = load_diagnostics_policy(world.path)
            if policy_result.issue is not None:
                issue = policy_result.issue
                findings.append(
                    DiagnosticFinding(
                        world_id=world.world_id,
                        finding_type=issue.code,
                        path=str(policy_result.path),
                        detail=issue.detail,
                        severity="warning",
                        why_it_matters=issue.why_it_matters,
                        suggested_action=issue.suggested_action,
                        policy_source=str(policy_result.path),
                        fingerprint=f"diagnostics-policy:{world.world_id}",
                        summary=f"invalid diagnostics policy for {world.world_id}",
                    )
                )
            repo = WorldRepository(world.world_id, world.path)
            for conflict in run_world_detectors(repo, policy=policy_result.policy):
                finding = DiagnosticFinding(
                    world_id=world.world_id,
                    finding_type=conflict.conflict_type,
                    path=str(world.path / "diagnostics"),
                    detail=conflict.detail,
                    severity=conflict.severity,
                    correction_preview=self._correction_preview(conflict),
                    record_ids=tuple(conflict.record_ids),
                    why_it_matters=conflict.why_it_matters,
                    suggested_action=conflict.suggested_action,
                    policy_source=conflict.policy_source,
                    fingerprint=conflict.fingerprint,
                    summary=conflict.summary,
                )
                findings.append(finding)
                if record_findings:
                    persist_conflict_finding(repo, conflict)

            findings.extend(
                self._dynamic_dimension_findings(world, repo, record_findings)
            )
            findings.extend(self._pending_ticket_findings(world, repo, record_findings))
            findings.extend(self._unfinished_scene_findings(world, repo, record_findings))
        return findings

    def _artifact_findings(
        self,
        repair_safe_artifacts: bool,
    ) -> List[DiagnosticFinding]:
        findings: List[DiagnosticFinding] = []
        artifact_map_findings = validate_artifact_architecture_map(self.workspace)
        if artifact_map_findings:
            path = artifact_architecture_map_path(self.workspace)
            if repair_safe_artifacts:
                written = write_artifact_architecture_map(self.workspace)
                findings.append(
                    DiagnosticFinding(
                        world_id="*",
                        finding_type="artifact_architecture_map_created",
                        path=str(written),
                        detail="created artifact architecture map",
                        severity="info",
                    )
                )
            else:
                findings.append(
                    DiagnosticFinding(
                        world_id="*",
                        finding_type="artifact_architecture_map_missing_or_invalid",
                        path=str(path),
                        detail="; ".join(artifact_map_findings),
                    )
                )

        empty_reports = list_empty_mailbox_files(self.workspace)
        if empty_reports:
            if repair_safe_artifacts:
                detail = (
                    f"removed {remove_empty_mailbox_files(self.workspace)} "
                    "empty report files"
                )
                finding_type = "empty_report_cleanup"
                severity = "info"
            else:
                detail = (
                    f"{len(empty_reports)} empty report files found; rerun with "
                    "--repair-safe-artifacts to remove"
                )
                finding_type = "empty_report_files"
                severity = "warning"
            findings.append(
                DiagnosticFinding(
                    world_id="*",
                    finding_type=finding_type,
                    path=str(self.workspace / "reports"),
                    detail=detail,
                    severity=severity,
                )
            )
        return findings

    def _dynamic_dimension_findings(
        self,
        world: WorldRecord,
        repo: WorldRepository,
        record_findings: bool,
    ) -> List[DiagnosticFinding]:
        findings: List[DiagnosticFinding] = []
        active_entities = repo.list_entities(status="active")
        if not active_entities:
            return findings
        active_entity_ids = {entity.entity_id for entity in active_entities}
        for dimension in repo.list_dimension_definitions():
            if dimension.status in {"rejected", "deprecated"}:
                continue
            if dimension.applies_to not in {"entity", "any", "*"}:
                continue
            spans = repo.query_entity_attribute_spans(
                dimension_key=dimension.dimension_key
            )
            covered = {
                span.entity_id
                for span in spans
                if span.status not in {"rejected", "deprecated"}
            }
            missing = sorted(active_entity_ids - covered)
            if not missing:
                continue
            detail = (
                f"{len(missing)} active entities lack dynamic dimension "
                f"{dimension.dimension_key}; scene filters may return gaps"
            )
            finding = DiagnosticFinding(
                world_id=world.world_id,
                finding_type="dynamic_dimension_missing_values",
                path=str(world.path / "diagnostics"),
                detail=detail,
                severity="warning",
                record_ids=tuple(missing),
            )
            findings.append(finding)
            if record_findings:
                repo.create_diagnostic_log(
                    finding.finding_type,
                    "open",
                    payload={
                        "severity": finding.severity,
                        "dimension_key": dimension.dimension_key,
                        "missing_entity_ids": missing[:32],
                        "missing_count": len(missing),
                        "recommended_action": (
                            "run Meetup or Patrol to propose sparse values before "
                            "Scene relies on this dimension"
                        ),
                    },
                )
        return findings

    def _pending_ticket_findings(
        self,
        world: WorldRecord,
        repo: WorldRepository,
        record_findings: bool,
    ) -> List[DiagnosticFinding]:
        pending = repo.list_tickets(status="proposed")
        if not pending:
            return []
        ticket_ids = [item.ticket_id for item in pending]
        finding = DiagnosticFinding(
            world_id=world.world_id,
            finding_type="pending_tickets",
            path=str(world.path / "tickets"),
            detail=f"{len(pending)} proposed tickets need policy action",
            severity="info",
            record_ids=tuple(ticket_ids),
        )
        if record_findings:
            repo.create_diagnostic_log(
                finding.finding_type,
                "open",
                payload={
                    "severity": finding.severity,
                    "count": len(pending),
                    "ticket_ids": ticket_ids,
                },
            )
        return [finding]

    def _unfinished_scene_findings(
        self,
        world: WorldRecord,
        repo: WorldRepository,
        record_findings: bool,
    ) -> List[DiagnosticFinding]:
        findings: List[DiagnosticFinding] = []
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
                    severity="warning",
                )
                findings.append(finding)
                if record_findings:
                    repo.create_diagnostic_log(
                        finding.finding_type,
                        "open",
                        payload={
                            "severity": finding.severity,
                            "path": str(tmp_dir),
                        },
                    )
        return findings

    @staticmethod
    def _correction_preview(
        conflict: ConflictFinding,
    ) -> Dict[str, Any] | None:
        if conflict.target_type != "fact":
            return None
        options: List[Dict[str, Any]] = []
        source_ref = f"diagnostic:{conflict.fingerprint}"
        for fact_id in conflict.record_ids:
            title = f"Reject conflicting fact {fact_id}"
            changes = [
                {
                    "change_type": "update_fact_status",
                    "target_type": "fact",
                    "target_id": fact_id,
                    "status": "rejected",
                }
            ]
            options.append(
                {
                    "title": title,
                    "changes": changes,
                    "change_set": {
                        "schema": "wsa.ticket.changes.v1",
                        "changes": changes,
                    },
                    "ticket_input": {
                        "title": title,
                        "risk": "medium",
                        "source_ref": source_ref,
                        "changes": changes,
                    },
                }
            )
        return {
            "schema": "wsa.diagnostic.correction_preview.v1",
            "mode": "proposal_only",
            "finding_fingerprint": conflict.fingerprint,
            "finding_summary": conflict.summary,
            "options": options,
            "side_effect_status": "read_only_preview_no_world_mutation",
        }
