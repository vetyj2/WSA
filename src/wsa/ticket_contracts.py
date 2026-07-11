from __future__ import annotations

from dataclasses import dataclass
from typing import List


class UnsupportedTicketChangeError(ValueError):
    """Raised when a PR packet contains a change this MVP cannot apply."""


class NonApplicableTicketError(ValueError):
    """Raised when a candidate container has no concrete world changes to apply."""


class InvalidTicketStateError(ValueError):
    """Raised when a ticket cannot enter the requested application state."""


FACT_STATUSES = {"draft", "proposed", "approved", "canon", "deprecated", "rejected"}
DEEP_AUTHORING_ADD_CHANGE_TYPES = {
    "add_actor_profile",
    "add_entity_attribute_span",
    "add_knowledge_attribution",
    "add_actor_memory_packet",
}
DEEP_AUTHORING_UPDATE_TARGET_TYPES = {
    "update_actor_profile": "actor_profile",
    "update_entity_attribute_span": "entity_attribute_span",
    "update_knowledge_attribution": "knowledge_attribution",
    "update_actor_memory_packet": "actor_memory_packet",
}
DEEP_AUTHORING_UPDATE_CHANGE_TYPES = set(DEEP_AUTHORING_UPDATE_TARGET_TYPES)
DEEP_AUTHORING_CHANGE_TYPES = (
    DEEP_AUTHORING_ADD_CHANGE_TYPES | DEEP_AUTHORING_UPDATE_CHANGE_TYPES
)
DEEP_AUTHORING_TARGET_TYPES = {
    "add_actor_profile": "actor_profile",
    "add_entity_attribute_span": "entity_attribute_span",
    "add_knowledge_attribution": "knowledge_attribution",
    "add_actor_memory_packet": "actor_memory_packet",
    **DEEP_AUTHORING_UPDATE_TARGET_TYPES,
}
DEEP_LIFECYCLE_RECORD_TABLES = {
    "update_actor_profile": ("actor_profiles", "actor_profile_id"),
    "update_entity_attribute_span": (
        "entity_attribute_spans",
        "attribute_span_id",
    ),
    "update_knowledge_attribution": ("knowledge_attributions", "knowledge_id"),
    "update_actor_memory_packet": ("actor_memory_packets", "memory_packet_id"),
}
DEEP_LIFECYCLE_REVISION_FIELDS = {
    "update_actor_profile": ("status", "valid_from", "valid_until"),
    "update_entity_attribute_span": ("status", "valid_from", "valid_until"),
    "update_knowledge_attribution": ("status", "acquired_at", "valid_until"),
    "update_actor_memory_packet": ("status", "time_scope", "valid_until"),
}
PROFILE_FRAGMENT_TYPES = {"core", "goal", "secret", "speech", "style"}
KNOWLEDGE_STATES = {"known", "discovered", "witnessed", "unknown", "forbidden"}
APPLIED_CONTENT_STATUSES = {"active", "approved", "canon", "accepted"}
DEEP_LIFECYCLE_STATUSES = APPLIED_CONTENT_STATUSES | {"deprecated", "rejected"}
KNOWLEDGE_TARGET_TABLES = {
    "entity": ("entities", "entity_id"),
    "fact": ("facts", "fact_id"),
    "entity_attribute_span": ("entity_attribute_spans", "attribute_span_id"),
    "world_edge": ("world_edges", "edge_id"),
    "edge": ("world_edges", "edge_id"),
    "actor_profile": ("actor_profiles", "actor_profile_id"),
    "actor_memory_packet": ("actor_memory_packets", "memory_packet_id"),
    "timeline_point": ("timeline_points", "timeline_point_id"),
    "scene": ("scenes", "scene_id"),
    "scene_event": ("scene_events", "event_id"),
}
PORTABLE_CHANGE_TABLES = {
    "add_entity": ("entities", "entity_id"),
    "add_fact": ("facts", "fact_id"),
    "add_world_edge": ("world_edges", "edge_id"),
    "add_timeline_point": ("timeline_points", "timeline_point_id"),
    "add_actor_profile": ("actor_profiles", "actor_profile_id"),
    "add_entity_attribute_span": (
        "entity_attribute_spans",
        "attribute_span_id",
    ),
    "add_knowledge_attribution": ("knowledge_attributions", "knowledge_id"),
    "add_actor_memory_packet": ("actor_memory_packets", "memory_packet_id"),
}
PORTABLE_APPLY_ORDER = {
    "add_entity": 0,
    "add_fact": 1,
    "add_world_edge": 1,
    "add_timeline_point": 1,
    "add_actor_profile": 2,
    "add_entity_attribute_span": 2,
    "add_actor_memory_packet": 2,
    "add_knowledge_attribution": 3,
}
CANDIDATE_TICKET_TYPES = {"meeting_candidate", "orchestrator_candidate"}
REVISIONABLE_TICKET_STATUSES = {"proposed", "approved"}
PROPOSED_APPLY_COMPAT_WARNING = (
    "Applying a proposed ticket directly is deprecated; call review_ticket first. "
    "allow_proposed_compat is a temporary legacy compatibility path."
)


@dataclass(frozen=True)
class TicketApplyResult:
    ticket_id: str
    previous_status: str
    status: str
    applied_ids: List[str]
    side_effect_status: str
    compatibility_mode: str | None = None
    deprecation_warning: str | None = None
