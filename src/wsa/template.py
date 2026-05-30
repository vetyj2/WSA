from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

from .hermes_adapter import HermesCliTemplateAdapter
from .paths import safe_child_path
from .workspace import control_db_path, init_workspace


TEMPLATE_SECRET_KEYS = ("api_key", "secret", "token", "password", "credential", "private_key")


@dataclass(frozen=True)
class TemplateCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class TemplateReadiness:
    checks: List[TemplateCheck]

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)


class TemplateChecker:
    """Checks whether a workspace is clean enough to serve as an MVP template."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def run(self, write_missing: bool = False) -> TemplateReadiness:
        if write_missing:
            init_workspace(self.workspace)
            HermesCliTemplateAdapter(self.workspace).write_example_config()

        checks = [
            self._workspace_initialized_check(),
            self._hermes_dirs_check(),
            self._example_config_check(),
            self._live_adapter_config_check(),
            self._queue_clean_check("task_queue"),
            self._queue_clean_check("callbacks"),
            self._queue_clean_check("reports_outbox"),
        ]
        return TemplateReadiness(checks)

    def _workspace_initialized_check(self) -> TemplateCheck:
        db_path = control_db_path(self.workspace)
        if db_path.exists():
            return TemplateCheck("workspace_initialized", "ok", str(db_path))
        return TemplateCheck("workspace_initialized", "fail", "control.sqlite is missing")

    def _hermes_dirs_check(self) -> TemplateCheck:
        missing = [
            item
            for item in (
                "adapter_config",
                "task_queue",
                "callbacks",
                "reports_outbox",
                "maintenance",
            )
            if not safe_child_path(self.workspace, "hermes", item).is_dir()
        ]
        if missing:
            return TemplateCheck("hermes_dirs", "fail", f"missing: {', '.join(missing)}")
        return TemplateCheck("hermes_dirs", "ok", "all Hermes template directories exist")

    def _example_config_check(self) -> TemplateCheck:
        path = safe_child_path(
            self.workspace,
            "hermes",
            "adapter_config",
            "hermes_cli.example.json",
        )
        if not path.exists():
            return TemplateCheck("example_config", "fail", "hermes_cli.example.json is missing")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return TemplateCheck("example_config", "fail", f"invalid JSON: {exc}")
        if payload.get("schema") != "wsa.hermes.cli_config.example.v1":
            return TemplateCheck("example_config", "fail", "unexpected example config schema")
        secret_paths = list(self._secret_value_paths(payload))
        if secret_paths:
            return TemplateCheck(
                "example_config",
                "fail",
                f"secret-like values present at: {', '.join(secret_paths)}",
            )
        return TemplateCheck("example_config", "ok", str(path))

    def _live_adapter_config_check(self) -> TemplateCheck:
        config_dir = safe_child_path(self.workspace, "hermes", "adapter_config")
        if not config_dir.exists():
            return TemplateCheck("live_adapter_config", "fail", "adapter_config is missing")
        live_files = [
            path.name
            for path in sorted(config_dir.iterdir())
            if path.is_file() and ".example." not in path.name
        ]
        if live_files:
            return TemplateCheck(
                "live_adapter_config",
                "fail",
                f"template workspace has live config files: {', '.join(live_files)}",
            )
        return TemplateCheck("live_adapter_config", "ok", "no live adapter config files")

    def _queue_clean_check(self, name: str) -> TemplateCheck:
        path = safe_child_path(self.workspace, "hermes", name)
        if not path.exists():
            return TemplateCheck(f"{name}_clean", "fail", f"{name} is missing")
        files = [item.name for item in sorted(path.iterdir()) if item.is_file()]
        if files:
            return TemplateCheck(
                f"{name}_clean",
                "fail",
                f"template workspace has runtime files: {', '.join(files)}",
            )
        return TemplateCheck(f"{name}_clean", "ok", "no runtime files")

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


def format_template_readiness(readiness: TemplateReadiness) -> List[str]:
    lines = [f"template_ready: {'yes' if readiness.ok else 'no'}"]
    lines.extend(
        "\t".join([check.status, check.name, check.detail])
        for check in readiness.checks
    )
    return lines
