from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from . import __version__
from .autonomous_orchestrator import AutonomousOrchestrator, resolve_scene_filter_contract
from .orchestrator_bridge import OrchestratorBridge
from .orchestrator_contract import (
    DEFAULT_CONTEXT_POLICY,
    DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
    DEFAULT_MAX_QUEUE_TURNS,
    DEFAULT_MAX_SUBSESSION_CALLS,
    DEFAULT_TERMINATION_POLICY,
)
from .config import load_config
from .hermes_adapter import (
    DELIVERY_TARGETS,
    SENSITIVITY_LEVELS,
    SESSION_MODES,
    HermesCliTemplateAdapter,
    build_delivery_contract,
    build_runtime_target,
    build_sensitivity_contract,
)
from .hermes_commands import (
    HERMES_COMMAND_REGISTRY_FILENAME,
    HERMES_LOCAL_COMMAND_REGISTRY_FILENAME,
    build_hermes_command_registry,
    empty_local_command_overlay_report,
    format_local_command_overlay_report,
    format_hermes_commands,
    merge_hermes_command_registries,
    validate_local_command_registry_report,
    write_hermes_command_registry,
    write_hermes_local_command_registry_template,
)
from .hermes_doctor import HermesDoctor, format_hermes_doctor
from .manager import WorldManager
from .meeting import MeetingOrchestrator
from .orchestrator import SceneOrchestrator
from .repositories import WorldRepository
from .review_cleanup import (
    archive_callback_residue,
    format_cleanup_audit,
    format_review_triage,
    reject_pending_review,
    triage_review_queue,
)
from .startup import (
    QUESTION_STATUSES,
    StartupProfileManager,
    format_startup_interview,
    format_startup_status,
    startup_interview_to_dict,
    startup_status_to_dict,
)
from .template import TemplateChecker, format_template_readiness
from .tickets import approve_ticket
from .update import (
    UpdateBackupError,
    UpdateLockError,
    assert_update_unlocked,
    backup_result_to_dict,
    backup_workspace,
    format_backup_result,
    format_update_preflight,
    run_update_preflight,
    update_preflight_to_dict,
)
from .workspace import (
    SchemaVersionError,
    WorkspacePathError,
    control_db_path,
    create_world,
    get_world,
    init_workspace,
    list_worlds,
    schema_version,
    sqlite_connection,
    world_db_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wsa",
        description="World Scene Actors local-first world management prototype.",
    )
    parser.add_argument(
        "--workspace",
        help="Workspace directory. Defaults to WSA_WORKSPACE or ./workspace.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="Check local configuration.")
    subparsers.add_parser("init", help="Initialize workspace directories and control DB.")

    world_parser = subparsers.add_parser("world", help="Manage worlds.")
    world_subparsers = world_parser.add_subparsers(dest="world_command")

    def add_startup_output_format(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Output format.",
        )

    world_create = world_subparsers.add_parser("create", help="Create a new isolated world.")
    world_create.add_argument("name", help="Human-readable world name.")

    world_subparsers.add_parser("list", help="List registered worlds.")
    world_startup = world_subparsers.add_parser(
        "startup",
        help="Run open-ended startup interview utilities.",
    )
    world_startup_subparsers = world_startup.add_subparsers(dest="world_startup_command")
    world_startup_status = world_startup_subparsers.add_parser(
        "status",
        help="Show startup ambiguity score.",
    )
    world_startup_status.add_argument("world_id", help="World ID.")
    add_startup_output_format(world_startup_status)
    world_startup_interview = world_startup_subparsers.add_parser(
        "interview",
        help="Generate a limited numbered startup interview round.",
    )
    world_startup_interview.add_argument("world_id", help="World ID.")
    world_startup_interview.add_argument(
        "--budget",
        type=int,
        default=4,
        help="Maximum questions in this round.",
    )
    add_startup_output_format(world_startup_interview)
    world_startup_answer = world_startup_subparsers.add_parser(
        "answer",
        help="Record an author answer for a startup question.",
    )
    world_startup_answer.add_argument("world_id", help="World ID.")
    world_startup_answer.add_argument("question_id", help="Question ID such as 0001.")
    world_startup_answer.add_argument("--text", required=True, help="Author answer text.")
    world_startup_answer.add_argument("--choice", help="Optional choice label a-i.")
    add_startup_output_format(world_startup_answer)
    world_startup_batch = world_startup_subparsers.add_parser(
        "batch-answer",
        help="Record parallel answers such as '0001a 0002b plus notes'.",
    )
    world_startup_batch.add_argument("world_id", help="World ID.")
    world_startup_batch.add_argument("--text", required=True, help="Answer code text.")
    add_startup_output_format(world_startup_batch)
    world_startup_set_status = world_startup_subparsers.add_parser(
        "set-status",
        help="Set a startup question status without changing its answer.",
    )
    world_startup_set_status.add_argument("world_id", help="World ID.")
    world_startup_set_status.add_argument("question_id", help="Question ID such as 0001.")
    world_startup_set_status.add_argument(
        "--status",
        required=True,
        choices=sorted(QUESTION_STATUSES),
        help="Question status.",
    )
    add_startup_output_format(world_startup_set_status)
    world_startup_discretion = world_startup_subparsers.add_parser(
        "set-discretion",
        help="Set Hermes discretion level from 0 to 5.",
    )
    world_startup_discretion.add_argument("world_id", help="World ID.")
    world_startup_discretion.add_argument(
        "--level",
        type=int,
        required=True,
        choices=range(0, 6),
        help="Discretion level from 0 author-only to 5 challenge autonomy.",
    )
    add_startup_output_format(world_startup_discretion)

    world_easystartup = world_subparsers.add_parser(
        "easystartup",
        help="Run easy-pick startup interview utilities.",
    )
    world_easystartup_subparsers = world_easystartup.add_subparsers(
        dest="world_easystartup_command"
    )
    world_easystartup_status = world_easystartup_subparsers.add_parser(
        "status",
        help="Show startup ambiguity score.",
    )
    world_easystartup_status.add_argument("world_id", help="World ID.")
    add_startup_output_format(world_easystartup_status)
    world_easystartup_interview = world_easystartup_subparsers.add_parser(
        "interview",
        help="Generate an easy-pick numbered startup interview round.",
    )
    world_easystartup_interview.add_argument("world_id", help="World ID.")
    world_easystartup_interview.add_argument(
        "--budget",
        type=int,
        default=8,
        help="Maximum questions in this round.",
    )
    add_startup_output_format(world_easystartup_interview)
    world_easystartup_answer = world_easystartup_subparsers.add_parser(
        "answer",
        help="Record an author answer for an easy-pick startup question.",
    )
    world_easystartup_answer.add_argument("world_id", help="World ID.")
    world_easystartup_answer.add_argument("question_id", help="Question ID such as 0001.")
    world_easystartup_answer.add_argument("--text", required=True, help="Author answer text.")
    world_easystartup_answer.add_argument("--choice", help="Optional choice label a-i.")
    add_startup_output_format(world_easystartup_answer)
    world_easystartup_batch = world_easystartup_subparsers.add_parser(
        "batch-answer",
        help="Record parallel answers such as '0001a 0002b plus notes'.",
    )
    world_easystartup_batch.add_argument("world_id", help="World ID.")
    world_easystartup_batch.add_argument("--text", required=True, help="Answer code text.")
    add_startup_output_format(world_easystartup_batch)
    world_easystartup_discretion = world_easystartup_subparsers.add_parser(
        "set-discretion",
        help="Set Hermes discretion level from 0 to 5.",
    )
    world_easystartup_discretion.add_argument("world_id", help="World ID.")
    world_easystartup_discretion.add_argument(
        "--level",
        type=int,
        required=True,
        choices=range(0, 6),
        help="Discretion level from 0 author-only to 5 challenge autonomy.",
    )
    add_startup_output_format(world_easystartup_discretion)

    manager_parser = subparsers.add_parser("manager", help="Run world manager utilities.")
    manager_subparsers = manager_parser.add_subparsers(dest="manager_command")
    manager_diagnose = manager_subparsers.add_parser("diagnose", help="Run local diagnostics.")
    manager_diagnose.add_argument(
        "--fix",
        action="store_true",
        help="Apply safe diagnostic cleanups and record diagnostic logs.",
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
    orchestrator_run.add_argument("--mode", default="agent", help="Runtime mode label.")
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

    report_parser = subparsers.add_parser("report", help="Inspect reports.")
    report_subparsers = report_parser.add_subparsers(dest="report_command")
    report_list = report_subparsers.add_parser("list", help="List reports for a world.")
    report_list.add_argument("world_id", help="World ID.")
    report_list.add_argument("--status", help="Optional report status filter.")
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

    ticket_parser = subparsers.add_parser("ticket", help="Inspect or apply tickets.")
    ticket_subparsers = ticket_parser.add_subparsers(dest="ticket_command")
    ticket_list = ticket_subparsers.add_parser("list", help="List tickets for a world.")
    ticket_list.add_argument("world_id", help="World ID.")
    ticket_list.add_argument("--status", help="Optional ticket status filter.")
    ticket_approve = ticket_subparsers.add_parser("approve", help="Approve and apply a ticket.")
    ticket_approve.add_argument("world_id", help="World ID.")
    ticket_approve.add_argument("ticket_id", help="Ticket ID.")

    scene_parser = subparsers.add_parser("scene", help="Run scene orchestration utilities.")
    scene_subparsers = scene_parser.add_subparsers(dest="scene_command")
    scene_start = scene_subparsers.add_parser(
        "start",
        aliases=["prep"],
        help="Start a bounded Hermes-bridge scene prep run.",
    )
    scene_start.add_argument("world_id", help="World ID.")
    scene_start.add_argument("--topic", required=True, help="Scene or scene-prep topic.")
    scene_start.add_argument(
        "--question",
        default=(
            "Prepare scene facts, actor assignments, role isolation, "
            "model/thinking guidance, and approval choices."
        ),
        help="Scene-prep question to resolve before drafting.",
    )
    scene_start.add_argument("--rounds", type=int, default=3, help="Internal round budget.")
    scene_start.add_argument(
        "--max-queue-turns",
        type=int,
        default=DEFAULT_MAX_QUEUE_TURNS,
        help=f"Maximum autonomous queue turns before stopping. Default: {DEFAULT_MAX_QUEUE_TURNS}.",
    )
    scene_start.add_argument(
        "--max-concurrent-subsessions",
        type=int,
        default=DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
        help=(
            "Maximum subsessions Hermes should run at the same time. "
            f"Default: {DEFAULT_MAX_CONCURRENT_SUBSESSIONS}."
        ),
    )
    scene_start.add_argument(
        "--max-subsession-calls",
        type=int,
        default=DEFAULT_MAX_SUBSESSION_CALLS,
        help=(
            "Maximum total subsession calls before returning a partial package. "
            f"Default: {DEFAULT_MAX_SUBSESSION_CALLS}."
        ),
    )
    scene_start.add_argument(
        "--context-policy",
        default=DEFAULT_CONTEXT_POLICY,
        help=f"Context carry-forward policy. Default: {DEFAULT_CONTEXT_POLICY}.",
    )
    scene_start.add_argument(
        "--frame-plan",
        help="Optional scene frame, viewpoint, location, timeframe, or guardrail.",
    )
    scene_start.add_argument(
        "--termination-policy",
        default=DEFAULT_TERMINATION_POLICY,
        help=f"Termination policy label. Default: {DEFAULT_TERMINATION_POLICY}.",
    )
    scene_start.add_argument("--time-scope", help="Optional scene time scope.")
    scene_start.add_argument("--location-scope", help="Optional scene location scope.")
    scene_start.add_argument("--viewpoint", help="Optional viewpoint or POV scope.")
    scene_start.add_argument(
        "--generation-mode",
        choices=("auto", "fact-audit-synthesis", "writing-room-line-build"),
        default="auto",
        help=(
            "Scene generation mode disclosure. Default: auto, letting Hermes/profile/natural "
            "language resolve the final execution mode."
        ),
    )
    scene_start.add_argument(
        "--condition",
        action="append",
        default=[],
        help="Optional scene selection condition. Can be repeated.",
    )
    scene_start.add_argument(
        "--participant",
        action="append",
        default=[],
        help="Actor, narrator, crowd, continuity role, or scene-prep viewpoint. Can be repeated.",
    )
    scene_start.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    scene_start.add_argument(
        "--no-prep-review",
        action="store_true",
        help="Opt out of the default prep review hook before first Hermes actor call.",
    )
    scene_mock = scene_subparsers.add_parser("mock", help="Run a mock scene vertical slice.")
    scene_mock.add_argument("world_id", help="World ID.")
    scene_mock.add_argument("name", help="Scene name.")
    scene_mock.add_argument("--goal", required=True, help="Scene goal.")
    scene_mock.add_argument(
        "--actor",
        action="append",
        default=[],
        help="Actor display name. Can be provided multiple times.",
    )

    hermes_parser = subparsers.add_parser("hermes", help="Prepare Hermes adapter contracts.")
    hermes_subparsers = hermes_parser.add_subparsers(dest="hermes_command")
    hermes_example = hermes_subparsers.add_parser(
        "init-example",
        help="Write example CLI adapter config without secrets.",
    )
    hermes_example.add_argument("--adapter-name", default="example-hermes", help="Hermes adapter name.")
    hermes_example.add_argument(
        "--command",
        dest="adapter_command",
        default="wsa-hermes-cli",
        help="CLI wrapper command.",
    )
    hermes_example.add_argument("--overwrite", action="store_true", help="Overwrite example config.")

    hermes_commands = hermes_subparsers.add_parser(
        "commands",
        help="List or write Hermes shortcut command registry.",
    )
    hermes_commands.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format when printing the registry.",
    )
    hermes_commands.add_argument(
        "--write-example",
        action="store_true",
        help="Write hermes_commands.example.json under workspace/hermes/adapter_config.",
    )
    hermes_commands.add_argument(
        "--write-local-template",
        action="store_true",
        help="Write hermes_commands.local.json template under workspace/hermes/adapter_config.",
    )
    hermes_commands.add_argument(
        "--validate-local-overlay",
        action="store_true",
        help="Validate local Hermes command overlay collisions and side-effect metadata.",
    )
    hermes_commands.add_argument(
        "--merged",
        action="store_true",
        help="Print or write the base registry merged with a valid local overlay.",
    )
    hermes_commands.add_argument(
        "--local-overlay",
        help="Optional local overlay path. Defaults to workspace/hermes/adapter_config/hermes_commands.local.json.",
    )
    hermes_commands.add_argument("--output", help="Optional output path for registry JSON.")
    hermes_commands.add_argument("--overwrite", action="store_true", help="Overwrite existing output.")

    hermes_doctor = hermes_subparsers.add_parser(
        "doctor",
        help="Run read-only Hermes adapter preflight checks.",
    )
    hermes_doctor.add_argument(
        "--command",
        dest="adapter_command",
        default="wsa-hermes-cli",
        help="Hermes wrapper command to check.",
    )
    hermes_doctor.add_argument("--config", help="Optional Hermes adapter config path.")
    hermes_doctor.add_argument("--operation-policy", help="Optional operation policy path.")
    hermes_doctor.add_argument("--source-root", help="Optional source repository root.")

    hermes_task = hermes_subparsers.add_parser(
        "task",
        help="Create a filesystem task packet for a Hermes CLI wrapper.",
    )
    hermes_task.add_argument("world_id", help="World ID.")
    hermes_task.add_argument("--title", required=True, help="Task title.")
    hermes_task.add_argument("--instruction", required=True, help="Instruction for Hermes.")
    hermes_task.add_argument("--task-type", default="manager_diagnostic", help="Task type.")
    hermes_task.add_argument("--role", default="world_manager", help="Runtime role.")
    hermes_task.add_argument("--session-id", help="Existing runtime session ID.")
    hermes_task.add_argument("--adapter-name", default="example-hermes", help="Hermes adapter name.")
    hermes_task.add_argument(
        "--command",
        dest="adapter_command",
        default="wsa-hermes-cli",
        help="CLI wrapper command.",
    )
    hermes_task.add_argument("--input-json", help="Optional JSON object payload.")
    hermes_task.add_argument("--runtime-profile", default="default", help="Expected Hermes profile.")
    hermes_task.add_argument("--runtime-source", default="cli", help="Hermes task source.")
    hermes_task.add_argument(
        "--session-mode",
        choices=SESSION_MODES,
        default="callback_only",
        help="Expected Hermes session mode.",
    )
    hermes_task.add_argument("--runtime-workdir", default=".", help="Expected Hermes workdir.")
    hermes_task.add_argument("--interactive", action="store_true", help="Mark task interactive.")
    hermes_task.add_argument("--background", action="store_true", help="Mark task background-capable.")
    hermes_task.add_argument(
        "--toolset",
        action="append",
        default=[],
        help="Expected Hermes toolset. Can be repeated.",
    )
    hermes_task.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Expected Hermes skill. Can be repeated.",
    )
    hermes_task.add_argument(
        "--delivery-target",
        choices=DELIVERY_TARGETS,
        default="origin",
        help="Intended result delivery target.",
    )
    hermes_task.add_argument(
        "--safe-for-chat",
        action="store_true",
        help="Mark generated summaries as safe for chat delivery.",
    )
    hermes_task.add_argument(
        "--sensitivity",
        choices=SENSITIVITY_LEVELS,
        default="internal",
        help="Task payload sensitivity level.",
    )

    hermes_collect = hermes_subparsers.add_parser(
        "collect-callback",
        help="Collect and validate a Hermes callback JSON file.",
    )
    hermes_collect.add_argument("callback_path", help="Callback JSON path.")
    hermes_collect.add_argument("--adapter-name", default="example-hermes", help="Hermes adapter name.")
    hermes_collect.add_argument(
        "--command",
        dest="adapter_command",
        default="wsa-hermes-cli",
        help="CLI wrapper command.",
    )
    hermes_collect.add_argument(
        "--allow-external-callback",
        action="store_true",
        help="Allow callback JSON outside workspace/hermes/callbacks.",
    )

    template_parser = subparsers.add_parser("template", help="Check MVP template readiness.")
    template_subparsers = template_parser.add_subparsers(dest="template_command")
    template_check = template_subparsers.add_parser(
        "check",
        help="Check that a workspace is clean enough to copy as a template.",
    )
    template_check.add_argument(
        "--write-missing",
        action="store_true",
        help="Create missing template workspace files before checking.",
    )

    update_parser = subparsers.add_parser("update", help="Check safe update readiness.")
    update_subparsers = update_parser.add_subparsers(dest="update_command")
    update_preflight = update_subparsers.add_parser(
        "preflight",
        help="Run read-only checks before Hermes-owned WSA source updates.",
    )
    update_preflight.add_argument(
        "--source-root",
        help="WSA source checkout or package root to inspect. Omit when unknown.",
    )
    update_preflight.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    update_backup = update_subparsers.add_parser(
        "backup",
        help="Create a workspace backup before a Hermes-owned WSA source update.",
    )
    update_backup.add_argument(
        "--output-dir",
        required=True,
        help="Directory outside the workspace where the backup folder will be created.",
    )
    update_backup.add_argument(
        "--source-root",
        help="WSA source checkout or package root to inspect. Omit when unknown.",
    )
    update_backup.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )

    return parser


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")


