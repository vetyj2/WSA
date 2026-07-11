from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import ContextManager, List, Optional

from .repository_common import Payload, decode_payload, encode_payload, new_id
from .repository_records import RuntimeMessageRecord, RuntimeSessionRecord
from .workspace import SCHEMA_VERSION, control_db_path, sqlite_connection, utc_now

class ControlRepository:
    def __init__(self, workspace: Path, workspace_id: str = "local") -> None:
        self.workspace = workspace
        self.workspace_id = workspace_id

    def _connect(self) -> ContextManager[sqlite3.Connection]:
        return sqlite_connection(control_db_path(self.workspace), schema_name="control")

    def get_runtime_session(self, session_id: str) -> RuntimeSessionRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, workspace_id, world_id, scene_id, role,
                       runtime_target, status, payload
                FROM runtime_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"runtime session not found: {session_id}")
        return RuntimeSessionRecord(
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            world_id=row["world_id"],
            scene_id=row["scene_id"],
            role=row["role"],
            runtime_target=row["runtime_target"],
            status=row["status"],
            payload=decode_payload(row["payload"]),
        )

    def create_runtime_session(
        self,
        role: str,
        runtime_target: str = "mock",
        world_id: str | None = None,
        scene_id: str | None = None,
        payload: Optional[Payload] = None,
        status: str = "created",
    ) -> RuntimeSessionRecord:
        session_id = new_id("session")
        now = utc_now()
        encoded = encode_payload(payload)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_sessions (
                    session_id, workspace_id, world_id, scene_id, role,
                    runtime_target, status, payload, schema_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    self.workspace_id,
                    world_id,
                    scene_id,
                    role,
                    runtime_target,
                    status,
                    encoded,
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return RuntimeSessionRecord(
            session_id=session_id,
            workspace_id=self.workspace_id,
            world_id=world_id,
            scene_id=scene_id,
            role=role,
            runtime_target=runtime_target,
            status=status,
            payload=payload or {},
        )

    def update_runtime_session_status(self, session_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runtime_sessions
                SET status = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (status, utc_now(), session_id),
            )
            conn.commit()

    def add_runtime_message(
        self,
        session_id: str,
        role: str,
        message_type: str,
        payload: Optional[Payload] = None,
        world_id: str | None = None,
        scene_id: str | None = None,
        parent_message_id: str | None = None,
        artifact_refs: Optional[List[str]] = None,
        status: str = "queued",
    ) -> RuntimeMessageRecord:
        message_id = new_id("msg")
        with self._connect() as conn:
            current = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM runtime_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            sequence = int(current) + 1
            conn.execute(
                """
                INSERT INTO runtime_messages (
                    message_id, protocol_version, workspace_id, world_id,
                    scene_id, session_id, role, message_type, sequence,
                    parent_message_id, payload, artifact_refs, status,
                    schema_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    1,
                    self.workspace_id,
                    world_id,
                    scene_id,
                    session_id,
                    role,
                    message_type,
                    sequence,
                    parent_message_id,
                    encode_payload(payload),
                    json.dumps(artifact_refs or [], ensure_ascii=False),
                    status,
                    SCHEMA_VERSION,
                    utc_now(),
                ),
            )
            conn.commit()
        return RuntimeMessageRecord(
            message_id=message_id,
            session_id=session_id,
            message_type=message_type,
            sequence=sequence,
            payload=payload or {},
            status=status,
        )

    def list_runtime_messages(self, session_id: str) -> List[RuntimeMessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT message_id, session_id, message_type, sequence, payload, status
                FROM runtime_messages
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            RuntimeMessageRecord(
                message_id=row["message_id"],
                session_id=row["session_id"],
                message_type=row["message_type"],
                sequence=row["sequence"],
                payload=decode_payload(row["payload"]),
                status=row["status"],
            )
            for row in rows
        ]
