from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from .autonomy import discretion_scale_contract, fill_the_rest_contract
from .command_specs import canonical_menu_surface
from .hermes_command_catalog import _default_commands
from .hermes_command_constants import (
    HERMES_COMMAND_OVERLAY_REPORT_SCHEMA,
    HERMES_COMMAND_REGISTRY_FILENAME,
    HERMES_COMMAND_REGISTRY_SCHEMA,
    HERMES_LOCAL_COMMAND_REGISTRY_FILENAME,
    HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA,
    KNOWN_COMMAND_SAFETIES,
    LOCAL_COMMAND_MUTATING_SAFETIES,
    LOCAL_COMMAND_RESERVED_PREFIXES,
)
from .hermes_command_overlays import (
    build_local_command_registry_template,
    command_lookup_keys,
    empty_local_command_overlay_report,
    format_local_command_overlay_report,
    merge_hermes_command_registries,
    validate_local_command_registry,
    validate_local_command_registry_report,
    write_hermes_local_command_registry_template,
)
from .reporting_contract import build_reporting_artifact_contract

__all__ = [
    "HERMES_COMMAND_OVERLAY_REPORT_SCHEMA",
    "HERMES_COMMAND_REGISTRY_FILENAME",
    "HERMES_COMMAND_REGISTRY_SCHEMA",
    "HERMES_LOCAL_COMMAND_REGISTRY_FILENAME",
    "HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA",
    "KNOWN_COMMAND_SAFETIES",
    "LOCAL_COMMAND_MUTATING_SAFETIES",
    "LOCAL_COMMAND_RESERVED_PREFIXES",
    "build_hermes_command_registry",
    "build_local_command_registry_template",
    "command_lookup_keys",
    "empty_local_command_overlay_report",
    "format_hermes_commands",
    "format_local_command_overlay_report",
    "merge_hermes_command_registries",
    "validate_local_command_registry",
    "validate_local_command_registry_report",
    "write_hermes_command_registry",
    "write_hermes_local_command_registry_template",
]


def build_hermes_command_registry(compact: bool = False) -> Dict[str, Any]:
    registry = {
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
        "canonical_menu_surface": canonical_menu_surface(),
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
        "reporting_artifact_policy": build_reporting_artifact_contract(),
        "discretion_policy": {
            "customizable": True,
            "scale": discretion_scale_contract(),
            "level_5_requires_destination_checkpoint": True,
        },
        "fill_the_rest": fill_the_rest_contract(),
        "commands": _default_commands(),
    }
    return _compact_registry(registry) if compact else registry
def _canonical_menu_surface() -> Dict[str, Any]:
    """Compatibility wrapper for callers that imported the old private helper."""

    return canonical_menu_surface()
def _compact_registry(registry: Dict[str, Any]) -> Dict[str, Any]:
    commands = []
    for command in registry["commands"]:
        compact_command = {
            key: command[key]
            for key in (
                "command",
                "aliases",
                "title",
                "intent",
                "category",
                "safety",
                "arguments",
                "cli_templates",
                "execution_policy",
                "cli_template_policy",
            )
            if key in command
        }
        for key in ("runtime_contract", "input_json_template", "operation_request"):
            if key in command:
                compact_command[f"{key}_ref"] = {
                    "schema": "wsa.hermes.inline_contract_ref.v1",
                    "digest": _payload_digest(command[key]),
                    "source": "build_hermes_command_registry(compact=False)",
                }
        commands.append(compact_command)
    return {
        "schema": "wsa.hermes.command_registry.compact.v1",
        "schema_version": registry["schema_version"],
        "owner": registry["owner"],
        "purpose": registry["purpose"],
        "canonical_menu_surface": registry["canonical_menu_surface"],
        "commands": commands,
        "expansion": {
            "installed_builder": "wsa.hermes_commands.build_hermes_command_registry",
            "compact_argument": False,
        },
    }
def _payload_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
def write_hermes_command_registry(
    path: Path,
    overwrite: bool = False,
    compact: bool = False,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return path
    payload = build_hermes_command_registry(compact=compact)
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
