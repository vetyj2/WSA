from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


HERMES_COMMAND_REGISTRY_SCHEMA = "wsa.hermes.command_registry.v1"
HERMES_COMMAND_REGISTRY_FILENAME = "hermes_commands.example.json"


def build_hermes_command_registry() -> Dict[str, Any]:
    return {
        "schema": HERMES_COMMAND_REGISTRY_SCHEMA,
        "schema_version": 1,
        "owner": "user_hermes_runtime",
        "purpose": "Public-safe shortcut command manifest for Hermes chat adapters.",
        "parser_policy": {
            "canonical_style": "telegram_safe_underscore",
            "aliases_may_include_hyphen": True,
            "unknown_command_policy": "show_help_without_execution",
            "execution_owner": "user_hermes_runtime",
            "wsa_role": "declare_intents_and_cli_templates_only",
        },
        "commands": _default_commands(),
    }


def write_hermes_command_registry(path: Path, overwrite: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return path
    payload = build_hermes_command_registry()
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def format_hermes_commands(registry: Dict[str, Any] | None = None) -> List[str]:
    payload = registry or build_hermes_command_registry()
    lines = [
        f"command_registry: {payload['schema']}",
        f"owner: {payload['owner']}",
        "commands:",
    ]
    for item in payload["commands"]:
        aliases = ", ".join(item.get("aliases", []))
        lines.append(
            "\t".join(
                [
                    item["command"],
                    item["safety"],
                    item["intent"],
                    item["title"],
                    aliases,
                ]
            )
        )
    return lines


def _arg(name: str, required: bool, description: str) -> Dict[str, Any]:
    return {
        "name": name,
        "required": required,
        "description": description,
    }


def _command(
    command: str,
    aliases: List[str],
    title: str,
    intent: str,
    category: str,
    safety: str,
    arguments: List[Dict[str, Any]],
    cli_templates: List[List[str]],
    notes: List[str] | None = None,
    operation_request: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "command": command,
        "aliases": aliases,
        "title": title,
        "intent": intent,
        "category": category,
        "safety": safety,
        "arguments": arguments,
        "cli_templates": cli_templates,
        "delivery": {
            "default": "chat_summary",
            "full_artifact": "local_report_or_file_attachment",
        },
        "execution_policy": {
            "owner": "user_hermes_runtime",
            "requires_user_confirmation": safety in {"requires_approval", "world_mutating"},
        },
    }
    if notes:
        payload["notes"] = notes
    if operation_request:
        payload["operation_request"] = operation_request
    return payload


def _default_commands() -> List[Dict[str, Any]]:
    return [
        _command(
            "/wsa_help",
            ["/wsa-help", "/wsa", "wsa help"],
            "Show the WSA shortcut menu.",
            "show_command_registry",
            "meta",
            "read_only",
            [],
            [["wsa", "hermes", "commands"]],
        ),
        _command(
            "/wsa_doctor",
            ["/wsa-doctor", "/wsa_diag", "/wsa-diagnose"],
            "Run local WSA and Hermes readiness diagnostics.",
            "run_diagnostics",
            "diagnostics",
            "read_only",
            [],
            [
                ["wsa", "doctor"],
                ["wsa", "manager", "diagnose"],
                ["wsa", "hermes", "doctor", "--command", "{hermes_wrapper_command}"],
            ],
        ),
        _command(
            "/wsa_worlds",
            ["/wsa-worlds", "/wsa_list_worlds"],
            "List registered worlds.",
            "list_worlds",
            "world",
            "read_only",
            [],
            [["wsa", "world", "list"]],
        ),
        _command(
            "/wsa_create_world",
            ["/wsa-create-world", "/wsa_new_world"],
            "Create a new isolated world workspace.",
            "create_world",
            "world",
            "requires_approval",
            [_arg("name", True, "Human-readable world name.")],
            [["wsa", "world", "create", "{name}"]],
        ),
        _command(
            "/wsa_easystart",
            ["/wsa-easystart", "/wsa_startup", "/wsa-startup"],
            "Start or continue the numbered Easy Startup interview.",
            "easy_startup_interview",
            "startup",
            "read_only",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("budget", False, "Maximum startup questions for this round. Default: 8."),
            ],
            [
                ["wsa", "world", "startup", "status", "{world_id}"],
                ["wsa", "world", "startup", "interview", "{world_id}", "--budget", "{budget:8}"],
            ],
            [
                "Hermes should summarize the numbered questions and ask the author which answers to record.",
            ],
        ),
        _command(
            "/wsa_answer",
            ["/wsa-answer", "/wsa_startup_answer"],
            "Record an author answer for a startup question.",
            "record_startup_answer",
            "startup",
            "requires_approval",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("question_id", True, "Startup question ID such as Q001."),
                _arg("text", True, "Author-approved answer text."),
            ],
            [["wsa", "world", "startup", "answer", "{world_id}", "{question_id}", "--text", "{text}"]],
        ),
        _command(
            "/wsa_autogen",
            ["/wsa-autogen", "/wsa_random", "/wsa-random"],
            "Ask Hermes to generate world candidates until a natural-language checkpoint.",
            "autonomous_world_generation",
            "startup",
            "proposal_only",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg(
                    "checkpoint",
                    True,
                    "Natural-language stopping point, such as 'until 100 characters exist'.",
                ),
                _arg("autonomy", False, "Autonomy level from 0 to 100. Default decided by Hermes/user dialogue."),
            ],
            [
                [
                    "wsa",
                    "hermes",
                    "task",
                    "{world_id}",
                    "--task-type",
                    "autonomous_world_generation",
                    "--title",
                    "Autonomous world generation",
                    "--instruction",
                    "{checkpoint}",
                    "--background",
                ]
            ],
            [
                "This command generates candidates only; canon mutation still follows user review policy.",
                "A 100% autonomy value is allowed when the author wants a challenge world.",
            ],
        ),
        _command(
            "/wsa_meeting",
            ["/wsa-meeting", "/wsa_council", "/wsa-council"],
            "Run a non-mutating representative meeting.",
            "run_meeting",
            "meeting",
            "proposal_only",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("topic", True, "Meeting topic."),
                _arg("question", False, "Question for representatives to discuss."),
                _arg("participant", False, "Participant/viewpoint. May be repeated by Hermes."),
            ],
            [
                [
                    "wsa",
                    "meeting",
                    "run",
                    "{world_id}",
                    "--topic",
                    "{topic}",
                    "--question",
                    "{question}",
                    "--participant",
                    "{participant}",
                ]
            ],
        ),
        _command(
            "/wsa_meeting_decide",
            ["/wsa-meeting-decide", "/wsa_decide_meeting"],
            "Approve, retry, or hold a meeting report.",
            "decide_meeting_report",
            "meeting",
            "requires_approval",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("report_id", True, "Meeting report ID."),
                _arg("decision", True, "One of approve, retry, or hold."),
            ],
            [["wsa", "meeting", "decide", "{world_id}", "{report_id}", "--decision", "{decision}"]],
        ),
        _command(
            "/wsa_reports",
            ["/wsa-reports", "/wsa_report_list"],
            "List reports for review.",
            "list_reports",
            "review",
            "read_only",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("status", False, "Optional report status filter."),
            ],
            [["wsa", "report", "list", "{world_id}", "--status", "{status}"]],
        ),
        _command(
            "/wsa_tickets",
            ["/wsa-tickets", "/wsa_ticket_list"],
            "List pending or applied tickets.",
            "list_tickets",
            "review",
            "read_only",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("status", False, "Optional ticket status filter."),
            ],
            [["wsa", "ticket", "list", "{world_id}", "--status", "{status}"]],
        ),
        _command(
            "/wsa_approve_ticket",
            ["/wsa-approve-ticket", "/wsa_apply_ticket"],
            "Approve and apply a ticket to world state.",
            "approve_ticket",
            "review",
            "world_mutating",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("ticket_id", True, "Ticket ID."),
            ],
            [["wsa", "ticket", "approve", "{world_id}", "{ticket_id}"]],
            ["Hermes should obtain explicit user confirmation before executing this command."],
        ),
        _command(
            "/wsa_snapshot",
            ["/wsa-snapshot", "/wsa_commit", "/wsa-commit"],
            "Request a local or remote version-control snapshot through Hermes policy.",
            "version_control_snapshot",
            "operations",
            "requires_approval",
            [_arg("summary", True, "User-facing snapshot summary.")],
            [],
            [
                "WSA declares the operation request only.",
                "The user's Hermes runtime decides whether this means none, local commit, remote push, or custom.",
            ],
            operation_request={
                "action": "version_control.snapshot",
                "allowed_modes": ["none", "local_commit", "remote_push", "custom"],
            },
        ),
    ]
