from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .autonomy import discretion_scale_contract, fill_the_rest_contract
from .orchestrator_contract import (
    DEFAULT_CONTEXT_POLICY,
    DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
    DEFAULT_MAX_QUEUE_TURNS,
    DEFAULT_MAX_SUBSESSION_CALLS,
    DEFAULT_TERMINATION_POLICY,
    build_hermes_orchestrator_runtime_contract,
)


HERMES_COMMAND_REGISTRY_SCHEMA = "wsa.hermes.command_registry.v1"
HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA = "wsa.hermes.command_registry.local.v1"
HERMES_COMMAND_OVERLAY_REPORT_SCHEMA = "wsa.hermes.command_overlay_report.v1"
HERMES_COMMAND_REGISTRY_FILENAME = "hermes_commands.example.json"
HERMES_LOCAL_COMMAND_REGISTRY_FILENAME = "hermes_commands.local.json"
LOCAL_COMMAND_RESERVED_PREFIXES = ("/wsa_", "/filltherest", "/fill_the_rest", "/fillrest")
LOCAL_COMMAND_MUTATING_SAFETIES = {"requires_approval", "workspace_mutating", "world_mutating"}
KNOWN_COMMAND_SAFETIES = {
    "proposal_only",
    "read_only",
    "requires_approval",
    "workspace_mutating",
    "world_mutating",
}


def build_hermes_command_registry() -> Dict[str, Any]:
    return {
        "schema": HERMES_COMMAND_REGISTRY_SCHEMA,
        "schema_version": 1,
        "owner": "user_hermes_runtime",
        "purpose": "Public-safe shortcut command manifest for Hermes chat adapters.",
        "parser_policy": {
            "canonical_style": "telegram_safe_underscore",
            "aliases_may_include_hyphen": True,
            "telegram_menu_policy": (
                "prefer_canonical_menu_surface; keep compatibility commands available "
                "for free-form parsing"
            ),
            "unknown_command_policy": "show_help_without_execution",
            "execution_owner": "user_hermes_runtime",
            "wsa_role": "declare_intents_and_cli_templates_only",
        },
        "canonical_menu_surface": _canonical_menu_surface(),
        "cli_template_policy": {
            "argv_array_required": True,
            "shell_joining": "forbidden_by_default",
            "multiple_templates_default": "run_all",
            "optional_unset_policy": "omit_flag_and_value_or_omit_input_json_key",
            "placeholder_resolution": "resolve_all_placeholders_before_execution",
            "input_json_template": "json_serialize_after_placeholder_resolution",
            "repeatable_argument_policy": "repeat_flag_once_per_value",
            "machine_readable_argument_hints": True,
        },
        "runtime_portability": {
            "supported_runtime_shapes": ["local_shell", "docker_container", "vps_service"],
            "command_wrapper": "wsa",
            "fallback_command_wrapper": "python -m wsa",
            "cwd_policy": "workspace_root_recommended",
            "workspace_env": "WSA_WORKSPACE",
            "path_policy": "relative_to_workspace_root",
        },
        "local_overlay_policy": {
            "schema": HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA,
            "filename": HERMES_LOCAL_COMMAND_REGISTRY_FILENAME,
            "owner": "user_hermes_runtime",
            "merge_order": ["base_registry", "local_overlay"],
            "base_updates_replace_generated_registry_only": True,
            "local_overlay_preserved_across_updates": True,
            "override_base_commands": "forbidden_by_default",
            "conflict_policy": "block_update_until_resolved",
            "official_command_surface_policy": (
                "Do not upstream personal shortcut names; preserve them as local overlay commands "
                "unless a pattern is broadly useful and can attach to an existing compact entrypoint."
            ),
            "pre_post_update_diagnostics": {
                "run_before_source_update": [
                    "wsa hermes commands --validate-local-overlay --format json",
                    "wsa update preflight --format json",
                ],
                "run_after_source_update": [
                    "wsa hermes commands --validate-local-overlay --format json",
                    "wsa update preflight --format json",
                ],
                "high_risk_policy": (
                    "If block findings or mutating-command warnings exist, Hermes should report "
                    "them to the user and recommend overlay changes before live execution resumes."
                ),
            },
            "local_namespace_recommendation": (
                "Use user/runtime-specific commands such as /local_status or /project_status; "
                "the /wsa_ and /filltherest namespaces are reserved for upstream compatibility."
            ),
        },
        "side_effect_metadata_policy": {
            "applies_to": ["base_commands", "local_overlay_commands"],
            "required_fields": ["safety", "intent"],
            "recommended_for_mutating_commands": [
                "execution_policy.requires_user_confirmation",
                "side_effects",
                "rollback_or_backup_recommendation",
                "delivery.default",
            ],
            "adapter_briefing_rule": (
                "Hermes should brief the user before workspace/world mutating commands and should "
                "show update-preflight overlay findings before and after source updates."
            ),
        },
        "discretion_policy": {
            "customizable": True,
            "scale": discretion_scale_contract(),
            "level_5_requires_destination_checkpoint": True,
        },
        "fill_the_rest": fill_the_rest_contract(),
        "commands": _default_commands(),
    }


