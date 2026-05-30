from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


PROTOCOL_VERSION = 1

MESSAGE_TYPES = {
    "context_assignment",
    "intent_request",
    "action_proposal",
    "dialogue_proposal",
    "inner_thought",
    "state_delta",
    "correction_request",
    "rollback_notice",
    "commit_event",
    "progress_summary",
    "final_report",
    "pr_packet_request",
}

DIRECTIONS = {"inbox", "outbox"}


class InvalidMessageTypeError(ValueError):
    """Raised when a message type is outside the supported protocol."""


class InvalidDirectionError(ValueError):
    """Raised when a transport direction is not inbox/outbox."""


class RuntimeRouteError(ValueError):
    """Raised when a runtime message route conflicts with its session route."""


def validate_message_type(message_type: str) -> None:
    if message_type not in MESSAGE_TYPES:
        raise InvalidMessageTypeError(f"unsupported message_type: {message_type}")


def validate_direction(direction: str) -> None:
    if direction not in DIRECTIONS:
        raise InvalidDirectionError(f"unsupported direction: {direction}")


@dataclass(frozen=True)
class RuntimeEnvelope:
    message_id: str
    protocol_version: int
    workspace_id: str
    world_id: Optional[str]
    scene_id: Optional[str]
    session_id: str
    role: str
    message_type: str
    sequence: int
    payload: Dict[str, Any] = field(default_factory=dict)
    artifact_refs: List[str] = field(default_factory=list)
    status: str = "queued"
    parent_message_id: Optional[str] = None

    def __post_init__(self) -> None:
        validate_message_type(self.message_type)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "protocol_version": self.protocol_version,
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "scene_id": self.scene_id,
            "session_id": self.session_id,
            "role": self.role,
            "message_type": self.message_type,
            "sequence": self.sequence,
            "parent_message_id": self.parent_message_id,
            "payload": self.payload,
            "artifact_refs": self.artifact_refs,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "RuntimeEnvelope":
        return cls(
            message_id=value["message_id"],
            protocol_version=int(value["protocol_version"]),
            workspace_id=value["workspace_id"],
            world_id=value.get("world_id"),
            scene_id=value.get("scene_id"),
            session_id=value["session_id"],
            role=value["role"],
            message_type=value["message_type"],
            sequence=int(value["sequence"]),
            parent_message_id=value.get("parent_message_id"),
            payload=dict(value.get("payload") or {}),
            artifact_refs=list(value.get("artifact_refs") or []),
            status=value.get("status", "queued"),
        )
