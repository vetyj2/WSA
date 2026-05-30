from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WORKSPACE_DIRNAME = "workspace"
WORKSPACE_ENV_VAR = "WSA_WORKSPACE"


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration resolved from CLI/env/defaults."""

    workspace: Path


def resolve_workspace(value: str | None = None, cwd: Path | None = None) -> Path:
    """Resolve the workspace path without creating it."""

    if value:
        return Path(value).expanduser().resolve()

    env_value = os.environ.get(WORKSPACE_ENV_VAR)
    if env_value:
        return Path(env_value).expanduser().resolve()

    base = cwd if cwd is not None else Path.cwd()
    return (base / DEFAULT_WORKSPACE_DIRNAME).resolve()


def load_config(workspace: str | None = None, cwd: Path | None = None) -> AppConfig:
    return AppConfig(workspace=resolve_workspace(workspace, cwd))
