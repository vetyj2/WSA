from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from . import runtime_support as _support
from .hermes_adapter import (
    CALLBACK_ROUTE_KEYS as CALLBACK_ROUTE_KEYS,
    HERMES_CALLBACK_SCHEMA as HERMES_CALLBACK_SCHEMA,
    callback_route_digest as callback_route_digest,
    validate_orchestrator_dispatch_receipt as validate_orchestrator_dispatch_receipt,
)


STDIO_RUNTIME_PROTOCOL_SCHEMA = "wsa.runtime_adapter.stdio.v1"
RUNTIME_ADAPTER_REQUEST_SCHEMA = "wsa.runtime_adapter.request.v1"
RUNTIME_CAPABILITY_RESPONSE_SCHEMA = "wsa.runtime_adapter.capability_response.v1"
RUNTIME_DISPATCH_PLAN_SCHEMA = "wsa.runtime_adapter.dispatch_plan.v1"
RUNTIME_EXECUTION_RESULT_SCHEMA = "wsa.runtime_adapter.execution_result.v1"

CAPABILITY_STDIO_SINGLE_HOOK = "stdio_single_hook_json"
CAPABILITY_CALLBACK_JSON = "hermes_callback_json_v1"
CAPABILITY_DISPATCH_RECEIPT = "orchestrator_dispatch_receipt_v1"
CAPABILITY_CANCELLATION = "process_cancellation"
DEFAULT_REQUIRED_CAPABILITIES = (
    CAPABILITY_STDIO_SINGLE_HOOK,
    CAPABILITY_CALLBACK_JSON,
    CAPABILITY_DISPATCH_RECEIPT,
    CAPABILITY_CANCELLATION,
)

DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_HOOK_BYTES = 256 * 1024
DEFAULT_MAX_CALLBACK_BYTES = 256 * 1024
MINIMAL_INHERITED_ENV_KEYS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "WINDIR",
)

EXECUTION_COMPLETED = "completed"
EXECUTION_TIMEOUT = "timeout"
EXECUTION_NONZERO_EXIT = "nonzero_exit"
EXECUTION_MALFORMED_JSON = "malformed_json"
EXECUTION_MALFORMED_CALLBACK = "malformed_callback"
EXECUTION_CAPABILITY_MISMATCH = "capability_mismatch"
EXECUTION_CANCELLED = "cancelled"
EXECUTION_NO_RUNTIME = "no_runtime"
EXECUTION_OUTPUT_TOO_LARGE = "output_too_large"
EXECUTION_LAUNCH_FAILED = "launch_failed"


class RuntimeAdapterError(ValueError):
    """Raised when a runtime adapter is configured or called incorrectly."""


class RuntimeAdapterProtocolError(RuntimeAdapterError):
    """Raised when a hook cannot be represented by the stdio protocol."""


