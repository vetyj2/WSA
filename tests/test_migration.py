import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.migration import apply_migrations, migration_plan_to_dict, plan_migrations
from wsa.repositories import WorldRepository
from wsa.workspace import (
    CONTROL_SCHEMA_VERSION,
    WORLD_SCHEMA_VERSION,
    control_db_path,
    create_world,
    schema_version,
    sqlite_connection,
    world_db_path,
)


class MigrationTests(TestCase):
    def test_v1_fixture_migrates_with_backup_and_preserves_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Migration Fixture")
            repo = WorldRepository(world.world_id, world.path)
            entity = repo.create_entity(
                "character",
                "Mina",
                payload={"provenance": "user_explicit"},
            )
            fact = repo.create_fact(
                entity.entity_id,
                "goal",
                "return home",
                authority="user_explicit",
                status="canon",
            )
            with sqlite_connection(control_db_path(workspace)) as conn:
                conn.execute("DROP TABLE workflow_callback_receipts")
                conn.execute("DROP TABLE workflow_runs")
                conn.execute("DROP TABLE schema_migrations")
                conn.execute("UPDATE schema_info SET version = 1 WHERE name = 'control'")
            with sqlite_connection(world_db_path(world.path)) as conn:
                conn.execute("DROP TABLE ticket_applications")
                conn.execute("DROP TABLE schema_migrations")
                conn.execute("UPDATE schema_info SET version = 1 WHERE name = 'world'")
                conn.execute("UPDATE world_metadata SET schema_version = 1")

            plan = plan_migrations(workspace)
            result = apply_migrations(workspace)

            self.assertEqual(migration_plan_to_dict(plan)["status"], "upgrade_required")
            self.assertIsNotNone(result.backup_path)
            assert result.backup_path is not None
            self.assertTrue((result.backup_path / "control.sqlite").exists())
            self.assertTrue(
                (result.backup_path / f"world-{world.world_id}.sqlite").exists()
            )
            self.assertIn("control:1_to_2", result.applied)
            self.assertIn(f"world:1_to_2:{world.world_id}", result.applied)
            with sqlite_connection(control_db_path(workspace)) as conn:
                self.assertEqual(schema_version(conn, "control"), CONTROL_SCHEMA_VERSION)
                receipt = conn.execute(
                    "SELECT details FROM schema_migrations WHERE migration_id = 'control:1_to_2'"
                ).fetchone()
                self.assertFalse(json.loads(receipt["details"])["destructive"])
            with sqlite_connection(world_db_path(world.path)) as conn:
                self.assertEqual(schema_version(conn, "world"), WORLD_SCHEMA_VERSION)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(repo.get_entity(entity.entity_id).display_name, "Mina")
            self.assertEqual(repo.get_fact(fact.fact_id).object_value, "return home")
            self.assertEqual(
                repo.get_entity(entity.entity_id).payload["provenance"],
                "user_explicit",
            )

    def test_migration_rerun_is_read_only_when_current(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "Current World")

            result = apply_migrations(workspace)

            self.assertEqual(result.applied, [])
            self.assertIsNone(result.backup_path)
            self.assertTrue(result.verified)
