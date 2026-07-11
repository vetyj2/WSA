from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.cli import main
from wsa.context import ContextBuilder
from wsa.repositories import WorldRepository
from wsa.workspace import create_world


class DeepAuthoringLifecycleCliTests(TestCase):
    def test_profile_replacement_preserves_the_old_time_range(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Replacement CLI World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Mina")
            old = repo.create_actor_profile(
                actor.entity_id,
                "goal",
                {
                    "summary": "Keep the harbor open.",
                    "_wsa": {
                        "source_ref": "seed:goal",
                        "authority": "canon",
                        "valid_from": "001",
                        "valid_until": None,
                    },
                },
            )
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "--workspace",
                            str(workspace),
                            "world",
                            "actor",
                            "profile",
                            world.world_id,
                            "Mina",
                            "--fragment",
                            "goal",
                            "--text",
                            "Escort the envoy.",
                            "--replace-record",
                            old.actor_profile_id,
                            "--replace-at",
                            "005",
                            "--write-ticket",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(["--workspace", str(workspace), "ticket", "review-next"]),
                    0,
                )
                self.assertEqual(
                    main(["--workspace", str(workspace), "ticket", "apply-next"]),
                    0,
                )

            profiles = repo.list_actor_profiles(actor.entity_id)
            old_record = next(
                item for item in profiles if item.actor_profile_id == old.actor_profile_id
            )
            new_record = next(
                item for item in profiles if item.actor_profile_id != old.actor_profile_id
            )
            self.assertEqual(old_record.status, "active")
            self.assertEqual(old_record.payload["_wsa"]["valid_until"], "005")
            self.assertEqual(new_record.payload["_wsa"]["valid_from"], "005")

            before = ContextBuilder(repo).build_actor_context(
                actor,
                "scene-before",
                "before replacement",
                time_scope="004",
                persist=False,
            )
            after = ContextBuilder(repo).build_actor_context(
                actor,
                "scene-after",
                "after replacement",
                time_scope="005",
                persist=False,
            )
            self.assertEqual(
                [item["actor_profile_id"] for item in before["actor_profiles"]],
                [old.actor_profile_id],
            )
            self.assertEqual(
                [item["actor_profile_id"] for item in after["actor_profiles"]],
                [new_record.actor_profile_id],
            )

    def test_memory_validity_can_be_closed_and_reopened_from_cli(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Memory Lifecycle CLI World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Ren")
            memory = repo.create_actor_memory_packet(
                actor.entity_id,
                "001",
                {
                    "summary": "Saw the first signal.",
                    "_wsa": {
                        "source_ref": "seed:memory",
                        "authority": "canon",
                        "valid_from": "001",
                        "valid_until": None,
                    },
                },
            )

            self._revise_and_apply(
                workspace,
                world.world_id,
                memory.memory_packet_id,
                ["--valid-until", "003"],
            )
            closed = ContextBuilder(repo).build_actor_context(
                actor,
                "scene-004",
                "recall",
                time_scope="004",
                persist=False,
            )
            self.assertEqual(closed["memories"], [])
            self.assertIn(
                "outside_time_scope",
                {item["reason"] for item in closed["receipt"]["excluded"]},
            )

            self._revise_and_apply(
                workspace,
                world.world_id,
                memory.memory_packet_id,
                ["--clear-valid-until"],
            )
            reopened = ContextBuilder(repo).build_actor_context(
                actor,
                "scene-004",
                "recall",
                time_scope="004",
                persist=False,
            )
            self.assertEqual(
                reopened["memories"][0]["memory_packet_id"],
                memory.memory_packet_id,
            )

    def test_revise_rejects_a_record_owned_by_another_actor(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Ownership CLI World")
            repo = WorldRepository(world.world_id, world.path)
            mina = repo.create_entity("character", "Mina")
            repo.create_entity("character", "Sol")
            profile = repo.create_actor_profile(
                mina.entity_id,
                "goal",
                {"summary": "Leave the island."},
            )

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "actor",
                        "revise",
                        world.world_id,
                        "Sol",
                        "--record-type",
                        "actor_profile",
                        "--record-id",
                        profile.actor_profile_id,
                        "--status",
                        "deprecated",
                        "--write-ticket",
                    ]
                )
            self.assertEqual(code, 1)
            self.assertIn("does not belong to the selected actor", output.getvalue())
            self.assertEqual(repo.list_tickets(), [])

    def _revise_and_apply(
        self,
        workspace: Path,
        world_id: str,
        record_id: str,
        revision_args: list[str],
    ) -> None:
        with redirect_stdout(StringIO()):
            self.assertEqual(
                main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "actor",
                        "revise",
                        world_id,
                        "Ren",
                        "--record-type",
                        "actor_memory_packet",
                        "--record-id",
                        record_id,
                        *revision_args,
                        "--write-ticket",
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(["--workspace", str(workspace), "ticket", "review-next"]),
                0,
            )
            self.assertEqual(
                main(["--workspace", str(workspace), "ticket", "apply-next"]),
                0,
            )
