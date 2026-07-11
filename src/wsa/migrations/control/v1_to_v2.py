from __future__ import annotations

import json
import sqlite3

from ...workspace import CONTROL_SCHEMA_VERSION, init_control_schema, utc_now


MIGRATION_ID = "control:1_to_2"


def apply(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    init_control_schema(conn)
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (
            migration_id, store_name, from_version, to_version, applied_at, details
        )
        VALUES (?, 'control', 1, ?, ?, ?)
        """,
        (
            MIGRATION_ID,
            CONTROL_SCHEMA_VERSION,
            utc_now(),
            json.dumps(
                {
                    "adds": [
                        "workflow_runs",
                        "workflow_callback_receipts",
                        "schema_migrations",
                    ],
                    "destructive": False,
                },
                sort_keys=True,
            ),
        ),
    )
    conn.commit()
