from __future__ import annotations

from typing import Any, Dict, Iterable, List


SCENE_MODE_DISCLOSURE_SCHEMA = "wsa.scene_generation.mode_disclosure.v1"
ACTOR_CONTRIBUTION_SUMMARY_SCHEMA = "wsa.actor_contribution_summary.v1"
FACT_AUDIT_EVIDENCE_SCHEMA = "wsa.scene.fact_audit_evidence.v1"
LINE_BUILD_LEDGER_SCHEMA = "wsa.scene.line_build_ledger.v1"
SCENE_GENERATION_MODES = {
    "auto",
    "fact_audit_synthesis",
    "writing_room_line_build",
}
FACT_AUDIT_EVIDENCE_FIELDS = [
    "source_refs",
    "fact_lookup_queries",
    "checked_tables",
    "checked_reports",
    "proposal_or_quarantine_refs",
    "conflicts_found",
    "deferred_claims",
    "unchecked_claims",
]
LINE_BUILD_LEDGER_FIELDS = [
    "beat_id",
    "line_id",
    "candidate_text",
    "line_candidates",
    "accepted_lines",
    "accepted_beats",
    "adopted_proposals",
    "validation_decision",
    "rollback_reason",
    "retry_count",
]


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
        "mode_contracts": {
            "fact_audit_synthesis": build_fact_audit_evidence_contract(),
            "writing_room_line_build": build_line_build_ledger_contract(),
        },
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
    fact_evidence = bool(contribution_summary.get("fact_audit_evidence_available"))
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
        if fact_evidence:
            updated["what_actors_actually_did"] = "fact_audit_evidence_reported"
        elif contribution_summary.get("sql_or_fact_lookup_performed"):
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
    fact_evidence = build_fact_audit_evidence_summary(output_list)
    line_ledger = build_line_build_ledger(output_list, rejected_list)
    return {
        "schema": ACTOR_CONTRIBUTION_SUMMARY_SCHEMA,
        "callback_total": len(submitted_list) if submitted_list else len(output_list) + len(rejected_list),
        "callback_accepted": len(output_list),
        "callback_rejected": len(rejected_list),
        "rollback_event_count": len(rejected_list),
        "sql_or_fact_lookup_performed": sql_lookup,
        "actor_authored_sentence_count": actor_sentence_count,
        "adopted_actor_proposal_count": adopted_count,
        "fact_audit_evidence_available": fact_evidence["evidence_available"],
        "fact_audit_evidence_count": fact_evidence["evidence_field_total"],
        "fact_audit_evidence_field_counts": fact_evidence["field_counts"],
        "line_build_ledger_entry_count": line_ledger["entry_count"],
        "final_synthesizer": final_synthesizer,
        "actor_function_labels": role_records,
        "interpretation": _interpretation(sql_lookup, actor_sentence_count, adopted_count, rejected_list),
    }


def build_fact_audit_evidence_contract() -> Dict[str, Any]:
    return {
        "schema": FACT_AUDIT_EVIDENCE_SCHEMA,
        "mode": "fact_audit_synthesis",
        "purpose": (
            "Record concrete evidence that actors or the external runtime checked facts, "
            "reports, proposal ledgers, quarantine/deferred items, or conflicts before synthesis."
        ),
        "recommended_output_fields": FACT_AUDIT_EVIDENCE_FIELDS,
        "minimum_useful_evidence": [
            "source_refs or checked_tables/checked_reports",
            "conflicts_found or deferred_claims when a claim is risky",
            "unchecked_claims for material that must remain proposal-only",
        ],
        "no_evidence_interpretation": (
            "Treat the run as guardrail/synthesis only; do not present it as deep fact audit."
        ),
        "side_effect_status": "read_only_evidence_report_no_wsa_db_mutation",
    }


def build_line_build_ledger_contract() -> Dict[str, Any]:
    return {
        "schema": LINE_BUILD_LEDGER_SCHEMA,
        "mode": "writing_room_line_build",
        "purpose": (
            "Record candidate beats or lines proposed by actors, validator decisions, retry/rollback "
            "events, and which items were adopted into the draft."
        ),
        "recommended_output_fields": LINE_BUILD_LEDGER_FIELDS,
        "status_values": ["PASS", "FAIL", "HOLD", "RETRY"],
        "target_length_policy": "target_length_guides_generation_but_does_not_cut_before_ending_hook",
        "ending_hook_policy": "scene_ending_hook_is_primary_stop_condition_when_provided",
        "retry_policy": {
            "max_retry_per_beat_required": True,
            "rollback_reason_required_on_fail_or_retry": True,
        },
        "no_ledger_interpretation": (
            "Do not present the run as line-build consensus when no ledger entries exist."
        ),
        "side_effect_status": "proposal_only_no_canon_or_scene_db_mutation",
    }


