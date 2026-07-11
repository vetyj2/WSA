from __future__ import annotations


from .hermes_adapter import (
    DELIVERY_TARGETS,
    SENSITIVITY_LEVELS,
    SESSION_MODES,
)


from typing import Any

def add_hermes_parsers(subparsers: Any) -> None:
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
        "--compact",
        action="store_true",
        help="Omit expanded policy text and emit digest references for review-friendly JSON.",
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
