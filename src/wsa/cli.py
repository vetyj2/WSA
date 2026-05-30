from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from . import __version__
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
    build_hermes_command_registry,
    format_hermes_commands,
    write_hermes_command_registry,
)
from .hermes_doctor import HermesDoctor, format_hermes_doctor
from .manager import WorldManager
from .meeting import MeetingOrchestrator
from .orchestrator import SceneOrchestrator
from .repositories import WorldRepository
from .startup import (
    QUESTION_STATUSES,
    StartupProfileManager,
    format_startup_interview,
    format_startup_status,
)
from .template import TemplateChecker, format_template_readiness
from .tickets import approve_ticket
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

    world_create = world_subparsers.add_parser("create", help="Create a new isolated world.")
    world_create.add_argument("name", help="Human-readable world name.")

    world_subparsers.add_parser("list", help="List registered worlds.")
    world_startup = world_subparsers.add_parser(
        "startup",
        help="Run Easy Startup worldbuilding interview utilities.",
    )
    world_startup_subparsers = world_startup.add_subparsers(dest="world_startup_command")
    world_startup_status = world_startup_subparsers.add_parser(
        "status",
        help="Show startup ambiguity score.",
    )
    world_startup_status.add_argument("world_id", help="World ID.")
    world_startup_interview = world_startup_subparsers.add_parser(
        "interview",
        help="Generate a limited numbered startup interview round.",
    )
    world_startup_interview.add_argument("world_id", help="World ID.")
    world_startup_interview.add_argument(
        "--budget",
        type=int,
        default=8,
        help="Maximum questions in this round.",
    )
    world_startup_answer = world_startup_subparsers.add_parser(
        "answer",
        help="Record an author answer for a startup question.",
    )
    world_startup_answer.add_argument("world_id", help="World ID.")
    world_startup_answer.add_argument("question_id", help="Question ID such as Q001.")
    world_startup_answer.add_argument("--text", required=True, help="Author answer text.")
    world_startup_set_status = world_startup_subparsers.add_parser(
        "set-status",
        help="Set a startup question status without changing its answer.",
    )
    world_startup_set_status.add_argument("world_id", help="World ID.")
    world_startup_set_status.add_argument("question_id", help="Question ID such as Q001.")
    world_startup_set_status.add_argument(
        "--status",
        required=True,
        choices=sorted(QUESTION_STATUSES),
        help="Question status.",
    )

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

    report_parser = subparsers.add_parser("report", help="Inspect reports.")
    report_subparsers = report_parser.add_subparsers(dest="report_command")
    report_list = report_subparsers.add_parser("list", help="List reports for a world.")
    report_list.add_argument("world_id", help="World ID.")
    report_list.add_argument("--status", help="Optional report status filter.")

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


def run_init(workspace: Path) -> int:
    db_path = init_workspace(workspace)
    print(f"workspace_initialized: {workspace}")
    print(f"control_db: {db_path}")
    return 0


def run_world_create(workspace: Path, name: str) -> int:
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


def run_world_startup_status(workspace: Path, world_id: str) -> int:
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).status()
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_interview(workspace: Path, world_id: str, budget: int) -> int:
    world = get_world(workspace, world_id)
    round_ = StartupProfileManager(world).interview(budget=budget)
    for line in format_startup_interview(round_):
        print(line)
    return 0


def run_world_startup_answer(
    workspace: Path,
    world_id: str,
    question_id: str,
    text: str,
) -> int:
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).answer(question_id, text)
    print(f"startup_answer_recorded: {question_id}")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_set_status(
    workspace: Path,
    world_id: str,
    question_id: str,
    status_value: str,
) -> int:
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).set_status(question_id, status_value)
    print(f"startup_status_updated: {question_id}")
    print(f"question_status: {status_value}")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_manager_diagnose(workspace: Path, fix: bool = False) -> int:
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


def run_meeting(
    workspace: Path,
    world_id: str,
    topic: str,
    question: str,
    participants: list[str],
) -> int:
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
    output_path: str | None,
    overwrite: bool,
) -> int:
    registry = build_hermes_command_registry()
    if write_example or output_path:
        if output_path:
            path = Path(output_path).expanduser()
        else:
            adapter = HermesCliTemplateAdapter(workspace)
            adapter.ensure_layout()
            path = adapter.adapter_config_dir() / HERMES_COMMAND_REGISTRY_FILENAME
        written = write_hermes_command_registry(path, overwrite=overwrite)
        print(f"command_registry: {written}")
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
    readiness = TemplateChecker(workspace).run(write_missing=write_missing)
    for line in format_template_readiness(readiness):
        print(line)
    return 0 if readiness.ok else 1


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
                return run_world_startup_status(config.workspace, args.world_id)
            if args.world_startup_command == "interview":
                return run_world_startup_interview(config.workspace, args.world_id, args.budget)
            if args.world_startup_command == "answer":
                return run_world_startup_answer(
                    config.workspace,
                    args.world_id,
                    args.question_id,
                    args.text,
                )
            if args.world_startup_command == "set-status":
                return run_world_startup_set_status(
                    config.workspace,
                    args.world_id,
                    args.question_id,
                    args.status,
                )
            parser.parse_args(["world", "startup", "--help"])
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
    if args.command == "scene":
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

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
