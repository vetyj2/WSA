from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.manager import WorldManager
from wsa.repositories import WorldRepository
from wsa.tickets import create_pr_packet
from wsa.workspace import create_world


class WorldManagerTests(TestCase):
    def test_diagnostics_find_pending_tickets_and_unfinished_tmp(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Manager World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")
            create_pr_packet(
                repo,
                "Pending fact",
                [
                    {
                        "change_type": "add_fact",
                        "subject_id": actor.entity_id,
                        "predicate": "knows",
                        "object_value": "secret",
                    }
                ],
            )
            tmp_dir = world.path / "scenes" / "scene_demo" / "tmp"
            tmp_dir.mkdir(parents=True)
            (tmp_dir / "prep_receipt.json").write_text("{}", encoding="utf-8")

            findings = WorldManager(workspace).run_diagnostics()
            finding_types = {item.finding_type for item in findings}

            self.assertIn("pending_tickets", finding_types)
            self.assertIn("unfinished_scene_tmp", finding_types)
