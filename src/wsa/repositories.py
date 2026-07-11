from __future__ import annotations

from .control_repository import ControlRepository
from .repository_common import (
    new_id,
    encode_payload,
    decode_payload,
    encode_json_value,
    decode_json_value,
    bounded_level,
    infer_attribute_value_type,
    Payload,
)
from .repository_records import (
    RuntimeSessionRecord,
    RuntimeMessageRecord,
    EntityRecord,
    FactRecord,
    DimensionDefinitionRecord,
    EntityAttributeSpanRecord,
    WorldEdgeRecord,
    KnowledgeAttributionRecord,
    ActorProfileRecord,
    ActorMemoryPacketRecord,
    TimelinePointRecord,
    SceneRecord,
    TicketRecord,
    TicketChangeRecord,
    ReportRecord,
    DiagnosticLogRecord,
    ContextPacketRecord,
)
from .world_repository_core import WorldCoreRepositoryMixin
from .world_repository_graph import WorldGraphRepositoryMixin
from .world_repository_workflow import WorldWorkflowRepositoryMixin


class WorldRepository(
    WorldCoreRepositoryMixin,
    WorldGraphRepositoryMixin,
    WorldWorkflowRepositoryMixin,
):
    pass


__all__ = [
    "new_id",
    "encode_payload",
    "decode_payload",
    "encode_json_value",
    "decode_json_value",
    "bounded_level",
    "infer_attribute_value_type",
    "Payload",
    "RuntimeSessionRecord",
    "RuntimeMessageRecord",
    "EntityRecord",
    "FactRecord",
    "DimensionDefinitionRecord",
    "EntityAttributeSpanRecord",
    "WorldEdgeRecord",
    "KnowledgeAttributionRecord",
    "ActorProfileRecord",
    "ActorMemoryPacketRecord",
    "TimelinePointRecord",
    "SceneRecord",
    "TicketRecord",
    "TicketChangeRecord",
    "ReportRecord",
    "DiagnosticLogRecord",
    "ContextPacketRecord",
    "ControlRepository",
    "WorldRepository",
]
