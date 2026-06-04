from __future__ import annotations

from typing import Any, Dict, Iterable, List


SCENE_MODE_DISCLOSURE_SCHEMA = "wsa.scene_generation.mode_disclosure.v1"
ACTOR_CONTRIBUTION_SUMMARY_SCHEMA = "wsa.actor_contribution_summary.v1"
SCENE_GENERATION_MODES = {
    "auto",
    "fact_audit_synthesis",
    "writing_room_line_build",
}


def normalize_scene_generation_mode(value: str | None) -> str:
    if not value:
        return "auto"
    normalized = value.strip().lower().replace("-", "_")
    if normalized not in SCENE_GENERATION_MODES:
        raise ValueError(
            "scene generation mode must be one of: auto, fact-audit-synthesis, "
            "writing-room-line-build"
        )
    return normalized


def build_scene_mode_disclosure(
    workflow: str,
    skill: str,
    requested_mode: str | None,
) -> Dict[str, Any]:
    requested = normalize_scene_generation_mode(requested_mode)
    applies = workflow == "scene_generation" or skill == "scene_start"
    if not applies:
        return {
            "schema": SCENE_MODE_DISCLOSURE_SCHEMA,
            "applicable": False,
            "workflow": workflow,
            "skill": skill,
        }

    if requested == "auto":
        resolved = "fact_audit_synthesis"
        source = "fallback_until_hermes_or_profile_reports_mode"
        confidence = "low"
    else:
        resolved = requested
        source = "explicit_user_or_cli"
        confidence = "high"

    return {
        "schema": SCENE_MODE_DISCLOSURE_SCHEMA,
        "applicable": True,
        "requested_mode": requested,
        "resolved_mode": resolved,
        "mode_resolution_source": source,
        "mode_confidence": confidence,
        "available_modes": [
            {
                "mode": "fact_audit_synthesis",
                "meaning": (
                    "Actors verify facts, constraints, reports, and ledgers; a synthesizer "
                    "writes or packages the draft."
                ),
                "requires_actor_line_authorship": False,
            },
            {
                "mode": "writing_room_line_build",
                "meaning": (
                    "Actors propose, validate, reject, retry, and accept beats or lines into "
                    "an accepted draft ledger."
                ),
                "requires_actor_line_authorship": True,
            },
        ],
        "execution_boundary": {
            "wsa_direct_scene_generation": False,
            "external_runtime_executes_actor_work": True,
            "wsa_records_mode_and_accounting": True,
        },
        "what_actors_actually_did": "pending_runtime_outputs",
        "what_was_not_performed": [
            "no_actor_authored_line_build_confirmed_yet",
            "no_accepted_draft_ledger_confirmed_yet",
        ],
    }


def update_scene_mode_disclosure_for_outputs(
    disclosure: Dict[str, Any],
    contribution_summary: Dict[str, Any],
) -> Dict[str, Any]:
    if not disclosure.get("applicable"):
        return disclosure
    updated = dict(disclosure)
    actor_sentences = int(contribution_summary.get("actor_authored_sentence_count") or 0)
    adopted = int(contribution_summary.get("adopted_actor_proposal_count") or 0)
    rollback_count = int(contribution_summary.get("rollback_event_count") or 0)
    if updated.get("resolved_mode") == "writing_room_line_build":
        if actor_sentences or adopted or rollback_count:
            updated["what_actors_actually_did"] = "line_build_callbacks_reported"
            updated["what_was_not_performed"] = []
        else:
            updated["what_actors_actually_did"] = "line_build_requested_but_not_evidenced"
            updated["what_was_not_performed"] = [
                "no_actor_authored_sentence_count_reported",
                "no_adopted_actor_proposal_count_reported",
                "no_rollback_or_retry_event_reported",
            ]
    else:
        if contribution_summary.get("sql_or_fact_lookup_performed"):
            updated["what_actors_actually_did"] = "fact_audit_or_constraint_outputs_reported"
        elif contribution_summary.get("callback_accepted"):
            updated["what_actors_actually_did"] = "guardrail_or_constraint_callbacks_reported"
        else:
            updated["what_actors_actually_did"] = "no_runtime_actor_outputs_reported"
        updated["what_was_not_performed"] = [
            "writing_room_line_build_not_confirmed",
            "accepted_draft_ledger_not_confirmed",
        ]
    return updated


