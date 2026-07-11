from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Dict, Iterable, List, Mapping, Tuple

from .diagnostics_policy import (
    BUILTIN_POLICY_SOURCE,
    CARDINALITY_SINGLETON,
    INTERVAL_POLICY_OVERLAP,
    DiagnosticsPolicy,
    EdgeDiagnosticsPolicy,
    default_diagnostics_policy,
)
from .repositories import (
    EntityAttributeSpanRecord,
    FactRecord,
    WorldEdgeRecord,
    WorldRepository,
)


INACTIVE_STATUSES = {"rejected", "deprecated"}
DEFAULT_SINGLETON_EDGE_SEVERITY = {
    "located_at": "error",
}


@dataclass(frozen=True)
class ConflictFinding:
    conflict_type: str
    subject_id: str
    predicate: str
    fact_ids: List[str]
    detail: str
    severity: str = "error"
    target_type: str = "fact"
    why_it_matters: str = (
        "Conflicting world records can make downstream context selection ambiguous."
    )
    suggested_action: str = (
        "Review the conflicting records and propose an explicit change ticket."
    )
    policy_source: str = BUILTIN_POLICY_SOURCE

    @property
    def record_ids(self) -> List[str]:
        return list(self.fact_ids)

    @property
    def fingerprint(self) -> str:
        return conflict_fingerprint(self)

    @property
    def summary(self) -> str:
        return conflict_summary(self)

    def persistence_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "severity": self.severity,
            "target_type": self.target_type,
            "subject_id": self.subject_id,
            "predicate": self.predicate,
            "record_ids": self.record_ids,
            "detail": self.detail,
            "why_it_matters": self.why_it_matters,
            "suggested_action": self.suggested_action,
            "policy_source": self.policy_source,
            "fingerprint": self.fingerprint,
            "summary": self.summary,
        }
        if self.target_type == "fact":
            payload["fact_ids"] = self.record_ids
        return payload


def conflict_root_key(finding: ConflictFinding) -> Tuple[str, str, str, str]:
    """Return the stable root shared by pairwise findings for one conflict."""

    return (
        finding.conflict_type,
        finding.target_type,
        finding.subject_id,
        finding.predicate,
    )


