from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List

from .ids import new_world_id, slugify
from .paths import UnsafePathError, safe_child_path


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
    "meetings",
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


class SchemaVersionError(RuntimeError):
    """Raised when a workspace database is newer than this WSA build supports."""


class WorkspacePathError(ValueError):
    """Raised when a registered workspace path does not match the safe layout."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_sqlite(path: Path) -> sqlite3.Connection:
    """Open a configured SQLite connection.

    Callers that use this low-level factory must close the returned connection.
    Prefer sqlite_connection() for ordinary workspace access.
    """

    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def schema_version(conn: sqlite3.Connection, name: str) -> int | None:
    try:
        row = conn.execute(
            "SELECT version FROM schema_info WHERE name = ?",
            (name,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    if row is None:
        return None
    return int(row["version"])


def ensure_supported_schema(conn: sqlite3.Connection, name: str) -> None:
    version = schema_version(conn, name)
    if version is not None and version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"{name} schema version {version} is newer than supported version {SCHEMA_VERSION}"
        )


@contextmanager
def sqlite_connection(path: Path, schema_name: str | None = None) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection and always close it on exit."""

    conn = connect_sqlite(path)
    try:
        if schema_name is not None:
            ensure_supported_schema(conn, schema_name)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_dirs(base: Path, dirs: Iterable[str]) -> None:
    for item in dirs:
        (base / item).mkdir(parents=True, exist_ok=True)


def control_db_path(workspace: Path) -> Path:
    return workspace / "control.sqlite"


def world_db_path(world_path: Path) -> Path:
    return world_path / "world.sqlite"


def world_root_path(workspace: Path, world_id: str) -> Path:
    candidate = Path(world_id)
    if (
        not world_id
        or candidate.is_absolute()
        or candidate.name != world_id
        or ".." in candidate.parts
    ):
        raise WorkspacePathError(f"invalid world_id path segment: {world_id}")
    try:
        return safe_child_path(workspace, "worlds", world_id)
    except UnsafePathError as exc:
        raise WorkspacePathError(f"invalid world_id path segment: {world_id}") from exc


def registered_world_path(world_id: str) -> Path:
    return Path("worlds") / world_id


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
    with sqlite_connection(db_path, schema_name="control") as conn:
        init_control_schema(conn)
    return db_path


def create_world(workspace: Path, display_name: str) -> WorldRecord:
    init_workspace(workspace)
    world_id = new_world_id(display_name)
    slug = slugify(display_name)
    world_path = world_root_path(workspace, world_id)
    ensure_dirs(world_path, WORLD_DIRS)

    with sqlite_connection(world_db_path(world_path), schema_name="world") as conn:
        init_world_schema(conn, world_id, display_name)

    now = utc_now()
    with sqlite_connection(control_db_path(workspace), schema_name="control") as conn:
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
                str(registered_world_path(world_id)),
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

    with sqlite_connection(db_path, schema_name="control") as conn:
        rows = conn.execute(
            """
            SELECT world_id, display_name, slug, path, status, schema_version
            FROM worlds
            ORDER BY created_at ASC
            """
        ).fetchall()

    return [_world_record_from_row(workspace, row) for row in rows]


def get_world(workspace: Path, world_id: str) -> WorldRecord:
    db_path = control_db_path(workspace)
    with sqlite_connection(db_path, schema_name="control") as conn:
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
    return _world_record_from_row(workspace, row)


def _world_record_from_row(workspace: Path, row: sqlite3.Row) -> WorldRecord:
    world_id = row["world_id"]
    expected_path = world_root_path(workspace, world_id)
    stored_path = Path(row["path"]).expanduser()
    if stored_path.is_absolute():
        resolved_stored_path = stored_path.resolve()
    else:
        resolved_stored_path = (workspace / stored_path).resolve()
    if resolved_stored_path != expected_path:
        raise WorkspacePathError(
            f"registered path for world {world_id} does not match workspace layout"
        )
    return WorldRecord(
        world_id=world_id,
        display_name=row["display_name"],
        slug=row["slug"],
        path=expected_path,
        status=row["status"],
        schema_version=row["schema_version"],
    )