def build_actor_contribution_summary(
    outputs: Iterable[Dict[str, Any]],
    rejected_callbacks: Iterable[Dict[str, Any]] | None = None,
    submitted_callbacks: Iterable[Dict[str, Any]] | None = None,
    final_synthesizer: str = "external_runtime_or_orchestrator_synthesis",
    actor_authorship_evidence: bool = True,
) -> Dict[str, Any]:
    output_list = [item for item in outputs if isinstance(item, dict)]
    rejected_list = [item for item in (rejected_callbacks or []) if isinstance(item, dict)]
    submitted_list = [item for item in (submitted_callbacks or []) if isinstance(item, dict)]
    actor_roles: Dict[str, Dict[str, Any]] = {}
    for output in output_list:
        participant_id = str(output.get("participant_id") or "unknown")
        record = actor_roles.setdefault(
            participant_id,
            {
                "participant_id": participant_id,
                "represents": output.get("represents"),
                "labels": set(),
                "accepted_output_count": 0,
            },
        )
        record["accepted_output_count"] += 1
        for label in _labels_for_output(output, actor_authorship_evidence=actor_authorship_evidence):
            record["labels"].add(label)

    for rejected in rejected_list:
        participant_id = _participant_from_turn_id(rejected.get("turn_id")) or "unknown"
        record = actor_roles.setdefault(
            participant_id,
            {
                "participant_id": participant_id,
                "represents": rejected.get("represents"),
                "labels": set(),
                "accepted_output_count": 0,
            },
        )
        record["labels"].add("rollback_trigger")

    role_records = []
    for record in actor_roles.values():
        labels = sorted(record.pop("labels"))
        record["function_labels"] = labels or ["observer"]
        role_records.append(record)

    actor_sentence_count = (
        sum(_count_actor_authored_sentences(output) for output in output_list)
        if actor_authorship_evidence
        else 0
    )
    adopted_count = (
        sum(_count_adopted_proposals(output) for output in output_list)
        if actor_authorship_evidence
        else 0
    )
    sql_lookup = any(_has_fact_audit_signal(output) for output in output_list)
    return {
        "schema": ACTOR_CONTRIBUTION_SUMMARY_SCHEMA,
        "callback_total": len(submitted_list) if submitted_list else len(output_list) + len(rejected_list),
        "callback_accepted": len(output_list),
        "callback_rejected": len(rejected_list),
        "rollback_event_count": len(rejected_list),
        "sql_or_fact_lookup_performed": sql_lookup,
        "actor_authored_sentence_count": actor_sentence_count,
        "adopted_actor_proposal_count": adopted_count,
        "final_synthesizer": final_synthesizer,
        "actor_function_labels": role_records,
        "interpretation": _interpretation(sql_lookup, actor_sentence_count, adopted_count, rejected_list),
    }


def _labels_for_output(
    output: Dict[str, Any],
    actor_authorship_evidence: bool = True,
) -> List[str]:
    labels = ["constraint_panel"]
    if _has_fact_audit_signal(output):
        labels.append("sql_auditor")
    if actor_authorship_evidence and (
        _count_actor_authored_sentences(output) or output.get("dialogue") or output.get("draft_text")
    ):
        labels.append("co_writer")
    if output.get("prep_completion_check") or output.get("confidence") or output.get("conflicts"):
        labels.append("validator")
    return labels


def _has_fact_audit_signal(output: Dict[str, Any]) -> bool:
    return any(
        output.get(field)
        for field in (
            "source_refs",
            "facts_to_include",
            "facts_to_hide",
            "conflicts_with",
            "dependencies",
        )
    )


def _count_actor_authored_sentences(output: Dict[str, Any]) -> int:
    count = 0
    for field in ("scene_beat", "draft_text", "dialogue", "line_candidates", "accepted_lines"):
        value = output.get(field)
        if isinstance(value, str) and value.strip():
            count += 1
        elif isinstance(value, list):
            count += len([item for item in value if str(item).strip()])
    return count


def _count_adopted_proposals(output: Dict[str, Any]) -> int:
    for field in ("adopted_proposals", "accepted_lines", "accepted_beats"):
        value = output.get(field)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, str) and value.strip():
            return 1
    return 0


def _participant_from_turn_id(turn_id: Any) -> str | None:
    if not isinstance(turn_id, str):
        return None
    parts = turn_id.split(":")
    return parts[1] if len(parts) >= 3 else None


def _interpretation(
    sql_lookup: bool,
    actor_sentences: int,
    adopted: int,
    rejected: List[Dict[str, Any]],
) -> str:
    if actor_sentences or adopted or rejected:
        return "actor_agency_evidenced_by_line_or_validation_events"
    if sql_lookup:
        return "fact_audit_or_constraint_synthesis_run"
    return "guardrail_or_synthesis_run_not_line_build_consensus"
