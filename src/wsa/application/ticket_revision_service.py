from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence

from ..repositories import TicketRecord, WorldRepository
from ..ticket_revision_store import (
    _MergeTicketStoreResult,
    _RevisionSource,
    _SplitTicketStoreResult,
    _highest_risk,
    _load_revision_source_in_connection,
    _merge_ticket_packets,
    _merge_title,
    _normalize_merge_source_ids,
    _normalize_split_groups,
    _split_ticket_packet,
    _split_titles,
    _unique_text,
    _validate_revision_packet_in_connection,
)


PREVIEW_SIDE_EFFECT_STATUS = "read_only_preview_no_world_mutation"
SPLIT_SIDE_EFFECT_STATUS = (
    "split_tickets_created_source_superseded_no_world_mutation"
)
MERGE_SIDE_EFFECT_STATUS = (
    "merged_ticket_created_sources_superseded_no_world_mutation"
)


@dataclass(frozen=True)
class TicketSplitGroupPreview:
    group_index: int
    change_indexes: List[int]
    title: str
    changes: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_index": self.group_index,
            "change_indexes": list(self.change_indexes),
            "title": self.title,
            "changes": deepcopy(self.changes),
            "change_count": len(self.changes),
        }


@dataclass(frozen=True)
class TicketSplitPreview:
    world_id: str
    source_ticket_id: str
    source_ticket_status: str
    source_title: str
    source_ref: Any
    source_changes: List[Dict[str, Any]]
    risk: str
    compact: bool
    root_ticket_ids: List[str]
    revision_number: int
    groups: List[TicketSplitGroupPreview]
    side_effect_status: str = PREVIEW_SIDE_EFFECT_STATUS

    @property
    def operation(self) -> str:
        return "split"

    @property
    def root_ticket_id(self) -> str:
        return self.root_ticket_ids[0]

    @property
    def change_index_groups(self) -> List[List[int]]:
        return [list(group.change_indexes) for group in self.groups]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "wsa.ticket_split.preview.v1",
            "operation": self.operation,
            "world_id": self.world_id,
            "source_ticket_id": self.source_ticket_id,
            "source_ticket_status": self.source_ticket_status,
            "source_title": self.source_title,
            "source_ref": deepcopy(self.source_ref),
            "source_changes": deepcopy(self.source_changes),
            "change_count": len(self.source_changes),
            "risk": self.risk,
            "compact": self.compact,
            "root_ticket_id": self.root_ticket_id,
            "root_ticket_ids": list(self.root_ticket_ids),
            "revision_number": self.revision_number,
            "groups": [group.to_dict() for group in self.groups],
            "group_count": len(self.groups),
            "change_index_groups": self.change_index_groups,
            "mutation_count": 0,
            "ticket_mutation_count": 0,
            "world_mutation_count": 0,
            "side_effect_status": self.side_effect_status,
        }


@dataclass(frozen=True)
class TicketMergeSourcePreview:
    ticket_id: str
    title: str
    status: str
    risk: str
    compact: bool
    source_ref: Any
    changes: List[Dict[str, Any]]
    root_ticket_ids: List[str]
    revision_number: int

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "ticket_id": self.ticket_id,
            "title": self.title,
            "status": self.status,
            "risk": self.risk,
            "compact": self.compact,
            "source_ref": deepcopy(self.source_ref),
            "changes": deepcopy(self.changes),
            "change_count": len(self.changes),
            "root_ticket_ids": list(self.root_ticket_ids),
            "revision_number": self.revision_number,
        }
        if len(self.root_ticket_ids) == 1:
            payload["root_ticket_id"] = self.root_ticket_ids[0]
        return payload


@dataclass(frozen=True)
class TicketMergePreview:
    world_id: str
    source_tickets: List[TicketMergeSourcePreview]
    title: str
    risk: str
    compact: bool
    changes: List[Dict[str, Any]]
    root_ticket_ids: List[str]
    revision_number: int
    side_effect_status: str = PREVIEW_SIDE_EFFECT_STATUS

    @property
    def operation(self) -> str:
        return "merge"

    @property
    def sources(self) -> List[TicketMergeSourcePreview]:
        return list(self.source_tickets)

    @property
    def source_ticket_ids(self) -> List[str]:
        return [source.ticket_id for source in self.source_tickets]

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "schema": "wsa.ticket_merge.preview.v1",
            "operation": self.operation,
            "world_id": self.world_id,
            "source_ticket_ids": self.source_ticket_ids,
            "sources": [source.to_dict() for source in self.source_tickets],
            "title": self.title,
            "risk": self.risk,
            "compact": self.compact,
            "changes": deepcopy(self.changes),
            "change_count": len(self.changes),
            "root_ticket_ids": list(self.root_ticket_ids),
            "revision_number": self.revision_number,
            "mutation_count": 0,
            "ticket_mutation_count": 0,
            "world_mutation_count": 0,
            "side_effect_status": self.side_effect_status,
        }
        if len(self.root_ticket_ids) == 1:
            payload["root_ticket_id"] = self.root_ticket_ids[0]
        return payload


