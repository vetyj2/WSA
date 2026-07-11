from __future__ import annotations

from typing import Any


DRAFT_CHANGE_TYPES = {
    "add_entity",
    "add_fact",
    "add_world_edge",
    "add_timeline_point",
}
DRAFT_TARGET_TYPES = {
    "add_entity": "entity",
    "add_fact": "fact",
    "add_world_edge": "world_edge",
    "add_timeline_point": "timeline_point",
}
STRUCTURED_CANDIDATE_KEYS = (
    "candidate_changes",
    "changes",
    "world_mutations",
)


class ChangeDraftError(ValueError):
    """Base error for invalid change draft input."""


class ChangeSpecError(ChangeDraftError):
    """Raised when a CLI change string cannot be parsed safely."""


class EntityNameNotFoundError(ChangeDraftError):
    """Raised when an entity display name has no match in the draft or world."""


class AmbiguousEntityNameError(ChangeDraftError):
    """Raised when an entity display name does not identify exactly one entity."""


# These errors remain public through change_draft_service after the implementation split.
_PUBLIC_MODULE = f"{__package__}.change_draft_service"
for _error_type in (
    ChangeDraftError,
    ChangeSpecError,
    EntityNameNotFoundError,
    AmbiguousEntityNameError,
):
    _error_type.__module__ = _PUBLIC_MODULE


def _required(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ChangeSpecError(f"{label} must not be blank")
    return text
