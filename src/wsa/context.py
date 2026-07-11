from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable

from .repositories import EntityRecord, FactRecord, WorldRepository
from .workspace import SCHEMA_VERSION


CONTEXT_BUNDLE_SCHEMA = "wsa.context.bundle.v2"
DEFAULT_CONTEXT_CHARACTER_BUDGET = 12_000
DEFAULT_CONTEXT_TOKEN_BUDGET = 3_000
VISIBLE_STATUSES = {"active", "approved", "canon", "accepted"}
KNOWN_STATES = {"known", "discovered", "witnessed"}
FORBIDDEN_STATES = {"forbidden"}
HIDDEN_VISIBILITIES = {"hidden", "private", "secret"}


@dataclass(frozen=True)
class ContextRequest:
    actor: EntityRecord
    scene_id: str | None
    scene_goal: str
    time_scope: str | None = None
    location_scope: str | None = None
    viewpoint_entity_id: str | None = None
    character_budget: int = DEFAULT_CONTEXT_CHARACTER_BUDGET
    token_budget: int | None = None


@dataclass(frozen=True)
class ContextBundle:
    packet: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return self.packet


@dataclass(frozen=True)
class _Candidate:
    source: str
    item_id: str
    priority: int
    payload: Dict[str, Any]
    relevance: int = 0


