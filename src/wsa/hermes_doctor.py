from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

from .hermes_commands import HERMES_COMMAND_REGISTRY_SCHEMA
from .paths import safe_child_path
from .template import TEMPLATE_SECRET_KEYS
from .workspace import control_db_path


HERMES_CONFIG_SCHEMA = "wsa.hermes.cli_config.example.v1"


@dataclass(frozen=True)
class HermesDoctorCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class HermesDoctorReport:
    checks: List[HermesDoctorCheck]

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)


class HermesDoctor:
    """Read-only preflight for local Hermes adapter readiness."""

    def __init__(
        self,
        workspace: Path,
        command: str = "wsa-hermes-cli",
        config_path: Path | None = None,
        operation_policy_path: Path | None = None,
        source_root: Path | None = None,
    ) -> None:
        self.workspace = workspace
        self.command = command
        self.config_path = config_path or safe_child_path(
            workspace,
            "hermes",
            "adapter_config",
            "hermes_cli.example.json",
        )
        self.operation_policy_path = operation_policy_path
        self.source_root = source_root

    def run(self) -> HermesDoctorReport:
        config_payload = self._load_config_if_available()
        checks = [
            self._workspace_check(),
            self._source_workspace_separation_check(),
            self._command_check(),
            self._config_check(config_payload),
            self._command_registry_check(config_payload),
            self._hermes_dirs_check(),
            self._operation_policy_check(),
        ]
        checks.extend(self._secret_env_checks(config_payload))
        return HermesDoctorReport(checks)

    def _workspace_check(self) -> HermesDoctorCheck:
        if not self.workspace.exists():
            return HermesDoctorCheck("workspace_exists", "fail", "workspace is missing")
        if not control_db_path(self.workspace).exists():
            return HermesDoctorCheck("control_db_exists", "fail", "control.sqlite is missing")
        return HermesDoctorCheck("control_db_exists", "ok", "workspace control DB exists")

    def _source_workspace_separation_check(self) -> HermesDoctorCheck:
        if self.source_root is None:
            return HermesDoctorCheck(
                "source_workspace_separation",
                "warn",
                "source root not provided",
            )
        try:
            source = self.source_root.resolve()
            workspace = self.workspace.resolve()
            workspace.relative_to(source)
        except ValueError:
            return HermesDoctorCheck(
                "source_workspace_separation",
                "ok",
                "workspace is outside source root",
            )
        return HermesDoctorCheck(
            "source_workspace_separation",
            "warn",
            "workspace is inside source root; keep live runtime state out of the repo",
        )

    def _command_check(self) -> HermesDoctorCheck:
        if shutil.which(self.command):
            return HermesDoctorCheck("command_available", "ok", self.command)
        return HermesDoctorCheck(
            "command_available",
            "fail",
            f"command not found on PATH: {self.command}",
        )

    def _config_check(self, payload: dict[str, Any] | None) -> HermesDoctorCheck:
        if payload is None:
            return HermesDoctorCheck(
                "adapter_config",
                "fail",
                f"missing or invalid config: {self.config_path}",
            )
        if payload.get("schema") != HERMES_CONFIG_SCHEMA:
            return HermesDoctorCheck("adapter_config", "fail", "unexpected config schema")
        secret_paths = list(self._secret_value_paths(payload))
        if secret_paths:
            return HermesDoctorCheck(
                "adapter_config",
                "fail",
                f"secret-like values present at: {', '.join(secret_paths)}",
            )
        return HermesDoctorCheck("adapter_config", "ok", str(self.config_path))

    def _command_registry_check(self, config_payload: dict[str, Any] | None) -> HermesDoctorCheck:
        if config_payload is None:
            return HermesDoctorCheck(
                "command_registry",
                "warn",
                "adapter config unavailable",
            )
        command_registry = config_payload.get("command_registry")
        if not isinstance(command_registry, str) or not command_registry:
            return HermesDoctorCheck(
                "command_registry",
                "warn",
                "adapter config does not declare a command registry",
            )
        path = safe_child_path(self.workspace, command_registry)
        payload = self._load_json(path)
        if payload is None:
            return HermesDoctorCheck(
                "command_registry",
                "fail",
                f"missing or invalid registry: {path}",
            )
        if payload.get("schema") != HERMES_COMMAND_REGISTRY_SCHEMA:
            return HermesDoctorCheck("command_registry", "fail", "unexpected registry schema")
        commands = payload.get("commands")
        if not isinstance(commands, list) or not commands:
            return HermesDoctorCheck("command_registry", "fail", "command list is empty")
        secret_paths = list(self._secret_value_paths(payload))
        if secret_paths:
            return HermesDoctorCheck(
                "command_registry",
                "fail",
                f"secret-like values present at: {', '.join(secret_paths)}",
            )
        return HermesDoctorCheck("command_registry", "ok", str(path))

    def _hermes_dirs_check(self) -> HermesDoctorCheck:
        required = (
            "task_queue",
            "task_state",
            "callbacks",
            "reports_outbox",
            "quarantine",
            "maintenance",
        )
        missing = []
        unwritable = []
        for name in required:
            path = safe_child_path(self.workspace, "hermes", name)
            if not path.is_dir():
                missing.append(name)
            elif not os.access(path, os.W_OK):
                unwritable.append(name)
        if missing:
            return HermesDoctorCheck("hermes_dirs", "fail", f"missing: {', '.join(missing)}")
        if unwritable:
            return HermesDoctorCheck(
                "hermes_dirs",
                "fail",
                f"not writable: {', '.join(unwritable)}",
            )
        return HermesDoctorCheck("hermes_dirs", "ok", "required Hermes dirs are writable")

    def _operation_policy_check(self) -> HermesDoctorCheck:
        if self.operation_policy_path is None:
            return HermesDoctorCheck(
                "operation_policy",
                "warn",
                "no operation policy path provided",
            )
        payload = self._load_json(self.operation_policy_path)
        if payload is None:
            return HermesDoctorCheck(
                "operation_policy",
                "fail",
                f"missing or invalid policy: {self.operation_policy_path}",
            )
        secret_paths = list(self._secret_value_paths(payload))
        if secret_paths:
            return HermesDoctorCheck(
                "operation_policy",
                "fail",
                f"secret-like values present at: {', '.join(secret_paths)}",
            )
        version_control = payload.get("version_control")
        if isinstance(version_control, dict):
            enabled_modes = [
                mode
                for mode in ("remote_push", "custom")
                if isinstance(version_control.get(mode), dict)
                and version_control[mode].get("enabled") is True
            ]
            if enabled_modes:
                return HermesDoctorCheck(
                    "operation_policy",
                    "fail",
                    f"high-risk modes enabled: {', '.join(enabled_modes)}",
                )
        return HermesDoctorCheck("operation_policy", "ok", str(self.operation_policy_path))

    def _secret_env_checks(self, payload: dict[str, Any] | None) -> List[HermesDoctorCheck]:
        if payload is None:
            return []
        value = payload.get("secret_env")
        if not isinstance(value, list):
            return [
                HermesDoctorCheck(
                    "secret_env",
                    "warn",
                    "config has no secret_env list",
                )
            ]

        checks = []
        for item in value:
            if not isinstance(item, str) or not item:
                checks.append(HermesDoctorCheck("secret_env", "fail", "invalid secret env name"))
                continue
            status = "ok" if os.environ.get(item) else "warn"
            detail = "present" if status == "ok" else "not set"
            checks.append(HermesDoctorCheck(f"secret_env:{item}", status, detail))
        return checks

    def _load_config_if_available(self) -> dict[str, Any] | None:
        return self._load_json(self.config_path)

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(value, dict):
            return None
        return value

    def _secret_value_paths(self, value: Any, path: str = "$") -> Iterable[str]:
        if isinstance(value, dict):
            for key, item in value.items():
                key_path = f"{path}.{key}"
                lowered = str(key).lower()
                if key == "secret_env":
                    continue
                if any(secret_key in lowered for secret_key in TEMPLATE_SECRET_KEYS):
                    if isinstance(item, str) and item and not item.startswith("EXAMPLE_"):
                        yield key_path
                    elif not isinstance(item, (str, type(None), list)):
                        yield key_path
                yield from self._secret_value_paths(item, key_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from self._secret_value_paths(item, f"{path}[{index}]")


def format_hermes_doctor(report: HermesDoctorReport) -> List[str]:
    lines = [f"hermes_ready: {'yes' if report.ok else 'no'}"]
    lines.extend(
        "\t".join([check.status, check.name, check.detail])
        for check in report.checks
    )
    return lines
