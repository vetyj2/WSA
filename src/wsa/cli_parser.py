from __future__ import annotations

import argparse

from . import __version__


from .cli_parser_hermes import add_hermes_parsers
from .cli_parser_system import add_system_parsers
from .cli_parser_tools import add_tool_parsers
from .cli_parser_workflows import add_workflow_parsers
from .cli_parser_world import add_world_parsers

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
        "--lang",
        choices=("ko", "en"),
        default="ko",
        help="Human-readable output language. JSON field names remain stable English.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="Check local configuration.")
    subparsers.add_parser("init", help="Initialize workspace directories and control DB.")
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Plan or explicitly apply ordered workspace schema migrations.",
    )
    migrate_parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up SQLite stores, apply migrations, and verify integrity.",
    )
    migrate_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    migrate_subparsers = migrate_parser.add_subparsers(dest="migrate_command")
    restore_plan = migrate_subparsers.add_parser(
        "restore-plan",
        help="Validate a migration backup and a new restore destination without writing.",
    )
    restore_plan.add_argument("backup_root", help="Migration backup directory.")
    restore_plan.add_argument("destination", help="New destination path; must not exist.")
    restore_plan.add_argument("--format", choices=("text", "json"), default="text")
    restore_execute = migrate_subparsers.add_parser(
        "restore",
        help="Restore a validated migration backup to a new destination and verify it.",
    )
    restore_execute.add_argument("backup_root", help="Migration backup directory.")
    restore_execute.add_argument("destination", help="New destination path; must not exist.")
    restore_execute.add_argument("--format", choices=("text", "json"), default="text")

    add_world_parsers(subparsers)
    add_workflow_parsers(subparsers)
    add_tool_parsers(subparsers)
    add_hermes_parsers(subparsers)
    add_system_parsers(subparsers)
    return parser