class ContextAssembler:
    def __init__(self, repo: WorldRepository) -> None:
        self.repo = repo

    def assemble(self, request: ContextRequest, persist: bool = False) -> ContextBundle:
        actor = request.actor
        retrieval_terms = _retrieval_terms(request.scene_goal)
        viewpoint_id = request.viewpoint_entity_id or actor.entity_id
        knowledge = self.repo.query_knowledge_attributions(
            actor_entity_id=viewpoint_id,
            as_of=request.time_scope,
        )
        usable_knowledge = [item for item in knowledge if item.status in VISIBLE_STATUSES]
        forbidden_targets = {
            target
            for item in usable_knowledge
            if item.knowledge_state in FORBIDDEN_STATES
            for target in _knowledge_target_aliases(item.target_type, item.target_id)
        }
        known_targets = {
            target
            for item in usable_knowledge
            if item.knowledge_state in KNOWN_STATES
            for target in _knowledge_target_aliases(item.target_type, item.target_id)
            if target not in forbidden_targets
        }

        candidates: list[_Candidate] = []
        excluded: list[Dict[str, Any]] = []
        for fact in self.repo.list_facts():
            reason = self._fact_exclusion_reason(
                fact,
                request,
                known_targets,
                forbidden_targets,
            )
            if reason is not None:
                excluded.append(_exclusion("facts", fact.fact_id, reason))
                continue
            candidates.append(
                _Candidate(
                    source="facts",
                    item_id=fact.fact_id,
                    priority=self._fact_priority(fact, actor.entity_id),
                    payload=_fact_payload(fact),
                    relevance=_fact_relevance(fact, retrieval_terms),
                )
            )

        for profile in self.repo.list_actor_profiles(actor.entity_id):
            if profile.status not in VISIBLE_STATUSES:
                excluded.append(
                    _exclusion(
                        "actor_profiles",
                        profile.actor_profile_id,
                        "status_not_visible",
                    )
                )
                continue
            if not _payload_valid_at(profile.payload, request.time_scope):
                excluded.append(
                    _exclusion(
                        "actor_profiles",
                        profile.actor_profile_id,
                        "outside_time_scope",
                    )
                )
                continue
            profile_target = ("actor_profile", profile.actor_profile_id)
            if profile_target in forbidden_targets:
                excluded.append(
                    _exclusion(
                        "actor_profiles",
                        profile.actor_profile_id,
                        "forbidden_to_viewpoint",
                    )
                )
                continue
            if (
                (_is_hidden(profile.payload) or profile.fragment_type == "secret")
                and viewpoint_id != actor.entity_id
                and profile_target not in known_targets
            ):
                excluded.append(
                    _exclusion(
                        "actor_profiles",
                        profile.actor_profile_id,
                        "hidden_from_viewpoint",
                    )
                )
                continue
            candidates.append(
                _Candidate("actor_profiles", profile.actor_profile_id, 15, asdict(profile))
            )

        for span in self.repo.query_entity_attribute_spans(
            entity_id=actor.entity_id,
            as_of=request.time_scope,
        ):
            if span.status not in VISIBLE_STATUSES:
                excluded.append(
                    _exclusion(
                        "temporal_attributes",
                        span.attribute_span_id,
                        "status_not_visible",
                    )
                )
                continue
            span_target = (
                "entity_attribute_span",
                span.attribute_span_id,
            )
            if span_target in forbidden_targets:
                excluded.append(
                    _exclusion(
                        "temporal_attributes",
                        span.attribute_span_id,
                        "forbidden_to_viewpoint",
                    )
                )
                continue
            if _is_hidden(span.payload) and span_target not in known_targets:
                excluded.append(
                    _exclusion(
                        "temporal_attributes",
                        span.attribute_span_id,
                        "hidden_from_viewpoint",
                    )
                )
                continue
            candidates.append(
                _Candidate("temporal_attributes", span.attribute_span_id, 20, asdict(span))
            )

        edges = self._actor_edges(actor.entity_id, request.time_scope)
        for edge in edges:
            if edge.status not in VISIBLE_STATUSES:
                excluded.append(_exclusion("relationships", edge.edge_id, "status_not_visible"))
                continue
            if _target_is_known(
                forbidden_targets,
                ("world_edge", edge.edge_id),
                ("edge", edge.edge_id),
            ):
                excluded.append(_exclusion("relationships", edge.edge_id, "forbidden_to_viewpoint"))
                continue
            if _is_hidden(edge.payload) and not _target_is_known(
                known_targets,
                ("world_edge", edge.edge_id),
                ("edge", edge.edge_id),
            ):
                excluded.append(_exclusion("relationships", edge.edge_id, "hidden_from_viewpoint"))
                continue
            candidates.append(_Candidate("relationships", edge.edge_id, 25, asdict(edge)))

        for item in usable_knowledge:
            candidates.append(_Candidate("knowledge", item.knowledge_id, 30, asdict(item)))

        for memory in self.repo.list_actor_memory_packets(
            actor.entity_id,
            as_of=request.time_scope,
        ):
            if memory.status not in VISIBLE_STATUSES:
                excluded.append(
                    _exclusion(
                        "memories",
                        memory.memory_packet_id,
                        "status_not_visible",
                    )
                )
                continue
            if not _payload_valid_at(memory.payload, request.time_scope):
                excluded.append(
                    _exclusion(
                        "memories",
                        memory.memory_packet_id,
                        "outside_time_scope",
                    )
                )
                continue
            memory_target = ("actor_memory_packet", memory.memory_packet_id)
            if memory_target in forbidden_targets:
                excluded.append(
                    _exclusion(
                        "memories",
                        memory.memory_packet_id,
                        "forbidden_to_viewpoint",
                    )
                )
                continue
            if (
                _is_hidden(memory.payload)
                and viewpoint_id != actor.entity_id
                and memory_target not in known_targets
            ):
                excluded.append(
                    _exclusion(
                        "memories",
                        memory.memory_packet_id,
                        "hidden_from_viewpoint",
                    )
                )
                continue
            candidates.append(_Candidate("memories", memory.memory_packet_id, 35, asdict(memory)))

        selected, budget_exclusions, used, estimated_tokens = _apply_budget(
            candidates,
            max(0, int(request.character_budget)),
            (
                max(0, int(request.token_budget))
                if request.token_budget is not None
                else None
            ),
        )
        excluded.extend(budget_exclusions)
        grouped: Dict[str, list[Dict[str, Any]]] = {
            "facts": [],
            "actor_profiles": [],
            "temporal_attributes": [],
            "relationships": [],
            "knowledge": [],
            "memories": [],
        }
        for candidate in selected:
            grouped[candidate.source].append(candidate.payload)

        packet: Dict[str, Any] = {
            "schema": CONTEXT_BUNDLE_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "world_id": self.repo.world_id,
            "scene_id": request.scene_id,
            "actor": {
                "entity_id": actor.entity_id,
                "display_name": actor.display_name,
                "entity_type": actor.entity_type,
                "payload": actor.payload,
            },
            "scene": {
                "goal": request.scene_goal,
                "time_scope": request.time_scope,
                "location_scope": request.location_scope,
                "viewpoint_entity_id": viewpoint_id,
            },
            **grouped,
            "receipt": {
                "schema": "wsa.context.receipt.v1",
                "query": {
                    "actor_entity_id": actor.entity_id,
                    "viewpoint_entity_id": viewpoint_id,
                    "time_scope": request.time_scope,
                    "location_scope": request.location_scope,
                },
                "character_budget": max(0, int(request.character_budget)),
                "characters_used": used,
                "token_budget": (
                    max(0, int(request.token_budget))
                    if request.token_budget is not None
                    else None
                ),
                "estimated_tokens_used": estimated_tokens,
                "token_estimation_policy": "deterministic_utf8_conservative_v1",
                "retrieval": {
                    "policy": "authority_then_lexical_overlap_v1",
                    "query_terms": sorted(retrieval_terms),
                    "candidate_count": len(candidates),
                },
                "included_count": len(selected),
                "included": [
                    {"source": item.source, "item_id": item.item_id, "priority": item.priority}
                    for item in selected
                ],
                "excluded_count": len(excluded),
                "excluded": excluded,
            },
            "compression": {
                "priority": [
                    "actor_canon_and_profile",
                    "current_temporal_state",
                    "relationships",
                    "viewpoint_knowledge",
                    "actor_memory",
                    "remaining_visible_world_facts",
                ],
                "overload_warning": bool(budget_exclusions),
                "policy": (
                    "deterministic_character_and_token_budget_v1"
                    if request.token_budget is not None
                    else "deterministic_character_budget_v1"
                ),
            },
        }
        if persist:
            self.repo.create_context_packet(
                "actor_context",
                packet,
                scene_id=request.scene_id,
                actor_entity_id=actor.entity_id,
            )
        return ContextBundle(packet)

    def _actor_edges(self, entity_id: str, as_of: str | None) -> list[Any]:
        by_id = {
            edge.edge_id: edge
            for edge in self.repo.query_world_edges(subject_id=entity_id, as_of=as_of)
        }
        for edge in self.repo.query_world_edges(object_id=entity_id, as_of=as_of):
            by_id[edge.edge_id] = edge
        return list(by_id.values())

    def _fact_exclusion_reason(
        self,
        fact: FactRecord,
        request: ContextRequest,
        known_targets: set[tuple[str, str]],
        forbidden_targets: set[tuple[str, str]],
    ) -> str | None:
        if fact.status not in VISIBLE_STATUSES:
            return "status_not_visible"
        if fact.time_scope and request.time_scope and fact.time_scope != request.time_scope:
            return "outside_time_scope"
        if (
            fact.location_scope
            and request.location_scope
            and fact.location_scope != request.location_scope
        ):
            return "outside_location_scope"
        if ("fact", fact.fact_id) in forbidden_targets:
            return "forbidden_to_viewpoint"
        if _is_hidden(fact.payload) and not _target_is_known(
            known_targets,
            ("fact", fact.fact_id),
        ):
            return "hidden_from_viewpoint"
        return None

    def _fact_priority(self, fact: FactRecord, actor_entity_id: str) -> int:
        if fact.subject_id == actor_entity_id or fact.object_ref_id == actor_entity_id:
            return 10
        if fact.subject_id == self.repo.world_id:
            return 40
        return 50


