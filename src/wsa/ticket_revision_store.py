from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from sqlite3 import Connection
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .repositories import (
    TicketChangeRecord,
    TicketRecord,
    WorldRepository,
    encode_payload,
    new_id,
)
from .ticket_contracts import (
    CANDIDATE_TICKET_TYPES,
    REVISIONABLE_TICKET_STATUSES,
    InvalidTicketStateError,
    NonApplicableTicketError,
)
from .ticket_references import (
    _validate_deep_authoring_references_in_connection,
    _validate_portable_changes_in_connection,
)
from .ticket_store import (
    _append_commit_in_connection,
    _create_pr_packet_in_connection,
    _decode_mapping,
    _ticket_changes_in_connection,
)
from .ticket_validation import _validate_ticket_changes
from .unit_of_work import WorldUnitOfWork
from .workspace import utc_now


@dataclass(frozen=True)
class _RevisionSource:
    ticket_id: str
    ticket_type: str
    title: str
    status: str
    risk: str
    payload: Dict[str, Any]
    changes: List[TicketChangeRecord]
    lineage: Dict[str, Any]
    root_ticket_ids: List[str]
    revision_number: int

    @property
    def compact(self) -> bool:
        return bool(
            self.payload.get("compact", self.ticket_type == "pr_packet_compact")
        )


@dataclass(frozen=True)
class _SplitTicketStoreResult:
    source_ticket_id: str
    source_previous_status: str
    child_tickets: List[TicketRecord]
    root_ticket_ids: List[str]
    revision_number: int


@dataclass(frozen=True)
class _MergeTicketStoreResult:
    source_previous_statuses: Dict[str, str]
    merged_ticket: TicketRecord
    root_ticket_ids: List[str]
    revision_number: int


def _split_ticket_packet(
    repo: WorldRepository,
    source_ticket_id: str,
    change_index_groups: Iterable[Iterable[int]],
    *,
    titles: Sequence[str] | None = None,
    expected_source_changes: Sequence[Mapping[str, Any]] | None = None,
) -> _SplitTicketStoreResult:
    """Create split children and supersede their source in one transaction."""

    requested_groups = [list(group) for group in change_index_groups]
    requested_titles = list(titles) if titles is not None else None
    repo._ensure_additive_world_schema()
    with WorldUnitOfWork(repo, immediate=True) as conn:
        source = _load_revision_source_in_connection(
            conn,
            repo.world_id,
            source_ticket_id,
            operation="split",
        )
        groups = _normalize_split_groups(requested_groups, len(source.changes))
        _assert_expected_changes(source, expected_source_changes)
        child_change_lists = [
            _validate_revision_packet_in_connection(
                repo,
                conn,
                [source.changes[index - 1] for index in group],
            )
            for group in groups
        ]
        child_titles = _split_titles(source.title, len(groups), requested_titles)
        child_ticket_ids = [new_id("ticket") for _ in groups]
        revision_number = source.revision_number + 1
        child_tickets: List[TicketRecord] = []
        for index, (ticket_id, title, changes) in enumerate(
            zip(child_ticket_ids, child_titles, child_change_lists),
            start=1,
        ):
            lineage = {
                "operation": "split",
                "root_ticket_id": source.root_ticket_ids[0],
                "root_ticket_ids": list(source.root_ticket_ids),
                "parent_ticket_id": source.ticket_id,
                "parent_ticket_ids": [source.ticket_id],
                "revision_number": revision_number,
                "sibling_ticket_ids": [
                    sibling_id
                    for sibling_id in child_ticket_ids
                    if sibling_id != ticket_id
                ],
                "split_ticket_ids": list(child_ticket_ids),
                "split_group_index": index,
            }
            child_tickets.append(
                _create_pr_packet_in_connection(
                    repo,
                    conn,
                    title,
                    changes,
                    source.risk,
                    source.compact,
                    deepcopy(source.payload.get("source_ref")),
                    {
                        "split_from_ticket_id": source.ticket_id,
                        "lineage": lineage,
                    },
                    ticket_id=ticket_id,
                )
            )

        source_payload = deepcopy(source.payload)
        source_payload["superseded_by_ticket_ids"] = list(child_ticket_ids)
        source_payload["lineage"] = {
            **deepcopy(source.lineage),
            "operation": "split",
            "root_ticket_id": source.root_ticket_ids[0],
            "root_ticket_ids": list(source.root_ticket_ids),
            "revision_number": source.revision_number,
            "superseded_by_ticket_ids": list(child_ticket_ids),
        }
        _supersede_source_in_connection(repo, conn, source, source_payload)
        _append_commit_in_connection(
            repo,
            conn,
            "ticket_split",
            "ticket",
            source.ticket_id,
            {
                "source_ticket_id": source.ticket_id,
                "source_previous_status": source.status,
                "child_ticket_ids": list(child_ticket_ids),
                "revision_number": revision_number,
                "change_index_groups": [list(group) for group in groups],
            },
        )
        return _SplitTicketStoreResult(
            source_ticket_id=source.ticket_id,
            source_previous_status=source.status,
            child_tickets=child_tickets,
            root_ticket_ids=list(source.root_ticket_ids),
            revision_number=revision_number,
        )


