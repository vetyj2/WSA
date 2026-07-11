import json
from unittest import TestCase

from wsa.application.startup_source_service import (
    STARTUP_SOURCE_RECORD_SCHEMA,
    StartupSourceService,
    startup_source_record_contract,
)


class StartupSourceServiceTests(TestCase):
    def test_cross_world_source_is_excluded_with_reason(self) -> None:
        summary = self._summary("world-current", ready=True)
        records = [
            self._source(
                "source-current",
                "world-current",
                "notes/current.md",
                excerpt="The opening stays close to one neighborhood.",
            ),
            self._source(
                "source-other",
                "world-other",
                "notes/other.md",
                excerpt="This belongs only to another world.",
            ),
        ]

        result = StartupSourceService().compile(summary, records)

        self.assertEqual(
            [item["source_id"] for item in result["sources"]["accepted"]],
            ["source-current"],
        )
        self.assertEqual(
            result["sources"]["excluded"],
            [
                {
                    "input_index": 1,
                    "source_id": "source-other",
                    "source_type": "notes",
                    "reason": "other_world_source_not_allowed",
                    "detail": (
                        "source world_id does not match the current Startup summary"
                    ),
                    "content_retained": False,
                }
            ],
        )
        self.assertEqual(len(result["follow_up_questions"]), 1)
        self.assertNotIn(
            "notes/other.md",
            json.dumps(result, ensure_ascii=False),
        )

    def test_no_source_before_minimum_frame_stays_neutral(self) -> None:
        summary = self._summary("world-current", ready=False)

        result = StartupSourceService().compile(summary, [])

        self.assertEqual(result["mode"], "neutral_minimum_frame")
        self.assertFalse(result["specific_followups_allowed"])
        self.assertEqual(result["follow_up_questions"], [])
        self.assertEqual(result["outcome"]["blockers"], summary["unresolved_blockers"])
        self.assertEqual(
            result["outcome"]["recommended_artifact"]["artifact_type"],
            "neutral_minimum_frame_question_set",
        )
        self.assertFalse(result["input_policy"]["model_provider_dependency"])

    def test_ready_follow_up_has_reason_refs_and_current_world_scope(self) -> None:
        summary = self._summary("world-current", ready=True)
        record = self._source(
            "source-tone",
            "world-current",
            "imports/author-notes.json#tone",
            source_type="import",
            structured_claims=[
                {
                    "claim_id": "tone-1",
                    "dimension": "tone_experience",
                    "status": "explicit",
                    "text": "The opening should feel restrained.",
                }
            ],
        )

        result = StartupSourceService(max_questions=1).compile(summary, [record])
        question = result["follow_up_questions"][0]

        self.assertTrue(result["specific_followups_allowed"])
        self.assertEqual(question["source_refs"], ["imports/author-notes.json#tone"])
        self.assertEqual(question["source_ids"], ["source-tone"])
        self.assertEqual(question["scope"], "current_world_only")
        self.assertIn("tone_experience", question["why_asked"])
        self.assertIn("The opening should feel restrained.", question["question"])
        self.assertFalse(question["bounds"]["allow_new_lore"])
        self.assertEqual(
            result["outcome"]["recommended_artifact"]["artifact_type"],
            "source_grounded_world_outline",
        )

    def test_private_memory_categories_are_excluded_without_content(self) -> None:
        summary = self._summary("world-current", ready=True)
        records = [
            self._source(
                "private-beta",
                "world-current",
                "private/beta",
                source_type="beta_memory",
                excerpt="PRIVATE_BETA_CONTENT",
            ),
            self._source(
                "private-manager",
                "world-current",
                "private/manager",
                source_type="manager_memory",
                excerpt="PRIVATE_MANAGER_CONTENT",
            ),
            self._source(
                "private-profile",
                "world-current",
                "private/profile",
                source_type="user_profile",
                excerpt="PRIVATE_PROFILE_CONTENT",
            ),
        ]

        result = StartupSourceService().compile(
            summary,
            records,
            private_inputs={"manager_memory": "PRIVATE_DIRECT_INPUT"},
        )
        rendered = json.dumps(result, ensure_ascii=False)

        self.assertEqual(result["sources"]["accepted"], [])
        self.assertEqual(result["follow_up_questions"], [])
        self.assertEqual(
            {item["reason"] for item in result["sources"]["excluded"]},
            {"private_memory_category_not_allowed"},
        )
        self.assertEqual(
            {item["source_type"] for item in result["sources"]["excluded"]},
            {"beta_memory", "manager_memory", "user_profile"},
        )
        for private_value in (
            "PRIVATE_BETA_CONTENT",
            "PRIVATE_MANAGER_CONTENT",
            "PRIVATE_PROFILE_CONTENT",
            "PRIVATE_DIRECT_INPUT",
            "private/beta",
            "private/manager",
            "private/profile",
        ):
            self.assertNotIn(private_value, rendered)

    def test_source_contract_requires_content_and_user_provenance(self) -> None:
        contract = startup_source_record_contract()

        self.assertEqual(contract["schema"], STARTUP_SOURCE_RECORD_SCHEMA)
        self.assertEqual(
            contract["content_requirement"],
            "non_empty_excerpt_or_structured_claims",
        )
        self.assertEqual(
            contract["provenance_requirement"],
            "user_supplied_or_user_approved",
        )

    @staticmethod
    def _summary(world_id: str, *, ready: bool) -> dict:
        blockers = []
        if not ready:
            blockers = [
                {
                    "question_id": "0001",
                    "dimension": "creation_goal",
                    "state": "unasked",
                }
            ]
        return {
            "schema": "wsa.world_startup.summary.v1",
            "world_id": world_id,
            "minimum_frame_ready": ready,
            "project_intent": [],
            "workflow_preferences": [
                {
                    "dimension": "output_target",
                    "semantic_value": "world_outline",
                }
            ],
            "explicit_world_assertions": [],
            "unresolved_blockers": blockers,
            "optional_unknowns": [
                {
                    "question_id": "0006",
                    "dimension": "tone_experience",
                    "state": "unasked",
                }
            ],
        }

    @staticmethod
    def _source(
        source_id: str,
        world_id: str,
        source_ref: str,
        *,
        source_type: str = "notes",
        excerpt: str = "",
        structured_claims: object = None,
    ) -> dict:
        return {
            "source_id": source_id,
            "world_id": world_id,
            "source_type": source_type,
            "source_ref": source_ref,
            "excerpt": excerpt,
            "structured_claims": structured_claims,
            "provenance": {"user_supplied": True},
        }
