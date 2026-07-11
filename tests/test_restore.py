import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.repositories import WorldRepository
from wsa.restore import (
    RestoreError,
    execute_restore_to_new_path,
    plan_restore_to_new_path,
    restore_plan_to_dict,
)
from wsa.workspace import control_db_path, create_world, list_worlds, world_db_path


class RestoreTests(TestCase):
    def test_backup_restores_to_new_path_and_rewrites_world_routes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            world = create_world(workspace, "Restore World")
            repo = WorldRepository(world.world_id, world.path)
            repo.create_entity("character", "Mina")
            backup = self._backup(workspace, root / "backup")
            destination = root / "restored"

            plan = plan_restore_to_new_path(workspace, backup, destination)
            self.assertEqual(restore_plan_to_dict(plan)["status"], "ready")
            receipt = execute_restore_to_new_path(plan)

            restored_world = list_worlds(destination)[0]
            self.assertEqual(
                restored_world.path.resolve(),
                (destination / "worlds" / world.world_id).resolve(),
            )
            restored_repo = WorldRepository(restored_world.world_id, restored_world.path)
            self.assertEqual(restored_repo.list_entities()[0].display_name, "Mina")
            self.assertEqual(receipt["status"], "restored_and_verified")
            self.assertTrue(Path(receipt["receipt_path"]).exists())
            self.assertTrue(control_db_path(workspace).exists())

    def test_active_callback_blocks_restore_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            create_world(workspace, "Busy World")
            backup = self._backup(workspace, root / "backup")
            callback = workspace / "hermes" / "callbacks" / "active.json"
            callback.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(RestoreError, "active runtime files"):
                plan_restore_to_new_path(workspace, backup, root / "restored")

    @staticmethod
    def _backup(workspace: Path, backup: Path) -> Path:
        backup.mkdir(parents=True)
        control_target = backup / "control.sqlite"
        source = sqlite3.connect(control_db_path(workspace))
        target = sqlite3.connect(control_target)
        source.backup(target)
        target.close()
        source.close()
        files = ["control.sqlite"]
        for world in list_worlds(workspace):
            name = f"world-{world.world_id}.sqlite"
            source = sqlite3.connect(world_db_path(world.path))
            target = sqlite3.connect(backup / name)
            source.backup(target)
            target.close()
            source.close()
            files.append(name)
        (backup / "manifest.json").write_text(
            json.dumps({"schema": "wsa.migration.backup.v1", "files": files}) + "\n",
            encoding="utf-8",
        )
        return backup
