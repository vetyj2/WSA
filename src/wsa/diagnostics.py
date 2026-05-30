from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .repositories import FactRecord, WorldRepository


@dataclass(frozen=True)
class ConflictFinding:
    conflict_type: str
    subject_id: str
    predicate: str
    fact_ids: List[str]
    detail: str


def detect_explicit_fact_conflicts(repo: WorldRepository) -> List[ConflictFinding]:
    facts = [fact for fact in repo.list_facts() if fact.status not in {"rejected", "deprecated"}]
    grouped: Dict[Tuple[str, str], List[FactRecord]] = defaultdict(list)
    for fact in facts:
        grouped[(fact.subject_id, fact.predicate)].append(fact)

    findings: List[ConflictFinding] = []
    for (subject_id, predicate), group in grouped.items():
        values = {fact.object_value for fact in group}
        if len(values) > 1:
            finding = ConflictFinding(
                conflict_type="explicit_contradiction",
                subject_id=subject_id,
                predicate=predicate,
                fact_ids=[fact.fact_id for fact in group],
                detail=f"{subject_id}.{predicate} has conflicting values: {sorted(str(v) for v in values)}",
            )
            findings.append(finding)
            repo.create_diagnostic_log(
                "explicit_contradiction",
                "open",
                payload={
                    "subject_id": subject_id,
                    "predicate": predicate,
                    "fact_ids": finding.fact_ids,
                    "detail": finding.detail,
                },
            )
    return findings