@dataclass(frozen=True)
class TicketSplitResult:
    world_id: str
    source_ticket_id: str
    source_previous_status: str
    child_tickets: List[TicketRecord]
    root_ticket_ids: List[str]
    revision_number: int
    side_effect_status: str = SPLIT_SIDE_EFFECT_STATUS

    @property
    def operation(self) -> str:
        return "split"

    @property
    def source_status(self) -> str:
        return "superseded"

    @property
    def children(self) -> List[TicketRecord]:
        return list(self.child_tickets)

    @property
    def tickets(self) -> List[TicketRecord]:
        return self.children

    @property
    def child_ticket_ids(self) -> List[str]:
        return [ticket.ticket_id for ticket in self.child_tickets]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "wsa.ticket_split.result.v1",
            "operation": self.operation,
            "world_id": self.world_id,
            "source_ticket_id": self.source_ticket_id,
            "source_previous_status": self.source_previous_status,
            "source_status": self.source_status,
            "child_ticket_ids": self.child_ticket_ids,
            "children": [_ticket_to_dict(ticket) for ticket in self.child_tickets],
            "root_ticket_id": self.root_ticket_ids[0],
            "root_ticket_ids": list(self.root_ticket_ids),
            "revision_number": self.revision_number,
            "mutation_count": len(self.child_tickets) + 1,
            "ticket_mutation_count": len(self.child_tickets) + 1,
            "world_mutation_count": 0,
            "side_effect_status": self.side_effect_status,
        }


@dataclass(frozen=True)
class TicketMergeResult:
    world_id: str
    source_previous_statuses: Dict[str, str]
    merged_ticket: TicketRecord
    root_ticket_ids: List[str]
    revision_number: int
    side_effect_status: str = MERGE_SIDE_EFFECT_STATUS

    @property
    def operation(self) -> str:
        return "merge"

    @property
    def source_ticket_ids(self) -> List[str]:
        return list(self.source_previous_statuses)

    @property
    def source_statuses(self) -> Dict[str, str]:
        return {ticket_id: "superseded" for ticket_id in self.source_ticket_ids}

    @property
    def ticket(self) -> TicketRecord:
        return self.merged_ticket

    @property
    def merged_ticket_id(self) -> str:
        return self.merged_ticket.ticket_id

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "schema": "wsa.ticket_merge.result.v1",
            "operation": self.operation,
            "world_id": self.world_id,
            "source_ticket_ids": self.source_ticket_ids,
            "source_previous_statuses": dict(self.source_previous_statuses),
            "source_statuses": self.source_statuses,
            "merged_ticket_id": self.merged_ticket_id,
            "merged_ticket": _ticket_to_dict(self.merged_ticket),
            "root_ticket_ids": list(self.root_ticket_ids),
            "revision_number": self.revision_number,
            "mutation_count": len(self.source_ticket_ids) + 1,
            "ticket_mutation_count": len(self.source_ticket_ids) + 1,
            "world_mutation_count": 0,
            "side_effect_status": self.side_effect_status,
        }
        if len(self.root_ticket_ids) == 1:
            payload["root_ticket_id"] = self.root_ticket_ids[0]
        return payload


TicketSplitWriteResult = TicketSplitResult
TicketMergeWriteResult = TicketMergeResult


