from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..autonomous_orchestrator import AutonomousOrchestrator
from ..autonomous_orchestrator import OrchestratorDecisionResult
from ..autonomous_orchestrator import normalize_execution_payload
from ..meeting import MeetingOrchestrator
from ..orchestrator_bridge import OrchestratorBridge
from ..reports import ReportMailbox
from ..repositories import WorldRepository
from ..review_cleanup import triage_review_queue
from ..run_store import RunStore
from ..tickets import apply_ticket, review_ticket
from ..workflow_engine import WorkflowEngine
from ..workspace import utc_now
from ..workspace import WorldRecord


class ReviewInboxService:
    def __init__(self, workspace: Path, world: WorldRecord) -> None:
        self.workspace = workspace.resolve()
        self.world = world
        self.repo = WorldRepository(world.world_id, world.path)

    def inbox(self) -> dict[str, Any]:
        triage = triage_review_queue(self.workspace, self.world)
        run_records = [
            record
            for record in RunStore(self.workspace).list(self.world.world_id)
            if record.status in {"awaiting_prep_review", "awaiting_author_review", "interrupted"}
        ]
        active_run_ids = {record.run_id for record in run_records}
        reports = [
            self._report_item(report)
            for report in self.repo.list_reports()
            if report.status in {"inbox", "pending_review"}
            and not (
                report.purpose == "orchestrator_run"
                and report.payload.get("run_id") in active_run_ids
            )
        ]
        tickets = [
            self._ticket_item(ticket)
            for ticket in self.repo.list_tickets()
            if ticket.status in {"proposed", "approved"}
        ]
        runs = [
            self._run_item(record.payload, record.runner_type)
            for record in run_records
        ]
        callbacks = [
            {
                "item_id": item.get("callback_id") or item["path"],
                "kind": "callback_residue",
                "status": "pending_ingest_or_archive",
                "title": item["path"],
                "risk": "medium",
                "source": item["path"],
                "execution_mode": "external_waiting",
                "summary": "World-scoped callback file awaiting an explicit action.",
                "allowed_actions": ["inspect", "archive"],
            }
            for item in triage.get("callback_residue_details", [])
        ]
        items = reports + runs + tickets + callbacks
        return {
            "schema": "wsa.review.inbox.v1",
            "world": {
                "world_id": self.world.world_id,
                "display_name": self.world.display_name,
            },
            "count": len(items),
            "items": items,
            "unscoped_callbacks": triage.get(
                "unscoped_callback_residue",
                {"count": 0, "items": []},
            ),
            "side_effect_status": "read_only_no_state_transition",
        }

    def show(self, item_id: str) -> dict[str, Any]:
        value = item_id.strip()
        if not value:
            raise ValueError("review item ID is required")
        if value.startswith("report_"):
            report = self.repo.get_report(value)
            return {
                "schema": "wsa.review.item.v1",
                "item": self._report_item(report),
                "details": asdict(report),
                "side_effect_status": "read_only_no_state_transition",
            }
        if value.startswith("ticket_"):
            ticket = self.repo.get_ticket(value)
            changes = [asdict(item) for item in self.repo.list_ticket_changes(value)]
            return {
                "schema": "wsa.review.item.v1",
                "item": self._ticket_item(ticket),
                "details": {**asdict(ticket), "changes": changes},
                "side_effect_status": "read_only_no_state_transition",
            }
        if value.startswith("orun_"):
            record = RunStore(self.workspace).get(value)
            normalized = normalize_execution_payload(record.payload)
            return {
                "schema": "wsa.review.item.v1",
                "item": self._run_item(normalized, record.runner_type),
                "details": {
                    "run_id": record.run_id,
                    "status": record.status,
                    "workflow": record.workflow,
                    "execution_mode": normalized.get("execution_mode"),
                    "execution_summary": normalized.get("execution_summary"),
                    "topic": normalized.get("topic"),
                    "synthesis": normalized.get("synthesis"),
                    "draft_options": normalized.get("draft_options", []),
                    "conflict_gap_diagnosis": normalized.get("conflict_gap_diagnosis"),
                    "next_action": normalized.get("next_action"),
                },
                "side_effect_status": "read_only_no_state_transition",
            }
        raise KeyError(f"review item not found or unsupported: {value}")

    def decide(
        self,
        item_id: str,
        decision: str,
        *,
        option: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        value = item_id.strip()
        action = decision.strip().casefold().replace("-", "_")
        if value.startswith("ticket_"):
            return self._decide_ticket(value, action, note)
        if value.startswith("orun_"):
            return self._decide_run(value, action, option, note)
        if value.startswith("report_"):
            return self._decide_report(value, action, option, note)
        raise KeyError(f"review item not found or unsupported: {value}")

    def _decide_ticket(
        self,
        ticket_id: str,
        action: str,
        note: str | None,
    ) -> dict[str, Any]:
        ticket = self.repo.get_ticket(ticket_id)
        if action == "approve":
            result = review_ticket(self.repo, ticket_id)
            return _decision_payload(
                ticket_id,
                "ticket",
                action,
                result.status,
                result.side_effect_status,
            )
        if action == "apply":
            result = apply_ticket(self.repo, ticket_id)
            return {
                **_decision_payload(
                    ticket_id,
                    "ticket",
                    action,
                    result.status,
                    result.side_effect_status,
                ),
                "applied_ids": result.applied_ids,
            }
        if action == "reject":
            if ticket.status == "applied":
                raise ValueError("applied ticket cannot be rejected; create a correction ticket")
            self.repo.update_ticket_status(ticket_id, "rejected")
            self.repo.append_commit(
                "ticket_rejected",
                "ticket",
                ticket_id,
                payload={"note": note, "previous_status": ticket.status},
            )
            return _decision_payload(
                ticket_id,
                "ticket",
                action,
                "rejected",
                "ticket_state_changed_no_world_mutation",
            )
        if action in {"hold", "revise"}:
            self.repo.append_commit(
                f"ticket_{action}_requested",
                "ticket",
                ticket_id,
                payload={"note": note, "status": ticket.status},
            )
            return _decision_payload(
                ticket_id,
                "ticket",
                action,
                ticket.status,
                "audit_note_recorded_no_world_mutation",
            )
        raise ValueError(f"unsupported ticket review decision: {action}")

    def _decide_run(
        self,
        run_id: str,
        action: str,
        option: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        record = RunStore(self.workspace).get(run_id)
        if record.world_id != self.world.world_id:
            raise ValueError("run belongs to a different world")
        if record.status == "awaiting_prep_review":
            if action == "approve":
                result = OrchestratorBridge(self.workspace).approve_prep(run_id)
                return _decision_payload(
                    run_id,
                    "orchestrator_run",
                    "approve_prep",
                    str(result["status"]),
                    "prep_approved_no_world_mutation",
                    next_action=result.get("next_action"),
                )
            if action in {"hold", "refine", "restart"}:
                return self._record_prep_decision(record, action, note)
            raise ValueError("prep review supports approve, hold, refine, or restart")
        if action == "resume":
            result = AutonomousOrchestrator.resume(self.workspace, run_id)
            return _decision_payload(
                run_id,
                "orchestrator_run",
                action,
                str(result["status"]),
                "run_resumed_no_world_mutation",
                next_action=result.get("next_action"),
            )
        if action not in {"approve", "retry", "hold"}:
            raise ValueError("run review supports approve, retry, or hold")
        decision_result: OrchestratorDecisionResult = AutonomousOrchestrator.decide(
            self.workspace,
            run_id,
            action,
            option=option,
            note=note,
        )
        payload = _decision_payload(
            run_id,
            "orchestrator_run",
            action,
            decision_result.report_status,
            "proposal_decision_recorded_no_world_mutation",
        )
        if decision_result.ticket is not None:
            payload["candidate_ticket_id"] = decision_result.ticket.ticket_id
        return payload

    def _record_prep_decision(
        self,
        record: Any,
        action: str,
        note: str | None,
    ) -> dict[str, Any]:
        payload = dict(record.payload)
        payload["prep_decision"] = {
            "decision": action,
            "note": note,
            "decided_at": utc_now(),
        }
        if action == "hold":
            payload["status"] = "interrupted"
            payload["execution_status"] = "prep_review_held"
            payload["next_action"] = "resume"
        elif action == "refine":
            payload["status"] = "awaiting_prep_review"
            payload["execution_status"] = "prep_refinement_requested"
            payload["next_action"] = "refine_prep_request"
        else:
            payload["status"] = "closed"
            payload["execution_status"] = "prep_restart_requested"
            payload["next_action"] = "start_new_run_with_revised_frame"
        updated = WorkflowEngine(self.workspace).update(
            payload,
            expected_revision=record.revision,
        )
        return _decision_payload(
            record.run_id,
            "orchestrator_run",
            action,
            updated.status,
            "prep_decision_recorded_no_world_mutation",
            next_action=updated.payload.get("next_action"),
        )

    def _decide_report(
        self,
        report_id: str,
        action: str,
        option: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        report = self.repo.get_report(report_id)
        if report.purpose == "meeting":
            if action not in {"approve", "retry", "hold"}:
                raise ValueError("meeting report supports approve, retry, or hold")
            result = MeetingOrchestrator(self.workspace, self.world).decide_report(
                report_id,
                action,
                note=note,
            )
            payload = _decision_payload(
                report_id,
                "report",
                action,
                result.report_status,
                "proposal_decision_recorded_no_world_mutation",
            )
            if result.ticket is not None:
                payload["candidate_ticket_id"] = result.ticket.ticket_id
            return payload
        if report.purpose == "orchestrator_run" and report.payload.get("run_id"):
            return self._decide_run(str(report.payload["run_id"]), action, option, note)
        status = {
            "approve": "approved",
            "hold": "pending_review",
            "reject": "rejected",
        }.get(action)
        if status is None:
            raise ValueError("generic report supports approve, hold, or reject")
        transitioned = ReportMailbox(self.workspace).transition_report(
            self.repo,
            report_id,
            status,
        )
        return _decision_payload(
            report_id,
            "report",
            action,
            transitioned.status,
            "report_state_changed_no_world_mutation",
        )

    def _report_item(self, report: Any) -> dict[str, Any]:
        payload = report.payload if isinstance(report.payload, dict) else {}
        mode = str(
            payload.get("execution_mode")
            or payload.get("execution_provenance", {}).get("execution_mode")
            or "not_applicable"
        )
        return {
            "item_id": report.report_id,
            "kind": "report",
            "status": report.status,
            "title": report.title,
            "risk": report.risk,
            "source": report.artifact_ref or payload.get("source_ref"),
            "execution_mode": mode,
            "summary": _summary(payload, report.title),
            "allowed_actions": _report_actions(report.purpose),
        }

    def _ticket_item(self, ticket: Any) -> dict[str, Any]:
        changes = self.repo.list_ticket_changes(ticket.ticket_id)
        candidate = ticket.ticket_type in {"meeting_candidate", "orchestrator_candidate"}
        actions = ["inspect", "revise", "reject"]
        if changes and ticket.status == "proposed":
            actions.insert(1, "approve")
        if ticket.status == "approved":
            actions.insert(1, "apply")
        return {
            "item_id": ticket.ticket_id,
            "kind": "candidate" if candidate else "ticket",
            "status": ticket.status,
            "title": ticket.title,
            "risk": ticket.risk,
            "source": ticket.payload.get("source_ref"),
            "execution_mode": ticket.payload.get("execution_mode", "not_applicable"),
            "summary": f"{len(changes)} concrete change(s)",
            "change_count": len(changes),
            "allowed_actions": actions,
        }

    @staticmethod
    def _run_item(payload: dict[str, Any], runner_type: str) -> dict[str, Any]:
        normalized = normalize_execution_payload(payload)
        status = str(normalized.get("status", "unknown"))
        actions = ["inspect"]
        if status == "awaiting_prep_review":
            actions.extend(["approve_prep", "refine", "hold", "restart"])
        elif status == "awaiting_author_review":
            actions.extend(["approve", "retry", "hold"])
        elif status == "interrupted":
            actions.append("resume")
        return {
            "item_id": str(normalized.get("run_id")),
            "kind": "orchestrator_run",
            "status": status,
            "title": str(normalized.get("topic") or normalized.get("workflow") or "Run"),
            "risk": str(normalized.get("risk", "medium")),
            "source": normalized.get("report_id"),
            "execution_mode": normalized.get("execution_mode"),
            "runner_type": runner_type,
            "summary": normalized.get("execution_summary", {}).get("statement"),
            "allowed_actions": actions,
        }


def format_review_inbox(payload: dict[str, Any], language: str = "ko") -> list[str]:
    world = payload["world"]
    if language == "en":
        lines = [
            f"review_inbox: {world['display_name']} ({world['world_id']})",
            f"pending_items: {payload['count']}",
        ]
    else:
        lines = [
            f"검토함: {world['display_name']} ({world['world_id']})",
            f"대기_항목: {payload['count']}",
        ]
    for item in payload["items"]:
        lines.append(
            "\t".join(
                [
                    item["kind"],
                    item["item_id"],
                    item["status"],
                    item["execution_mode"],
                    item["title"],
                    ",".join(item["allowed_actions"]),
                ]
            )
        )
    if payload.get("unscoped_callbacks", {}).get("count"):
        label = "unscoped_callbacks" if language == "en" else "범위불명_콜백"
        lines.append(f"{label}: {payload['unscoped_callbacks']['count']}")
    lines.append(
        "side_effect_status: read_only_no_state_transition"
        if language == "en"
        else "변경_상태: 읽기_전용"
    )
    return lines


def _summary(payload: dict[str, Any], fallback: str) -> str:
    synthesis = payload.get("synthesis")
    if isinstance(synthesis, dict) and synthesis.get("summary"):
        return str(synthesis["summary"])
    for key in ("summary", "description", "question", "topic"):
        if payload.get(key):
            return str(payload[key])
    return fallback


def _report_actions(purpose: str) -> list[str]:
    if purpose == "meeting":
        return ["inspect", "approve", "retry", "hold"]
    if purpose == "orchestrator_run":
        return ["inspect", "approve", "retry", "hold"]
    return ["inspect", "approve", "hold", "reject"]


def _decision_payload(
    item_id: str,
    kind: str,
    decision: str,
    status: str,
    side_effect_status: str,
    *,
    next_action: Any = None,
) -> dict[str, Any]:
    return {
        "schema": "wsa.review.decision.v1",
        "item_id": item_id,
        "kind": kind,
        "decision": decision,
        "status": status,
        "next_action": next_action,
        "side_effect_status": side_effect_status,
    }
