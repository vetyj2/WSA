import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.startup import (
    StartupProfileManager,
    format_startup_interview,
    format_startup_status,
    parse_startup_answer_text,
    startup_interview_to_dict,
    startup_status_to_dict,
)
from wsa.workspace import create_world


class StartupTests(TestCase):
    def test_startup_profile_starts_fully_ambiguous(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Startup World")
            manager = StartupProfileManager(world)

            status = manager.status()
            profile = json.loads(manager.profile_path.read_text(encoding="utf-8"))

            self.assertEqual(status.startup_ambiguity_percent, 100)
            self.assertEqual(status.required_resolved, 0)
            self.assertFalse(status.startup_ready)
            self.assertEqual(len(profile["dimensions"]), 10)
            self.assertEqual(profile["dimensions"][0]["question_id"], "0001")
            self.assertEqual(profile["interview_policy"]["question_id_format"], "four_digit")
            self.assertEqual(profile["discretion_level"], 2)
            self.assertTrue(profile["generation_policy"]["fully_autonomous_generation_allowed"])
            self.assertEqual(
                profile["generation_policy"]["discretion_scale"]["5"]["label"],
                "challenge_world_autonomy",
            )
            self.assertTrue(profile["generation_policy"]["discretion_scale"]["5"]["cron_allowed"])
            self.assertTrue(profile["generation_policy"]["discretion_customizable"])
            self.assertTrue(
                profile["generation_policy"]["fill_the_rest"][
                    "requires_destination_checkpoint"
                ]
            )
            self.assertEqual(
                profile["generation_policy"]["checkpoint_style"],
                "natural_language_recommended",
            )

    def test_interview_marks_limited_numbered_questions_asked(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Interview World")
            manager = StartupProfileManager(world)

            round_ = manager.interview(budget=3)
            lines = format_startup_interview(round_)

            self.assertEqual(round_.round_id, "R001")
            self.assertEqual([item["question_id"] for item in round_.questions], ["0001", "0002", "0003"])
            self.assertIn("startup_interview_round: R001", lines)
            self.assertIn("startup_interview_mode: startup", lines)
            self.assertTrue(any("0001a=" in line for line in lines))
            self.assertIn("deferred_to_meeting:", lines)

    def test_easystartup_uses_easy_picks_and_batch_answer_codes(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Easy Startup World")
            manager = StartupProfileManager(world)

            round_ = manager.interview(budget=2, mode="easystartup")
            lines = format_startup_interview(round_)
            status = manager.answer_batch("0001a 0002b 그리고 학교물은 조금 어둡게")
            profile = json.loads(manager.profile_path.read_text(encoding="utf-8"))

            self.assertEqual(round_.mode, "easystartup")
            self.assertTrue(any("0001f=" in line for line in lines))
            self.assertEqual(status.startup_ambiguity_percent, 80)
            self.assertEqual(profile["dimensions"][0]["selected_choice"], "a")
            self.assertEqual(profile["dimensions"][1]["selected_choice"], "b")
            self.assertEqual(profile["freeform_notes"][0]["text"], "그리고 학교물은 조금 어둡게")

    def test_easystartup_batch_can_start_without_prior_interview(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Direct Easy Startup World")
            manager = StartupProfileManager(world)

            status = manager.answer_batch("0001f 첫 사건은 조용히 시작", mode="easystartup")
            profile = json.loads(manager.profile_path.read_text(encoding="utf-8"))

            self.assertEqual(status.active_mode, "easystartup")
            self.assertEqual(status.startup_ambiguity_percent, 90)
            self.assertEqual(profile["active_mode"], "easystartup")
            self.assertEqual(profile["dimensions"][0]["selected_choice"], "f")
            self.assertIn("court intrigue", profile["dimensions"][0]["answer"])

    def test_status_can_report_requested_mode_without_mutating_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Mode Status World")
            manager = StartupProfileManager(world)

            status = manager.status(mode="easystartup")
            profile = json.loads(manager.profile_path.read_text(encoding="utf-8"))

            self.assertEqual(status.active_mode, "easystartup")
            self.assertEqual(profile["active_mode"], "startup")

    def test_parse_parallel_answer_codes(self) -> None:
        selections, note = parse_startup_answer_text("0001a\n0002b\nQ003e 그리고 이런 점은 저렇게")

        self.assertEqual(selections, [("0001", "a"), ("0002", "b"), ("0003", "e")])
        self.assertEqual(note, "그리고 이런 점은 저렇게")

    def test_discretion_level_is_visible_in_status(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Discretion World")
            manager = StartupProfileManager(world)

            status = manager.set_discretion(5)
            lines = format_startup_status(status)

            self.assertEqual(status.discretion_level, 5)
            self.assertEqual(status.discretion_label, "challenge_world_autonomy")
            self.assertIn("discretion_level: 5 (challenge_world_autonomy)", lines)

    def test_answering_required_questions_reduces_startup_ambiguity(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Answer World")
            manager = StartupProfileManager(world)

            status = manager.answer("Q001", "A school mystery fantasy with a bitter tone.")
            lines = format_startup_status(status)

            self.assertEqual(status.startup_ambiguity_percent, 90)
            self.assertEqual(status.required_resolved, 1)
            self.assertIn("startup_ready: no", lines)

    def test_all_required_answers_make_world_startup_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Ready World")
            manager = StartupProfileManager(world)

            for index in range(1, 11):
                status = manager.answer(f"Q{index:03d}", f"Answer {index}")

            self.assertEqual(status.startup_ambiguity_percent, 0)
            self.assertTrue(status.startup_ready)

    def test_startup_json_serializers_expose_machine_readable_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "JSON Startup World")
            manager = StartupProfileManager(world)

            status_payload = startup_status_to_dict(manager.status(mode="easystartup"))
            round_payload = startup_interview_to_dict(
                manager.interview(budget=1, mode="easystartup")
            )

            self.assertEqual(status_payload["active_mode"], "easystartup")
            self.assertEqual(round_payload["mode"], "easystartup")
            self.assertEqual(round_payload["questions"][0]["question_id"], "0001")
            self.assertEqual(round_payload["questions"][0]["choices"][5]["code"], "0001f")

    def test_agent_proposal_does_not_resolve_until_author_approval(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Approval World")
            manager = StartupProfileManager(world)

            proposed = manager.answer("Q001", "An agent-suggested premise.", answered_by="agent_proposal")
            approved = manager.set_status("Q001", "approved_by_author")

            self.assertEqual(proposed.startup_ambiguity_percent, 100)
            self.assertEqual(proposed.required_resolved, 0)
            self.assertEqual(approved.startup_ambiguity_percent, 90)
            self.assertEqual(approved.required_resolved, 1)

    def test_resolved_status_requires_answer_text(self) -> None:
        with TemporaryDirectory() as tmp:
            world = create_world(Path(tmp) / "workspace", "Empty Approval World")
            manager = StartupProfileManager(world)

            with self.assertRaises(ValueError):
                manager.set_status("Q001", "approved_by_author")