def _merge_ticket_packets(
    repo: WorldRepository,
    source_ticket_ids: Iterable[str],
    *,
    title: str | None = None,
    risk: str | None = None,
    compact: bool | None = None,
    expected_source_changes: Mapping[
        str, Sequence[Mapping[str, Any]]
    ] | None = None,
) -> _MergeTicketStoreResult:
    """Create a merged packet and supersede every source in one transaction."""

    requested_ids = _normalize_merge_source_ids(source_ticket_ids)
    repo._ensure_additive_world_schema()
    with WorldUnitOfWork(repo, immediate=True) as conn:
        sources = [
            _load_revision_source_in_connection(
                conn,
                repo.world_id,
                ticket_id,
                operation="merge",
            )
            for ticket_id in requested_ids
        ]
        for source in sources:
            expected = (
                expected_source_changes.get(source.ticket_id)
                if expected_source_changes is not None
                else None
            )
            _assert_expected_changes(source, expected)

        merged_changes = _validate_revision_packet_in_connection(
            repo,
            conn,
            [change for source in sources for change in source.changes],
        )
        root_ticket_ids = _unique_text(
            root_id
            for source in sources
            for root_id in source.root_ticket_ids
        )
        revision_number = max(source.revision_number for source in sources) + 1
        parent_ticket_ids = [source.ticket_id for source in sources]
        source_refs = [
            deepcopy(source.payload.get("source_ref")) for source in sources
        ]
        merged_source_ref = (
            source_refs[0]
            if all(source_ref == source_refs[0] for source_ref in source_refs)
            else None
        )
        merged_lineage: Dict[str, Any] = {
            "operation": "merge",
            "root_ticket_ids": list(root_ticket_ids),
            "parent_ticket_ids": list(parent_ticket_ids),
            "revision_number": revision_number,
        }
        if len(root_ticket_ids) == 1:
            merged_lineage["root_ticket_id"] = root_ticket_ids[0]

        merged_ticket = _create_pr_packet_in_connection(
            repo,
            conn,
            _merge_title(sources, title),
            merged_changes,
            risk or _highest_risk(source.risk for source in sources),
            (
                bool(compact)
                if compact is not None
                else all(source.compact for source in sources)
            ),
            merged_source_ref,
            {
                "merged_from_ticket_ids": list(parent_ticket_ids),
                "source_refs": source_refs,
                "lineage": merged_lineage,
            },
        )

        for source in sources:
            source_payload = deepcopy(source.payload)
            source_payload["superseded_by"] = merged_ticket.ticket_id
            source_payload["superseded_by_ticket_ids"] = [merged_ticket.ticket_id]
            source_payload["lineage"] = {
                **deepcopy(source.lineage),
                "operation": "merge",
                "root_ticket_ids": list(root_ticket_ids),
                "parent_ticket_ids": list(parent_ticket_ids),
                "revision_number": source.revision_number,
                "superseded_by_ticket_id": merged_ticket.ticket_id,
                "superseded_by_ticket_ids": [merged_ticket.ticket_id],
            }
            _supersede_source_in_connection(repo, conn, source, source_payload)

        _append_commit_in_connection(
            repo,
            conn,
            "ticket_merged",
            "ticket",
            merged_ticket.ticket_id,
            {
                "source_ticket_ids": list(parent_ticket_ids),
                "source_previous_statuses": {
                    source.ticket_id: source.status for source in sources
                },
                "revision_number": revision_number,
                "change_count": len(merged_changes),
            },
        )
        return _MergeTicketStoreResult(
            source_previous_statuses={
                source.ticket_id: source.status for source in sources
            },
            merged_ticket=merged_ticket,
            root_ticket_ids=list(root_ticket_ids),
            revision_number=revision_number,
        )


