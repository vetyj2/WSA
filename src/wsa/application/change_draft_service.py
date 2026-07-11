from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ..repositories import TicketRecord, WorldRepository
from ..tickets import (
    CANDIDATE_TICKET_TYPES,
    REVISIONABLE_TICKET_STATUSES,
    InvalidTicketStateError,
    NonApplicableTicketError,
    create_pr_packet,
    create_revision_packet,
    materialize_candidate_ticket,
    validate_change_payloads,
)
from ._change_draft_contracts import (
    DRAFT_CHANGE_TYPES as DRAFT_CHANGE_TYPES,
    DRAFT_TARGET_TYPES as DRAFT_TARGET_TYPES,
    STRUCTURED_CANDIDATE_KEYS as STRUCTURED_CANDIDATE_KEYS,
    AmbiguousEntityNameError as AmbiguousEntityNameError,
    ChangeDraftError as ChangeDraftError,
    ChangeSpecError as ChangeSpecError,
    EntityNameNotFoundError as EntityNameNotFoundError,
    _required,
)
from ._change_draft_parsing import (
    extract_structured_candidate_changes as _extract_structured_candidate_changes,
)
from ._change_draft_parsing import parse_change_specs as _parse_change_specs
from ._change_draft_references import (
    resolve_change_references as _resolve_change_references,
)
from ._change_draft_ticket_views import (
    _ticket_change_payloads,
    diff_change_lists as _diff_change_lists,
    ticket_detail as _ticket_detail,
    ticket_diff as _ticket_diff,
)


@dataclass(frozen=True)
class ChangeDraft:
    world_id: str
    title: str
    mode: str
    changes: List[Dict[str, Any]]
    risk: str = "low"
    compact: bool = False
    source_ticket_id: str | None = None
    source_ticket_status: str | None = None
    source_changes: List[Dict[str, Any]] = field(default_factory=list)
    skipped_change_indexes: List[int] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema": "wsa.change_draft.preview.v1",
            "world_id": self.world_id,
            "title": self.title,
            "mode": self.mode,
            "risk": self.risk,
            "compact": self.compact,
            "source_ticket_id": self.source_ticket_id,
            "source_ticket_status": self.source_ticket_status,
            "changes": deepcopy(self.changes),
            "change_count": len(self.changes),
            "skipped_change_indexes": list(self.skipped_change_indexes),
            "warnings": list(self.warnings),
            "mutation_count": 0,
            "world_mutation_count": 0,
            "ticket_mutation_count": 0,
            "side_effect_status": "read_only_preview_no_world_mutation",
        }
        if self.source_ticket_id is not None:
            payload["diff"] = diff_change_lists(self.source_changes, self.changes)
        return payload


