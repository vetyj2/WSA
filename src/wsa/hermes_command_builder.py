from __future__ import annotations

from typing import Any, Dict, List

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
