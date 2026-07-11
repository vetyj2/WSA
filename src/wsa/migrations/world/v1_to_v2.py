from __future__ import annotations

import json
import sqlite3

from ...workspace import WORLD_SCHEMA_VERSION, init_world_schema, utc_now


MIGRATION_ID = "world:1_to_2"


def apply(conn: sqlite3.Connection, world_id: str, display_name: str) -> None:
    conn.execute("BEGIN IMMEDIATE")
    init_world_schema(conn, world_id, display_name)
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (
            migration_id, store_name, from_version, to_version, applied_at, details
        )
        VALUES (?, 'world', 1, ?, ?, ?)
        """,
        (
            MIGRATION_ID,
            WORLD_SCHEMA_VERSION,
            utc_now(),
            json.dumps(
                {
                    "adds": [
                        "ticket_applications",
                        "diagnostic fingerprint index",
                        "unique commit sequence index",
                        "schema_migrations",
                    ],
                    "destructive": False,
                },
                sort_keys=True,
            ),
        ),
    )
    conn.commit()