def _canonical_menu_surface() -> Dict[str, Any]:
    return {
        "schema": "wsa.hermes.canonical_menu_surface.v1",
        "purpose": (
            "Keep the user-facing Hermes command surface small while allowing internal "
            "workflow, mode, scope, and action routing to grow."
        ),
        "max_visible_entrypoints": 6,
        "entries": [
            {
                "label": "Startup",
                "primary_command": "/wsa_startup",
                "modes": ["open", "easy"],
                "current_routes": ["/wsa_startup", "/wsa_easystartup", "/wsa_answer", "/wsa_pick"],
                "intent": "initial_world_setup_and_interview_progress",
                "notes": [
                    "Easystartup is Startup with easy-pick mode, not a separate top-level product surface.",
                ],
            },
            {
                "label": "Meetup",
                "primary_command": "/wsa_orchestrator",
                "modes": ["meetup", "retry", "fill_the_rest", "decision_meeting"],
                "current_routes": [
                    "/wsa_orchestrator",
                    "/wsa_meeting",
                    "/fill_the_rest",
                    "/filltherest_plan",
                    "/filltherest_start",
                ],
                "intent": "non_canon_worldbuilding_discussion_and_candidate_generation",
                "notes": [
                    "Meetup is a working belief or intermediate orchestration surface; it does not directly commit canon.",
                ],
            },
            {
                "label": "Scene",
                "primary_command": "/wsa_scene_start",
                "modes": ["prep", "actor_assignment", "viewpoint_filter", "draft_boundary"],
                "current_routes": ["/wsa_scene_start"],
                "intent": "scene_prep_scene_data_logs_actor_context_and_localized_viewpoint_work",
                "notes": [
                    "Scene is the reliability layer for localized scene data, actor packets, viewpoints, and script-prep scope.",
                ],
            },
            {
                "label": "Patrol",
                "primary_command": None,
                "modes": ["scheduled", "world_health", "gap_scan", "stale_work_review"],
                "current_routes": ["/wsa_autogen", "/filltherest_plan"],
                "intent": "reactive_and_periodic_world_hygiene_patrol",
                "status": "route_group_no_single_command_yet",
                "notes": [
                    "Patrol should become a visible entrypoint before adding more narrow patrol-style slash commands.",
                ],
            },
            {
                "label": "Doctor",
                "primary_command": "/wsa_doctor",
                "modes": ["readiness", "update_preflight", "runtime_contract", "template_check"],
                "current_routes": ["/wsa_doctor", "/wsa_update", "/wsa_update_backup"],
                "intent": "installation_runtime_update_and_contract_diagnostics",
            },
            {
                "label": "Database",
                "primary_command": None,
                "modes": ["query", "reports", "tickets", "facts", "export", "migration"],
                "current_routes": ["/wsa_worlds", "/wsa_reports", "/wsa_tickets", "/wsa_approve_ticket"],
                "intent": "world_data_inspection_review_and_structural_management",
                "status": "route_group_no_single_command_yet",
                "notes": [
                    "Database is separate from Doctor: Doctor diagnoses health; Database inspects and manages world data.",
                ],
            },
        ],
        "compatibility_policy": {
            "keep_existing_commands_available": True,
            "do_not_expand_visible_menu_for_every_new_feature": True,
            "new_capability_rule": (
                "First attach new behavior to an existing entrypoint with workflow, mode, "
                "scope, target, or action before creating a new user-visible command."
            ),
            "telegram_menu_policy": "show_entrypoints_or_primary_commands_only",
            "free_form_alias_policy": "hyphenated_and_legacy_aliases_may_remain_for_parsing",
        },
        "hierarchy": ["entrypoint", "workflow", "mode", "scope", "target", "action"],
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


def build_local_command_registry_template() -> Dict[str, Any]:
    return {
        "schema": HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA,
        "schema_version": 1,
        "owner": "user_hermes_runtime",
        "purpose": "Runtime-owned custom shortcuts preserved across WSA source updates.",
        "notes": [
            "Local overlays are runtime-owned and should stay outside the public repository.",
            "Base WSA updates may refresh hermes_commands.example.json, but must preserve this local file.",
            "Do not reuse a base command name or alias; update preflight blocks collisions.",
            "Keep personal path-bound commands here rather than upstreaming them into the official registry.",
        ],
        "commands": [
            {
                "command": "/local_command",
                "aliases": ["/local-command"],
                "title": "Example local Hermes command.",
                "intent": "local_custom_command_example",
                "category": "local",
                "safety": "read_only",
                "arguments": [
                    {
                        "name": "topic",
                        "required": False,
                        "description": "Example argument handled by the user's Hermes runtime.",
                    }
                ],
                "cli_templates": [],
                "delivery": {
                    "default": "chat_summary",
                    "full_artifact": "local_report_or_file_attachment",
                },
                "execution_policy": {
                    "owner": "user_hermes_runtime",
                    "requires_user_confirmation": False,
                },
                "cli_template_policy": {
                    "execution": "run_single",
                },
                "side_effects": {
                    "workspace": False,
                    "world": False,
                    "external_runtime": False,
                },
                "rollback_or_backup_recommendation": "not_required_for_read_only_commands",
                "notes": [
                    "Copy this shape to workspace/hermes/adapter_config/hermes_commands.local.json.",
                    "Do not use /wsa_ or /filltherest names for local-only commands.",
                ],
            }
        ],
    }


def write_hermes_local_command_registry_template(path: Path, overwrite: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return path
    payload = build_local_command_registry_template()
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def command_lookup_keys(command: Dict[str, Any]) -> List[str]:
    values = [str(command.get("command", "")), *[str(item) for item in command.get("aliases", [])]]
    keys = []
    for value in values:
        lowered = " ".join(value.strip().lower().split())
        if lowered.startswith("/"):
            lowered = lowered.replace("-", "_")
        if lowered:
            keys.append(lowered)
    return keys


def _overlay_finding(
    severity: str,
    code: str,
    message: str,
    command: str | None = None,
    key: str | None = None,
    recommendation: str | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if command:
        payload["command"] = command
    if key:
        payload["key"] = key
    if recommendation:
        payload["recommendation"] = recommendation
    return payload


def empty_local_command_overlay_report(path: Path | None = None) -> Dict[str, Any]:
    return {
        "schema": HERMES_COMMAND_OVERLAY_REPORT_SCHEMA,
        "status": "pass",
        "blocked": False,
        "warnings": False,
        "path": str(path) if path is not None else None,
        "command_count": 0,
        "finding_counts": {"block": 0, "warn": 0, "info": 1},
        "findings": [
            _overlay_finding(
                "info",
                "overlay_absent",
                "no local command overlay found",
                recommendation="No action required unless this Hermes runtime needs local shortcuts.",
            )
        ],
        "recommended_actions": [],
    }


def validate_local_command_registry_report(
    local_registry: Dict[str, Any],
    base_registry: Dict[str, Any] | None = None,
    path: Path | None = None,
) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    if local_registry.get("schema") != HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA:
        findings.append(
            _overlay_finding(
                "block",
                "invalid_schema",
                "unexpected local command registry schema",
                recommendation=(
                    f"Use schema {HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA} or regenerate a local "
                    "template with wsa hermes commands --write-local-template."
                ),
            )
        )
    commands = local_registry.get("commands")
    if not isinstance(commands, list):
        findings.append(
            _overlay_finding(
                "block",
                "invalid_commands",
                "local command registry commands must be a list",
                recommendation="Rewrite the overlay commands field as a list of command objects.",
            )
        )
        return _overlay_report_from_findings(findings, 0, path)

    base_keys = set()
    if base_registry is not None:
        for command in base_registry.get("commands", []):
            base_keys.update(command_lookup_keys(command))

    local_keys: Dict[str, str] = {}
    for command in commands:
        if not isinstance(command, dict):
            findings.append(
                _overlay_finding(
                    "block",
                    "invalid_command_entry",
                    "local command entries must be objects",
                    recommendation="Remove non-object entries from the local overlay.",
                )
            )
            continue
        name = str(command.get("command") or "")
        if not name.startswith("/"):
            findings.append(
                _overlay_finding(
                    "block",
                    "command_missing_slash",
                    f"local command must start with /: {name or '<missing>'}",
                    command=name or None,
                    recommendation="Rename the local shortcut to a slash command such as /my_command.",
                )
            )
        safety = command.get("safety")
        if safety is None:
            findings.append(
                _overlay_finding(
                    "block",
                    "missing_safety",
                    f"local command missing safety: {name or '<missing>'}",
                    command=name or None,
                    recommendation="Declare safety as read_only, proposal_only, requires_approval, workspace_mutating, or world_mutating.",
                )
            )
        elif str(safety) not in KNOWN_COMMAND_SAFETIES:
            findings.append(
                _overlay_finding(
                    "warn",
                    "unknown_safety",
                    f"local command uses an unknown safety value: {safety}",
                    command=name or None,
                    recommendation="Use a known WSA safety value so Hermes can brief the user correctly.",
                )
            )
        if command.get("intent") is None:
            findings.append(
                _overlay_finding(
                    "block",
                    "missing_intent",
                    f"local command missing intent: {name or '<missing>'}",
                    command=name or None,
                    recommendation="Declare a stable intent so merged help and diagnostics can explain the shortcut.",
                )
            )
        for key in command_lookup_keys(command):
            if key in base_keys:
                findings.append(
                    _overlay_finding(
                        "block",
                        "base_collision",
                        f"local command collides with base command or alias: {key}",
                        command=name or None,
                        key=key,
                        recommendation=(
                            "Rename the local command or alias outside the official WSA namespace before update/live use."
                        ),
                    )
                )
            elif key.startswith(LOCAL_COMMAND_RESERVED_PREFIXES):
                findings.append(
                    _overlay_finding(
                        "block",
                        "reserved_namespace",
                        f"local command uses reserved WSA namespace: {key}",
                        command=name or None,
                        key=key,
                        recommendation=(
                            "Use a runtime-local namespace instead; /wsa_ and /filltherest are reserved for upstream commands."
                        ),
                    )
                )
            previous = local_keys.get(key)
            if previous is not None and previous != name:
                findings.append(
                    _overlay_finding(
                        "block",
                        "local_alias_collision",
                        f"local command alias collides inside overlay: {key}",
                        command=name or None,
                        key=key,
                        recommendation="Give each local command and alias a unique lookup key.",
                    )
                )
            local_keys[key] = name
        if str(safety) in LOCAL_COMMAND_MUTATING_SAFETIES:
            execution_policy = command.get("execution_policy")
            requires_confirmation = (
                isinstance(execution_policy, dict)
                and execution_policy.get("requires_user_confirmation") is True
            )
            if not requires_confirmation:
                findings.append(
                    _overlay_finding(
                        "warn",
                        "mutating_without_confirmation_metadata",
                        "mutating local command lacks execution_policy.requires_user_confirmation=true",
                        command=name or None,
                        recommendation=(
                            "Add confirmation metadata so Hermes can brief the user before side effects."
                        ),
                    )
                )
            if not command.get("side_effects"):
                findings.append(
                    _overlay_finding(
                        "warn",
                        "missing_side_effect_metadata",
                        "mutating local command does not describe side effects",
                        command=name or None,
                        recommendation=(
                            "Add side_effects metadata such as workspace/world/external_runtime booleans."
                        ),
                    )
                )
            if not command.get("rollback_or_backup_recommendation"):
                findings.append(
                    _overlay_finding(
                        "warn",
                        "missing_rollback_guidance",
                        "mutating local command does not declare rollback or backup guidance",
                        command=name or None,
                        recommendation=(
                            "Add rollback_or_backup_recommendation so update/preflight reports can guide the user."
                        ),
                    )
                )
    return _overlay_report_from_findings(findings, len(commands), path)


def _overlay_report_from_findings(
    findings: List[Dict[str, Any]],
    command_count: int,
    path: Path | None,
) -> Dict[str, Any]:
    block_count = sum(1 for finding in findings if finding["severity"] == "block")
    warn_count = sum(1 for finding in findings if finding["severity"] == "warn")
    info_count = sum(1 for finding in findings if finding["severity"] == "info")
    status = "blocked" if block_count else ("warn" if warn_count else "pass")
    actions: List[str] = []
    if block_count:
        actions.append("resolve blocking local overlay collisions before update or live command execution")
    if warn_count:
        actions.append("review local mutating-command metadata and brief the user before side effects")
    if not findings:
        findings = [
            _overlay_finding(
                "info",
                "overlay_valid",
                "local command overlay is valid and has no base namespace collisions",
            )
        ]
        info_count = 1
    return {
        "schema": HERMES_COMMAND_OVERLAY_REPORT_SCHEMA,
        "status": status,
        "blocked": bool(block_count),
        "warnings": bool(warn_count),
        "path": str(path) if path is not None else None,
        "command_count": command_count,
        "finding_counts": {"block": block_count, "warn": warn_count, "info": info_count},
        "findings": findings,
        "recommended_actions": actions,
    }


def validate_local_command_registry(
    local_registry: Dict[str, Any],
    base_registry: Dict[str, Any] | None = None,
) -> List[str]:
    report = validate_local_command_registry_report(local_registry, base_registry)
    return [
        str(finding["message"])
        for finding in report["findings"]
        if finding["severity"] == "block"
    ]


def merge_hermes_command_registries(
    base_registry: Dict[str, Any] | None = None,
    local_registry: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    base = base_registry or build_hermes_command_registry()
    if local_registry is None:
        return base
    issues = validate_local_command_registry(local_registry, base)
    if issues:
        raise ValueError("; ".join(issues))
    merged = json.loads(json.dumps(base, ensure_ascii=False))
    merged["commands"] = [*base.get("commands", []), *local_registry.get("commands", [])]
    merged["local_overlay"] = {
        "schema": HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA,
        "owner": local_registry.get("owner", "user_hermes_runtime"),
        "command_count": len(local_registry.get("commands", [])),
        "conflict_policy": "validated_no_base_collisions",
        "validation": validate_local_command_registry_report(local_registry, base),
    }
    return merged


def format_local_command_overlay_report(report: Dict[str, Any]) -> List[str]:
    lines = [
        f"local_command_overlay: {report['status']}",
        f"blocked: {str(report['blocked']).lower()}",
        f"warnings: {str(report['warnings']).lower()}",
        f"command_count: {report['command_count']}",
    ]
    if report.get("path"):
        lines.append(f"path: {report['path']}")
    for finding in report["findings"]:
        fields = [finding["severity"], finding["code"], finding["message"]]
        if finding.get("command"):
            fields.append(f"command={finding['command']}")
        if finding.get("key"):
            fields.append(f"key={finding['key']}")
        if finding.get("recommendation"):
            fields.append(f"recommendation={finding['recommendation']}")
        lines.append("\t".join(fields))
    if report.get("recommended_actions"):
        lines.append("recommended_actions:")
        lines.extend(f"\t{item}" for item in report["recommended_actions"])
    return lines


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


def _arg(
    name: str,
    required: bool,
    description: str,
    default: str | int | None = None,
    repeatable: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "required": required,
        "description": description,
    }
    if default is not None:
        payload["default"] = default
    if repeatable:
        payload["repeatable"] = True
    return payload


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
    runtime_contract: Dict[str, Any] | None = None,
    input_json_template: Dict[str, Any] | None = None,
    template_execution: str | None = None,
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
        "cli_template_policy": {
            "execution": template_execution or ("run_all" if len(cli_templates) > 1 else "run_single"),
            "optional_arguments": [
                item["name"] for item in arguments if item.get("required") is False
            ],
            "repeatable_arguments": [
                item["name"] for item in arguments if item.get("repeatable") is True
            ],
            "optional_placeholder_rule": (
                "If an optional placeholder is unresolved or empty, omit that argv token; "
                "if the previous argv token is the option flag for that placeholder, omit the flag too."
            ),
            "repeatable_placeholder_rule": (
                "For repeatable placeholders, emit one flag/value pair per value rather than joining."
            ),
        },
    }
    if notes:
        payload["notes"] = notes
    if operation_request:
        payload["operation_request"] = operation_request
    if runtime_contract:
        payload["runtime_contract"] = runtime_contract
    if input_json_template:
        payload["input_json_template"] = input_json_template
        payload["input_json_policy"] = {
            "target_flag": "--input-json",
            "serialization": "json_object_argv_value",
            "omit_unresolved_optional_keys": True,
        }
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
            [
                _arg(
                    "hermes_wrapper_command",
                    False,
                    "Hermes wrapper command visible inside the runtime.",
                    default="wsa-hermes-cli",
                ),
            ],
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
            "/wsa_startup",
            ["/wsa-startup", "/wsa_open_startup"],
            "Start or continue the open-ended startup interview.",
            "open_startup_interview",
            "startup",
            "workspace_mutating",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("budget", False, "Maximum startup questions for this round. Default: 4.", default=4),
            ],
            [
                ["wsa", "world", "startup", "status", "{world_id}", "--format", "json"],
                [
                    "wsa",
                    "world",
                    "startup",
                    "interview",
                    "{world_id}",
                    "--budget",
                    "{budget:4}",
                    "--format",
                    "json",
                ],
            ],
            [
                "This command may create or update startup_profile.json; do not run during update.lock.",
                "Use at most three choices per question and encourage longer free-text author answers.",
            ],
        ),
        _command(
            "/wsa_easystartup",
            ["/wsa-easystartup", "/wsa_easystart", "/wsa-easystart"],
            "Start or continue the easy-pick startup interview.",
            "easy_pick_startup_interview",
            "startup",
            "workspace_mutating",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("budget", False, "Maximum easy-pick questions for this round. Default: 8.", default=8),
            ],
            [
                ["wsa", "world", "easystartup", "status", "{world_id}", "--format", "json"],
                [
                    "wsa",
                    "world",
                    "easystartup",
                    "interview",
                    "{world_id}",
                    "--budget",
                    "{budget:8}",
                    "--format",
                    "json",
                ],
            ],
            [
                "This command may create or update startup_profile.json; do not run during update.lock.",
                "Offer five to eight easy-pick choices per question and let Hermes fill details according to discretion level.",
                "Hermes should keep returning to the interview with progress unless the user stops it.",
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
                _arg("question_id", True, "Startup question ID such as 0001."),
                _arg("text", True, "Author-approved answer text."),
            ],
            [
                [
                    "wsa",
                    "world",
                    "startup",
                    "answer",
                    "{world_id}",
                    "{question_id}",
                    "--text",
                    "{text}",
                    "--format",
                    "json",
                ],
                [
                    "wsa",
                    "world",
                    "easystartup",
                    "answer",
                    "{world_id}",
                    "{question_id}",
                    "--text",
                    "{text}",
                    "--format",
                    "json",
                ],
            ],
            [
                "Hermes chooses the startup or easystartup answer endpoint based on the active interview mode.",
            ],
            template_execution="choose_one_by_active_mode",
        ),
        _command(
            "/wsa_pick",
            ["/wsa-pick", "/wsa_batch_answer", "/wsa-batch-answer"],
            "Record parallel startup choices such as 0001a 0002b plus notes.",
            "record_parallel_startup_choices",
            "startup",
            "requires_approval",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("text", True, "Answer text containing codes such as 0001a 0002b."),
            ],
            [
                [
                    "wsa",
                    "world",
                    "startup",
                    "batch-answer",
                    "{world_id}",
                    "--text",
                    "{text}",
                    "--format",
                    "json",
                ],
                [
                    "wsa",
                    "world",
                    "easystartup",
                    "batch-answer",
                    "{world_id}",
                    "--text",
                    "{text}",
                    "--format",
                    "json",
                ],
            ],
            [
                "Hermes chooses the startup or easystartup batch endpoint based on the active interview mode.",
            ],
            template_execution="choose_one_by_active_mode",
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
                _arg("discretion", False, "Discretion level from 0 to 5. Default decided by Hermes/user dialogue."),
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
                "Discretion level 5 requires a destination checkpoint before cron automation starts.",
            ],
        ),
        _command(
            "/wsa_update",
            ["/wsa-update", "/wsa_upgrade", "/wsa-upgrade"],
            "Run update preflight before a Hermes-owned WSA source upgrade.",
            "preflight_wsa_update",
            "operations",
            "read_only",
            [
                _arg(
                    "source_root",
                    False,
                    "WSA source checkout or package root to inspect before update. Pass explicitly when known.",
                ),
            ],
            [
                [
                    "wsa",
                    "update",
                    "preflight",
                    "--source-root",
                    "{source_root}",
                    "--format",
                    "json",
                ]
            ],
            [
                "This command does not pull, overwrite, migrate, or delete files.",
                "If Hermes runs from the workspace root, pass the installed WSA source root explicitly or omit source_root.",
                "Hermes should run this before and after any runtime-owned source update.",
                "If preflight blocks, Hermes should stop update automation and report the blocking condition.",
            ],
        ),
        _command(
            "/wsa_update_backup",
            ["/wsa-update-backup", "/wsa_backup", "/wsa-backup"],
            "Create a workspace backup before a Hermes-owned WSA source upgrade.",
            "backup_before_wsa_update",
            "operations",
            "requires_approval",
            [
                _arg(
                    "output_dir",
                    True,
                    "Directory outside the workspace where the backup folder will be created.",
                ),
                _arg(
                    "source_root",
                    False,
                    "WSA source checkout or package root to inspect before backup. Pass explicitly when known.",
                ),
            ],
            [
                [
                    "wsa",
                    "update",
                    "backup",
                    "--output-dir",
                    "{output_dir}",
                    "--source-root",
                    "{source_root}",
                    "--format",
                    "json",
                ]
            ],
            [
                "This command creates a backup artifact only; it does not pull, overwrite, migrate, or delete source files.",
                "If Hermes runs from the workspace root, pass the installed WSA source root explicitly or omit source_root.",
                "Hermes should run update preflight before and after backup, then request approval for any source update command.",
            ],
        ),
        _command(
            "/wsa_orchestrator",
            ["/wsa-orchestrator", "/wsa_meetup", "/wsa-meetup"],
            "Run a manual-trigger autonomous orchestrator workflow.",
            "run_autonomous_orchestrator",
            "orchestrator",
            "proposal_only",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("workflow", False, "Workflow type such as meetup. Default: meetup.", default="meetup"),
                _arg(
                    "skill",
                    False,
                    "Hermes skill shortcut scope such as meetup or scene_start. Default: workflow.",
                    default="meetup",
                ),
                _arg("topic", True, "Topic or high-level request to orchestrate."),
                _arg("question", False, "Question to resolve during orchestration."),
                _arg("rounds", False, "Internal round budget. Default: 2.", default=2),
                _arg(
                    "max_queue_turns",
                    False,
                    "Maximum autonomous queue turns before stopping. Default: 12.",
                    default=DEFAULT_MAX_QUEUE_TURNS,
                ),
                _arg(
                    "max_concurrent_subsessions",
                    False,
                    "Maximum simultaneous subsessions before Hermes should batch work. Default: 4.",
                    default=DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
                ),
                _arg(
                    "max_subsession_calls",
                    False,
                    "Maximum total subsession calls before partial report. Default: 48.",
                    default=DEFAULT_MAX_SUBSESSION_CALLS,
                ),
                _arg(
                    "context_policy",
                    False,
                    "Context carry-forward policy. Default: compressed-continuity.",
                    default=DEFAULT_CONTEXT_POLICY,
                ),
                _arg(
                    "frame_plan",
                    False,
                    "Optional user-defined plan/frame. Conservative default guardrail is used when omitted.",
                ),
                _arg(
                    "termination_policy",
                    False,
                    "Termination policy. Default: chair_or_conclusion_or_queue_limit.",
                    default=DEFAULT_TERMINATION_POLICY,
                ),
                _arg(
                    "participant",
                    False,
                    "Participant/viewpoint. May be repeated by Hermes.",
                    repeatable=True,
                ),
            ],
            [
                [
                    "wsa",
                    "orchestrator",
                    "run",
                    "{world_id}",
                    "--workflow",
                    "{workflow:meetup}",
                    "--skill",
                    "{skill:meetup}",
                    "--topic",
                    "{topic}",
                    "--question",
                    "{question:Synthesize proposals, conflicts, gaps, and approval options.}",
                    "--rounds",
                    "{rounds:2}",
                    "--max-queue-turns",
                    "{max_queue_turns:12}",
                    "--max-concurrent-subsessions",
                    "{max_concurrent_subsessions:4}",
                    "--max-subsession-calls",
                    "{max_subsession_calls:48}",
                    "--context-policy",
                    f"{{context_policy:{DEFAULT_CONTEXT_POLICY}}}",
                    "--frame-plan",
                    "{frame_plan}",
                    "--termination-policy",
                    f"{{termination_policy:{DEFAULT_TERMINATION_POLICY}}}",
                    "--participant",
                    "{participant}",
                    "--subsession-policy",
                    "ephemeral",
                    "--canon-policy",
                    "proposal-only",
                    "--approval",
                    "required",
                    "--close-on",
                    "complete",
                ]
            ],
            [
                "Manual trigger, then autonomous execution until review boundary or max queue turns.",
                "WSA declares the orchestration contract and audit artifact; Hermes owns actual subagent invocation.",
                "The template CLI produces local simulated subsession outputs unless a Hermes runtime uses the prompt packets to run real subagents.",
                "Hermes should preserve a compressed meeting context inside this run and adapt prompt packets to its subagent syntax.",
                "Hermes should not start without a plan/frame and hard limits; WSA supplies conservative defaults when the user has not customized them.",
                "Prep review is default-on in bridge mode; inspect prep_report and run wsa orchestrator prep-approve before actor/subagent calls unless the user opted out.",
                "Treat the run as a live meeting floor: participants receive compressed continuity until the chair closes it or a hard limit stops it.",
                "Subsession prompts should be short and precise; accumulate only outputs that pass the quality gate.",
                "Temporary subsessions are closed after the report package is created.",
                "Generated material stays proposal-only until explicit author approval.",
            ],
            runtime_contract=build_hermes_orchestrator_runtime_contract(),
        ),
        _command(
            "/wsa_scene_start",
            ["/wsa-scene-start", "/scene-start", "/wsa_scene_prep", "/wsa-scene-prep"],
            "Prepare a scene-generation lifecycle through the WSA orchestrator.",
            "run_scene_generation_orchestrator",
            "orchestrator",
            "proposal_only",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg("topic", True, "Scene or scene-prep topic."),
                _arg(
                    "question",
                    False,
                    "Scene-prep question to resolve before drafting.",
                    default=(
                        "Prepare scene facts, actor assignments, role isolation, "
                        "model/thinking guidance, and approval choices."
                    ),
                ),
                _arg("rounds", False, "Internal round budget. Default: 3.", default=3),
                _arg(
                    "max_queue_turns",
                    False,
                    "Maximum autonomous queue turns before stopping. Default: 12.",
                    default=DEFAULT_MAX_QUEUE_TURNS,
                ),
                _arg(
                    "max_concurrent_subsessions",
                    False,
                    "Maximum simultaneous actor/subsession calls before batching. Default: 4.",
                    default=DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
                ),
                _arg(
                    "max_subsession_calls",
                    False,
                    "Maximum total actor/subsession calls before partial report. Default: 48.",
                    default=DEFAULT_MAX_SUBSESSION_CALLS,
                ),
                _arg(
                    "frame_plan",
                    False,
                    "Optional user-defined scene frame, viewpoint, location, timeframe, or guardrail.",
                ),
                _arg("time_scope", False, "Optional scene time scope."),
                _arg("location_scope", False, "Optional scene location scope."),
                _arg("viewpoint", False, "Optional viewpoint or POV scope."),
                _arg(
                    "condition",
                    False,
                    "Optional scene selection condition. May be repeated.",
                    repeatable=True,
                ),
                _arg(
                    "participant",
                    False,
                    "Actor, narrator, crowd, continuity role, or scene-prep viewpoint. May be repeated.",
                    repeatable=True,
                ),
                _arg(
                    "run_id",
                    False,
                    "Run ID returned by the start command; used when approving prep or fetching hook packets.",
                ),
            ],
            [
                [
                    "wsa",
                    "scene",
                    "start",
                    "{world_id}",
                    "--topic",
                    "{topic}",
                    "--question",
                    "{question:Prepare scene facts, actor assignments, role isolation, model/thinking guidance, and approval choices.}",
                    "--rounds",
                    "{rounds:3}",
                    "--max-queue-turns",
                    "{max_queue_turns:12}",
                    "--max-concurrent-subsessions",
                    "{max_concurrent_subsessions:4}",
                    "--max-subsession-calls",
                    "{max_subsession_calls:48}",
                    "--frame-plan",
                    "{frame_plan}",
                    "--time-scope",
                    "{time_scope}",
                    "--location-scope",
                    "{location_scope}",
                    "--viewpoint",
                    "{viewpoint}",
                    "--condition",
                    "{condition}",
                    "--participant",
                    "{participant}",
                    "--format",
                    "json",
                ],
                ["wsa", "orchestrator", "prep-approve", "{run_id}", "--format", "json"],
                ["wsa", "orchestrator", "next", "{run_id}", "--format", "json"],
            ],
            [
                "Manual trigger for scene-prep, not direct script canonization.",
                "The first template starts the run and returns a prep review report by default.",
                "The second template approves the prep report and opens the first Hermes actor hook for a returned run_id.",
                "The third template remains available when Hermes needs to fetch the next hook for a returned run_id.",
                "Scene prep should filter facts/history/memory by viewpoint, cross-check contradictions, assign actors, isolate multi-role sessions, recommend model/thinking levels, and stop at approval boundary.",
                "Hermes owns actual actor/subagent calls. WSA records prompt packets, floor state, turn records, quality gates, and approval package.",
            ],
            runtime_contract=build_hermes_orchestrator_runtime_contract(),
            input_json_template={
                "workflow": "scene_generation",
                "skill": "scene_start",
                "topic": "{topic}",
                "question": "{question:Prepare scene facts, actor assignments, role isolation, model/thinking guidance, and approval choices.}",
                "frame_plan": "{frame_plan}",
                "time_scope": "{time_scope}",
                "location_scope": "{location_scope}",
                "viewpoint": "{viewpoint}",
                "condition": "{condition}",
                "participant": "{participant}",
                "boundary": "prep_package_before_scene_draft_or_canon_mutation",
            },
            template_execution="run_scene_start_then_review_prep_then_fetch_next_hook_by_run_id",
        ),
        _command(
            "/wsa_orchestrator_decide",
            ["/wsa-orchestrator-decide", "/wsa_meetup_decide", "/wsa-meetup-decide"],
            "Approve, retry, or hold an orchestrator package.",
            "decide_autonomous_orchestrator",
            "orchestrator",
            "requires_approval",
            [
                _arg("run_id", True, "Orchestrator run ID."),
                _arg("decision", True, "One of approve, retry, or hold."),
                _arg("option", False, "Approved option ID, such as option-a."),
            ],
            [
                [
                    "wsa",
                    "orchestrator",
                    "decide",
                    "{run_id}",
                    "--decision",
                    "{decision}",
                    "--option",
                    "{option}",
                ]
            ],
            [
                "Approval creates a candidate ticket only; canon mutation remains a later explicit step.",
            ],
        ),
        _command(
            "/fill_the_rest",
            ["/fill-the-rest", "/filltherest", "/wsa_fill_the_rest", "/wsa-fill-the-rest"],
            "Prepare lower-layer fill work until a destination checkpoint.",
            "fill_remaining_lower_layer_candidates",
            "operations",
            "proposal_only",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg(
                    "destination",
                    True,
                    "Natural-language endpoint, such as 'until every region has factions and hooks'.",
                ),
                _arg("scope", False, "Optional area to fill. Can be initial, midstream, or late-stage."),
                _arg("discretion_level", False, "0-5 discretion level. Level 5 enables cron-capable automation."),
                _arg("cron_schedule", False, "Optional Hermes-owned cron schedule for level 5."),
                _arg("quality_bar", False, "Optional quality conditions Hermes must verify before stopping."),
            ],
            [
                [
                    "wsa",
                    "hermes",
                    "task",
                    "{world_id}",
                    "--task-type",
                    "fill_the_rest_plan",
                    "--title",
                    "Plan fill-the-rest pass",
                    "--instruction",
                    "{destination}",
                    "--background",
                ]
            ],
            [
                "Generates lower-layer candidate material only; it does not directly mutate canon.",
                "Can be used at initial setup, mid-project, or late-project cleanup.",
                "Compatibility command: Hermes should plan first, then use /filltherest_start after explicit approval for cron work.",
                "At discretion level 5 Hermes must ask for the destination checkpoint before preparing automation.",
                "Before completion, Hermes must diagnose whether the generated material actually satisfies the destination and quality bar.",
                "After completion, Hermes should request user approval before canon conversion.",
            ],
            runtime_contract=fill_the_rest_contract(),
            input_json_template={
                "destination": "{destination}",
                "scope": "{scope}",
                "discretion_level": "{discretion_level:5}",
                "cron_schedule": "{cron_schedule}",
                "quality_bar": "{quality_bar}",
                "quality_gate": "required_before_completion",
                "completion": "plan_only_no_cron",
            },
        ),
        _command(
            "/filltherest_plan",
            ["/filltherest-plan", "/fill-the-rest-plan", "/fillrest-plan", "/wsa_filltherest_plan"],
            "Plan a lower-layer fill pass without starting cron automation.",
            "plan_fill_remaining_lower_layer_candidates",
            "operations",
            "proposal_only",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg(
                    "destination",
                    True,
                    "Natural-language endpoint, such as 'until every region has factions and hooks'.",
                ),
                _arg("scope", False, "Optional area to fill. Can be initial, midstream, or late-stage."),
                _arg("discretion_level", False, "0-5 discretion level to evaluate for the plan."),
                _arg("quality_bar", False, "Optional quality conditions Hermes must verify before stopping."),
            ],
            [
                [
                    "wsa",
                    "hermes",
                    "task",
                    "{world_id}",
                    "--task-type",
                    "fill_the_rest_plan",
                    "--title",
                    "Plan fill-the-rest pass",
                    "--instruction",
                    "{destination}",
                    "--background",
                ]
            ],
            [
                "Read-only from the user's canon perspective: it produces a plan and candidate checklist.",
                "Hermes should report risks, stop conditions, and whether cron would be justified.",
            ],
            runtime_contract=fill_the_rest_contract(),
            input_json_template={
                "destination": "{destination}",
                "scope": "{scope}",
                "discretion_level": "{discretion_level:5}",
                "quality_bar": "{quality_bar}",
                "quality_gate": "required_before_completion",
                "completion": "plan_only_no_cron",
            },
        ),
        _command(
            "/filltherest_start",
            ["/filltherest-start", "/fill-the-rest-start", "/fillrest-start", "/wsa_filltherest_start"],
            "Start an approved cron-capable fill pass toward a destination checkpoint.",
            "start_fill_remaining_lower_layer_candidates",
            "operations",
            "requires_approval",
            [
                _arg("world_id", True, "World ID or active world selected by Hermes."),
                _arg(
                    "destination",
                    True,
                    "Natural-language endpoint, such as 'until every region has factions and hooks'.",
                ),
                _arg("scope", False, "Optional area to fill. Can be initial, midstream, or late-stage."),
                _arg("discretion_level", False, "0-5 discretion level. Level 5 enables cron-capable automation."),
                _arg("cron_schedule", False, "Hermes-owned cron schedule for level 5."),
                _arg("quality_bar", False, "Quality conditions Hermes must verify before stopping."),
            ],
            [
                [
                    "wsa",
                    "hermes",
                    "task",
                    "{world_id}",
                    "--task-type",
                    "fill_the_rest_start",
                    "--title",
                    "Start fill-the-rest pass",
                    "--instruction",
                    "{destination}",
                    "--session-mode",
                    "cron",
                    "--runtime-source",
                    "cron",
                    "--background",
                ]
            ],
            [
                "Requires explicit user approval before Hermes starts cron-capable work.",
                "When the destination is met, Hermes must stop the cron job and explicitly report that it stopped.",
                "Before completion, Hermes must diagnose whether the generated material actually satisfies the destination and quality bar.",
                "After completion, Hermes should request user approval before canon conversion.",
            ],
            runtime_contract=fill_the_rest_contract(),
            input_json_template={
                "destination": "{destination}",
                "scope": "{scope}",
                "discretion_level": "{discretion_level:5}",
                "cron_schedule": "{cron_schedule}",
                "quality_bar": "{quality_bar}",
                "quality_gate": "required_before_completion",
                "completion": "stop_cron_then_report_and_request_approval",
            },
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
                _arg(
                    "participant",
                    False,
                    "Participant/viewpoint. May be repeated by Hermes.",
                    repeatable=True,
                ),
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
