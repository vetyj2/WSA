from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping, Protocol, Sequence

from ..repositories import WorldRepository
from ._change_draft_contracts import ChangeDraftError


class _ChangeDraftLike(Protocol):
    @property
    def world_id(self) -> str: ...

    @property
    def changes(self) -> Sequence[Mapping[str, Any]]: ...


def ticket_detail(repo: WorldRepository, ticket_id: str) -> Dict[str, Any]:
    ticket = repo.get_ticket(ticket_id)
    changes = []
    for index, record in enumerate(repo.list_ticket_changes(ticket_id), start=1):
        changes.append(
            {
                "index": index,
                "ticket_change_id": record.ticket_change_id,
                "change_type": record.change_type,
                "target_type": record.target_type,
                "target_id": record.target_id,
                "payload": deepcopy(record.payload),
            }
        )
    return {
        "schema": "wsa.ticket.detail.v1",
        "ticket_id": ticket.ticket_id,
        "ticket_type": ticket.ticket_type,
        "title": ticket.title,
        "status": ticket.status,
        "risk": ticket.risk,
        "payload": deepcopy(ticket.payload),
        "changes": changes,
        "change_count": len(changes),
        "side_effect_status": "read_only_no_state_transition",
    }


def diff_change_lists(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    before_items = [deepcopy(dict(item)) for item in before]
    after_items = [deepcopy(dict(item)) for item in after]
    matched_after = set()
    unchanged = []
    removed = []
    for before_index, item in enumerate(before_items, start=1):
        match = next(
            (
                after_index
                for after_index, candidate in enumerate(after_items, start=1)
                if after_index not in matched_after and candidate == item
            ),
            None,
        )
        if match is None:
            removed.append({"source_index": before_index, "change": item})
        else:
            matched_after.add(match)
            unchanged.append(
                {
                    "source_index": before_index,
                    "target_index": match,
                    "change": item,
                }
            )
    added = [
        {"target_index": index, "change": item}
        for index, item in enumerate(after_items, start=1)
        if index not in matched_after
    ]
    return {
        "before_count": len(before_items),
        "after_count": len(after_items),
        "unchanged_count": len(unchanged),
        "removed_count": len(removed),
        "added_count": len(added),
        "unchanged": unchanged,
        "removed": removed,
        "added": added,
    }


def ticket_diff(
    repo: WorldRepository,
    source_ticket_id: str,
    target_ticket_id: str | None = None,
    *,
    draft: _ChangeDraftLike | None = None,
) -> Dict[str, Any]:
    if target_ticket_id and draft is not None:
        raise ChangeDraftError("target_ticket_id and draft cannot both be supplied")
    source = repo.get_ticket(source_ticket_id)
    if target_ticket_id is None and draft is None:
        candidate = source.payload.get("superseded_by")
        target_ticket_id = str(candidate) if candidate else None
    if target_ticket_id:
        target_changes = _ticket_change_payloads(repo, target_ticket_id)
        target_id = target_ticket_id
    elif draft is not None:
        if draft.world_id != repo.world_id:
            raise ChangeDraftError("draft and ticket belong to different worlds")
        target_changes = [deepcopy(dict(change)) for change in draft.changes]
        target_id = None
    else:
        raise ChangeDraftError("ticket diff requires a target ticket or draft")
    payload = diff_change_lists(
        _ticket_change_payloads(repo, source_ticket_id),
        target_changes,
    )
    return {
        "schema": "wsa.ticket.diff.v1",
        "source_ticket_id": source_ticket_id,
        "target_ticket_id": target_id,
        **payload,
        "side_effect_status": "read_only_no_state_transition",
    }


def _ticket_change_payloads(
    repo: WorldRepository,
    ticket_id: str,
) -> list[Dict[str, Any]]:
    changes = []
    for record in repo.list_ticket_changes(ticket_id):
        payload = deepcopy(dict(record.payload))
        payload.setdefault("change_type", record.change_type)
        payload.setdefault("target_type", record.target_type)
        if record.target_id is not None:
            payload.setdefault("target_id", record.target_id)
        changes.append(payload)
    return changes