class CancellationToken:
    """Thread-safe cooperative cancellation token for an adapter execution."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def is_set(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class CapabilityNegotiation:
    required: Tuple[str, ...]
    offered: Tuple[str, ...] = ()
    state: str = "pending"

    @property
    def missing(self) -> Tuple[str, ...]:
        offered = set(self.offered)
        return tuple(item for item in self.required if item not in offered)

    @classmethod
    def from_offered(
        cls,
        required: Sequence[str],
        offered: Sequence[str],
    ) -> "CapabilityNegotiation":
        required_tuple = _support.normalized_capabilities(
            required,
            RuntimeAdapterProtocolError,
        )
        offered_tuple = _support.normalized_capabilities(
            offered,
            RuntimeAdapterProtocolError,
        )
        missing = set(required_tuple) - set(offered_tuple)
        return cls(
            required=required_tuple,
            offered=offered_tuple,
            state="rejected" if missing else "accepted",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": RUNTIME_CAPABILITY_RESPONSE_SCHEMA,
            "state": self.state,
            "required": list(self.required),
            "offered": list(self.offered),
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class DispatchPlan:
    """A read-only preview of one possible stdio runtime dispatch."""

    run_id: str
    turn_id: str
    argv: Tuple[str, ...]
    workdir: Path
    route_digest: str
    timeout_seconds: float
    required_capabilities: Tuple[str, ...]
    input_bytes: int
    max_input_bytes: int
    max_output_bytes: int
    runtime_available: bool
    inherited_environment_count: int
    caller_environment_count: int
    _stdin_json: str = field(repr=False, compare=False)
    _adapter_identity: object = field(repr=False, compare=False)

    @property
    def side_effect_status(self) -> str:
        return "read_only_no_process_started"

    def to_dict(self) -> Dict[str, Any]:
        return _support.dispatch_plan_payload(self, RUNTIME_DISPATCH_PLAN_SCHEMA)


RuntimeDispatchPlan = DispatchPlan


@dataclass(frozen=True)
class RuntimeExecutionResult:
    status: str
    run_id: str
    turn_id: str
    duration_ms: int
    process_started: bool
    returncode: Optional[int]
    capability_negotiation: CapabilityNegotiation
    callback: Optional[Dict[str, Any]] = field(default=None, repr=False, compare=False)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    stdout_bytes: int = 0
    stderr_bytes: int = 0

    @property
    def ok(self) -> bool:
        return self.status == EXECUTION_COMPLETED and self.callback is not None

    @property
    def outcome(self) -> str:
        return self.status

    def to_dict(self) -> Dict[str, Any]:
        return _support.execution_result_payload(
            self,
            RUNTIME_EXECUTION_RESULT_SCHEMA,
        )


ExecutionResult = RuntimeExecutionResult


class StdioRuntimeAdapter:
    """Execute one bounded hook through a caller-selected stdio command.

    Planning is side-effect free. Only :meth:`execute` starts a process. The
    adapter does not select a provider, discover credentials, or persist its
    command/environment configuration.
    """

    def __init__(
        self,
        argv: Optional[Sequence[str]],
        workdir: Path,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        env: Optional[Mapping[str, str]] = None,
        inherit_env: Sequence[str] = MINIMAL_INHERITED_ENV_KEYS,
        required_capabilities: Sequence[str] = DEFAULT_REQUIRED_CAPABILITIES,
        max_hook_bytes: int = DEFAULT_MAX_HOOK_BYTES,
        max_callback_bytes: int = DEFAULT_MAX_CALLBACK_BYTES,
    ) -> None:
        if isinstance(argv, (str, bytes)):
            raise RuntimeAdapterError("argv must be an array; shell command strings are forbidden")
        self._argv = tuple(_support.validate_argv(argv or (), RuntimeAdapterError))
        self._workdir = Path(workdir).expanduser()
        self._timeout_seconds = _support.validate_timeout(
            timeout_seconds,
            RuntimeAdapterError,
        )
        self._caller_env = _support.validate_environment(
            env or {},
            RuntimeAdapterError,
        )
        self._inherit_env = tuple(
            _support.validate_environment_names(inherit_env, RuntimeAdapterError)
        )
        self._required_capabilities = _support.normalized_capabilities(
            required_capabilities,
            RuntimeAdapterProtocolError,
        )
        self._max_hook_bytes = _support.positive_limit(
            max_hook_bytes,
            "max_hook_bytes",
            RuntimeAdapterError,
        )
        self._max_callback_bytes = _support.positive_limit(
            max_callback_bytes,
            "max_callback_bytes",
            RuntimeAdapterError,
        )
        self._identity = object()

    def build_dispatch_plan(self, hook: Dict[str, Any]) -> DispatchPlan:
        workdir = self._workdir.resolve()
        if not workdir.exists() or not workdir.is_dir():
            raise RuntimeAdapterError(f"runtime workdir is not a directory: {workdir}")

        run_id, turn_id, route_digest = _support.validate_hook(
            hook,
            RuntimeAdapterProtocolError,
        )
        hook_copy = _support.json_object_copy(hook, RuntimeAdapterProtocolError)
        hook_copy["runtime_adapter_request"] = {
            "schema": RUNTIME_ADAPTER_REQUEST_SCHEMA,
            "protocol": STDIO_RUNTIME_PROTOCOL_SCHEMA,
            "required_capabilities": list(self._required_capabilities),
            "route_digest": route_digest,
            "timeout_seconds": self._timeout_seconds,
            "limits": {
                "max_input_bytes": self._max_hook_bytes,
                "max_output_bytes": self._max_callback_bytes,
            },
            "side_effect_policy": {
                "callback_only": True,
                "callback_artifact_owner": "wsa_runtime_loop_service",
                "canon_mutation_forbidden": True,
                "provider_and_secret_owner": "external_runtime",
            },
        }
        stdin_json = json.dumps(
            hook_copy,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"
        input_bytes = len(stdin_json.encode("utf-8"))
        if input_bytes > self._max_hook_bytes:
            raise RuntimeAdapterProtocolError(
                f"hook exceeds maximum stdio input size: {input_bytes} bytes"
            )

        inherited_count = sum(1 for key in self._inherit_env if key in os.environ)
        return DispatchPlan(
            run_id=run_id,
            turn_id=turn_id,
            argv=_support.redacted_argv(self._argv),
            workdir=workdir,
            route_digest=route_digest,
            timeout_seconds=self._timeout_seconds,
            required_capabilities=self._required_capabilities,
            input_bytes=input_bytes,
            max_input_bytes=self._max_hook_bytes,
            max_output_bytes=self._max_callback_bytes,
            runtime_available=bool(self._argv),
            inherited_environment_count=inherited_count,
            caller_environment_count=len(self._caller_env),
            _stdin_json=stdin_json,
            _adapter_identity=self._identity,
        )

    def plan(self, hook: Dict[str, Any]) -> DispatchPlan:
        return self.build_dispatch_plan(hook)

    def prepare(self, hook: Dict[str, Any]) -> DispatchPlan:
        return self.build_dispatch_plan(hook)

    def execute(
        self,
        plan: DispatchPlan,
        cancellation: Optional[Any] = None,
        *,
        cancel_token: Optional[Any] = None,
    ) -> RuntimeExecutionResult:
        if cancel_token is not None:
            if cancellation is not None:
                raise RuntimeAdapterError("pass cancellation or cancel_token, not both")
            cancellation = cancel_token
        if not isinstance(plan, DispatchPlan) or plan._adapter_identity is not self._identity:
            raise RuntimeAdapterError("dispatch plan was not created by this adapter")

        pending = CapabilityNegotiation(required=plan.required_capabilities)
        if not plan.runtime_available:
            return self._result(
                plan,
                status=EXECUTION_NO_RUNTIME,
                start=None,
                process_started=False,
                negotiation=pending,
                error_message="no runtime command was configured",
            )
        if _support.is_cancelled(cancellation, CancellationToken):
            return self._result(
                plan,
                status=EXECUTION_CANCELLED,
                start=None,
                process_started=False,
                negotiation=pending,
                error_message="execution was cancelled before process start",
            )

        start = time.monotonic()
        try:
            process = subprocess.Popen(
                list(self._argv),
                cwd=plan.workdir,
                env=_support.execution_environment(
                    self._inherit_env,
                    self._caller_env,
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="strict",
                shell=False,
            )
        except (FileNotFoundError, PermissionError):
            return self._result(
                plan,
                status=EXECUTION_NO_RUNTIME,
                start=start,
                process_started=False,
                negotiation=pending,
                error_message="configured runtime command could not be started",
            )
        except OSError:
            return self._result(
                plan,
                status=EXECUTION_LAUNCH_FAILED,
                start=start,
                process_started=False,
                negotiation=pending,
                error_message="runtime process launch failed",
            )

        try:
            communication = _support.communicate_process(
                process,
                stdin_json=plan._stdin_json,
                timeout_seconds=plan.timeout_seconds,
                cancellation=cancellation,
                cancellation_token_type=CancellationToken,
                start=start,
                clock=time.monotonic,
            )
        except UnicodeError:
            _support.terminate_process(process)
            return self._result(
                plan,
                status=EXECUTION_MALFORMED_JSON,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=pending,
                error_message="runtime stdout was not valid UTF-8 JSON",
            )
        except OSError:
            _support.terminate_process(process)
            return self._result(
                plan,
                status=EXECUTION_LAUNCH_FAILED,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=pending,
                error_message="runtime process communication failed",
            )

        if communication[0] in {EXECUTION_TIMEOUT, EXECUTION_CANCELLED}:
            status, stdout, stderr = communication
            return self._result(
                plan,
                status=status,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=pending,
                stdout=stdout,
                stderr=stderr,
                error_message=(
                    "runtime exceeded its configured timeout"
                    if status == EXECUTION_TIMEOUT
                    else "execution was cancelled by the caller"
                ),
            )

        _, stdout, stderr = communication
        if process.returncode != 0:
            return self._result(
                plan,
                status=EXECUTION_NONZERO_EXIT,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=pending,
                stdout=stdout,
                stderr=stderr,
                error_message="runtime exited without a successful callback",
            )

        stdout_bytes = len(stdout.encode("utf-8"))
        if stdout_bytes > plan.max_output_bytes:
            return self._result(
                plan,
                status=EXECUTION_OUTPUT_TOO_LARGE,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=pending,
                stdout=stdout,
                stderr=stderr,
                error_message="runtime callback exceeded the configured output limit",
            )

        try:
            callback = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            return self._result(
                plan,
                status=EXECUTION_MALFORMED_JSON,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=pending,
                stdout=stdout,
                stderr=stderr,
                error_message="runtime stdout was not one callback JSON object",
            )
        if not isinstance(callback, dict):
            return self._result(
                plan,
                status=EXECUTION_MALFORMED_JSON,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=pending,
                stdout=stdout,
                stderr=stderr,
                error_message="runtime stdout was not one callback JSON object",
            )

        try:
            offered = _support.callback_capabilities(
                callback,
                response_schema=RUNTIME_CAPABILITY_RESPONSE_SCHEMA,
                protocol_schema=STDIO_RUNTIME_PROTOCOL_SCHEMA,
                error_type=RuntimeAdapterProtocolError,
            )
        except RuntimeAdapterProtocolError:
            return self._result(
                plan,
                status=EXECUTION_MALFORMED_CALLBACK,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=pending,
                stdout=stdout,
                stderr=stderr,
                error_message="runtime capability response was malformed",
            )
        negotiation = CapabilityNegotiation.from_offered(
            plan.required_capabilities,
            offered,
        )
        if negotiation.missing:
            return self._result(
                plan,
                status=EXECUTION_CAPABILITY_MISMATCH,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=negotiation,
                stdout=stdout,
                stderr=stderr,
                error_message="runtime did not report all required capabilities",
            )

        try:
            _support.validate_callback_binding(
                callback,
                plan,
                RuntimeAdapterProtocolError,
            )
        except (RuntimeAdapterProtocolError, ValueError):
            return self._result(
                plan,
                status=EXECUTION_MALFORMED_CALLBACK,
                start=start,
                process_started=True,
                returncode=process.returncode,
                negotiation=negotiation,
                stdout=stdout,
                stderr=stderr,
                error_message="callback did not match the pending hook contract",
            )

        return self._result(
            plan,
            status=EXECUTION_COMPLETED,
            start=start,
            process_started=True,
            returncode=process.returncode,
            negotiation=negotiation,
            callback=callback,
            stdout=stdout,
            stderr=stderr,
        )

    def _result(
        self,
        plan: DispatchPlan,
        *,
        status: str,
        start: Optional[float],
        process_started: bool,
        negotiation: CapabilityNegotiation,
        returncode: Optional[int] = None,
        callback: Optional[Dict[str, Any]] = None,
        stdout: str = "",
        stderr: str = "",
        error_message: Optional[str] = None,
    ) -> RuntimeExecutionResult:
        return _support.build_execution_result(
            RuntimeExecutionResult,
            plan,
            status=status,
            start=start,
            process_started=process_started,
            negotiation=negotiation,
            completed_status=EXECUTION_COMPLETED,
            clock=time.monotonic,
            returncode=returncode,
            callback=callback,
            stdout=stdout,
            stderr=stderr,
            error_message=error_message,
        )
