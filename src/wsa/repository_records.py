from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .repository_common import Payload

@dataclass(frozen=True)
class RuntimeSessionRecord:
    session_id: str
    workspace_id: str
    world_id: Optional[str]
    scene_id: Optional[str]
    role: str
    runtime_target: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class RuntimeMessageRecord:
    message_id: str
    session_id: str
    message_type: str
    sequence: int
    payload: Payload
    status: str


@dataclass(frozen=True)
class EntityRecord:
    entity_id: str
    entity_type: str
    display_name: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class FactRecord:
    fact_id: str
    subject_id: str
    predicate: str
    object_value: Optional[str]
    authority: str
    status: str
    confidence: float
    payload: Payload
    object_ref_id: Optional[str] = None
    time_scope: Optional[str] = None
    location_scope: Optional[str] = None
    source_ref: Optional[str] = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DimensionDefinitionRecord:
    dimension_id: str
    dimension_key: str
    display_name: str
    dimension_type: str
    value_type: str
    applies_to: str
    temporal: bool
    missing_policy: str
    authority: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class EntityAttributeSpanRecord:
    attribute_span_id: str
    entity_id: str
    dimension_key: str
    value_number: Optional[float]
    value_text: Optional[str]
    value_ref_id: Optional[str]
    value_json: Any
    valid_from: Optional[str]
    valid_until: Optional[str]
    authority: str
    status: str
    confidence: float
    stability_level: int
    revision_cost_level: int
    payload: Payload
    source_event_id: Optional[str] = None


@dataclass(frozen=True)
class WorldEdgeRecord:
    edge_id: str
    subject_type: str
    subject_id: str
    edge_type: str
    object_type: str
    object_id: Optional[str]
    object_value: Optional[str]
    valid_from: Optional[str]
    valid_until: Optional[str]
    authority: str
    status: str
    confidence: float
    stability_level: int
    revision_cost_level: int
    payload: Payload
    source_event_id: Optional[str] = None


@dataclass(frozen=True)
class KnowledgeAttributionRecord:
    knowledge_id: str
    actor_entity_id: str
    target_type: str
    target_id: str
    knowledge_state: str
    acquired_at: Optional[str]
    valid_until: Optional[str]
    authority: str
    status: str
    confidence: float
    payload: Payload
    acquired_event_id: Optional[str] = None
    source_entity_id: Optional[str] = None


@dataclass(frozen=True)
class ActorProfileRecord:
    actor_profile_id: str
    entity_id: str
    fragment_type: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class ActorMemoryPacketRecord:
    memory_packet_id: str
    entity_id: str
    time_scope: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class TimelinePointRecord:
    timeline_point_id: str
    label: str
    sort_key: str
    payload: Payload


@dataclass(frozen=True)
class SceneRecord:
    scene_id: str
    name: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class TicketRecord:
    ticket_id: str
    ticket_type: str
    title: str
    status: str
    risk: str
    payload: Payload


@dataclass(frozen=True)
class TicketChangeRecord:
    ticket_change_id: str
    ticket_id: str
    change_type: str
    target_type: str
    target_id: Optional[str]
    payload: Payload


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    purpose: str
    title: str
    risk: str
    status: str
    payload: Payload
    artifact_ref: Optional[str] = None


@dataclass(frozen=True)
class DiagnosticLogRecord:
    diagnostic_log_id: str
    diagnostic_type: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class ContextPacketRecord:
    context_packet_id: str
    packet_type: str
    status: str
    payload: Payload