def _load_revision_source_in_connection(
    conn: Connection,
    world_id: str,
    ticket_id: str,
    *,
    operation: str,
) -> _RevisionSource:
    row = conn.execute(
        """
        SELECT ticket_id, ticket_type, title, status, risk, payload
        FROM tickets
        WHERE world_id = ? AND ticket_id = ?
        """,
        (world_id, ticket_id),
    ).fetchone()
    if row is None:
        raise KeyError(f"ticket not found: {ticket_id}")
    if row["ticket_type"] in CANDIDATE_TICKET_TYPES:
        raise NonApplicableTicketError(
            f"candidate ticket cannot be used as a {operation} source: {ticket_id}"
        )
    status = str(row["status"])
    if status not in REVISIONABLE_TICKET_STATUSES:
        operation_past_tense = "split" if operation == "split" else "merged"
        raise InvalidTicketStateError(
            f"ticket {ticket_id} cannot be {operation_past_tense} from status "
            f"{status}"
        )
    changes = _validate_ticket_changes(
        _ticket_changes_in_connection(conn, ticket_id)
    )
    if not changes:
        raise NonApplicableTicketError(
            f"ticket {ticket_id} has no concrete changes to {operation}"
        )
    payload = _decode_mapping(row["payload"])
    raw_lineage = payload.get("lineage")
    lineage = dict(raw_lineage) if isinstance(raw_lineage, Mapping) else {}
    root_ticket_ids = _lineage_root_ticket_ids(ticket_id, lineage)
    try:
        revision_number = int(lineage.get("revision_number", 1))
    except (TypeError, ValueError):
        revision_number = 1
    return _RevisionSource(
        ticket_id=str(row["ticket_id"]),
        ticket_type=str(row["ticket_type"]),
        title=str(row["title"]),
        status=status,
        risk=str(row["risk"]),
        payload=payload,
        changes=changes,
        lineage=lineage,
        root_ticket_ids=root_ticket_ids,
        revision_number=max(1, revision_number),
    )


def _validate_revision_packet_in_connection(
    repo: WorldRepository,
    conn: Connection,
    changes: Iterable[TicketChangeRecord],
) -> List[Dict[str, Any]]:
    change_list = _validate_ticket_changes(changes)
    if not change_list:
        raise NonApplicableTicketError(
            "ticket revision packet requires at least one concrete change"
        )
    _validate_portable_changes_in_connection(conn, repo.world_id, change_list)
    _validate_deep_authoring_references_in_connection(
        conn,
        repo.world_id,
        change_list,
    )
    return [deepcopy(change.payload) for change in change_list]


