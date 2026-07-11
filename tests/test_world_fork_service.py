import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.application.world_fork_service import WorldForkService
from wsa.application.proposal_service import portable_import_preview
from wsa.cli import main
from wsa.repositories import WorldRepository
from wsa.workspace import create_world, list_worlds


class WorldForkServiceTests(TestCase):
    def test_selective_export_closes_outgoing_references_and_excludes_runtime(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Fork Source")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Mina")
            place = repo.create_entity("location", "Harbor")
            excluded = repo.create_entity("character", "Elsewhere")
            repo.create_fact(
                actor.entity_id,
                "home",
                object_ref_id=place.entity_id,
                status="canon",
            )
            repo.add_world_edge(
                "entity",
                actor.entity_id,
                "located_at",
                "entity",
                object_id=place.entity_id,
                status="canon",
            )
            repo.create_fact(excluded.entity_id, "role", "unused", status="canon")
            repo.create_timeline_point("Opening", "001")

            payload = WorldForkService(world).selective_export([actor.entity_id])

            self.assertEqual(
                [item["entity_id"] for item in payload["entities"]],
                [actor.entity_id, place.entity_id],
            )
            self.assertEqual(
                payload["selection"]["auto_included_dependency_ids"],
                [place.entity_id],
            )
            self.assertEqual(payload["timeline_points"], [])
            self.assertNotIn(excluded.entity_id, json.dumps(payload))
            self.assertIn("callbacks", payload["excluded"])
            self.assertEqual(
                payload["side_effect_status"],
                "read_only_no_world_mutation",
            )

            destination = create_world(workspace, "Fork Destination")
            preview = portable_import_preview(destination, payload)
            entity_changes = [
                item for item in preview.changes if item["change_type"] == "add_entity"
            ]
            self.assertEqual(len(entity_changes), 2)
            self.assertTrue(
                any(
                    item.get("object_change_ref")
                    for item in preview.changes
                    if item["change_type"] in {"add_fact", "add_world_edge"}
                )
            )

    def test_fork_plan_cli_is_read_only_and_contains_portable_selection(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Fork Plan Source")
            actor = WorldRepository(world.world_id, world.path).create_entity(
                "character",
                "Mina",
            )
            before_worlds = len(list_worlds(workspace))
            output = StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "fork-plan",
                        world.world_id,
                        "--name",
                        "Fork Target",
                        "--entity",
                        actor.entity_id,
                        "--format",
                        "json",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["target_display_name"], "Fork Target")
            self.assertEqual(payload["counts"]["entities"], 1)
            self.assertEqual(payload["execution"], "not_performed_plan_only")
            self.assertEqual(len(list_worlds(workspace)), before_worlds)

    def test_unknown_selection_is_blocked_without_mutation(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Fork Missing")

            with self.assertRaises(KeyError):
                WorldForkService(world).fork_plan("Target", ["missing-entity"])

            self.assertEqual(len(list_worlds(workspace)), 1)