class TicketRevisionService:
    def __init__(self, repo: WorldRepository) -> None:
        self.repo = repo

    def preview_split(
        self,
        source_ticket_id: str,
        change_index_groups: Iterable[Iterable[int]] | None = None,
        *,
        groups: Iterable[Iterable[int]] | None = None,
        titles: Sequence[str] | None = None,
    ) -> TicketSplitPreview:
        requested_groups = _one_split_group_input(change_index_groups, groups)
        requested_titles = list(titles) if titles is not None else None
        with self.repo._connect() as conn:
            source = _load_revision_source_in_connection(
                conn,
                self.repo.world_id,
                source_ticket_id,
                operation="split",
            )
            normalized_groups = _normalize_split_groups(
                requested_groups,
                len(source.changes),
            )
            child_titles = _split_titles(
                source.title,
                len(normalized_groups),
                requested_titles,
            )
            group_previews = [
                TicketSplitGroupPreview(
                    group_index=group_index,
                    change_indexes=list(group),
                    title=child_titles[group_index - 1],
                    changes=_validate_revision_packet_in_connection(
                        self.repo,
                        conn,
                        [source.changes[index - 1] for index in group],
                    ),
                )
                for group_index, group in enumerate(normalized_groups, start=1)
            ]
        return TicketSplitPreview(
            world_id=self.repo.world_id,
            source_ticket_id=source.ticket_id,
            source_ticket_status=source.status,
            source_title=source.title,
            source_ref=deepcopy(source.payload.get("source_ref")),
            source_changes=_source_changes(source),
            risk=source.risk,
            compact=source.compact,
            root_ticket_ids=list(source.root_ticket_ids),
            revision_number=source.revision_number + 1,
            groups=group_previews,
        )

    split_preview = preview_split

    def write_split(self, preview: TicketSplitPreview) -> TicketSplitResult:
        _require_preview_world(self.repo, preview.world_id)
        stored = _split_ticket_packet(
            self.repo,
            preview.source_ticket_id,
            preview.change_index_groups,
            titles=[group.title for group in preview.groups],
            expected_source_changes=preview.source_changes,
        )
        return _split_result(self.repo.world_id, stored)

    split = write_split
    write_ticket_split = write_split

    def preview_merge(
        self,
        source_ticket_ids: Iterable[str],
        *,
        title: str | None = None,
        risk: str | None = None,
        compact: bool | None = None,
    ) -> TicketMergePreview:
        requested_ids = _normalize_merge_source_ids(source_ticket_ids)
        with self.repo._connect() as conn:
            sources = [
                _load_revision_source_in_connection(
                    conn,
                    self.repo.world_id,
                    ticket_id,
                    operation="merge",
                )
                for ticket_id in requested_ids
            ]
            changes = _validate_revision_packet_in_connection(
                self.repo,
                conn,
                [change for source in sources for change in source.changes],
            )
        root_ticket_ids = _unique_text(
            root_id
            for source in sources
            for root_id in source.root_ticket_ids
        )
        source_previews = [_merge_source_preview(source) for source in sources]
        return TicketMergePreview(
            world_id=self.repo.world_id,
            source_tickets=source_previews,
            title=_merge_title(sources, title),
            risk=risk or _highest_risk(source.risk for source in sources),
            compact=(
                bool(compact)
                if compact is not None
                else all(source.compact for source in sources)
            ),
            changes=changes,
            root_ticket_ids=root_ticket_ids,
            revision_number=max(source.revision_number for source in sources) + 1,
        )

    merge_preview = preview_merge

    def write_merge(self, preview: TicketMergePreview) -> TicketMergeResult:
        _require_preview_world(self.repo, preview.world_id)
        stored = _merge_ticket_packets(
            self.repo,
            preview.source_ticket_ids,
            title=preview.title,
            risk=preview.risk,
            compact=preview.compact,
            expected_source_changes={
                source.ticket_id: source.changes
                for source in preview.source_tickets
            },
        )
        return _merge_result(self.repo.world_id, stored)

    merge = write_merge
    write_ticket_merge = write_merge

    def write(
        self,
        preview: TicketSplitPreview | TicketMergePreview,
    ) -> TicketSplitResult | TicketMergeResult:
        if isinstance(preview, TicketSplitPreview):
            return self.write_split(preview)
        if isinstance(preview, TicketMergePreview):
            return self.write_merge(preview)
        raise TypeError("ticket revision write requires a split or merge preview")


def preview_ticket_split(
    repo: WorldRepository,
    source_ticket_id: str,
    change_index_groups: Iterable[Iterable[int]] | None = None,
    *,
    groups: Iterable[Iterable[int]] | None = None,
    titles: Sequence[str] | None = None,
) -> TicketSplitPreview:
    return TicketRevisionService(repo).preview_split(
        source_ticket_id,
        change_index_groups,
        groups=groups,
        titles=titles,
    )


