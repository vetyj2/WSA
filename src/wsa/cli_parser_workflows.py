from __future__ import annotations

import argparse
from pathlib import Path

from .orchestrator_contract import (
    DEFAULT_CONTEXT_POLICY,
    DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
    DEFAULT_MAX_QUEUE_TURNS,
    DEFAULT_MAX_SUBSESSION_CALLS,
    DEFAULT_TERMINATION_POLICY,
)
from .report_exports import (
    REPORT_EXPORT_ARTIFACT_TYPES,
)


from typing import Any


def _add_change_draft_arguments(parser: Any, *, revision: bool = False) -> None:
    parser.add_argument(
        "--world",
        dest="world_selector",
        help="World ID or unique display name; omitted when exactly one world exists.",
    )
    parser.add_argument("--title", help="Ticket title shown in the review inbox.")
    parser.add_argument(
        "--add-entity",
        action="append",
        default=[],
        metavar="TYPE|NAME",
        help="Add an entity. Repeat for more entities.",
    )
    parser.add_argument(
        "--add-fact",
        action="append",
        default=[],
        metavar="SUBJECT|PREDICATE|VALUE",
        help="Add a fact using an entity ID, unique name, or @object reference.",
    )
    parser.add_argument(
        "--add-edge",
        action="append",
        default=[],
        metavar="SUBJECT|RELATION|OBJECT",
        help="Add a relationship using entity IDs or unique names.",
    )
    parser.add_argument(
        "--add-timeline",
        action="append",
        default=[],
        metavar="LABEL|SORT_KEY",
        help="Add a timeline point.",
    )
    if not revision:
        parser.add_argument(
            "--accept-candidate",
            help="Compile explicitly structured changes from a candidate ticket.",
        )
    parser.add_argument(
        "--skip-index",
        action="append",
        type=int,
        default=[],
        help="Omit a numbered candidate or source-ticket change. Repeatable.",
    )
    parser.add_argument(
        "--risk",
        choices=("low", "medium", "high"),
        help="Review risk label.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Request compact ticket presentation.",
    )
    parser.add_argument(
        "--write-ticket",
        action="store_true",
        help="Write the proposed ticket after printing the validated preview.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )

def add_workflow_parsers(subparsers: Any) -> None:
    manager_parser = subparsers.add_parser("manager", help="Run world manager utilities.")
    manager_subparsers = manager_parser.add_subparsers(dest="manager_command")
    manager_diagnose = manager_subparsers.add_parser("diagnose", help="Run local diagnostics.")
    manager_diagnose.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Compatibility option: record findings and repair safe artifacts. "
            "Prefer the explicit flags."
        ),
    )
    manager_diagnose.add_argument(
        "--record-findings",
        action="store_true",
        help="Persist deduplicated findings without changing world canon.",
    )
    manager_diagnose.add_argument(
        "--repair-safe-artifacts",
        action="store_true",
        help="Repair the generated artifact map and remove empty mailbox files.",
    )
    manager_diagnose.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )

    meeting_parser = subparsers.add_parser(
        "meeting",
        help="Run non-mutating representative meetings.",
    )
    meeting_subparsers = meeting_parser.add_subparsers(dest="meeting_command")
    meeting_run = meeting_subparsers.add_parser(
        "run",
        help="Create a meeting transcript and report without changing canon.",
    )
    meeting_run.add_argument("world_id", help="World ID.")
    meeting_run.add_argument("--topic", required=True, help="Meeting topic.")
    meeting_run.add_argument(
        "--question",
        default="Identify gaps, risks, and useful proposals.",
        help="Question for representatives to discuss.",
    )
    meeting_run.add_argument(
        "--participant",
        action="append",
        default=[],
        help="Character, group, faction, or viewpoint to represent. Can be repeated.",
    )
    meeting_decide = meeting_subparsers.add_parser(
        "decide",
        help="Approve, retry, or hold a meeting report.",
    )
    meeting_decide.add_argument("world_id", help="World ID.")
    meeting_decide.add_argument("report_id", help="Meeting report ID.")
    meeting_decide.add_argument(
        "--decision",
        required=True,
        choices=("approve", "retry", "hold"),
        help="Decision for the meeting report.",
    )
    meeting_decide.add_argument("--note", help="Optional decision note.")

    orchestrator_parser = subparsers.add_parser(
        "orchestrator",
        help="Run manual-trigger autonomous orchestration workflows.",
    )
    orchestrator_subparsers = orchestrator_parser.add_subparsers(dest="orchestrator_command")
    orchestrator_run = orchestrator_subparsers.add_parser(
        "run",
        help="Run an autonomous-until-boundary orchestrator workflow.",
    )
    orchestrator_run.add_argument("world_id", help="World ID.")
    orchestrator_run.add_argument(
        "--workflow",
        default="meetup",
        help="Workflow type, such as meetup or subsession.",
    )
    orchestrator_run.add_argument(
        "--skill",
        help="Hermes skill shortcut scope, such as meetup or scene_start. Defaults to workflow.",
    )
    orchestrator_run.add_argument("--topic", required=True, help="Orchestration topic.")
    orchestrator_run.add_argument(
        "--question",
        default="Synthesize proposals, conflicts, gaps, and approval options.",
        help="Question the orchestrator should resolve.",
    )
    orchestrator_run.add_argument(
        "--mode",
        default="deterministic_mock",
        help=(
            "Execution mode. deterministic_mock performs no external agent calls; "
            "use hermes-bridge to wait for external callbacks."
        ),
    )
    orchestrator_run.add_argument("--rounds", type=int, default=2, help="Internal round budget.")
    orchestrator_run.add_argument(
        "--max-queue-turns",
        type=int,
        default=DEFAULT_MAX_QUEUE_TURNS,
        help=f"Maximum autonomous queue turns before stopping. Default: {DEFAULT_MAX_QUEUE_TURNS}.",
    )
    orchestrator_run.add_argument(
        "--max-concurrent-subsessions",
        type=int,
        default=DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
        help=(
            "Maximum subsessions Hermes should run at the same time. "
            f"Default: {DEFAULT_MAX_CONCURRENT_SUBSESSIONS}."
        ),
    )
    orchestrator_run.add_argument(
        "--max-subsession-calls",
        type=int,
        default=DEFAULT_MAX_SUBSESSION_CALLS,
        help=(
            "Maximum total subsession calls before returning a partial package. "
            f"Default: {DEFAULT_MAX_SUBSESSION_CALLS}."
        ),
    )
    orchestrator_run.add_argument(
        "--context-policy",
        default=DEFAULT_CONTEXT_POLICY,
        help=f"Context carry-forward policy. Default: {DEFAULT_CONTEXT_POLICY}.",
    )
    orchestrator_run.add_argument(
        "--frame-plan",
        help="User-defined plan/frame for this run. A conservative default is used when omitted.",
    )
    orchestrator_run.add_argument(
        "--termination-policy",
        default=DEFAULT_TERMINATION_POLICY,
        help=f"Termination policy label. Default: {DEFAULT_TERMINATION_POLICY}.",
    )
    orchestrator_run.add_argument(
        "--participant",
        action="append",
        default=[],
        help="Participant/viewpoint. Can be repeated.",
    )
    orchestrator_run.add_argument(
        "--subsession-policy",
        default="ephemeral",
        help="Subsession lifecycle policy. Default: ephemeral.",
    )
    orchestrator_run.add_argument(
        "--canon-policy",
        default="proposal-only",
        help="Canon policy. Default: proposal-only.",
    )
    orchestrator_run.add_argument(
        "--approval",
        default="required",
        help="Approval boundary. Default: required.",
    )
    orchestrator_run.add_argument(
        "--close-on",
        default="complete",
        help="When temporary subsessions should close. Default: complete.",
    )
    orchestrator_run.add_argument(
        "--no-prep-review",
        action="store_true",
        help="Opt out of the default prep review hook before first Hermes actor call.",
    )
    orchestrator_status = orchestrator_subparsers.add_parser(
        "status",
        help="Show orchestrator run status.",
    )
    orchestrator_status.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_status.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    orchestrator_status.add_argument(
        "--expand-contracts",
        "--verbose-contract",
        action="store_true",
        help="Return full durable run state instead of the concise default JSON view.",
    )
    orchestrator_report = orchestrator_subparsers.add_parser(
        "report",
        help="Print orchestrator run artifact path and summary.",
    )
    orchestrator_report.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_report.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    orchestrator_report.add_argument(
        "--expand-contracts",
        "--verbose-contract",
        action="store_true",
        help="Return full durable run state instead of the concise default JSON view.",
    )
    orchestrator_hooks = orchestrator_subparsers.add_parser(
        "hooks",
        help="Print Hermes terminal/prompt hook packets for a run.",
    )
    orchestrator_hooks.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_hooks.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    orchestrator_next = orchestrator_subparsers.add_parser(
        "next",
        help="Return the next Hermes bridge hook packet for a run.",
    )
    orchestrator_next.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_next.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    orchestrator_prep_approve = orchestrator_subparsers.add_parser(
        "prep-approve",
        help="Approve a bridge prep report and open the first Hermes actor hook.",
    )
    orchestrator_prep_approve.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_prep_approve.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    orchestrator_submit = orchestrator_subparsers.add_parser(
        "submit",
        help="Submit a Hermes callback JSON file for a bridge run.",
    )
    orchestrator_submit.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_submit.add_argument("--callback", required=True, help="Callback JSON path.")
    orchestrator_submit.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    orchestrator_decide = orchestrator_subparsers.add_parser(
        "decide",
        help="Approve, retry, or hold an orchestrator package.",
    )
    orchestrator_decide.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_decide.add_argument(
        "--decision",
        required=True,
        choices=("approve", "retry", "hold"),
        help="Decision for the orchestrator package.",
    )
    orchestrator_decide.add_argument("--option", help="Approved option ID.")
    orchestrator_decide.add_argument("--note", help="Optional decision note.")
    orchestrator_close = orchestrator_subparsers.add_parser(
        "close",
        help="Close an orchestrator run record.",
    )
    orchestrator_close.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_close.add_argument("--reason", help="Close reason.")
    orchestrator_interrupt = orchestrator_subparsers.add_parser(
        "interrupt",
        help="Pause a resumable orchestrator run without discarding its next hook.",
    )
    orchestrator_interrupt.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_interrupt.add_argument("--reason", help="Interruption reason.")
    orchestrator_resume = orchestrator_subparsers.add_parser(
        "resume",
        help="Resume an interrupted orchestrator run from its previous state.",
    )
    orchestrator_resume.add_argument("run_id", help="Orchestrator run ID.")
    orchestrator_resume.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    orchestrator_repair_projection = orchestrator_subparsers.add_parser(
        "repair-projection",
        help="Regenerate a run.json projection from durable SQLite workflow state.",
    )
    orchestrator_repair_projection.add_argument("run_id", help="Orchestrator run ID.")
    for command_name, help_text in (
        ("dispatch-plan", "Preview one provider-neutral stdio dispatch without starting it."),
        ("dispatch", "Run one confirmed stdio hook and ingest its callback."),
    ):
        runtime_dispatch = orchestrator_subparsers.add_parser(
            command_name,
            help=help_text,
        )
        runtime_dispatch.add_argument("run_id", help="Orchestrator run ID.")
        runtime_dispatch.add_argument(
            "--workdir",
            type=Path,
            help="Runtime working directory. Defaults to the WSA workspace.",
        )
        runtime_dispatch.add_argument(
            "--timeout",
            type=float,
            default=120.0,
            help="Maximum runtime seconds for this hook.",
        )
        runtime_dispatch.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Output format.",
        )
        if command_name == "dispatch":
            runtime_dispatch.add_argument(
                "--confirm",
                action="store_true",
                help="Confirm the displayed command and start exactly one process.",
            )
        runtime_dispatch.add_argument(
            "--runtime-command",
            dest="runtime_argv",
            nargs=argparse.REMAINDER,
            default=[],
            help="Runtime argv as separate tokens. This option must be last.",
        )

    report_parser = subparsers.add_parser("report", help="Inspect reports.")
    report_subparsers = report_parser.add_subparsers(dest="report_command")
    report_list = report_subparsers.add_parser("list", help="List reports for a world.")
    report_list.add_argument("world_id", help="World ID.")
    report_list.add_argument("--status", help="Optional report status filter.")
    report_inbox = report_subparsers.add_parser(
        "inbox",
        help="Show reports, runs, candidates, tickets, and scoped callbacks awaiting review.",
    )
    report_inbox.add_argument("world_id", help="World ID.")
    report_inbox.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    report_show = report_subparsers.add_parser(
        "show",
        help="Inspect one report, run, candidate, or ticket without changing state.",
    )
    report_show.add_argument("world_id", help="World ID.")
    report_show.add_argument("item_id", help="Report, run, or ticket ID.")
    report_show.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    report_decide = report_subparsers.add_parser(
        "decide",
        help="Record an explicit decision for a report, run, candidate, or ticket.",
    )
    report_decide.add_argument("world_id", help="World ID.")
    report_decide.add_argument("item_id", help="Report, run, or ticket ID.")
    report_decide.add_argument(
        "--decision",
        required=True,
        choices=(
            "approve",
            "apply",
            "retry",
            "hold",
            "reject",
            "revise",
            "refine",
            "restart",
            "resume",
        ),
    )
    report_decide.add_argument("--option", help="Approved orchestrator option ID.")
    report_decide.add_argument("--note", help="Decision or revision note.")
    report_decide.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    report_triage = report_subparsers.add_parser(
        "triage",
        help="Read-only triage of pending reports, reviewable runs, and callback residue.",
    )
    report_triage.add_argument("world_id", help="World ID.")
    report_triage.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    report_reject_pending = report_subparsers.add_parser(
        "reject-pending",
        help="Reject pending proposal reports/runs after explicit author intent.",
    )
    report_reject_pending.add_argument("world_id", help="World ID.")
    report_reject_pending.add_argument(
        "--reason",
        default="bulk reject pending review by author request",
        help="Reason recorded in the cleanup audit.",
    )
    report_reject_pending.add_argument(
        "--archive-callbacks",
        action="store_true",
        help="Also move Hermes callback residue JSON files into callback_archive.",
    )
    report_reject_pending.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    report_archive_callbacks = report_subparsers.add_parser(
        "archive-callbacks",
        help="Archive callback residue without changing reports or runs.",
    )
    report_archive_callbacks.add_argument("world_id", help="World ID.")
    report_archive_callbacks.add_argument(
        "--reason",
        default="archive completed or discarded callback residue",
        help="Reason recorded in the cleanup audit.",
    )
    report_archive_callbacks.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    report_export = report_subparsers.add_parser(
        "export",
        help="Render an on-demand TXT/HTML report artifact from an orchestrator run.",
    )
    report_export.add_argument("world_id", help="World ID.")
    report_export.add_argument("--run-id", required=True, help="Orchestrator run ID.")
    report_export.add_argument(
        "--artifact-type",
        required=True,
        choices=sorted(REPORT_EXPORT_ARTIFACT_TYPES),
        help="Recommended report artifact type to render.",
    )
    report_export.add_argument(
        "--format",
        choices=("txt", "html"),
        default="txt",
        help="Artifact format.",
    )
    report_export.add_argument(
        "--write",
        action="store_true",
        help="Write the artifact under worlds/<world_id>/artifacts/session_logs/.",
    )

    ticket_parser = subparsers.add_parser("ticket", help="Inspect or apply tickets.")
    ticket_subparsers = ticket_parser.add_subparsers(dest="ticket_command")
    ticket_list = ticket_subparsers.add_parser("list", help="List tickets for a world.")
    ticket_list.add_argument("world_id", help="World ID.")
    ticket_list.add_argument("--status", help="Optional ticket status filter.")
    ticket_show = ticket_subparsers.add_parser(
        "show",
        help="Inspect a ticket and its concrete changes without changing state.",
    )
    ticket_show.add_argument("ticket_id", help="Ticket ID.")
    ticket_show.add_argument(
        "--world",
        dest="world_selector",
        help="World ID or unique display name; omitted when exactly one world exists.",
    )
    ticket_show.add_argument("--format", choices=("text", "json"), default="text")
    ticket_next = ticket_subparsers.add_parser(
        "next",
        help="Inspect the single next concrete ticket without copying its ID.",
    )
    ticket_next.add_argument(
        "--world",
        dest="world_selector",
        help="World ID or unique display name; omitted when exactly one world exists.",
    )
    ticket_next.add_argument("--format", choices=("text", "json"), default="text")
    ticket_review_next = ticket_subparsers.add_parser(
        "review-next",
        help="Review the single proposed concrete ticket without copying its ID.",
    )
    ticket_review_next.add_argument(
        "--world",
        dest="world_selector",
        help="World ID or unique display name; omitted when exactly one world exists.",
    )
    ticket_review_next.add_argument(
        "--format", choices=("text", "json"), default="text"
    )
    ticket_apply_next = ticket_subparsers.add_parser(
        "apply-next",
        help="Apply the single approved concrete ticket without copying its ID.",
    )
    ticket_apply_next.add_argument(
        "--world",
        dest="world_selector",
        help="World ID or unique display name; omitted when exactly one world exists.",
    )
    ticket_apply_next.add_argument(
        "--format", choices=("text", "json"), default="text"
    )
    ticket_compose = ticket_subparsers.add_parser(
        "compose",
        help="Preview a typed world-change ticket without authoring JSON.",
    )
    _add_change_draft_arguments(ticket_compose)
    ticket_amend = ticket_subparsers.add_parser(
        "amend",
        help="Preview a replacement ticket while preserving source lineage.",
    )
    ticket_amend.add_argument("ticket_id", help="Source ticket ID.")
    _add_change_draft_arguments(ticket_amend, revision=True)
    ticket_split = ticket_subparsers.add_parser(
        "split",
        help="Preview an exact partition of one concrete ticket.",
    )
    ticket_split.add_argument("ticket_id", help="Source ticket ID.")
    ticket_split.add_argument(
        "--part",
        action="append",
        required=True,
        help="Comma-separated 1-based change indexes. Repeat for each child.",
    )
    ticket_split.add_argument(
        "--part-title",
        action="append",
        default=[],
        help="Optional child title. Repeat once per part.",
    )
    ticket_split.add_argument(
        "--world",
        dest="world_selector",
        help="World ID or unique display name; omitted when exactly one world exists.",
    )
    ticket_split.add_argument(
        "--write-ticket",
        action="store_true",
        help="Create split child tickets and atomically supersede the source.",
    )
    ticket_split.add_argument("--format", choices=("text", "json"), default="text")
    ticket_merge = ticket_subparsers.add_parser(
        "merge",
        help="Preview combining two or more concrete tickets in caller order.",
    )
    ticket_merge.add_argument(
        "ticket_ids",
        nargs="+",
        help="Source ticket IDs in the desired change order.",
    )
    ticket_merge.add_argument("--title", help="Merged ticket title.")
    ticket_merge.add_argument("--risk", choices=("low", "medium", "high"))
    ticket_merge.add_argument(
        "--compact",
        action="store_true",
        default=None,
        help="Write the merged ticket as a compact packet.",
    )
    ticket_merge.add_argument(
        "--world",
        dest="world_selector",
        help="World ID or unique display name; omitted when exactly one world exists.",
    )
    ticket_merge.add_argument(
        "--write-ticket",
        action="store_true",
        help="Create one merged ticket and atomically supersede every source.",
    )
    ticket_merge.add_argument("--format", choices=("text", "json"), default="text")
    ticket_apply = ticket_subparsers.add_parser(
        "apply",
        aliases=["approve"],
        help="Apply a reviewed concrete change-set ticket.",
    )
    ticket_apply.add_argument("world_id", help="World ID.")
    ticket_apply.add_argument("ticket_id", help="Ticket ID.")
    ticket_review = ticket_subparsers.add_parser(
        "review",
        help="Validate and approve a concrete ticket without mutating world state.",
    )
    ticket_review.add_argument("world_id", help="World ID.")
    ticket_review.add_argument("ticket_id", help="Ticket ID.")
    ticket_review.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    ticket_materialize = ticket_subparsers.add_parser(
        "materialize",
        help="Preview or write concrete changes derived from a candidate ticket.",
    )
    ticket_materialize.add_argument("world_id", help="World ID.")
    ticket_materialize.add_argument("candidate_ticket_id", help="Candidate ticket ID.")
    ticket_materialize.add_argument(
        "changes_json",
        type=Path,
        help="JSON list, or object with a changes list, containing concrete changes.",
    )
    ticket_materialize.add_argument(
        "--write-ticket",
        action="store_true",
        help="Create an applicable ticket and mark the candidate converted.",
    )
    ticket_materialize.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
