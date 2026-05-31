from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .paths import safe_child_path
from .repositories import ControlRepository
from .runtime import (
    PROTOCOL_VERSION,
    RuntimeEnvelope,
    RuntimeRouteError,
    validate_direction,
    validate_message_type,
)


class RuntimeTransport:
    """Filesystem-backed runtime transport with SQLite message state."""

    def __init__(self, workspace: Path, workspace_id: str = "local") -> None:
        self.workspace = workspace
        self.workspace_id = workspace_id
        self.control = ControlRepository(workspace, workspace_id)

    def session_root(self, session_id: str) -> Path:
        return safe_child_path(self.workspace, "manager", "runtime_sessions", session_id)

    def ensure_session_dirs(self, session_id: str) -> Path:
        root = self.session_root(session_id)
        for directory in ("inbox", "outbox", "processed", "tmp"):
            safe_child_path(root, directory).mkdir(parents=True, exist_ok=True)
        return root

    def start_session(
        self,
        role: str,
        runtime_target: str = "mock",
        world_id: str | None = None,
        scene_id: str | None = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        session = self.control.create_runtime_session(
            role=role,
            runtime_target=runtime_target,
            world_id=world_id,
            scene_id=scene_id,
            payload=payload,
        )
        self.ensure_session_dirs(session.session_id)
        return session.session_id

    def close_session(self, session_id: str, status: str = "closed") -> None:
        self.control.update_runtime_session_status(session_id, status)

    def resolve_message_route(
        self,
        session_id: str,
        world_id: str | None = None,
        scene_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        session = self.control.get_runtime_session(session_id)
        resolved_world_id = world_id
        resolved_scene_id = scene_id

        if session.world_id is not None:
            if resolved_world_id is None:
                resolved_world_id = session.world_id
            elif resolved_world_id != session.world_id:
                raise RuntimeRouteError(
                    f"message world_id {resolved_world_id} does not match "
                    f"session world_id {session.world_id}"
                )

        if session.scene_id is not None:
            if resolved_scene_id is None:
                resolved_scene_id = session.scene_id
            elif resolved_scene_id != session.scene_id:
                raise RuntimeRouteError(
                    f"message scene_id {resolved_scene_id} does not match "
                    f"session scene_id {session.scene_id}"
                )

        return resolved_world_id, resolved_scene_id

    def send(
        self,
        session_id: str,
        direction: str,
        role: str,
        message_type: str,
        payload: Optional[Dict[str, Any]] = None,
        world_id: str | None = None,
        scene_id: str | None = None,
        parent_message_id: str | None = None,
        artifact_refs: Optional[List[str]] = None,
        status: str = "queued",
    ) -> RuntimeEnvelope:
        validate_direction(direction)
        validate_message_type(message_type)
        world_id, scene_id = self.resolve_message_route(session_id, world_id, scene_id)
        self.ensure_session_dirs(session_id)

        record = self.control.add_runtime_message(
            session_id=session_id,
            role=role,
            message_type=message_type,
            payload=payload,
            world_id=world_id,
            scene_id=scene_id,
            parent_message_id=parent_message_id,
            artifact_refs=artifact_refs,
            status=status,
        )
        envelope = RuntimeEnvelope(
            message_id=record.message_id,
            protocol_version=PROTOCOL_VERSION,
            workspace_id=self.workspace_id,
            world_id=world_id,
            scene_id=scene_id,
            session_id=session_id,
            role=role,
            message_type=message_type,
            sequence=record.sequence,
            parent_message_id=parent_message_id,
            payload=payload or {},
            artifact_refs=artifact_refs or [],
            status=status,
        )
        self._write_envelope(direction, envelope)
        return envelope

    def list_envelopes(self, session_id: str, direction: str) -> List[RuntimeEnvelope]:
        validate_direction(direction)
        directory = safe_child_path(self.session_root(session_id), direction)
        if not directory.exists():
            return []

        envelopes: List[RuntimeEnvelope] = []
        for path in sorted(directory.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                envelopes.append(RuntimeEnvelope.from_dict(json.load(handle)))
        return envelopes

    def write_tmp(self, session_id: str, name: str, payload: Dict[str, Any]) -> Path:
        self.ensure_session_dirs(session_id)
        if not name.endswith(".json"):
            name = f"{name}.json"
        path = safe_child_path(self.session_root(session_id), "tmp", name)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def cleanup_tmp(self, session_id: str) -> int:
        tmp_dir = safe_child_path(self.session_root(session_id), "tmp")
        if not tmp_dir.exists():
            return 0

        removed = 0
        for path in tmp_dir.iterdir():
            if path.is_file():
                path.unlink()
                removed += 1
        return removed

    def _write_envelope(self, direction: str, envelope: RuntimeEnvelope) -> Path:
        filename = f"{envelope.sequence:06d}_{envelope.message_id}.json"
        path = safe_child_path(self.session_root(envelope.session_id), direction, filename)
        path.write_text(
            json.dumps(envelope.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return path
