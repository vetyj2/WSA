import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.startup import (
    StartupProfileManager,
    format_startup_interview,
    format_startup_status,
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
            self.assertEqual(profile["dimensions"][0]["question_id"], "Q001")
            self.assertTrue(profile["generation_policy"]["fully_autonomous_generation_allowed"])
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
            self.assertEqual([item["question_id"] for item in round_.questions], ["Q001", "Q002", "Q003"])
            self.assertIn("startup_interview_round: R001", lines)
            self.assertIn("deferred_to_meeting:", lines)

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
