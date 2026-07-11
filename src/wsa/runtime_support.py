from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple, Type

from .hermes_adapter import (
    CALLBACK_ROUTE_KEYS,
    HERMES_CALLBACK_SCHEMA,
    callback_route_digest,
    validate_orchestrator_dispatch_receipt,
)


_ErrorType = Type[ValueError]


def dispatch_plan_payload(plan: Any, schema: str) -> Dict[str, Any]:
    return {
        "schema": schema,
        "run_id": plan.run_id,
        "turn_id": plan.turn_id,
        "dispatch_status": "ready" if plan.runtime_available else "no_runtime",
        "argv": list(plan.argv),
        "workdir": str(plan.workdir),
        "route_digest": plan.route_digest,
        "timeout_seconds": plan.timeout_seconds,
        "capability_negotiation": {
            "state": "pending_runtime_response",
            "required": list(plan.required_capabilities),
        },
        "limits": {
            "input_bytes": plan.input_bytes,
            "max_input_bytes": plan.max_input_bytes,
            "max_output_bytes": plan.max_output_bytes,
        },
        "environment": {
            "inheritance": "minimal_allowlist_only",
            "inherited_value_count": plan.inherited_environment_count,
            "caller_value_count": plan.caller_environment_count,
            "values_recorded": False,
        },
        "side_effect": {
            "plan": "read_only_no_process_started",
            "execute": "start_one_caller_configured_stdio_process",
            "callback_artifact": "not_written_by_runtime_adapter",
            "world_mutation": "none",
            "canon_mutation": "forbidden",
        },
        "side_effect_status": plan.side_effect_status,
        "provider_configuration": "external_to_wsa_core",
    }


def execution_result_payload(result: Any, schema: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema": schema,
        "status": result.status,
        "run_id": result.run_id,
        "turn_id": result.turn_id,
        "duration_ms": result.duration_ms,
        "process_started": result.process_started,
        "returncode": result.returncode,
        "callback_present": result.callback is not None,
        "capability_negotiation": result.capability_negotiation.to_dict(),
        "diagnostics": {
            "stdout_bytes": result.stdout_bytes,
            "stderr_bytes": result.stderr_bytes,
            "process_output_recorded": False,
        },
        "side_effect": {
            "callback_artifact_written": False,
            "canon_mutation_performed": False,
            "secret_values_recorded": False,
        },
    }
    if result.error_code is not None:
        payload["error"] = {
            "code": result.error_code,
            "message": result.error_message,
        }
    return payload


def validate_hook(
    hook: Dict[str, Any],
    error_type: _ErrorType,
) -> Tuple[str, str, str]:
    if not isinstance(hook, dict):
        raise error_type("runtime hook must be an object")
    if hook.get("schema") != "wsa.orchestrator.round_prompt_packet.v1":
        raise error_type(f"unsupported runtime hook schema: {hook.get('schema')}")
    run_id = required_text(hook, "run_id", "runtime hook", error_type)
    turn_id = required_text(hook, "turn_id", "runtime hook", error_type)
    route = hook.get("expected_callback_route")
    if not isinstance(route, dict):
        raise error_type("runtime hook requires expected_callback_route")
    expected_digest = callback_route_digest(route)
    dispatch_contract = hook.get("dispatch_contract")
    if not isinstance(dispatch_contract, dict):
        raise error_type("runtime hook requires dispatch_contract")
    route_digest = required_text(
        dispatch_contract,
        "route_digest",
        "dispatch contract",
        error_type,
    )
    if route_digest != expected_digest:
        raise error_type(
            "runtime hook route digest does not match expected callback route"
        )
    terminal_command = hook.get("terminal_command")
    if not isinstance(terminal_command, dict):
        raise error_type("runtime hook requires terminal_command")
    generated_argv = terminal_command.get("argv")
    if not isinstance(generated_argv, list) or not generated_argv:
        raise error_type("runtime hook terminal command requires argv")
    return run_id, turn_id, route_digest