class ContextBuilder:
    """Compatibility facade for the original actor-context API."""

    def __init__(self, repo: WorldRepository) -> None:
        self.repo = repo
        self.assembler = ContextAssembler(repo)

    def build_actor_context(
        self,
        actor: EntityRecord,
        scene_id: str | None,
        scene_goal: str,
        *,
        time_scope: str | None = None,
        location_scope: str | None = None,
        viewpoint_entity_id: str | None = None,
        character_budget: int = DEFAULT_CONTEXT_CHARACTER_BUDGET,
        token_budget: int | None = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        return self.assembler.assemble(
            ContextRequest(
                actor=actor,
                scene_id=scene_id,
                scene_goal=scene_goal,
                time_scope=time_scope,
                location_scope=location_scope,
                viewpoint_entity_id=viewpoint_entity_id,
                character_budget=character_budget,
                token_budget=token_budget,
            ),
            persist=persist,
        ).to_dict()


def _fact_payload(fact: FactRecord) -> Dict[str, Any]:
    return {
        "fact_id": fact.fact_id,
        "subject_id": fact.subject_id,
        "predicate": fact.predicate,
        "object_value": fact.object_value,
        "object_ref_id": fact.object_ref_id,
        "time_scope": fact.time_scope,
        "location_scope": fact.location_scope,
        "authority": fact.authority,
        "status": fact.status,
        "confidence": fact.confidence,
        "source_ref": fact.source_ref,
        "tags": list(fact.tags),
        "payload": fact.payload,
    }


def _is_hidden(payload: Dict[str, Any]) -> bool:
    visibility = str(payload.get("visibility") or "public").lower()
    return visibility in HIDDEN_VISIBILITIES or payload.get("hidden") is True


def _target_is_known(
    known_targets: set[tuple[str, str]],
    *targets: tuple[str, str],
) -> bool:
    return any(target in known_targets for target in targets)


def _knowledge_target_aliases(
    target_type: str,
    target_id: str,
) -> set[tuple[str, str]]:
    if target_type in {"edge", "world_edge"}:
        return {("edge", target_id), ("world_edge", target_id)}
    return {(target_type, target_id)}


def _payload_valid_at(payload: Dict[str, Any], as_of: str | None) -> bool:
    if as_of is None:
        return True
    metadata = payload.get("_wsa")
    if not isinstance(metadata, dict):
        return True
    valid_from = metadata.get("valid_from")
    valid_until = metadata.get("valid_until")
    if isinstance(valid_from, str) and valid_from and valid_from > as_of:
        return False
    if isinstance(valid_until, str) and valid_until and valid_until <= as_of:
        return False
    return True


def _exclusion(source: str, item_id: str, reason: str) -> Dict[str, Any]:
    return {"source": source, "item_id": item_id, "reason": reason}


def _apply_budget(
    candidates: Iterable[_Candidate],
    budget: int,
    token_budget: int | None = None,
) -> tuple[list[_Candidate], list[Dict[str, Any]], int, int]:
    selected: list[_Candidate] = []
    excluded: list[Dict[str, Any]] = []
    used = 0
    tokens_used = 0
    for item in sorted(
        candidates,
        key=lambda value: (
            value.priority,
            -value.relevance,
            value.source,
            value.item_id,
        ),
    ):
        encoded = json.dumps(
            item.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        size = len(encoded)
        estimated_tokens = _estimate_tokens(encoded)
        character_exceeded = used + size > budget
        token_exceeded = token_budget is not None and tokens_used + estimated_tokens > token_budget
        if character_exceeded or token_exceeded:
            excluded.append(
                {
                    "source": item.source,
                    "item_id": item.item_id,
                    "reason": (
                        "token_budget_exceeded"
                        if token_exceeded
                        else "character_budget_exceeded"
                    ),
                    "estimated_characters": size,
                    "estimated_tokens": estimated_tokens,
                }
            )
            continue
        selected.append(item)
        used += size
        tokens_used += estimated_tokens
    return selected, excluded, used, tokens_used


def _estimate_tokens(value: str) -> int:
    if not value:
        return 0
    utf8_bytes = len(value.encode("utf-8"))
    lexical_units = len(re.findall(r"\w+|[^\w\s]", value, flags=re.UNICODE))
    return max(1, lexical_units, (utf8_bytes + 3) // 4)


def _retrieval_terms(value: str) -> set[str]:
    return {
        item
        for item in re.findall(r"\w+", value.casefold(), flags=re.UNICODE)
        if len(item) > 1
    }


def _fact_relevance(fact: FactRecord, terms: set[str]) -> int:
    if not terms:
        return 0
    haystack = " ".join(
        str(item or "")
        for item in (
            fact.subject_id,
            fact.predicate,
            fact.object_value,
            fact.object_ref_id,
            " ".join(fact.tags),
        )
    ).casefold()
    return sum(1 for term in terms if term in haystack)