def run_doctor(workspace: Path) -> int:
    print(f"workspace: {workspace}")
    print(f"workspace_exists: {workspace.exists()}")
    db_path = control_db_path(workspace)
    print(f"control_db_exists: {db_path.exists()}")
    if db_path.exists():
        try:
            with sqlite_connection(db_path, schema_name="control") as conn:
                version = schema_version(conn, "control")
            world_count = 0
            for world in list_worlds(workspace):
                with sqlite_connection(world_db_path(world.path), schema_name="world") as conn:
                    schema_version(conn, "world")
                world_count += 1
        except SchemaVersionError as exc:
            print(f"schema_status: unsupported: {exc}")
            return 1
        except WorkspacePathError as exc:
            print(f"path_status: invalid: {exc}")
            return 1
        print(f"control_schema_version: {version if version is not None else 'unknown'}")
        print(f"world_count: {world_count}")
    print("schema_status: ok")
    return 0


def guard_update_unlocked(workspace: Path, operation: str) -> bool:
    try:
        assert_update_unlocked(workspace, operation)
    except UpdateLockError as exc:
        print("update_lock: blocked")
        print(f"operation: {operation}")
        print(f"detail: {exc}")
        return False
    return True


def run_init(workspace: Path) -> int:
    if not guard_update_unlocked(workspace, "init"):
        return 1
    db_path = init_workspace(workspace)
    print(f"workspace_initialized: {workspace}")
    print(f"control_db: {db_path}")
    return 0


