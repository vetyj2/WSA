"""Structured-claim, question, outcome, and artifact compilation support."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional

from .startup_source_policy import (
    _first_non_empty_string,
    _mapping_list,
    _normalize_token,
)


STARTUP_SOURCE_COMPILATION_SCHEMA = "wsa.world_startup.source_compilation.v1"
DEFAULT_MAX_FOLLOW_UPS = 5
MAX_QUESTION_SOURCE_CHARS = 240
_UNRESOLVED_STATUSES = frozenset(
    {
        "ambiguous",
        "needs_clarification",
        "open",
        "pending",
        "question",
        "unknown",
        "unresolved",
    }
)
_CANDIDATE_STATUSES = frozenset({"candidate", "proposed", "suggestion"})
_CLAIM_TEXT_KEYS = ("claim", "text", "statement", "value", "question", "summary")
_DIRECT_CLAIM_KEYS = frozenset(
    {
        "claim_id",
        "dimension",
        "field",
        "object",
        "object_ref_id",
        "object_value",
        "predicate",
        "subject",
        "subject_id",
        "status",
        "topic",
        "resolved",
        "unresolved",
        *_CLAIM_TEXT_KEYS,
    }
)
_CLAIM_GROUP_KINDS = {
    "assertions": "explicit",
    "candidate": "candidate",
    "candidates": "candidate",
    "explicit": "explicit",
    "known": "explicit",
    "open": "unresolved",
    "proposed": "candidate",
    "unknown": "unresolved",
    "unresolved": "unresolved",
}

_ARTIFACT_TYPES = {
    "character_candidates": "source_grounded_character_candidate_set",
    "first_scene_candidates": "source_grounded_first_scene_candidate_set",
    "place_or_situation_candidates": "source_grounded_place_or_situation_candidate_set",
    "question_list": "source_grounded_follow_up_question_set",
    "question_list_and_decision_log": "source_grounded_follow_up_question_set",
    "reviewable_world_candidates": "source_grounded_world_candidate_set",
    "rules_and_constraints_summary": "source_grounded_rules_and_constraints_summary",
    "world_outline": "source_grounded_world_outline",
    "world_outline_or_rules_summary": "source_grounded_world_outline",
}


def _normalize_structured_claims(value: Any) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []

    def visit(
        item: Any,
        *,
        default_status: str = "explicit",
        default_dimension: Optional[str] = None,
        default_claim_id: Optional[str] = None,
    ) -> None:
        if isinstance(item, Mapping):
            normalized_keys = {_normalize_token(str(key)) for key in item}
            if normalized_keys and normalized_keys <= _CLAIM_GROUP_KINDS.keys():
                for key in sorted(item, key=lambda candidate: str(candidate)):
                    normalized_key = _normalize_token(str(key))
                    visit(item[key], default_status=_CLAIM_GROUP_KINDS[normalized_key])
                return
            if normalized_keys & _DIRECT_CLAIM_KEYS:
                text = _claim_text(item)
                if text is None:
                    text = _claim_payload_text(item)
                if text is None:
                    return
                raw_status = item.get("status", default_status)
                if item.get("unresolved") is True or item.get("resolved") is False:
                    raw_status = "unresolved"
                dimension = _first_non_empty_string(
                    item.get("dimension"),
                    item.get("topic"),
                    item.get("field"),
                    default_dimension,
                )
                claim_id = _first_non_empty_string(
                    item.get("claim_id"),
                    default_claim_id,
                )
                claims.append(
                    {
                        "claim_id": claim_id,
                        "dimension": dimension,
                        "text": text,
                        "kind": _claim_kind(raw_status),
                        "status": _normalize_token(str(raw_status or "explicit")),
                    }
                )
                return

            for key in sorted(item, key=lambda candidate: str(candidate)):
                child = item[key]
                normalized_key = _normalize_token(str(key))
                visit(
                    child,
                    default_status=_CLAIM_GROUP_KINDS.get(
                        normalized_key,
                        default_status,
                    ),
                    default_dimension=(
                        None
                        if normalized_key in _CLAIM_GROUP_KINDS
                        else str(key)
                    ),
                    default_claim_id=(
                        None
                        if normalized_key in _CLAIM_GROUP_KINDS
                        else str(key)
                    ),
                )
            return

        if isinstance(item, Sequence) and not isinstance(
            item,
            (str, bytes, bytearray),
        ):
            for index, child in enumerate(item, start=1):
                visit(
                    child,
                    default_status=default_status,
                    default_dimension=default_dimension,
                    default_claim_id=f"claim-{index:03d}",
                )
            return

        text = _claim_value_text(item)
        if text is not None:
            claims.append(
                {
                    "claim_id": default_claim_id,
                    "dimension": default_dimension,
                    "text": text,
                    "kind": _claim_kind(default_status),
                    "status": _normalize_token(default_status),
                }
            )

    if value not in (None, "", [], {}):
        visit(value)
    for index, claim in enumerate(claims, start=1):
        if not claim["claim_id"]:
            claim["claim_id"] = f"claim-{index:03d}"
    claims.sort(
        key=lambda claim: (
            {"unresolved": 0, "candidate": 1, "explicit": 2}[claim["kind"]],
            claim.get("dimension") or "",
            claim["claim_id"],
            claim["text"],
        )
    )
    return claims


def _claim_text(item: Mapping[str, Any]) -> Optional[str]:
    for key in _CLAIM_TEXT_KEYS:
        if key in item:
            return _claim_value_text(item[key])
    return None


def _claim_payload_text(item: Mapping[str, Any]) -> Optional[str]:
    payload = {
        str(key): value
        for key, value in item.items()
        if _normalize_token(str(key))
        not in {
            "claim_id",
            "dimension",
            "field",
            "resolved",
            "status",
            "topic",
            "unresolved",
        }
    }
    return _claim_value_text(payload) if payload else None


def _claim_value_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    return text if text not in ("", "null") else None


def _claim_kind(status: Any) -> str:
    normalized = _normalize_token(str(status or "explicit"))
    if normalized in _UNRESOLVED_STATUSES:
        return "unresolved"
    if normalized in _CANDIDATE_STATUSES:
        return "candidate"
    return "explicit"


def _compile_questions(
    accepted: List[Dict[str, Any]],
    claims_by_source: Dict[str, List[Dict[str, Any]]],
    optional_unknowns: List[Dict[str, Any]],
    max_questions: int,
) -> List[Dict[str, Any]]:
    unknown_dimensions = {
        str(item.get("dimension"))
        for item in optional_unknowns
        if item.get("dimension")
    }
    questions: List[Dict[str, Any]] = []
    for source in accepted[:max_questions]:
        claims = claims_by_source[source["source_id"]]
        anchor = claims[0] if claims else None
        source_text = anchor["text"] if anchor else source.get("excerpt")
        if not source_text:
            continue
        quote = _bounded_source_text(source_text)
        dimension = anchor.get("dimension") if anchor else None
        kind = anchor["kind"] if anchor else "excerpt"
        if kind == "unresolved":
            question = (
                "What one author decision should resolve or explicitly defer this "
                f'current-world source item: "{quote}"?'
            )
            why_asked = (
                f"Registered source {source['source_id']} explicitly marks this item "
                "as unresolved."
            )
            question_type = "resolve_source_unknown"
        elif kind == "candidate":
            question = (
                "Should this registered candidate be accepted, revised, or kept "
                f'optional for the current world: "{quote}"?'
            )
            why_asked = (
                f"Registered source {source['source_id']} labels this content as a "
                "candidate rather than an established assertion."
            )
            question_type = "review_source_candidate"
        elif dimension and dimension in unknown_dimensions:
            question = (
                f'For the unresolved Startup dimension "{dimension}", what one detail '
                "should be explicitly established or deferred using only this source "
                f'item: "{quote}"?'
            )
            why_asked = (
                f"Startup leaves {dimension} unresolved and registered source "
                f"{source['source_id']} contains an explicit claim for that dimension."
            )
            question_type = "resolve_startup_unknown_from_source"
        elif kind == "explicit":
            question = (
                "Should this explicit current-world source item remain established, "
                f'become a candidate, or leave one named unknown: "{quote}"?'
            )
            why_asked = (
                f"Registered source {source['source_id']} contains an explicit claim "
                "that can be bounded before producing the requested artifact."
            )
            question_type = "bound_explicit_source_claim"
        else:
            question = (
                "Which one detail in this current-world excerpt should be marked "
                f'explicit or unresolved: "{quote}"?'
            )
            why_asked = (
                f"Registered source {source['source_id']} supplies an excerpt without "
                "structured claim status."
            )
            question_type = "classify_source_excerpt"

        questions.append(
            {
                "question_id": f"SF{len(questions) + 1:03d}",
                "question_type": question_type,
                "dimension": dimension,
                "question": question,
                "why_asked": why_asked,
                "source_refs": [source["source_ref"]],
                "source_ids": [source["source_id"]],
                "scope": "current_world_only",
                "bounds": {
                    "max_answer_items": 1,
                    "allowed_evidence": "listed_source_refs_only",
                    "allow_new_lore": False,
                },
            }
        )
    return questions


def _source_claims_by_kind(
    accepted: List[Dict[str, Any]],
    claims_by_source: Dict[str, List[Dict[str, Any]]],
    kind: str,
) -> List[Dict[str, Any]]:
    result = []
    for source in accepted:
        for claim in claims_by_source[source["source_id"]]:
            if claim["kind"] != kind:
                continue
            result.append(
                {
                    "origin": "registered_current_world_source",
                    "source_id": source["source_id"],
                    "source_ref": source["source_ref"],
                    "claim_id": claim["claim_id"],
                    "dimension": claim["dimension"],
                    "text": claim["text"],
                    "status": claim["status"],
                    "scope": "current_world_only",
                }
            )
    return result


def _source_unknowns(
    accepted: List[Dict[str, Any]],
    claims_by_source: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    result = []
    for source in accepted:
        for claim in claims_by_source[source["source_id"]]:
            if claim["kind"] != "unresolved":
                continue
            result.append(
                {
                    "state": "unresolved_source_claim",
                    "dimension": claim["dimension"],
                    "claim_id": claim["claim_id"],
                    "text": claim["text"],
                    "source_refs": [source["source_ref"]],
                    "scope": "current_world_only",
                }
            )
    return result


def _recommended_artifact(
    *,
    startup_summary: Mapping[str, Any],
    minimum_frame_ready: bool,
    has_sources: bool,
    has_questions: bool,
    source_refs: List[str],
) -> Dict[str, Any]:
    requested_value = _requested_output_value(startup_summary)
    requested_type = _ARTIFACT_TYPES.get(
        requested_value,
        "source_grounded_startup_decision_log",
    )
    if not minimum_frame_ready:
        return {
            "artifact_type": "neutral_minimum_frame_question_set",
            "status": "blocked_on_minimum_frame",
            "reason": "complete the neutral minimum frame before any specific follow-up",
            "requested_artifact_type": requested_type,
            "source_refs": [],
        }
    if not has_sources:
        return {
            "artifact_type": "neutral_optional_unknown_review",
            "status": "waiting_for_explicit_current_world_source",
            "reason": "no eligible registered source exists for a specific follow-up",
            "requested_artifact_type": requested_type,
            "source_refs": [],
        }
    return {
        "artifact_type": requested_type,
        "status": "after_follow_up_review" if has_questions else "ready_for_review",
        "reason": "matches the explicit Startup output target without adding unsourced lore",
        "requested_artifact_type": requested_type,
        "source_refs": sorted(set(source_refs)),
    }


def _requested_output_value(startup_summary: Mapping[str, Any]) -> str:
    preferences = _mapping_list(startup_summary.get("workflow_preferences"))
    for item in preferences:
        if item.get("dimension") != "output_target":
            continue
        value = item.get("semantic_value", item.get("answer"))
        if value:
            return _normalize_token(str(value))
    return ""


def _bounded_source_text(value: str) -> str:
    compact = " ".join(value.split())
    if len(compact) <= MAX_QUESTION_SOURCE_CHARS:
        return compact
    return f"{compact[: MAX_QUESTION_SOURCE_CHARS - 3].rstrip()}..."