def _normalize_split_groups(
    change_index_groups: Iterable[Iterable[int]],
    change_count: int,
) -> List[List[int]]:
    try:
        groups = [list(group) for group in change_index_groups]
    except TypeError as exc:
        raise ValueError("split change indexes must be provided as groups") from exc
    if len(groups) < 2:
        raise ValueError("ticket split requires at least two change-index groups")

    seen: set[int] = set()
    for group_number, group in enumerate(groups, start=1):
        if not group:
            raise ValueError(f"split group {group_number} must not be empty")
        for index in group:
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError("split change indexes must be integers")
            if index < 1 or index > change_count:
                raise ValueError(
                    f"split change index {index} is outside 1..{change_count}"
                )
            if index in seen:
                raise ValueError(
                    f"split change index {index} appears in more than one group"
                )
            seen.add(index)

    required = set(range(1, change_count + 1))
    if seen != required:
        missing = sorted(required - seen)
        raise ValueError(
            "split groups must exactly partition every source change; "
            f"missing indexes: {missing}"
        )
    return groups


def _normalize_merge_source_ids(source_ticket_ids: Iterable[str]) -> List[str]:
    source_ids = [str(ticket_id).strip() for ticket_id in source_ticket_ids]
    if len(source_ids) < 2:
        raise ValueError("ticket merge requires at least two source tickets")
    if any(not ticket_id for ticket_id in source_ids):
        raise ValueError("merge source ticket IDs must not be blank")
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("merge source tickets must be distinct")
    return source_ids


def _split_titles(
    source_title: str,
    group_count: int,
    titles: Sequence[str] | None,
) -> List[str]:
    if titles is None:
        return [
            f"{source_title} (split {index}/{group_count})"
            for index in range(1, group_count + 1)
        ]
    if len(titles) != group_count:
        raise ValueError("split titles must match the number of change-index groups")
    normalized = [str(title).strip() for title in titles]
    if any(not title for title in normalized):
        raise ValueError("split child titles must not be blank")
    return normalized


def _merge_title(
    sources: Sequence[_RevisionSource],
    title: str | None,
) -> str:
    if title is not None:
        normalized = str(title).strip()
        if not normalized:
            raise ValueError("merged ticket title must not be blank")
        return normalized
    return "Merged: " + " + ".join(source.title for source in sources)


def _highest_risk(risks: Iterable[str]) -> str:
    levels = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    risk_list = [str(risk) for risk in risks]
    return max(risk_list, key=lambda value: levels.get(value, 0))


def _lineage_root_ticket_ids(
    ticket_id: str,
    lineage: Mapping[str, Any],
) -> List[str]:
    roots: List[str] = []
    raw_roots = lineage.get("root_ticket_ids")
    if isinstance(raw_roots, (list, tuple)):
        roots.extend(_unique_text(raw_roots))
    raw_root = lineage.get("root_ticket_id")
    if raw_root is not None:
        roots.extend(_unique_text([raw_root]))
    return _unique_text(roots or [ticket_id])


def _unique_text(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _assert_expected_changes(
    source: _RevisionSource,
    expected_changes: Sequence[Mapping[str, Any]] | None,
) -> None:
    if expected_changes is None:
        return
    expected = [deepcopy(dict(change)) for change in expected_changes]
    actual = [deepcopy(change.payload) for change in source.changes]
    if actual != expected:
        raise InvalidTicketStateError(
            f"ticket {source.ticket_id} changes changed after revision preview"
        )


def _supersede_source_in_connection(
    repo: WorldRepository,
    conn: Connection,
    source: _RevisionSource,
    payload: Mapping[str, Any],
) -> None:
    result = conn.execute(
        """
        UPDATE tickets
        SET status = 'superseded', payload = ?, updated_at = ?
        WHERE world_id = ? AND ticket_id = ? AND status = ?
        """,
        (
            encode_payload(dict(payload)),
            utc_now(),
            repo.world_id,
            source.ticket_id,
            source.status,
        ),
    )
    if result.rowcount != 1:
        raise InvalidTicketStateError(
            f"ticket {source.ticket_id} changed while its revision was being written"
        )