def run_world_create(workspace: Path, name: str) -> int:
    if not guard_update_unlocked(workspace, "world.create"):
        return 1
    record = create_world(workspace, name)
    print(f"world_created: {record.world_id}")
    print(f"display_name: {record.display_name}")
    print(f"path: {record.path}")
    return 0


def run_world_list(workspace: Path) -> int:
    worlds = list_worlds(workspace)
    if not worlds:
        print("worlds: none")
        return 0

    for world in worlds:
        print(
            "\t".join(
                [
                    world.world_id,
                    world.display_name,
                    world.status,
                    str(world.path),
                ]
            )
        )
    return 0


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def run_world_startup_status(
    workspace: Path,
    world_id: str,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.status"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).status(mode=mode)
    if output_format == "json":
        print_json(startup_status_to_dict(status))
        return 0
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_interview(
    workspace: Path,
    world_id: str,
    budget: int,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.interview"):
        return 1
    world = get_world(workspace, world_id)
    round_ = StartupProfileManager(world).interview(budget=budget, mode=mode)
    if output_format == "json":
        print_json(startup_interview_to_dict(round_))
        return 0
    for line in format_startup_interview(round_):
        print(line)
    return 0


def run_world_startup_answer(
    workspace: Path,
    world_id: str,
    question_id: str,
    text: str,
    choice: str | None = None,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.answer"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).answer(question_id, text, choice=choice, mode=mode)
    if output_format == "json":
        print_json(
            {
                "startup_answer_recorded": question_id,
                "status": startup_status_to_dict(status),
            }
        )
        return 0
    print(f"startup_answer_recorded: {question_id}")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_batch_answer(
    workspace: Path,
    world_id: str,
    text: str,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.batch_answer"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).answer_batch(text, mode=mode)
    if output_format == "json":
        print_json(
            {
                "startup_batch_answer_recorded": True,
                "status": startup_status_to_dict(status),
            }
        )
        return 0
    print("startup_batch_answer_recorded: yes")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_set_status(
    workspace: Path,
    world_id: str,
    question_id: str,
    status_value: str,
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, "world.startup.set_status"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).set_status(question_id, status_value)
    if output_format == "json":
        print_json(
            {
                "startup_status_updated": question_id,
                "question_status": status_value,
                "status": startup_status_to_dict(status),
            }
        )
        return 0
    print(f"startup_status_updated: {question_id}")
    print(f"question_status: {status_value}")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_set_discretion(
    workspace: Path,
    world_id: str,
    level: int,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.set_discretion"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).set_discretion(level, mode=mode)
    if output_format == "json":
        print_json(
            {
                "startup_discretion_updated": level,
                "status": startup_status_to_dict(status),
            }
        )
        return 0
    print(f"startup_discretion_updated: {level}")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_manager_diagnose(workspace: Path, fix: bool = False) -> int:
    if fix and not guard_update_unlocked(workspace, "manager.diagnose.fix"):
        return 1
    findings = WorldManager(workspace).run_diagnostics(fix=fix)
    if not findings:
        print("diagnostics: clean")
        return 0
    for finding in findings:
        print(
            "\t".join(
                [
                    finding.world_id,
                    finding.finding_type,
                    finding.path or "",
                    finding.detail,
                ]
            )
        )
    return 0


def run_scene_mock(workspace: Path, world_id: str, name: str, goal: str, actors: list[str]) -> int:
    if not guard_update_unlocked(workspace, "scene.mock"):
        return 1
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    actor_records = [
        repo.create_entity("character", actor_name, payload={"source": "scene_mock_cli"})
        for actor_name in (actors or ["Mock Actor"])
    ]
    result = SceneOrchestrator(workspace, world).run_mock_scene(name, goal, actor_records)
    print(f"scene_id: {result.scene_id}")
    print(f"scene_dir: {result.scene_dir}")
    print(f"prep_receipt: {result.prep_receipt}")
    print(f"progress_checkpoint: {result.progress_checkpoint}")
    print(f"ticket_id: {result.ticket_id}")
    print(f"report_id: {result.report_id}")
    return 0


def run_scene_start(
    workspace: Path,
    world_id: str,
    topic: str,
    question: str,
    rounds: int,
    max_queue_turns: int,
    max_concurrent_subsessions: int,
    max_subsession_calls: int,
    context_policy: str,
    frame_plan: str | None,
    termination_policy: str,
    time_scope: str | None,
    location_scope: str | None,
    viewpoint: str | None,
    conditions: list[str],
    participants: list[str],
    output_format: str,
    prep_review: bool,
    generation_mode: str,
) -> int:
    if not guard_update_unlocked(workspace, "scene.start"):
        return 1
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    scene_filter_contract = resolve_scene_filter_contract(
        repo,
        time_scope=time_scope,
        location_scope=location_scope,
        viewpoint=viewpoint,
        conditions=conditions,
    )
    try:
        result = AutonomousOrchestrator(workspace, world).run(
            workflow="scene_generation",
            topic=topic,
            question=question,
            participants=participants,
            rounds=rounds,
            skill="scene_start",
            mode="hermes-bridge",
            max_queue_turns=max_queue_turns,
            max_concurrent_subsessions=max_concurrent_subsessions,
            max_subsession_calls=max_subsession_calls,
            context_policy=context_policy,
            frame_plan=frame_plan,
            termination_policy=termination_policy,
            subsession_policy="ephemeral",
            canon_policy="proposal-only",
            approval="required",
            close_on="complete",
            scene_filter_contract=scene_filter_contract,
            prep_review=prep_review,
            scene_generation_mode=generation_mode,
        )
    except ValueError as exc:
        print("scene_start: blocked")
        print(f"detail: {exc}")
        return 1
    next_payload = OrchestratorBridge(workspace).next(result.run_id)
    if output_format == "json":
        print_json(
            {
                "scene_start_run_id": result.run_id,
                "orchestrator_status": result.status,
                "run_path": str(result.run_path),
                "report_id": result.report_id or None,
                "scene_filter_contract": scene_filter_contract,
                "scene_mode_disclosure": next_payload.get("scene_mode_disclosure", {}),
                "actor_contribution_summary": next_payload.get("actor_contribution_summary", {}),
                "next": next_payload,
            }
        )
        return 0
    print(f"scene_start_run_id: {result.run_id}")
    print(f"orchestrator_status: {result.status}")
    print("workflow: scene_generation")
    print("skill: scene_start")
    print("mode: hermes-bridge")
    print(f"run_path: {result.run_path}")
    print(f"report_id: {result.report_id or 'pending_hermes_completion'}")
    print(f"next_action: {next_payload.get('next_action')}")
    mode_disclosure = next_payload.get("scene_mode_disclosure", {})
    if mode_disclosure:
        print(f"scene_generation_mode: {mode_disclosure.get('resolved_mode')}")
        print(f"mode_resolution_source: {mode_disclosure.get('mode_resolution_source')}")
    hook = next_payload.get("hook")
    if hook:
        print(f"next_turn_id: {hook['turn_id']}")
        print(f"next_represents: {hook['represents']}")
    print("side_effect_status: proposal_only_no_scene_draft_no_canon_mutation")
    return 0


def run_meeting(
    workspace: Path,
    world_id: str,
    topic: str,
    question: str,
    participants: list[str],
) -> int:
    if not guard_update_unlocked(workspace, "meeting.run"):
        return 1
    world = get_world(workspace, world_id)
    result = MeetingOrchestrator(workspace, world).run_meeting(
        topic,
        question,
        participants,
    )
    print(f"meeting_id: {result.meeting_id}")
    print(f"meeting_dir: {result.meeting_dir}")
    print(f"transcript_path: {result.transcript_path}")
    print(f"report_id: {result.report_id}")
    print(f"manager_session_id: {result.manager_session_id}")
    for session_id in result.participant_session_ids:
        print(f"participant_session_id: {session_id}")
    return 0


def run_meeting_decide(
    workspace: Path,
    world_id: str,
    report_id: str,
    decision: str,
    note: str | None,
) -> int:
    if not guard_update_unlocked(workspace, "meeting.decide"):
        return 1
    world = get_world(workspace, world_id)
    result = MeetingOrchestrator(workspace, world).decide_report(
        report_id,
        decision,
        note=note,
    )
    print(f"meeting_decision: {result.decision}")
    print(f"report_id: {result.report_id}")
    print(f"report_status: {result.report_status}")
    if result.ticket is not None:
        print(f"ticket_id: {result.ticket.ticket_id}")
        print(f"ticket_type: {result.ticket.ticket_type}")
    return 0


def run_orchestrator(
    workspace: Path,
    world_id: str,
    workflow: str,
    skill: str | None,
    topic: str,
    question: str,
    mode: str,
    rounds: int,
    max_queue_turns: int,
    max_concurrent_subsessions: int,
    max_subsession_calls: int,
    context_policy: str,
    frame_plan: str | None,
    termination_policy: str,
    participants: list[str],
    subsession_policy: str,
    canon_policy: str,
    approval: str,
    close_on: str,
    prep_review: bool,
) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.run"):
        return 1
    world = get_world(workspace, world_id)
    try:
        result = AutonomousOrchestrator(workspace, world).run(
            workflow=workflow,
            topic=topic,
            question=question,
            participants=participants,
            rounds=rounds,
            skill=skill,
            mode=mode,
            max_queue_turns=max_queue_turns,
            max_concurrent_subsessions=max_concurrent_subsessions,
            max_subsession_calls=max_subsession_calls,
            context_policy=context_policy,
            frame_plan=frame_plan,
            termination_policy=termination_policy,
            subsession_policy=subsession_policy,
            canon_policy=canon_policy,
            approval=approval,
            close_on=close_on,
            prep_review=prep_review,
        )
    except ValueError as exc:
        print("orchestrator_run: blocked")
        print(f"detail: {exc}")
        return 1
    print(f"orchestrator_run_id: {result.run_id}")
    print(f"orchestrator_status: {result.status}")
    print(f"run_dir: {result.run_dir}")
    print(f"run_path: {result.run_path}")
    print(f"report_id: {result.report_id or 'pending_hermes_completion'}")
    print(f"manager_session_id: {result.manager_session_id}")
    for session_id in result.subsession_session_ids:
        print(f"subsession_session_id: {session_id}")
    return 0


def run_orchestrator_status(workspace: Path, run_id: str, output_format: str) -> int:
    payload = AutonomousOrchestrator.load_run(workspace, run_id)
    if output_format == "json":
        print_json(payload)
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"orchestrator_status: {payload['status']}")
    print(f"workflow: {payload['workflow']}")
    if payload.get("workflow_requested") and payload.get("workflow_requested") != payload["workflow"]:
        print(f"workflow_requested: {payload['workflow_requested']}")
    print(f"skill: {payload.get('skill', payload['workflow'])}")
    print(f"topic: {payload['topic']}")
    print(f"execution: {payload['execution']}")
    print(f"round_budget: {payload['plan']['round_budget']}")
    queue_limits = payload.get("queue_limits", {})
    if queue_limits:
        print(
            "queue_turns: "
            f"{queue_limits.get('queue_turns_used')}/{queue_limits.get('max_queue_turns')}"
        )
        print(
            "subsession_calls: "
            f"{queue_limits.get('planned_subsession_calls')}/"
            f"{queue_limits.get('max_subsession_calls')}"
        )
    print(f"frame_source: {payload.get('plan_frame', {}).get('source', 'unknown')}")
    print(
        "max_concurrent_subsessions: "
        f"{payload.get('concurrency_policy', {}).get('max_concurrent_subsessions', 'unknown')}"
    )
    print(f"closed_subsessions: {len(payload.get('closed_subsessions', []))}")
    print(f"approval_options: {', '.join(payload.get('approval_options', []))}")
    return 0


def run_orchestrator_report(workspace: Path, run_id: str, output_format: str) -> int:
    payload = AutonomousOrchestrator.load_run(workspace, run_id)
    path = AutonomousOrchestrator.report_path(workspace, run_id)
    if output_format == "json":
        print_json({"run_path": str(path), "run": payload})
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"run_path: {path}")
    print(f"summary: {payload['synthesis']['summary']}")
    print(f"requires_author_boundary: {payload['conflict_gap_diagnosis']['requires_author_boundary']}")
    for option in payload.get("draft_options", []):
        print(f"draft_option: {option['option_id']}\t{option['title']}")
    return 0


def run_orchestrator_hooks(workspace: Path, run_id: str, output_format: str) -> int:
    payload = AutonomousOrchestrator.load_run(workspace, run_id)
    hooks = payload.get("runtime_hook_packets", payload.get("round_prompt_packets", []))
    result = {
        "run_id": run_id,
        "workflow": payload.get("workflow"),
        "skill": payload.get("skill"),
        "subsession_execution_mode": payload.get("subsession_execution_mode"),
        "hook_count": len(hooks),
        "hooks": hooks,
    }
    if output_format == "json":
        print_json(result)
        return 0
    print(f"orchestrator_run_id: {run_id}")
    print(f"workflow: {result['workflow']}")
    print(f"subsession_execution_mode: {result['subsession_execution_mode']}")
    print(f"hook_count: {len(hooks)}")
    for hook in hooks:
        command = hook.get("terminal_command", {}).get("argv", [])
        print(f"hook: {hook.get('turn_id', hook.get('prompt_packet_id'))}")
        print(f"turn_type: {hook.get('turn_type')}")
        if command:
            print(f"terminal_command: {' '.join(str(item) for item in command[:8])} ...")
    return 0


def run_orchestrator_next(workspace: Path, run_id: str, output_format: str) -> int:
    payload = OrchestratorBridge(workspace).next(run_id)
    if output_format == "json":
        print_json(payload)
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"status: {payload['status']}")
    print(f"execution_status: {payload['execution_status']}")
    print(f"next_action: {payload['next_action']}")
    hook = payload.get("hook")
    if hook:
        print(f"turn_id: {hook['turn_id']}")
        print(f"turn_type: {hook['turn_type']}")
        print(f"represents: {hook['represents']}")
    prep_report = payload.get("prep_report")
    if prep_report:
        print(f"prep_report_status: {prep_report.get('status')}")
        print(f"prep_review_options: {', '.join(prep_report.get('review_options', []))}")
    return 0


def run_orchestrator_prep_approve(workspace: Path, run_id: str, output_format: str) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.prep-approve"):
        return 1
    try:
        payload = OrchestratorBridge(workspace).approve_prep(run_id)
    except KeyError as exc:
        print("orchestrator_prep_approve: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        print_json(payload)
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"prep_approved: {str(payload.get('prep_approved', False)).lower()}")
    print(f"status: {payload['status']}")
    print(f"execution_status: {payload['execution_status']}")
    print(f"next_action: {payload['next_action']}")
    hook = payload.get("hook")
    if hook:
        print(f"turn_id: {hook['turn_id']}")
        print(f"represents: {hook['represents']}")
    return 0


def run_orchestrator_submit(
    workspace: Path,
    run_id: str,
    callback_path: str,
    output_format: str,
) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.submit"):
        return 1
    try:
        payload = OrchestratorBridge(workspace).submit(run_id, Path(callback_path))
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print("orchestrator_submit: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        print_json(payload)
        return 0
    print(f"orchestrator_run_id: {payload['run_id']}")
    print(f"turn_id: {payload['turn_id']}")
    print(f"accepted: {str(payload['accepted']).lower()}")
    print(f"status: {payload['status']}")
    print(f"execution_status: {payload['execution_status']}")
    print(f"next_action: {payload['next_action']}")
    if payload.get("report_id"):
        print(f"report_id: {payload['report_id']}")
    return 0


def run_orchestrator_decide(
    workspace: Path,
    run_id: str,
    decision: str,
    option: str | None,
    note: str | None,
) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.decide"):
        return 1
    try:
        result = AutonomousOrchestrator.decide(
            workspace,
            run_id,
            decision=decision,
            option=option,
            note=note,
        )
    except ValueError as exc:
        print("orchestrator_decision: blocked")
        print(f"detail: {exc}")
        return 1
    print(f"orchestrator_decision: {result.decision}")
    print(f"orchestrator_run_id: {result.run_id}")
    print(f"report_id: {result.report_id}")
    print(f"report_status: {result.report_status}")
    if result.ticket is not None:
        print(f"ticket_id: {result.ticket.ticket_id}")
        print(f"ticket_type: {result.ticket.ticket_type}")
    return 0


def run_orchestrator_close(workspace: Path, run_id: str, reason: str | None) -> int:
    if not guard_update_unlocked(workspace, "orchestrator.close"):
        return 1
    payload = AutonomousOrchestrator.close(workspace, run_id, reason=reason)
    print(f"orchestrator_closed: {payload['run_id']}")
    print(f"orchestrator_status: {payload['status']}")
    print(f"close_reason: {payload['close_reason']}")
    return 0


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
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
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
    if not guard_update_unlocked(workspace, "report.reject_pending"):
        return 1
    world = get_world(workspace, world_id)
    payload = reject_pending_review(
        workspace,
        world,
        reason=reason,
        archive_callbacks=archive_callbacks,
    )
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
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
    if not guard_update_unlocked(workspace, "report.archive_callbacks"):
        return 1
    world = get_world(workspace, world_id)
    payload = archive_callback_residue(workspace, world, reason=reason)
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_cleanup_audit(payload):
            print(line)
    return 0


def run_ticket_list(workspace: Path, world_id: str, status: str | None) -> int:
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    tickets = repo.list_tickets(status=status)
    if not tickets:
        print("tickets: none")
        return 0
    for ticket in tickets:
        print(
            "\t".join(
                [
                    ticket.ticket_id,
                    ticket.status,
                    ticket.risk,
                    ticket.ticket_type,
                    ticket.title,
                ]
            )
        )
    return 0


def run_ticket_approve(workspace: Path, world_id: str, ticket_id: str) -> int:
    if not guard_update_unlocked(workspace, "ticket.approve"):
        return 1
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    applied = approve_ticket(repo, ticket_id)
    print(f"ticket_approved: {ticket_id}")
    print(f"applied_count: {len(applied)}")
    for item in applied:
        print(f"applied: {item}")
    return 0


def run_hermes_init_example(
    workspace: Path,
    adapter_name: str,
    command: str,
    overwrite: bool,
) -> int:
    if not guard_update_unlocked(workspace, "hermes.init_example"):
        return 1
    adapter = HermesCliTemplateAdapter(workspace, adapter_name=adapter_name, command=command)
    path = adapter.write_example_config(overwrite=overwrite)
    registry_path = write_hermes_command_registry(
        adapter.adapter_config_dir() / HERMES_COMMAND_REGISTRY_FILENAME,
        overwrite=overwrite,
    )
    print(f"example_config: {path}")
    print(f"command_registry: {registry_path}")
    return 0


def run_hermes_commands(
    workspace: Path,
    output_format: str,
    write_example: bool,
    write_local_template: bool,
    validate_local_overlay: bool,
    merged: bool,
    local_overlay_path: str | None,
    output_path: str | None,
    overwrite: bool,
) -> int:
    registry = build_hermes_command_registry()
    local_path = (
        Path(local_overlay_path).expanduser()
        if local_overlay_path
        else HermesCliTemplateAdapter(workspace).adapter_config_dir() / HERMES_LOCAL_COMMAND_REGISTRY_FILENAME
    )

    if write_local_template:
        if not guard_update_unlocked(workspace, "hermes.commands.write"):
            return 1
        path = Path(output_path).expanduser() if output_path else local_path
        written = write_hermes_local_command_registry_template(path, overwrite=overwrite)
        print(f"local_command_overlay_template: {written}")
        return 0

    if write_example or (output_path and not validate_local_overlay and not merged):
        if not guard_update_unlocked(workspace, "hermes.commands.write"):
            return 1
        if output_path:
            path = Path(output_path).expanduser()
        else:
            adapter = HermesCliTemplateAdapter(workspace)
            adapter.ensure_layout()
            path = adapter.adapter_config_dir() / HERMES_COMMAND_REGISTRY_FILENAME
        written = write_hermes_command_registry(path, overwrite=overwrite)
        print(f"command_registry: {written}")
        return 0

    local_registry = None
    if local_path.exists():
        try:
            local_registry = json.loads(local_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report = {
                "schema": "wsa.hermes.command_overlay_report.v1",
                "status": "blocked",
                "blocked": True,
                "warnings": False,
                "path": str(local_path),
                "command_count": 0,
                "finding_counts": {"block": 1, "warn": 0, "info": 0},
                "findings": [
                    {
                        "severity": "block",
                        "code": "invalid_json",
                        "message": f"invalid local overlay JSON: {exc}",
                        "recommendation": "Fix the JSON before update or live command execution.",
                    }
                ],
                "recommended_actions": ["repair local command overlay JSON"],
            }
            if output_format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                for line in format_local_command_overlay_report(report):
                    print(line)
            return 1

    if validate_local_overlay:
        report = (
            validate_local_command_registry_report(local_registry, registry, local_path)
            if local_registry is not None
            else empty_local_command_overlay_report(local_path)
        )
        if output_format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            for line in format_local_command_overlay_report(report):
                print(line)
        return 1 if report["blocked"] else 0

    if merged:
        if local_registry is not None:
            report = validate_local_command_registry_report(local_registry, registry, local_path)
            if report["blocked"]:
                if output_format == "json":
                    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                else:
                    for line in format_local_command_overlay_report(report):
                        print(line)
                return 1
            registry = merge_hermes_command_registries(registry, local_registry)
        if output_path:
            if not guard_update_unlocked(workspace, "hermes.commands.write"):
                return 1
            path = Path(output_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not overwrite:
                print(f"command_registry: {path}")
                return 0
            path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"command_registry: {path}")
            return 0
        if output_format == "json":
            print(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            for line in format_hermes_commands(registry):
                print(line)
        return 0

    if output_format == "json":
        print(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    for line in format_hermes_commands(registry):
        print(line)
    return 0


def run_hermes_doctor(
    workspace: Path,
    command: str,
    config_path: str | None,
    operation_policy_path: str | None,
    source_root: str | None,
) -> int:
    report = HermesDoctor(
        workspace,
        command=command,
        config_path=Path(config_path).expanduser() if config_path else None,
        operation_policy_path=(
            Path(operation_policy_path).expanduser() if operation_policy_path else None
        ),
        source_root=Path(source_root).expanduser() if source_root else None,
    ).run()
    for line in format_hermes_doctor(report):
        print(line)
    return 0 if report.ok else 1


def run_hermes_task_create(
    workspace: Path,
    world_id: str,
    title: str,
    instruction: str,
    task_type: str,
    role: str,
    session_id: str | None,
    adapter_name: str,
    command: str,
    input_json: str | None,
    runtime_profile: str,
    runtime_source: str,
    session_mode: str,
    runtime_workdir: str,
    interactive: bool,
    background: bool,
    toolsets: list[str],
    skills: list[str],
    delivery_target: str,
    safe_for_chat: bool,
    sensitivity_level: str,
) -> int:
    if not guard_update_unlocked(workspace, "hermes.task"):
        return 1
    payload = {}
    if input_json:
        parsed = json.loads(input_json)
        if not isinstance(parsed, dict):
            raise ValueError("--input-json must be a JSON object")
        payload = parsed

    adapter = HermesCliTemplateAdapter(workspace, adapter_name=adapter_name, command=command)
    runtime_target = build_runtime_target(
        profile=runtime_profile,
        source=runtime_source,
        session_mode=session_mode,
        workdir=runtime_workdir,
        interactive=interactive,
        background=background,
        toolsets=toolsets,
        skills=skills,
    )
    delivery = build_delivery_contract(
        target=delivery_target,
        safe_for_chat=safe_for_chat,
    )
    sensitivity = build_sensitivity_contract(level=sensitivity_level)
    task = adapter.create_task(
        world_id=world_id,
        title=title,
        instruction=instruction,
        task_type=task_type,
        role=role,
        session_id=session_id,
        payload=payload,
        runtime_target=runtime_target,
        delivery=delivery,
        sensitivity=sensitivity,
    )
    print(f"hermes_task_created: {task.task_id}")
    print(f"task_path: {task.task_ref}")
    print(f"session_id: {task.session_id}")
    print(f"world_id: {task.world_id}")
    print(f"command_preview: {command} run-task {task.task_ref}")
    return 0


def run_hermes_collect_callback(
    workspace: Path,
    callback_path: str,
    adapter_name: str,
    command: str,
    allow_external_callback: bool,
) -> int:
    if not guard_update_unlocked(workspace, "hermes.collect_callback"):
        return 1
    adapter = HermesCliTemplateAdapter(workspace, adapter_name=adapter_name, command=command)
    callback = adapter.collect_callback(
        Path(callback_path),
        allow_external_path=allow_external_callback,
    )
    print(f"hermes_callback_collected: {callback.callback_id}")
    print(f"task_id: {callback.task_id}")
    print(f"session_id: {callback.session_id}")
    print(f"world_id: {callback.world_id}")
    print(f"message_id: {callback.runtime_envelope.message_id}")
    if callback.report_id:
        print(f"report_id: {callback.report_id}")
    return 0


def run_template_check(workspace: Path, write_missing: bool) -> int:
    if write_missing and not guard_update_unlocked(workspace, "template.check.write_missing"):
        return 1
    readiness = TemplateChecker(workspace).run(write_missing=write_missing)
    for line in format_template_readiness(readiness):
        print(line)
    return 0 if readiness.ok else 1


def run_update_preflight_cli(
    workspace: Path,
    source_root: str | None,
    output_format: str,
) -> int:
    report = run_update_preflight(
        workspace,
        source_root=Path(source_root).expanduser().resolve() if source_root else None,
    )
    if output_format == "json":
        print(json.dumps(update_preflight_to_dict(report), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_update_preflight(report):
            print(line)
    return 1 if report.blocked else 0


def run_update_backup_cli(
    workspace: Path,
    output_dir: str,
    source_root: str | None,
    output_format: str,
) -> int:
    try:
        result = backup_workspace(
            workspace,
            Path(output_dir),
            source_root=Path(source_root).expanduser().resolve() if source_root else None,
        )
    except UpdateBackupError as exc:
        print("update_backup: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        print(json.dumps(backup_result_to_dict(result), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_backup_result(result):
            print(line)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    config = load_config(args.workspace)

    if args.command == "doctor":
        return run_doctor(config.workspace)
    if args.command == "init":
        return run_init(config.workspace)
    if args.command == "world":
        if args.world_command == "create":
            return run_world_create(config.workspace, args.name)
        if args.world_command == "list":
            return run_world_list(config.workspace)
        if args.world_command == "startup":
            if args.world_startup_command == "status":
                return run_world_startup_status(
                    config.workspace,
                    args.world_id,
                    mode="startup",
                    output_format=args.format,
                )
            if args.world_startup_command == "interview":
                return run_world_startup_interview(
                    config.workspace,
                    args.world_id,
                    args.budget,
                    mode="startup",
                    output_format=args.format,
                )
            if args.world_startup_command == "answer":
                return run_world_startup_answer(
                    config.workspace,
                    args.world_id,
                    args.question_id,
                    args.text,
                    choice=args.choice,
                    mode="startup",
                    output_format=args.format,
                )
            if args.world_startup_command == "batch-answer":
                return run_world_startup_batch_answer(
                    config.workspace,
                    args.world_id,
                    args.text,
                    mode="startup",
                    output_format=args.format,
                )
            if args.world_startup_command == "set-status":
                return run_world_startup_set_status(
                    config.workspace,
                    args.world_id,
                    args.question_id,
                    args.status,
                    output_format=args.format,
                )
            if args.world_startup_command == "set-discretion":
                return run_world_startup_set_discretion(
                    config.workspace,
                    args.world_id,
                    args.level,
                    mode="startup",
                    output_format=args.format,
                )
            parser.parse_args(["world", "startup", "--help"])
        if args.world_command == "easystartup":
            if args.world_easystartup_command == "status":
                return run_world_startup_status(
                    config.workspace,
                    args.world_id,
                    mode="easystartup",
                    output_format=args.format,
                )
            if args.world_easystartup_command == "interview":
                return run_world_startup_interview(
                    config.workspace,
                    args.world_id,
                    args.budget,
                    mode="easystartup",
                    output_format=args.format,
                )
            if args.world_easystartup_command == "answer":
                return run_world_startup_answer(
                    config.workspace,
                    args.world_id,
                    args.question_id,
                    args.text,
                    choice=args.choice,
                    mode="easystartup",
                    output_format=args.format,
                )
            if args.world_easystartup_command == "batch-answer":
                return run_world_startup_batch_answer(
                    config.workspace,
                    args.world_id,
                    args.text,
                    mode="easystartup",
                    output_format=args.format,
                )
            if args.world_easystartup_command == "set-discretion":
                return run_world_startup_set_discretion(
                    config.workspace,
                    args.world_id,
                    args.level,
                    mode="easystartup",
                    output_format=args.format,
                )
            parser.parse_args(["world", "easystartup", "--help"])
        parser.parse_args(["world", "--help"])
    if args.command == "manager":
        if args.manager_command == "diagnose":
            return run_manager_diagnose(config.workspace, args.fix)
        parser.parse_args(["manager", "--help"])
    if args.command == "meeting":
        if args.meeting_command == "run":
            return run_meeting(
                config.workspace,
                args.world_id,
                args.topic,
                args.question,
                args.participant,
            )
        if args.meeting_command == "decide":
            return run_meeting_decide(
                config.workspace,
                args.world_id,
                args.report_id,
                args.decision,
                args.note,
            )
        parser.parse_args(["meeting", "--help"])
    if args.command == "orchestrator":
        if args.orchestrator_command == "run":
            return run_orchestrator(
                config.workspace,
                args.world_id,
                args.workflow,
                args.skill,
                args.topic,
                args.question,
                args.mode,
                args.rounds,
                args.max_queue_turns,
                args.max_concurrent_subsessions,
                args.max_subsession_calls,
                args.context_policy,
                args.frame_plan,
                args.termination_policy,
                args.participant,
                args.subsession_policy,
                args.canon_policy,
                args.approval,
                args.close_on,
                not args.no_prep_review,
            )
        if args.orchestrator_command == "status":
            return run_orchestrator_status(config.workspace, args.run_id, args.format)
        if args.orchestrator_command == "report":
            return run_orchestrator_report(config.workspace, args.run_id, args.format)
        if args.orchestrator_command == "hooks":
            return run_orchestrator_hooks(config.workspace, args.run_id, args.format)
        if args.orchestrator_command == "next":
            return run_orchestrator_next(config.workspace, args.run_id, args.format)
        if args.orchestrator_command == "prep-approve":
            return run_orchestrator_prep_approve(config.workspace, args.run_id, args.format)
        if args.orchestrator_command == "submit":
            return run_orchestrator_submit(
                config.workspace,
                args.run_id,
                args.callback,
                args.format,
            )
        if args.orchestrator_command == "decide":
            return run_orchestrator_decide(
                config.workspace,
                args.run_id,
                args.decision,
                args.option,
                args.note,
            )
        if args.orchestrator_command == "close":
            return run_orchestrator_close(config.workspace, args.run_id, args.reason)
        parser.parse_args(["orchestrator", "--help"])
    if args.command == "scene":
        if args.scene_command in {"start", "prep"}:
            return run_scene_start(
                config.workspace,
                args.world_id,
                args.topic,
                args.question,
                args.rounds,
                args.max_queue_turns,
                args.max_concurrent_subsessions,
                args.max_subsession_calls,
                args.context_policy,
                args.frame_plan,
                args.termination_policy,
                args.time_scope,
                args.location_scope,
                args.viewpoint,
                args.condition,
                args.participant,
                args.format,
                not args.no_prep_review,
                args.generation_mode,
            )
        if args.scene_command == "mock":
            return run_scene_mock(
                config.workspace,
                args.world_id,
                args.name,
                args.goal,
                args.actor,
            )
        parser.parse_args(["scene", "--help"])
    if args.command == "report":
        if args.report_command == "list":
            return run_report_list(config.workspace, args.world_id, args.status)
        if args.report_command == "triage":
            return run_report_triage(config.workspace, args.world_id, args.format)
        if args.report_command == "reject-pending":
            return run_report_reject_pending(
                config.workspace,
                args.world_id,
                args.reason,
                args.archive_callbacks,
                args.format,
            )
        if args.report_command == "archive-callbacks":
            return run_report_archive_callbacks(
                config.workspace,
                args.world_id,
                args.reason,
                args.format,
            )
        parser.parse_args(["report", "--help"])
    if args.command == "ticket":
        if args.ticket_command == "list":
            return run_ticket_list(config.workspace, args.world_id, args.status)
        if args.ticket_command == "approve":
            return run_ticket_approve(config.workspace, args.world_id, args.ticket_id)
        parser.parse_args(["ticket", "--help"])
    if args.command == "hermes":
        if args.hermes_command == "init-example":
            return run_hermes_init_example(
                config.workspace,
                args.adapter_name,
                args.adapter_command,
                args.overwrite,
            )
        if args.hermes_command == "commands":
            return run_hermes_commands(
                config.workspace,
                args.format,
                args.write_example,
                args.write_local_template,
                args.validate_local_overlay,
                args.merged,
                args.local_overlay,
                args.output,
                args.overwrite,
            )
        if args.hermes_command == "doctor":
            return run_hermes_doctor(
                config.workspace,
                args.adapter_command,
                args.config,
                args.operation_policy,
                args.source_root,
            )
        if args.hermes_command == "task":
            return run_hermes_task_create(
                config.workspace,
                args.world_id,
                args.title,
                args.instruction,
                args.task_type,
                args.role,
                args.session_id,
                args.adapter_name,
                args.adapter_command,
                args.input_json,
                args.runtime_profile,
                args.runtime_source,
                args.session_mode,
                args.runtime_workdir,
                args.interactive,
                args.background,
                args.toolset,
                args.skill,
                args.delivery_target,
                args.safe_for_chat,
                args.sensitivity,
            )
        if args.hermes_command == "collect-callback":
            return run_hermes_collect_callback(
                config.workspace,
                args.callback_path,
                args.adapter_name,
                args.adapter_command,
                args.allow_external_callback,
            )
        parser.parse_args(["hermes", "--help"])
    if args.command == "template":
        if args.template_command == "check":
            return run_template_check(config.workspace, args.write_missing)
        parser.parse_args(["template", "--help"])
    if args.command == "update":
        if args.update_command == "preflight":
            return run_update_preflight_cli(
                config.workspace,
                args.source_root,
                args.format,
            )
        if args.update_command == "backup":
            return run_update_backup_cli(
                config.workspace,
                args.output_dir,
                args.source_root,
                args.format,
            )
        parser.parse_args(["update", "--help"])

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
