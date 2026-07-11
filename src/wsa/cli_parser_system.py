from __future__ import annotations




from typing import Any

def add_system_parsers(subparsers: Any) -> None:
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
