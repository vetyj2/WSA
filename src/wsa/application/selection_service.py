from __future__ import annotations

from pathlib import Path

from ..workspace import WorldRecord, list_worlds


class AmbiguousWorldSelectionError(ValueError):
    pass


def resolve_world_selector(workspace: Path, selector: str | None) -> WorldRecord:
    worlds = list_worlds(workspace)
    if not worlds:
        raise KeyError("no worlds are registered; run wsa world create NAME")

    value = (selector or "").strip()
    if not value:
        if len(worlds) == 1:
            return worlds[0]
        raise AmbiguousWorldSelectionError(
            "multiple worlds are registered; provide a unique world ID or display name"
        )

    exact_ids = [world for world in worlds if world.world_id == value]
    if exact_ids:
        return exact_ids[0]

    folded = value.casefold()
    name_matches = [world for world in worlds if world.display_name.casefold() == folded]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        raise AmbiguousWorldSelectionError(
            f"world display name is ambiguous: {value}; use a world ID"
        )
    raise KeyError(f"world not found: {value}; run wsa world list")
