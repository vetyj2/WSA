from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from .ids import new_world_id, slugify


SCHEMA_VERSION = 1

CONTROL_DIRS = (
    "user_profile",
    "reports/inbox",
    "reports/pending_review",
    "reports/approved",
    "reports/rejected",
    "reports/archived",
    "reports/telegram_queue",
    "hermes/adapter_config",
    "hermes/task_queue",
    "hermes/reports_outbox",
    "hermes/callbacks",
    "hermes/maintenance",
    "manager/world_registry",
    "manager/scheduler",
    "manager/diagnostics",
    "manager/automation_policy",
    "manager/runtime_sessions",
    "worlds",
)

WORLD_DIRS = (
    "artifacts",
    "indexes/fts",
    "indexes/vector",
    "scenes",
    "actors",
    "tickets",
    "reports",
    "diagnostics",
)


@dataclass(frozen=True)
class WorldRecord:
    world_id: str
    display_name: str
    slug: str
    path: Path
    status: str
    schema_version: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_dirs(base: Path, dirs: Iterable[str]) -> None:
    for item in dirs:
        (base / item).mkdir(parents=True, exist_ok=True)


def control_db_path(workspace: Path) -> Path:
    return workspace / "control.sqlite"


def world_db_path(world_path: Path) -> Path:
    return world_path / "world.sqlite"