split_ticket_preview = preview_ticket_split
preview_split_ticket = preview_ticket_split


def write_ticket_split(
    repo: WorldRepository,
    preview: TicketSplitPreview,
) -> TicketSplitResult:
    return TicketRevisionService(repo).write_split(preview)


split_ticket = write_ticket_split


def preview_ticket_merge(
    repo: WorldRepository,
    source_ticket_ids: Iterable[str],
    *,
    title: str | None = None,
    risk: str | None = None,
    compact: bool | None = None,
) -> TicketMergePreview:
    return TicketRevisionService(repo).preview_merge(
        source_ticket_ids,
        title=title,
        risk=risk,
        compact=compact,
    )


merge_ticket_preview = preview_ticket_merge
preview_merge_tickets = preview_ticket_merge


def write_ticket_merge(
    repo: WorldRepository,
    preview: TicketMergePreview,
) -> TicketMergeResult:
    return TicketRevisionService(repo).write_merge(preview)


merge_tickets = write_ticket_merge


def _one_split_group_input(
    change_index_groups: Iterable[Iterable[int]] | None,
    groups: Iterable[Iterable[int]] | None,
) -> List[List[int]]:
    if change_index_groups is not None and groups is not None:
        raise ValueError("provide either change_index_groups or groups, not both")
    selected = change_index_groups if change_index_groups is not None else groups
    if selected is None:
        raise ValueError("split change-index groups are required")
    try:
        return [list(group) for group in selected]
    except TypeError as exc:
        raise ValueError("split change indexes must be provided as groups") from exc


def _source_changes(source: _RevisionSource) -> List[Dict[str, Any]]:
    return [deepcopy(change.payload) for change in source.changes]


def _merge_source_preview(source: _RevisionSource) -> TicketMergeSourcePreview:
    return TicketMergeSourcePreview(
        ticket_id=source.ticket_id,
        title=source.title,
        status=source.status,
        risk=source.risk,
        compact=source.compact,
        source_ref=deepcopy(source.payload.get("source_ref")),
        changes=_source_changes(source),
        root_ticket_ids=list(source.root_ticket_ids),
        revision_number=source.revision_number,
    )


def _split_result(
    world_id: str,
    stored: _SplitTicketStoreResult,
) -> TicketSplitResult:
    return TicketSplitResult(
        world_id=world_id,
        source_ticket_id=stored.source_ticket_id,
        source_previous_status=stored.source_previous_status,
        child_tickets=list(stored.child_tickets),
        root_ticket_ids=list(stored.root_ticket_ids),
        revision_number=stored.revision_number,
    )


def _merge_result(
    world_id: str,
    stored: _MergeTicketStoreResult,
) -> TicketMergeResult:
    return TicketMergeResult(
        world_id=world_id,
        source_previous_statuses=dict(stored.source_previous_statuses),
        merged_ticket=stored.merged_ticket,
        root_ticket_ids=list(stored.root_ticket_ids),
        revision_number=stored.revision_number,
    )


def _require_preview_world(repo: WorldRepository, world_id: str) -> None:
    if world_id != repo.world_id:
        raise ValueError(
            f"ticket revision preview belongs to world {world_id}, not {repo.world_id}"
        )


def _ticket_to_dict(ticket: TicketRecord) -> Dict[str, Any]:
    return {
        "ticket_id": ticket.ticket_id,
        "ticket_type": ticket.ticket_type,
        "title": ticket.title,
        "status": ticket.status,
        "risk": ticket.risk,
        "payload": deepcopy(ticket.payload),
    }


__all__ = [
    "MERGE_SIDE_EFFECT_STATUS",
    "PREVIEW_SIDE_EFFECT_STATUS",
    "SPLIT_SIDE_EFFECT_STATUS",
    "TicketMergePreview",
    "TicketMergeResult",
    "TicketMergeSourcePreview",
    "TicketMergeWriteResult",
    "TicketRevisionService",
    "TicketSplitGroupPreview",
    "TicketSplitPreview",
    "TicketSplitResult",
    "TicketSplitWriteResult",
    "merge_ticket_preview",
    "merge_tickets",
    "preview_merge_tickets",
    "preview_split_ticket",
    "preview_ticket_merge",
    "preview_ticket_split",
    "split_ticket",
    "split_ticket_preview",
    "write_ticket_merge",
    "write_ticket_split",
]
