from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .hermes_command_constants import (
    HERMES_COMMAND_OVERLAY_REPORT_SCHEMA,
    HERMES_LOCAL_COMMAND_REGISTRY_SCHEMA,
    KNOWN_COMMAND_SAFETIES,
    LOCAL_COMMAND_MUTATING_SAFETIES,
    LOCAL_COMMAND_RESERVED_PREFIXES,
)


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
    if base_registry is None:
        from .hermes_commands import build_hermes_command_registry

        base = build_hermes_command_registry()
    else:
        base = base_registry
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