def callback_capabilities(
    callback: Dict[str, Any],
    *,
    response_schema: str,
    protocol_schema: str,
    error_type: _ErrorType,
) -> Tuple[str, ...]:
    metadata = callback.get("runtime_adapter")
    if metadata is None:
        metadata = callback.get("runtime_capabilities")
    if metadata is None:
        return ()
    if not isinstance(metadata, dict):
        raise error_type("runtime capability response must be an object")
    if metadata.get("schema") != response_schema:
        raise error_type("unsupported runtime capability response schema")
    if metadata.get("protocol") != protocol_schema:
        raise error_type("runtime capability protocol does not match")
    capabilities = metadata.get("capabilities")
    if not isinstance(capabilities, list):
        raise error_type("runtime capabilities must be an array")
    return normalized_capabilities(capabilities, error_type)


def validate_callback_binding(
    callback: Dict[str, Any],
    plan: Any,
    error_type: _ErrorType,
) -> None:
    if callback.get("schema") != HERMES_CALLBACK_SCHEMA:
        raise error_type(f"unsupported callback schema: {callback.get('schema')}")
    if callback.get("status", "completed") != "completed":
        raise error_type("runtime callback status must be completed")
    callback_id = required_text(
        callback,
        "callback_id",
        "runtime callback",
        error_type,
    )
    task_id = required_text(
        callback,
        "task_id",
        "runtime callback",
        error_type,
    )
    if not callback_id or not task_id:
        raise error_type("runtime callback identifiers are required")
    receipt = callback.get("dispatch_receipt")
    if not isinstance(receipt, dict):
        raise error_type("callback dispatch_receipt must be an object")
    validate_orchestrator_dispatch_receipt(receipt)
    if receipt.get("run_id") != plan.run_id:
        raise error_type("callback receipt run_id does not match hook")
    if receipt.get("turn_id") != plan.turn_id:
        raise error_type("callback receipt turn_id does not match hook")
    if receipt.get("task_id") != task_id:
        raise error_type("callback task_id does not match receipt")
    if receipt.get("route_digest") != plan.route_digest:
        raise error_type("callback receipt route digest does not match hook")

    route = callback.get("route")
    if not isinstance(route, dict):
        raise error_type("runtime callback route must be an object")
    if callback_route_digest(route) != plan.route_digest:
        raise error_type("callback route digest does not match hook")
    hook = json.loads(plan._stdin_json)
    expected_route = hook.get("expected_callback_route") or {}
    for key in CALLBACK_ROUTE_KEYS:
        if route.get(key) != expected_route.get(key):
            raise error_type(f"callback {key} does not match hook")

    payload = callback.get("payload")
    if not isinstance(payload, dict):
        raise error_type("runtime callback payload must be an object")
    if payload.get("run_id") != plan.run_id:
        raise error_type("callback payload run_id does not match hook")
    if payload.get("turn_id") != plan.turn_id:
        raise error_type("callback payload turn_id does not match hook")
    if not isinstance(payload.get("output"), dict):
        raise error_type("runtime callback payload output must be an object")


def communicate_process(
    process: subprocess.Popen,
    *,
    stdin_json: str,
    timeout_seconds: float,
    cancellation: Optional[Any],
    cancellation_token_type: Type[Any],
    start: float,
    clock: Callable[[], float] = time.monotonic,
) -> Tuple[str, str, str]:
    deadline = start + timeout_seconds
    first_input: Optional[str] = stdin_json
    while True:
        if is_cancelled(cancellation, cancellation_token_type):
            stdout, stderr = terminate_process(process)
            return "cancelled", stdout, stderr
        remaining = deadline - clock()
        if remaining <= 0:
            stdout, stderr = terminate_process(process)
            return "timeout", stdout, stderr
        wait_for = min(remaining, 0.05) if cancellation is not None else remaining
        try:
            stdout, stderr = process.communicate(input=first_input, timeout=wait_for)
            return "completed", stdout or "", stderr or ""
        except subprocess.TimeoutExpired:
            first_input = None


def terminate_process(process: subprocess.Popen) -> Tuple[str, str]:
    if process.poll() is None:
        process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    return stdout or "", stderr or ""


def is_cancelled(
    value: Optional[Any],
    cancellation_token_type: Type[Any],
) -> bool:
    if value is None:
        return False
    if isinstance(value, cancellation_token_type):
        return value.cancelled
    is_set = getattr(value, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    is_cancelled_value = getattr(value, "is_cancelled", None)
    if callable(is_cancelled_value):
        return bool(is_cancelled_value())
    if isinstance(is_cancelled_value, bool):
        return is_cancelled_value
    if callable(value):
        return bool(value())
    return bool(value)


def execution_environment(
    inherited_names: Sequence[str],
    caller_environment: Mapping[str, str],
) -> Dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in inherited_names
        if key in os.environ
    }
    environment.update(caller_environment)
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    return environment


