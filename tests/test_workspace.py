import gc
import sqlite3
import warnings
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.repositories import WorldRepository
from wsa.workspace import (
    CONTROL_DIRS,
    SCHEMA_VERSION,
    SchemaVersionError,
    WORLD_DIRS,
    WorkspacePathError,
    control_db_path,
    create_world,
    get_world,
    init_workspace,
    list_worlds,
    sqlite_connection,
    world_db_path,
)


class WorkspaceTests(TestCase):
    def test_init_workspace_creates_control_plane(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            db_path = init_workspace(workspace)

            self.assertEqual(db_path, control_db_path(workspace))
            self.assertTrue(db_path.exists())
            for directory in CONTROL_DIRS:
                self.assertTrue((workspace / directory).is_dir(), directory)

    def test_create_world_creates_isolated_world(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "My First World")

            self.assertEqual(world.display_name, "My First World")
            self.assertTrue(world.world_id.startswith("my-first-world-"))
            self.assertTrue(world.path.is_dir())
            self.assertTrue(world_db_path(world.path).exists())
            for directory in WORLD_DIRS:
                self.assertTrue((world.path / directory).is_dir(), directory)

            worlds = list_worlds(workspace)
            self.assertEqual([item.world_id for item in worlds], [world.world_id])

    def test_world_path_is_registered_relative_to_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Portable World")

            with sqlite_connection(control_db_path(workspace)) as conn:
                row = conn.execute(
                    "SELECT path FROM worlds WHERE world_id = ?",
                    (world.world_id,),
                ).fetchone()

            self.assertEqual(row["path"], f"worlds/{world.world_id}")
            self.assertEqual(list_worlds(workspace)[0].path, world.path)

    def test_sqlite_connection_context_closes_connection(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "close-check.sqlite"

            with sqlite_connection(db_path) as conn:
                conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

    def test_workspace_repository_operations_emit_no_resource_warnings(self) -> None:
        with TemporaryDirectory() as tmp:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                workspace = Path(tmp) / "workspace"
                world = create_world(workspace, "Warning World")
                repo = WorldRepository(world.world_id, world.path)
                entity = repo.create_entity("character", "Mina")
                repo.create_fact(entity.entity_id, "has_role", "pilot")
                list_worlds(workspace)
                repo.list_facts(entity.entity_id)
                gc.collect()

            resource_warnings = [item for item in caught if issubclass(item.category, ResourceWarning)]
            self.assertEqual(resource_warnings, [])

    def test_newer_control_schema_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "Future Control")
            with sqlite_connection(control_db_path(workspace)) as conn:
                conn.execute(
                    "UPDATE schema_info SET version = ? WHERE name = 'control'",
                    (SCHEMA_VERSION + 1,),
                )

            with self.assertRaises(SchemaVersionError):
                list_worlds(workspace)

    def test_newer_world_schema_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Future World")
            with sqlite_connection(world_db_path(world.path)) as conn:
                conn.execute(
                    "UPDATE schema_info SET version = ? WHERE name = 'world'",
                    (SCHEMA_VERSION + 1,),
                )

            repo = WorldRepository(world.world_id, world.path)
            with self.assertRaises(SchemaVersionError):
                repo.list_facts()

    def test_registered_world_path_must_match_workspace_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Path Guard World")
            with sqlite_connection(control_db_path(workspace)) as conn:
                conn.execute(
                    "UPDATE worlds SET path = ? WHERE world_id = ?",
                    (str(Path(tmp) / "outside-world"), world.world_id),
                )

            with self.assertRaises(WorkspacePathError):
                list_worlds(workspace)
            with self.assertRaises(WorkspacePathError):
                get_world(workspace, world.world_id)

    def test_registered_world_id_must_not_be_nested_path(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            init_workspace(workspace)
            now = "2026-01-01T00:00:00+00:00"
            with sqlite_connection(control_db_path(workspace)) as conn:
                conn.execute(
                    """
                    INSERT INTO worlds (
                        world_id, display_name, slug, path, status,
                        schema_version, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "nested/id",
                        "Nested ID",
                        "nested-id",
                        "worlds/nested/id",
                        "active",
                        SCHEMA_VERSION,
                        now,
                        now,
                    ),
                )

            with self.assertRaises(WorkspacePathError):
                list_worlds(workspace)