def parse_change_specs(
    *,
    add_entity: Iterable[str] = (),
    add_fact: Iterable[str] = (),
    add_world_edge: Iterable[str] = (),
    add_timeline_point: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """Parse repeated CLI flag values into typed, unresolved change dictionaries.

    Positional forms use ``|``:
    ``TYPE|NAME``, ``SUBJECT|PREDICATE|OBJECT``,
    ``SUBJECT|EDGE_TYPE|OBJECT``, and ``LABEL|SORT_KEY``.
    Named forms use ``key=value`` fields separated by ``|`` or ``;``.
    """

    return _parse_change_specs(
        add_entity=add_entity,
        add_fact=add_fact,
        add_world_edge=add_world_edge,
        add_timeline_point=add_timeline_point,
    )


def extract_structured_candidate_changes(
    payload: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Return only explicitly typed changes under known structured-list keys."""

    return _extract_structured_candidate_changes(payload)


class ChangeDraftService:
    def __init__(self, repo: WorldRepository) -> None:
        self.repo = repo

    def compose(
        self,
        *,
        title: str | None = None,
        add_entity: Iterable[str] = (),
        add_fact: Iterable[str] = (),
        add_world_edge: Iterable[str] = (),
        add_timeline_point: Iterable[str] = (),
        accept_candidate: str | None = None,
        revise_ticket: str | None = None,
        revision_ticket_id: str | None = None,
        skip_index: Iterable[int | str] = (),
        skip_indexes: Iterable[int | str] = (),
        risk: str | None = None,
        compact: bool = False,
    ) -> ChangeDraft:
        revision_id = _one_optional_value(
            revise_ticket,
            revision_ticket_id,
            "revise_ticket and revision_ticket_id",
        )
        if accept_candidate and revision_id:
            raise ChangeDraftError(
                "accept_candidate and revise_ticket cannot be used together"
            )
        requested_skips = list(skip_index or ()) + list(skip_indexes or ())
        if requested_skips and not (revision_id or accept_candidate):
            raise ChangeDraftError(
                "skip indexes require a candidate or revision source ticket"
            )

        manual_changes = parse_change_specs(
            add_entity=add_entity,
            add_fact=add_fact,
            add_world_edge=add_world_edge,
            add_timeline_point=add_timeline_point,
        )
        source_changes: List[Dict[str, Any]] = []
        source_ticket_status = None
        skipped: List[int] = []

        if accept_candidate:
            source = self.repo.get_ticket(accept_candidate)
            if source.ticket_type not in CANDIDATE_TICKET_TYPES:
                raise ChangeDraftError(
                    f"ticket is not a candidate container: {accept_candidate}"
                )
            if source.status != "proposed":
                raise InvalidTicketStateError(
                    "candidate ticket cannot be accepted from status "
                    f"{source.status}"
                )
            source_changes = extract_structured_candidate_changes(source.payload)
            skipped = _normalize_skip_indexes(requested_skips, len(source_changes))
            combined = [
                change
                for index, change in enumerate(source_changes, start=1)
                if index not in set(skipped)
            ]
            combined.extend(manual_changes)
            mode = "candidate"
            source_ticket_status = source.status
            draft_title = title or f"Materialized changes from {source.title}"
            draft_risk = risk or "medium"
            source_ticket_id = source.ticket_id
        elif revision_id:
            source = self.repo.get_ticket(revision_id)
            if source.ticket_type in CANDIDATE_TICKET_TYPES:
                raise NonApplicableTicketError(
                    "candidate ticket must be accepted through candidate materialization"
                )
            if source.status not in REVISIONABLE_TICKET_STATUSES:
                raise InvalidTicketStateError(
                    f"ticket {revision_id} cannot be revised from status {source.status}"
                )
            source_changes = _ticket_change_payloads(self.repo, revision_id)
            skipped = _normalize_skip_indexes(requested_skips, len(source_changes))
            combined = [
                change
                for index, change in enumerate(source_changes, start=1)
                if index not in set(skipped)
            ]
            combined.extend(manual_changes)
            mode = "revision"
            source_ticket_status = source.status
            draft_title = title or f"Revision of {source.title}"
            draft_risk = risk or source.risk
            source_ticket_id = source.ticket_id
        else:
            combined = manual_changes
            mode = "compose"
            draft_title = title or "World change draft"
            draft_risk = risk or "low"
            source_ticket_id = None

        normalized = resolve_change_references(self.repo, combined)
        validated = validate_change_payloads(normalized)
        normalized_source_changes = (
            validate_change_payloads(
                resolve_change_references(self.repo, source_changes)
            )
            if source_changes
            else []
        )
        return ChangeDraft(
            world_id=self.repo.world_id,
            title=_required(draft_title, "draft title"),
            mode=mode,
            changes=validated,
            risk=draft_risk,
            compact=bool(compact),
            source_ticket_id=source_ticket_id,
            source_ticket_status=source_ticket_status,
            source_changes=normalized_source_changes,
            skipped_change_indexes=skipped,
            warnings=(
                ["candidate free text was not interpreted as a canon change"]
                if mode == "candidate"
                else []
            ),
        )

    compose_from_flags = compose
    preview = compose

    def write(self, draft: ChangeDraft) -> TicketRecord:
        if draft.world_id != self.repo.world_id:
            raise ChangeDraftError(
                f"draft belongs to world {draft.world_id}, not {self.repo.world_id}"
            )
        if draft.mode == "candidate":
            if not draft.source_ticket_id:
                raise ChangeDraftError("candidate draft requires a source ticket")
            return materialize_candidate_ticket(
                self.repo,
                draft.source_ticket_id,
                draft.title,
                draft.changes,
                source_ref=f"ticket:{draft.source_ticket_id}",
            )
        if draft.mode == "revision":
            if not draft.source_ticket_id:
                raise ChangeDraftError("revision draft requires a source ticket")
            return create_revision_packet(
                self.repo,
                draft.source_ticket_id,
                draft.title,
                draft.changes,
                risk=draft.risk,
                compact=draft.compact,
                skipped_change_indexes=draft.skipped_change_indexes,
            )
        if draft.mode != "compose":
            raise ChangeDraftError(f"unsupported draft mode: {draft.mode}")
        return create_pr_packet(
            self.repo,
            draft.title,
            draft.changes,
            risk=draft.risk,
            compact=draft.compact,
            source_ref="user_cli",
        )

    write_ticket = write

    def ticket_detail(self, ticket_id: str) -> Dict[str, Any]:
        return ticket_detail(self.repo, ticket_id)

    detail = ticket_detail

    def ticket_diff(
        self,
        source_ticket_id: str,
        target_ticket_id: str | None = None,
        *,
        draft: ChangeDraft | None = None,
    ) -> Dict[str, Any]:
        return ticket_diff(
            self.repo,
            source_ticket_id,
            target_ticket_id,
            draft=draft,
        )

    diff = ticket_diff


def compose_change_draft(repo: WorldRepository, **kwargs: Any) -> ChangeDraft:
    return ChangeDraftService(repo).compose(**kwargs)


def write_change_draft(repo: WorldRepository, draft: ChangeDraft) -> TicketRecord:
    return ChangeDraftService(repo).write(draft)


def resolve_change_references(
    repo: WorldRepository,
    changes: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    return _resolve_change_references(repo, changes)


def ticket_detail(repo: WorldRepository, ticket_id: str) -> Dict[str, Any]:
    return _ticket_detail(repo, ticket_id)


get_ticket_detail = ticket_detail


def diff_change_lists(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return _diff_change_lists(before, after)


def ticket_diff(
    repo: WorldRepository,
    source_ticket_id: str,
    target_ticket_id: str | None = None,
    *,
    draft: ChangeDraft | None = None,
) -> Dict[str, Any]:
    return _ticket_diff(
        repo,
        source_ticket_id,
        target_ticket_id,
        draft=draft,
    )


get_ticket_diff = ticket_diff


def _normalize_skip_indexes(
    values: Iterable[int | str],
    change_count: int,
) -> List[int]:
    indexes = set()
    for raw in values:
        if isinstance(raw, bool):
            raise ChangeDraftError("skip index must be a 1-based integer")
        try:
            index = int(raw)
        except (TypeError, ValueError) as exc:
            raise ChangeDraftError(
                f"skip index must be a 1-based integer: {raw!r}"
            ) from exc
        if index < 1 or index > change_count:
            raise ChangeDraftError(
                f"skip index {index} is outside the 1..{change_count} change range"
            )
        indexes.add(index)
    return sorted(indexes)


def _one_optional_value(
    first: str | None,
    second: str | None,
    label: str,
) -> str | None:
    if first and second and first != second:
        raise ChangeDraftError(f"{label} identify different tickets")
    return first or second