def build_fact_audit_evidence_summary(
    outputs: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    output_list = [item for item in outputs if isinstance(item, dict)]
    collected = {
        field: _collect_field_values(output_list, field)
        for field in FACT_AUDIT_EVIDENCE_FIELDS
    }
    field_counts = {field: len(values) for field, values in collected.items()}
    evidence_total = sum(field_counts.values())
    return {
        "schema": FACT_AUDIT_EVIDENCE_SCHEMA,
        "mode": "fact_audit_synthesis",
        "evidence_available": evidence_total > 0,
        "evidence_field_total": evidence_total,
        "field_counts": field_counts,
        "source_refs": collected["source_refs"][:16],
        "fact_lookup_queries": collected["fact_lookup_queries"][:16],
        "checked_tables": collected["checked_tables"][:16],
        "checked_reports": collected["checked_reports"][:16],
        "proposal_or_quarantine_refs": collected["proposal_or_quarantine_refs"][:16],
        "conflicts_found": collected["conflicts_found"][:16],
        "deferred_claims": collected["deferred_claims"][:16],
        "unchecked_claims": collected["unchecked_claims"][:16],
        "contract": build_fact_audit_evidence_contract(),
        "interpretation": (
            "fact_audit_evidence_reported"
            if evidence_total
            else "no_fact_audit_evidence_reported_synthesis_must_stay_guardrail_only"
        ),
    }


def build_line_build_ledger(
    outputs: Iterable[Dict[str, Any]],
    rejected_callbacks: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    for output in [item for item in outputs if isinstance(item, dict)]:
        if not any(output.get(field) not in (None, "", []) for field in LINE_BUILD_LEDGER_FIELDS):
            continue
        candidates = _first_non_empty_list(
            output,
            ["line_candidates", "accepted_lines", "accepted_beats", "adopted_proposals", "candidate_text"],
        )
        if not candidates:
            candidates = [output.get("scene_beat")] if output.get("scene_beat") else []
        if not candidates and output.get("rollback_reason"):
            candidates = ["<rollback without accepted candidate text>"]
        status = _ledger_status(output)
        for candidate in candidates[:8]:
            entries.append(
                {
                    "ledger_entry_id": f"L{len(entries) + 1:03d}",
                    "participant_id": output.get("participant_id"),
                    "represents": output.get("represents"),
                    "round": output.get("round"),
                    "beat_id": output.get("beat_id"),
                    "line_id": output.get("line_id"),
                    "candidate_text": candidate,
                    "proposer_actor": output.get("participant_id"),
                    "validator_actor": output.get("validator_actor"),
                    "status": status,
                    "retry_count": int(output.get("retry_count") or 0),
                    "rollback_reason": output.get("rollback_reason"),
                    "adopted_into_draft": bool(
                        output.get("accepted_lines")
                        or output.get("accepted_beats")
                        or output.get("adopted_proposals")
                        or status == "PASS"
                    ),
                }
            )
    for rejected in [item for item in (rejected_callbacks or []) if isinstance(item, dict)]:
        gate = rejected.get("quality_gate", {}) if isinstance(rejected.get("quality_gate"), dict) else {}
        entries.append(
            {
                "ledger_entry_id": f"L{len(entries) + 1:03d}",
                "participant_id": _participant_from_turn_id(rejected.get("turn_id")),
                "represents": rejected.get("represents"),
                "round": None,
                "beat_id": None,
                "line_id": None,
                "candidate_text": "<callback rejected by quality gate>",
                "proposer_actor": _participant_from_turn_id(rejected.get("turn_id")),
                "validator_actor": "wsa_quality_gate",
                "status": "FAIL",
                "retry_count": 0,
                "rollback_reason": ",".join(gate.get("rejection_reasons", [])),
                "adopted_into_draft": False,
            }
        )
    status_counts = {
        status: len([entry for entry in entries if entry["status"] == status])
        for status in ("PASS", "FAIL", "HOLD", "RETRY")
    }
    return {
        "schema": LINE_BUILD_LEDGER_SCHEMA,
        "mode": "writing_room_line_build",
        "entry_count": len(entries),
        "evidence_available": bool(entries),
        "status_counts": status_counts,
        "adopted_entry_count": len([entry for entry in entries if entry["adopted_into_draft"]]),
        "entries": entries,
        "contract": build_line_build_ledger_contract(),
        "interpretation": (
            "line_build_ledger_reported"
            if entries
            else "no_line_build_ledger_reported_do_not_claim_consensus_drafting"
        ),
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
        for field in FACT_AUDIT_EVIDENCE_FIELDS
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


def _collect_field_values(outputs: List[Dict[str, Any]], field: str) -> List[Any]:
    values: List[Any] = []
    for output in outputs:
        value = output.get(field)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            values.extend(item for item in value if item not in (None, "", []))
        else:
            values.append(value)
    return values


def _first_non_empty_list(output: Dict[str, Any], fields: List[str]) -> List[Any]:
    for field in fields:
        value = output.get(field)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            return [item for item in value if item not in (None, "", [])]
        return [value]
    return []


def _ledger_status(output: Dict[str, Any]) -> str:
    raw = str(output.get("validation_decision") or "").strip().upper()
    if raw in {"PASS", "FAIL", "HOLD", "RETRY"}:
        return raw
    if output.get("rollback_reason"):
        return "RETRY"
    if output.get("accepted_lines") or output.get("accepted_beats") or output.get("adopted_proposals"):
        return "PASS"
    return "HOLD"


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
