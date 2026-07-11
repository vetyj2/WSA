import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.application.proposal_service import startup_proposal_preview
from wsa.startup import StartupProfileManager, startup_interview_to_dict
from wsa.workspace import create_world


class Phase0StartupIntentTests(TestCase):
    def test_summary_separates_intent_assertions_blockers_and_unknowns(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Intent World")
            manager = StartupProfileManager(world)

            manager.answer_batch(
                "0001a 0002a 0003b 0004b 0005a 0006f 0008f 0009f",
                mode="easystartup",
            )
            summary = manager.summary()

            self.assertTrue(summary["minimum_frame_ready"])
            self.assertTrue(summary["startup_ready"])
            self.assertFalse(summary["full_interview_complete"])
            self.assertEqual(
                [item["dimension"] for item in summary["project_intent"]],
                ["creation_goal", "starting_material"],
            )
            self.assertEqual(
                [item["dimension"] for item in summary["workflow_preferences"]],
                ["author_control", "output_target"],
            )
            self.assertEqual(
                [item["dimension"] for item in summary["explicit_world_assertions"]],
                ["reality_distance"],
            )
            self.assertEqual(summary["unresolved_blockers"], [])
            optional_dimensions = {
                item["dimension"] for item in summary["optional_unknowns"]
            }
            self.assertEqual(
                optional_dimensions,
                {
                    "tone_experience",
                    "scope_focus",
                    "change_pressure",
                    "known_vs_unknown",
                    "boundaries_and_preferences",
                },
            )

            manager.answer_batch("0007f 0010f", mode="easystartup")
            complete = manager.summary()
            self.assertTrue(complete["full_interview_complete"])
            self.assertEqual(complete["readiness"], complete["outcome"]["readiness"])

    def test_proposal_materializes_only_explicit_world_semantics(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Canon Filter World")
            manager = StartupProfileManager(world)
            interview = startup_interview_to_dict(
                manager.interview(budget=5, mode="easystartup")
            )
            reality_choice = interview["questions"][4]["choices"][0]

            self.assertEqual(reality_choice["choice_code"], "0005a")
            self.assertEqual(reality_choice["choice_label"], "close to present reality")
            self.assertEqual(
                reality_choice["semantic_value"], "close_to_present_reality"
            )

            manager.answer_batch(
                "0001a 0002f 0003b 0004c 0005a 0006f 0007f 0008c",
                mode="easystartup",
            )
            preview = startup_proposal_preview(world)

            self.assertEqual(
                [change["predicate"] for change in preview.changes],
                ["startup.reality_distance", "startup.change_pressure"],
            )
            self.assertEqual(
                preview.changes[0]["object_value"], "close_to_present_reality"
            )
            payload = preview.changes[0]["payload"]
            self.assertEqual(payload["choice_code"], "0005a")
            self.assertEqual(payload["choice_label"], "close to present reality")
            self.assertEqual(payload["source"]["kind"], "ui_choice")
            self.assertEqual(payload["provenance"]["authority"], "user_explicit")
            self.assertNotIn(
                "startup.creation_goal",
                {change["predicate"] for change in preview.changes},
            )

    def test_fixed_neutral_pack_contract_does_not_read_memory_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Neutral Contract World")
            manager = StartupProfileManager(world)
            profile = manager.load_or_create()
            read_paths = []
            original_read_text = Path.read_text

            def tracked_read_text(path: Path, *args: object, **kwargs: object) -> str:
                read_paths.append(path)
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", tracked_read_text):
                manager.interview(budget=1, mode="easystartup")

            contract = profile["question_pack_contract"]
            self.assertEqual(contract["pack_type"], "fixed_neutral")
            self.assertEqual(contract["memory_inputs"], [])
            self.assertEqual(
                contract["excluded_memory_inputs"],
                ["beta_memory", "user_memory", "manager_memory"],
            )
            self.assertFalse(contract["reads_beta_memory"])
            self.assertFalse(contract["reads_user_memory"])
            self.assertFalse(contract["reads_manager_memory"])
            self.assertEqual(read_paths, [manager.profile_path])

    def test_existing_profile_backfill_preserves_answer_and_choice(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Migration World")
            manager = StartupProfileManager(world)
            manager.answer_batch("0005a", mode="easystartup")
            profile = json.loads(manager.profile_path.read_text(encoding="utf-8"))
            item = profile["dimensions"][4]
            original_answer = item["answer"]
            for key in (
                "selected_choice_code",
                "selected_choice_label",
                "semantic_value",
                "semantic_state",
                "answer_mode",
                "answer_source",
                "answer_provenance",
            ):
                item.pop(key, None)
            profile.pop("question_pack_contract", None)
            profile.pop("readiness_policy", None)
            manager.profile_path.write_text(
                json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            migrated = manager.load_or_create()
            migrated_item = migrated["dimensions"][4]

            self.assertEqual(migrated_item["answer"], original_answer)
            self.assertEqual(migrated_item["selected_choice"], "a")
            self.assertEqual(migrated_item["selected_choice_code"], "0005a")
            self.assertEqual(
                migrated_item["semantic_value"], "close_to_present_reality"
            )
            self.assertIn("question_pack_contract", migrated)
            self.assertIn("readiness_policy", migrated)