def init_control_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS worlds (
            world_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            slug TEXT NOT NULL,
            path TEXT NOT NULL,
            status TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_info (
            name TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profile_entries (
            id TEXT PRIMARY KEY,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            source_ref TEXT,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS manager_memory (
            id TEXT PRIMARY KEY,
            memory_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            source_ref TEXT,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_sessions (
            session_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            world_id TEXT,
            scene_id TEXT,
            role TEXT NOT NULL,
            runtime_target TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_messages (
            message_id TEXT PRIMARY KEY,
            protocol_version INTEGER NOT NULL,
            workspace_id TEXT NOT NULL,
            world_id TEXT,
            scene_id TEXT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            message_type TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            parent_message_id TEXT,
            payload TEXT NOT NULL,
            artifact_refs TEXT NOT NULL,
            status TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES runtime_sessions(session_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_runtime_messages_session_sequence
        ON runtime_messages(session_id, sequence)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS global_reports (
            report_id TEXT PRIMARY KEY,
            world_id TEXT,
            purpose TEXT NOT NULL,
            title TEXT NOT NULL,
            risk TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            artifact_ref TEXT,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduler_jobs (
            job_id TEXT PRIMARY KEY,
            world_id TEXT,
            job_type TEXT NOT NULL,
            schedule TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_policies (
            policy_id TEXT PRIMARY KEY,
            world_id TEXT,
            policy_name TEXT NOT NULL,
            autonomy_level INTEGER NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO schema_info (name, version, updated_at)
        VALUES ('control', ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            version = excluded.version,
            updated_at = excluded.updated_at
        """,
        (SCHEMA_VERSION, utc_now()),
    )
    conn.commit()


def init_world_schema(conn: sqlite3.Connection, world_id: str, display_name: str) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_info (
            name TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS world_metadata (
            world_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            entity_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            display_name TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS facts (
            fact_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_value TEXT,
            object_ref_id TEXT,
            time_scope TEXT,
            location_scope TEXT,
            authority TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_ref TEXT,
            tags TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS relationships (
            relationship_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            object_id TEXT NOT NULL,
            time_scope TEXT,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS timeline_points (
            timeline_point_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            label TEXT NOT NULL,
            sort_key TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scenes (
            scene_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            name TEXT NOT NULL,
            timeline_position TEXT,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scene_events (
            event_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            scene_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            commit_status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(scene_id) REFERENCES scenes(scene_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scene_events_scene_sequence
        ON scene_events(scene_id, sequence)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS actor_profiles (
            actor_profile_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            fragment_type TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS actor_memory_packets (
            memory_packet_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            time_scope TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS context_packets (
            context_packet_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            scene_id TEXT,
            actor_entity_id TEXT,
            packet_type TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            ticket_type TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            risk TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_changes (
            ticket_change_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            change_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(ticket_id) REFERENCES tickets(ticket_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            title TEXT NOT NULL,
            risk TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            artifact_ref TEXT,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS diagnostic_logs (
            diagnostic_log_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            diagnostic_type TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS artifact_refs (
            artifact_ref_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            path TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
            tag_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            tag_type TEXT NOT NULL,
            name TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(world_id, tag_type, name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tag_links (
            tag_link_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(tag_id) REFERENCES tags(tag_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS commit_log (
            commit_id TEXT PRIMARY KEY,
            world_id TEXT NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            sequence INTEGER NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_commit_log_sequence
        ON commit_log(world_id, sequence)
        """
    )
    now = utc_now()
    conn.execute(
        """
        INSERT INTO schema_info (name, version, updated_at)
        VALUES ('world', ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            version = excluded.version,
            updated_at = excluded.updated_at
        """,
        (SCHEMA_VERSION, now),
    )
    conn.execute(
        """
        INSERT INTO world_metadata (
            world_id, display_name, schema_version, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(world_id) DO UPDATE SET
            display_name = excluded.display_name,
            schema_version = excluded.schema_version,
            updated_at = excluded.updated_at
        """,
        (world_id, display_name, SCHEMA_VERSION, now, now),
    )
    conn.commit()


def init_workspace(workspace: Path) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    ensure_dirs(workspace, CONTROL_DIRS)
    db_path = control_db_path(workspace)
    with connect_sqlite(db_path) as conn:
        init_control_schema(conn)
    return db_path


def create_world(workspace: Path, display_name: str) -> WorldRecord:
    init_workspace(workspace)
    world_id = new_world_id(display_name)
    slug = slugify(display_name)
    world_path = workspace / "worlds" / world_id
    ensure_dirs(world_path, WORLD_DIRS)

    with connect_sqlite(world_db_path(world_path)) as conn:
        init_world_schema(conn, world_id, display_name)

    now = utc_now()
    with connect_sqlite(control_db_path(workspace)) as conn:
        conn.execute(
            """
            INSERT INTO worlds (
                world_id, display_name, slug, path, status,
                schema_version, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                world_id,
                display_name,
                slug,
                str(world_path),
                "active",
                SCHEMA_VERSION,
                now,
                now,
            ),
        )
        conn.commit()

    return WorldRecord(
        world_id=world_id,
        display_name=display_name,
        slug=slug,
        path=world_path,
        status="active",
        schema_version=SCHEMA_VERSION,
    )


def list_worlds(workspace: Path) -> List[WorldRecord]:
    db_path = control_db_path(workspace)
    if not db_path.exists():
        return []

    with connect_sqlite(db_path) as conn:
        rows = conn.execute(
            """
            SELECT world_id, display_name, slug, path, status, schema_version
            FROM worlds
            ORDER BY created_at ASC
            """
        ).fetchall()

    return [
        WorldRecord(
            world_id=row["world_id"],
            display_name=row["display_name"],
            slug=row["slug"],
            path=Path(row["path"]),
            status=row["status"],
            schema_version=row["schema_version"],
        )
        for row in rows
    ]


def get_world(workspace: Path, world_id: str) -> WorldRecord:
    db_path = control_db_path(workspace)
    with connect_sqlite(db_path) as conn:
        row = conn.execute(
            """
            SELECT world_id, display_name, slug, path, status, schema_version
            FROM worlds
            WHERE world_id = ?
            """,
            (world_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"world not found: {world_id}")
    return WorldRecord(
        world_id=row["world_id"],
        display_name=row["display_name"],
        slug=row["slug"],
        path=Path(row["path"]),
        status=row["status"],
        schema_version=row["schema_version"],
    )