def build_execution_result(
    result_type: Any,
    plan: Any,
    *,
    status: str,
    start: Optional[float],
    process_started: bool,
    negotiation: Any,
    completed_status: str,
    clock: Callable[[], float] = time.monotonic,
    returncode: Optional[int] = None,
    callback: Optional[Dict[str, Any]] = None,
    stdout: str = "",
    stderr: str = "",
    error_message: Optional[str] = None,
) -> Any:
    duration_ms = 0 if start is None else max(0, int((clock() - start) * 1000))
    return result_type(
        status=status,
        run_id=plan.run_id,
        turn_id=plan.turn_id,
        duration_ms=duration_ms,
        process_started=process_started,
        returncode=returncode,
        capability_negotiation=negotiation,
        callback=callback,
        error_code=None if status == completed_status else status,
        error_message=error_message,
        stdout_bytes=len(stdout.encode("utf-8")),
        stderr_bytes=len(stderr.encode("utf-8")),
    )


def json_object_copy(
    value: Dict[str, Any],
    error_type: _ErrorType,
) -> Dict[str, Any]:
    try:
        copied = json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise error_type("runtime hook must be JSON serializable") from exc
    if not isinstance(copied, dict):
        raise error_type("runtime hook must be a JSON object")
    return copied


def required_text(
    value: Dict[str, Any],
    key: str,
    label: str,
    error_type: _ErrorType,
) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise error_type(f"{label} requires {key}")
    return item


def validate_timeout(value: float, error_type: _ErrorType) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise error_type("timeout_seconds must be a positive number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise error_type("timeout_seconds must be a positive number")
    return timeout


def positive_limit(value: int, label: str, error_type: _ErrorType) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise error_type(f"{label} must be a positive integer")
    return value


def validate_argv(
    argv: Sequence[str],
    error_type: _ErrorType,
) -> Tuple[str, ...]:
    validated = []
    for value in argv:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise error_type("argv entries must be non-empty strings without NUL")
        validated.append(value)
    return tuple(validated)


def validate_environment(
    environment: Mapping[str, str],
    error_type: _ErrorType,
) -> Dict[str, str]:
    validated: Dict[str, str] = {}
    for key, value in environment.items():
        if not isinstance(key, str) or not key or "=" in key or "\x00" in key:
            raise error_type("environment names must be non-empty strings")
        if not isinstance(value, str) or "\x00" in value:
            raise error_type("environment values must be strings without NUL")
        validated[key] = value
    return validated


def validate_environment_names(
    names: Sequence[str],
    error_type: _ErrorType,
) -> Tuple[str, ...]:
    result = []
    seen = set()
    for name in names:
        if not isinstance(name, str) or not name or "=" in name or "\x00" in name:
            raise error_type(
                "inherited environment names must be non-empty strings"
            )
        if name not in seen:
            result.append(name)
            seen.add(name)
    return tuple(result)


def normalized_capabilities(
    values: Sequence[str],
    error_type: _ErrorType,
) -> Tuple[str, ...]:
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise error_type("capability names must be non-empty strings")
        normalized = value.strip()
        if normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return tuple(result)


def redacted_argv(argv: Sequence[str]) -> Tuple[str, ...]:
    redacted = []
    redact_next = False
    for value in argv:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if value.startswith("-"):
            name, separator, _ = value.partition("=")
            if _looks_secret_name(name):
                redacted.append(f"{name}=<redacted>" if separator else name)
                redact_next = not separator
                continue
        if "=" in value and _looks_secret_name(value.split("=", 1)[0]):
            redacted.append(f"{value.split('=', 1)[0]}=<redacted>")
            continue
        redacted.append(re.sub(r"(https?://)[^/@\s]+@", r"\1<redacted>@", value))
    return tuple(redacted)


def _looks_secret_name(value: str) -> bool:
    parts = {
        item
        for item in re.split(r"[^a-z0-9]+", value.casefold().lstrip("-"))
        if item
    }
    return bool(parts & {"credential", "credentials", "key", "password", "secret", "token"})
