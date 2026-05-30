from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.workspace import (
    CONTROL_DIRS,
    WORLD_DIRS,
    control_db_path,
    create_world,
    init_workspace,
    list_worlds,
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
