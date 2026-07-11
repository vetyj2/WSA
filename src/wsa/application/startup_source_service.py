from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any, Dict, List, Optional

from . import startup_source_policy as _policy
from . import startup_source_support as _support


STARTUP_SOURCE_RECORD_SCHEMA = _policy.STARTUP_SOURCE_RECORD_SCHEMA
STARTUP_SOURCE_COMPILATION_SCHEMA = _support.STARTUP_SOURCE_COMPILATION_SCHEMA
DEFAULT_MAX_FOLLOW_UPS = _support.DEFAULT_MAX_FOLLOW_UPS
MAX_QUESTION_SOURCE_CHARS = _support.MAX_QUESTION_SOURCE_CHARS
ALLOWED_SOURCE_TYPES = _policy.ALLOWED_SOURCE_TYPES
PRIVATE_SOURCE_TYPES = _policy.PRIVATE_SOURCE_TYPES


class StartupSourceService:
    """Compile deterministic Startup follow-ups from explicit current-world sources."""

    def __init__(self, max_questions: int = DEFAULT_MAX_FOLLOW_UPS) -> None:
        if isinstance(max_questions, bool) or not isinstance(max_questions, int):
            raise TypeError("max_questions must be an integer")
        if max_questions <= 0:
            raise ValueError("max_questions must be positive")
        self.max_questions = max_questions

    def compile(
        self,
        startup_summary: Mapping[str, Any],
        source_records: Iterable[Mapping[str, Any]] = (),
        *,
        private_inputs: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        world_id = _policy._summary_world_id(startup_summary)
        blockers = _policy._mapping_list(startup_summary.get("unresolved_blockers"))
        optional_unknowns = _policy._mapping_list(
            startup_summary.get("optional_unknowns")
        )
        minimum_frame_ready = (
            _policy._minimum_frame_ready(startup_summary) and not blockers
        )

        accepted, excluded = _policy._filter_source_records(
            world_id,
            source_records,
        )
        excluded.extend(_policy._exclude_private_inputs(private_inputs))
        excluded.sort(key=_policy._exclusion_sort_key)

        normalized_claims = {
            source["source_id"]: _support._normalize_structured_claims(
                source.get("structured_claims")
            )
            for source in accepted
        }
        source_unknowns = _support._source_unknowns(accepted, normalized_claims)
        compiled_optional_unknowns = [
            *copy.deepcopy(optional_unknowns),
            *source_unknowns,
        ]

        specific_followups_allowed = minimum_frame_ready and bool(accepted)
        if not minimum_frame_ready:
            mode = "neutral_minimum_frame"
            questions: List[Dict[str, Any]] = []
        elif not accepted:
            mode = "neutral_no_registered_source"
            questions = []
        else:
            mode = "source_grounded_follow_up"
            questions = _support._compile_questions(
                accepted,
                normalized_claims,
                optional_unknowns,
                self.max_questions,
            )

        known_world_assertions = [
            *copy.deepcopy(
                _policy._mapping_list(
                    startup_summary.get("explicit_world_assertions")
                )
            ),
            *_support._source_claims_by_kind(
                accepted,
                normalized_claims,
                "explicit",
            ),
        ]
        candidate_directions = _support._source_claims_by_kind(
            accepted,
            normalized_claims,
            "candidate",
        )
        recommended_artifact = _support._recommended_artifact(
            startup_summary=startup_summary,
            minimum_frame_ready=minimum_frame_ready,
            has_sources=bool(accepted),
            has_questions=bool(questions),
            source_refs=[source["source_ref"] for source in accepted],
        )

        accepted_receipts = [
            {
                "source_id": source["source_id"],
                "world_id": source["world_id"],
                "source_type": source["source_type"],
                "source_ref": source["source_ref"],
                "content_kinds": [
                    key
                    for key in ("excerpt", "structured_claims")
                    if source.get(key) not in (None, "", [], {})
                ],
                "provenance": source["provenance_qualification"],
            }
            for source in accepted
        ]
        outcome = {
            "project_intent": copy.deepcopy(
                _policy._mapping_list(startup_summary.get("project_intent"))
            ),
            "known_world_assertions": known_world_assertions,
            "candidate_directions": candidate_directions,
            "blockers": copy.deepcopy(blockers),
            "optional_unknowns": compiled_optional_unknowns,
            "recommended_artifact": recommended_artifact,
        }
        return {
            "schema": STARTUP_SOURCE_COMPILATION_SCHEMA,
            "world_id": world_id,
            "scope": "current_world_only",
            "mode": mode,
            "minimum_frame_ready": minimum_frame_ready,
            "specific_followups_allowed": specific_followups_allowed,
            "follow_up_questions": questions,
            "question_limit": self.max_questions,
            "sources": {
                "record_schema": STARTUP_SOURCE_RECORD_SCHEMA,
                "accepted": accepted_receipts,
                "excluded": excluded,
            },
            "input_policy": startup_source_input_policy(),
            "outcome": outcome,
            "side_effect_status": "read_only_compilation_no_world_mutation",
        }


def compile_startup_source_follow_ups(
    startup_summary: Mapping[str, Any],
    source_records: Iterable[Mapping[str, Any]] = (),
    *,
    max_questions: int = DEFAULT_MAX_FOLLOW_UPS,
    private_inputs: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return StartupSourceService(max_questions=max_questions).compile(
        startup_summary,
        source_records,
        private_inputs=private_inputs,
    )


def startup_source_record_contract() -> Dict[str, Any]:
    return _policy.startup_source_record_contract()


def startup_source_input_policy() -> Dict[str, Any]:
    return _policy.startup_source_input_policy()