def conflict_fingerprint(finding: ConflictFinding) -> str:
    encoded = json.dumps(
        conflict_root_key(finding),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "diagnostic-root:" + hashlib.sha256(encoded).hexdigest()


def conflict_summary(finding: ConflictFinding) -> str:
    return (
        f"{finding.conflict_type} for {finding.target_type} "
        f"{finding.subject_id}.{finding.predicate}"
    )


def conflict_grouping_metadata(finding: ConflictFinding) -> Dict[str, str]:
    return {
        "fingerprint": conflict_fingerprint(finding),
        "summary": conflict_summary(finding),
    }


def _display_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _fact_value(fact: FactRecord) -> Tuple[str, object]:
    if fact.object_ref_id is not None:
        return ("ref", fact.object_ref_id)
    return ("value", fact.object_value)


def _span_value(span: EntityAttributeSpanRecord) -> Tuple[str, object]:
    if span.value_number is not None:
        return ("number", span.value_number)
    if span.value_ref_id is not None:
        return ("ref", span.value_ref_id)
    if span.value_json is not None:
        return ("json", _display_value(span.value_json))
    return ("text", span.value_text)


def _edge_value(edge: WorldEdgeRecord) -> Tuple[str, str | None, str | None]:
    return (edge.object_type, edge.object_id, edge.object_value)


def _intervals_overlap(
    first_from: str | None,
    first_until: str | None,
    second_from: str | None,
    second_until: str | None,
) -> bool:
    first_before_second_end = second_until is None or (
        first_from is None or first_from < second_until
    )
    second_before_first_end = first_until is None or (
        second_from is None or second_from < first_until
    )
    return first_before_second_end and second_before_first_end


def find_explicit_fact_conflicts(
    repo: WorldRepository,
    policy_source: str = "builtin:explicit_fact_conflict",
) -> List[ConflictFinding]:
    facts = [fact for fact in repo.list_facts() if fact.status not in INACTIVE_STATUSES]
    grouped: Dict[Tuple[str, str], List[FactRecord]] = defaultdict(list)
    for fact in facts:
        grouped[(fact.subject_id, fact.predicate)].append(fact)

    findings: List[ConflictFinding] = []
    for (subject_id, predicate), group in grouped.items():
        values = {_fact_value(fact) for fact in group}
        if len(values) > 1:
            findings.append(
                ConflictFinding(
                    conflict_type="explicit_contradiction",
                    subject_id=subject_id,
                    predicate=predicate,
                    fact_ids=sorted(fact.fact_id for fact in group),
                    detail=(
                        f"{subject_id}.{predicate} has conflicting values: "
                        f"{sorted(_display_value(value) for value in values)}"
                    ),
                    why_it_matters=(
                        "Conflicting facts can make actor context and scene decisions "
                        "nondeterministic."
                    ),
                    suggested_action=(
                        "Review authority and provenance, then reject or deprecate the "
                        "incorrect fact through a change ticket."
                    ),
                    policy_source=policy_source,
                )
            )
    return findings


def find_temporal_attribute_conflicts(
    repo: WorldRepository,
    policy_source: str = "builtin:temporal_attribute_overlap",
) -> List[ConflictFinding]:
    spans = [
        span
        for span in repo.query_entity_attribute_spans()
        if span.status not in INACTIVE_STATUSES
    ]
    grouped: Dict[Tuple[str, str], List[EntityAttributeSpanRecord]] = defaultdict(list)
    for span in spans:
        grouped[(span.entity_id, span.dimension_key)].append(span)

    findings: List[ConflictFinding] = []
    for (entity_id, dimension_key), group in grouped.items():
        for first, second in combinations(group, 2):
            if _span_value(first) == _span_value(second):
                continue
            if not _intervals_overlap(
                first.valid_from,
                first.valid_until,
                second.valid_from,
                second.valid_until,
            ):
                continue
            record_ids = sorted(
                [first.attribute_span_id, second.attribute_span_id]
            )
            findings.append(
                ConflictFinding(
                    conflict_type="temporal_attribute_overlap",
                    subject_id=entity_id,
                    predicate=dimension_key,
                    fact_ids=record_ids,
                    detail=(
                        f"{entity_id}.{dimension_key} has overlapping values "
                        f"{_display_value(_span_value(first))} and "
                        f"{_display_value(_span_value(second))}"
                    ),
                    severity="error",
                    target_type="entity_attribute_span",
                    why_it_matters=(
                        "Overlapping values make time-scoped actor context ambiguous."
                    ),
                    suggested_action=(
                        "Review the validity bounds and propose a ticket that revises or "
                        "deprecates the incorrect span."
                    ),
                    policy_source=policy_source,
                )
            )
    return findings


def find_singleton_edge_conflicts(
    repo: WorldRepository,
    edge_severity: Mapping[str, str] | None = None,
    *,
    policy: DiagnosticsPolicy | None = None,
) -> List[ConflictFinding]:
    resolved_policy = policy or default_diagnostics_policy()
    if edge_severity:
        resolved_policy = DiagnosticsPolicy(
            schema=resolved_policy.schema,
            edge_policies={
                edge_type: EdgeDiagnosticsPolicy(
                    cardinality=CARDINALITY_SINGLETON,
                    severity=severity,
                    interval_policy=INTERVAL_POLICY_OVERLAP,
                    policy_source="argument:edge_severity",
                )
                for edge_type, severity in edge_severity.items()
            },
            policy_source="argument:edge_severity",
        )
    singleton_rules = {
        edge_type: rule
        for edge_type, rule in resolved_policy.edge_policies.items()
        if rule.cardinality == CARDINALITY_SINGLETON
    }
    edges = [
        edge
        for edge in repo.query_world_edges()
        if edge.status not in INACTIVE_STATUSES and edge.edge_type in singleton_rules
    ]
    grouped: Dict[Tuple[str, str, str], List[WorldEdgeRecord]] = defaultdict(list)
    for edge in edges:
        grouped[(edge.subject_type, edge.subject_id, edge.edge_type)].append(edge)

    findings: List[ConflictFinding] = []
    for (_, subject_id, edge_type), group in grouped.items():
        rule = singleton_rules[edge_type]
        for first, second in combinations(group, 2):
            if _edge_value(first) == _edge_value(second):
                continue
            if rule.interval_policy == INTERVAL_POLICY_OVERLAP and not _intervals_overlap(
                first.valid_from,
                first.valid_until,
                second.valid_from,
                second.valid_until,
            ):
                continue
            findings.append(
                ConflictFinding(
                    conflict_type="singleton_edge_overlap",
                    subject_id=subject_id,
                    predicate=edge_type,
                    fact_ids=sorted([first.edge_id, second.edge_id]),
                    detail=(
                        f"{subject_id}.{edge_type} has overlapping targets "
                        f"{_display_value(_edge_value(first))} and "
                        f"{_display_value(_edge_value(second))}"
                    ),
                    severity=rule.severity,
                    target_type="world_edge",
                    why_it_matters=(
                        f"The world policy permits one {edge_type} target for the "
                        "relevant interval, so competing targets make relationship "
                        "resolution ambiguous."
                    ),
                    suggested_action=(
                        "Review the targets and validity bounds, then propose an explicit "
                        "change ticket for the incorrect edge."
                    ),
                    policy_source=rule.policy_source,
                )
            )
    return findings


def run_world_detectors(
    repo: WorldRepository,
    policy: DiagnosticsPolicy | None = None,
) -> List[ConflictFinding]:
    findings: Iterable[ConflictFinding] = (
        find_explicit_fact_conflicts(repo)
        + find_temporal_attribute_conflicts(repo)
        + find_singleton_edge_conflicts(repo, policy=policy)
    )
    return sorted(
        findings,
        key=lambda item: (
            item.conflict_type,
            item.subject_id,
            item.predicate,
            tuple(item.record_ids),
        ),
    )


def persist_conflict_finding(
    repo: WorldRepository,
    finding: ConflictFinding,
) -> None:
    repo.create_diagnostic_log(
        finding.conflict_type,
        "open",
        payload=finding.persistence_payload(),
        fingerprint=finding.fingerprint,
    )


def detect_explicit_fact_conflicts(repo: WorldRepository) -> List[ConflictFinding]:
    """Compatibility API that persists explicit fact findings."""

    findings = find_explicit_fact_conflicts(repo)
    for finding in findings:
        persist_conflict_finding(repo, finding)
    return findings
