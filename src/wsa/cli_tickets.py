from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Dict, List

from .application.change_draft_service import ChangeDraftService
from .application.proposal_service import (
    candidate_materialization_preview,
    write_materialized_candidate_ticket,
)
from .application.selection_service import resolve_world_selector
from .application.ticket_selection_service import (
    TicketSelectionError,
    select_guided_ticket,
)
from .application.ticket_revision_service import TicketRevisionService
from .repositories import WorldRepository
from .tickets import (
    InvalidTicketStateError,
    NonApplicableTicketError,
    TicketApplyResult,
    UnsupportedTicketChangeError,
    apply_ticket,
    review_ticket,
)
from .update import UpdateLockError, assert_update_unlocked
from .workspace import get_world


MAX_CHANGE_SET_BYTES = 4 * 1024 * 1024


def _guard_update_unlocked(workspace: Path, operation: str) -> bool:
    try:
        assert_update_unlocked(workspace, operation)
    except UpdateLockError as exc:
        print("update_lock: blocked")
        print(f"operation: {operation}")
        print(f"detail: {exc}")
        return False
    return True


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _guided_command(workspace: Path, command: str, world_name: str) -> str:
    return " ".join(
        [
            "wsa",
            "--workspace",
            shlex.quote(str(workspace)),
            "ticket",
            command,
            "--world",
            shlex.quote(world_name),
        ]
    )


def _change_summary(change: Dict[str, Any]) -> str:
    change_type = str(change.get("change_type") or "unknown")
    if change_type == "add_entity":
        return f"entity {change.get('entity_type')}: {change.get('display_name')}"
    if change_type == "add_fact":
        subject = change.get("subject_name") or change.get("subject_id") or change.get(
            "subject_change_ref"
        )
        value = (
            change.get("object_name")
            or change.get("object_value")
            or change.get("object_ref_id")
            or change.get("object_change_ref")
        )
        return f"fact {subject}.{change.get('predicate')} = {value}"
    if change_type == "add_world_edge":
        subject = change.get("subject_name") or change.get("subject_id") or change.get(
            "subject_change_ref"
        )
        target = (
            change.get("object_name")
            or change.get("object_id")
            or change.get("object_value")
            or change.get("object_change_ref")
        )
        return f"relationship {subject} --{change.get('edge_type')}--> {target}"
    if change_type == "add_timeline_point":
        return f"timeline {change.get('sort_key')}: {change.get('label')}"
    if change_type == "add_actor_profile":
        summary = (change.get("payload") or {}).get("summary")
        return f"actor {change.get('fragment_type')} profile: {summary}"
    if change_type == "add_entity_attribute_span":
        value = next(
            (
                change.get(key)
                for key in ("value_text", "value_number", "value_ref_id", "value_json")
                if change.get(key) is not None
            ),
            None,
        )
        interval = f"[{change.get('valid_from') or '*'}, {change.get('valid_until') or '*'})"
        return f"actor attribute {change.get('dimension_key')} = {value} {interval}"
    if change_type == "add_knowledge_attribution":
        return (
            f"knowledge {change.get('knowledge_state')}: "
            f"{change.get('knowledge_target_type')} {change.get('knowledge_target_id')}"
        )
    if change_type == "add_actor_memory_packet":
        summary = (change.get("payload") or {}).get("summary")
        return f"actor memory {change.get('time_scope')}: {summary}"
    if change_type.startswith("update_") and change.get("target_id"):
        revisions = ", ".join(
            f"{key}={change[key]}"
            for key in (
                "status",
                "valid_from",
                "acquired_at",
                "time_scope",
                "valid_until",
            )
            if key in change
        )
        return f"revise {change.get('target_type')} {change['target_id']}: {revisions}"
    return f"{change_type}: {json.dumps(change, ensure_ascii=False, sort_keys=True)}"


def _print_draft(payload: Dict[str, Any], *, language: str) -> None:
    korean = language == "ko"
    print("변경안 미리보기" if korean else "change draft preview")
    print(f"world_id: {payload['world_id']}")
    print(f"mode: {payload['mode']}")
    print(f"title: {payload['title']}")
    print(f"risk: {payload['risk']}")
    print(f"change_count: {payload['change_count']}")
    for index, change in enumerate(payload["changes"], start=1):
        print(f"{index}. {_change_summary(change)}")
    diff = payload.get("diff")
    if isinstance(diff, dict):
        print(
            "diff: "
            f"unchanged={diff.get('unchanged_count', 0)} "
            f"removed={diff.get('removed_count', 0)} "
            f"added={diff.get('added_count', 0)}"
        )
    ticket = payload.get("ticket")
    if isinstance(ticket, dict):
        print(f"ticket_id: {ticket['ticket_id']}")
        print(f"ticket_status: {ticket['status']}")
    print(f"side_effect_status: {payload['side_effect_status']}")
    if payload.get("next_action"):
        print(f"next_action: {payload['next_action']}")


def _result_payload(
    action: str,
    result: TicketApplyResult,
    descriptions: List[str] | None = None,
) -> Dict[str, Any]:
    payload = {
        "schema": "wsa.ticket.transition.v1",
        "action": action,
        "ticket_id": result.ticket_id,
        "previous_status": result.previous_status,
        "status": result.status,
        "side_effect_status": result.side_effect_status,
        "applied_count": len(result.applied_ids),
        "applied_ids": result.applied_ids,
    }
    if result.compatibility_mode is not None:
        payload["compatibility_mode"] = result.compatibility_mode
    if result.deprecation_warning is not None:
        payload["deprecation_warning"] = result.deprecation_warning
    if descriptions:
        payload["applied_changes"] = [
            {
                "summary": summary,
                "record_id": (
                    result.applied_ids[index]
                    if index < len(result.applied_ids)
                    else None
                ),
            }
            for index, summary in enumerate(descriptions)
        ]
    return payload


def _print_result(
    action: str,
    result: TicketApplyResult,
    descriptions: List[str] | None = None,
) -> None:
    payload = _result_payload(action, result, descriptions)
    print(f"ticket_{action}: {result.status}")
    print(f"ticket_id: {result.ticket_id}")
    print(f"previous_status: {result.previous_status}")
    print(f"side_effect_status: {result.side_effect_status}")
    print(f"applied_count: {payload['applied_count']}")
    for item in result.applied_ids:
        print(f"applied: {item}")
    for item in payload.get("applied_changes", []):
        print(f"changed: {item['summary']}")
    if result.deprecation_warning:
        print(f"compatibility_warning: {result.deprecation_warning}")


def _load_change_set(input_path: Path) -> tuple[Path, List[Dict[str, Any]]]:
    resolved = input_path.expanduser().resolve()
    if resolved.stat().st_size > MAX_CHANGE_SET_BYTES:
        raise ValueError("change-set JSON exceeds 4 MiB materialization limit")
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("changes")
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("change-set JSON must be a list or an object with a changes list")
    return resolved, [dict(item) for item in value]


def run_ticket_list(workspace: Path, world_id: str, status: str | None) -> int:
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    tickets = repo.list_tickets(status=status)
    if not tickets:
        print("tickets: none")
        return 0
    for ticket in tickets:
        print(
            "\t".join(
                [
                    ticket.ticket_id,
                    ticket.status,
                    ticket.risk,
                    ticket.ticket_type,
                    ticket.title,
                ]
            )
        )
    return 0


def run_ticket_show(
    workspace: Path,
    world_selector: str | None,
    ticket_id: str,
    output_format: str = "text",
    *,
    language: str = "ko",
) -> int:
    world = resolve_world_selector(workspace, world_selector)
    payload = ChangeDraftService(
        WorldRepository(world.world_id, world.path)
    ).ticket_detail(ticket_id)
    payload["world_id"] = world.world_id
    if output_format == "json":
        _print_json(payload)
        return 0
    print("티켓 상세" if language == "ko" else "ticket detail")
    print(f"ticket_id: {payload['ticket_id']}")
    print(f"title: {payload['title']}")
    print(f"status: {payload['status']}")
    print(f"risk: {payload['risk']}")
    print(f"change_count: {payload['change_count']}")
    for change in payload["changes"]:
        print(f"{change['index']}. {_change_summary(change['payload'])}")
    print(f"side_effect_status: {payload['side_effect_status']}")
    return 0


def run_ticket_next(
    workspace: Path,
    world_selector: str | None,
    output_format: str = "text",
    *,
    language: str = "ko",
) -> int:
    world = resolve_world_selector(workspace, world_selector)
    repo = WorldRepository(world.world_id, world.path)
    try:
        selection = select_guided_ticket(repo, "inspect")
    except TicketSelectionError as exc:
        print("ticket_next: blocked")
        print("side_effect_status: no_state_transition")
        print(f"detail: {exc}")
        return 1
    payload = ChangeDraftService(repo).ticket_detail(selection.ticket.ticket_id)
    payload["world_id"] = world.world_id
    payload["guided_action"] = selection.action
    payload["selection_policy"] = "single_eligible_ticket_only"
    payload["next_action"] = _guided_command(
        workspace,
        "review-next" if selection.action == "review" else "apply-next",
        world.display_name,
    )
    if output_format == "json":
        _print_json(payload)
        return 0
    print("다음 검토 티켓" if language == "ko" else "next review ticket")
    print(f"title: {payload['title']}")
    print(f"status: {payload['status']}")
    print(f"risk: {payload['risk']}")
    print(f"change_count: {payload['change_count']}")
    for change in payload["changes"]:
        print(f"{change['index']}. {_change_summary(change['payload'])}")
    print(f"next_action: {payload['next_action']}")
    print(f"side_effect_status: {payload['side_effect_status']}")
    return 0


def _select_guided_transition(
    workspace: Path,
    world_selector: str | None,
    action: str,
) -> tuple[Any, str] | None:
    world = resolve_world_selector(workspace, world_selector)
    repo = WorldRepository(world.world_id, world.path)
    try:
        selection = select_guided_ticket(repo, action)
    except TicketSelectionError as exc:
        print(f"ticket_{action}_next: blocked")
        print("side_effect_status: no_state_transition")
        print(f"detail: {exc}")
        return None
    return world, selection.ticket.ticket_id


def run_ticket_review_next(
    workspace: Path,
    world_selector: str | None,
    output_format: str = "text",
) -> int:
    selected = _select_guided_transition(workspace, world_selector, "review")
    if selected is None:
        return 1
    world, ticket_id = selected
    return run_ticket_review(workspace, world.world_id, ticket_id, output_format)


def run_ticket_apply_next(
    workspace: Path,
    world_selector: str | None,
    output_format: str = "text",
) -> int:
    selected = _select_guided_transition(workspace, world_selector, "apply")
    if selected is None:
        return 1
    world, ticket_id = selected
    return run_ticket_apply(
        workspace,
        world.world_id,
        ticket_id,
        output_format=output_format,
    )


def run_ticket_compose(
    workspace: Path,
    world_selector: str | None,
    *,
    title: str | None,
    add_entity: List[str],
    add_fact: List[str],
    add_edge: List[str],
    add_timeline: List[str],
    accept_candidate: str | None = None,
    revise_ticket: str | None = None,
    skip_index: List[int] | None = None,
    risk: str | None = None,
    compact: bool = False,
    write_ticket: bool = False,
    output_format: str = "text",
    language: str = "ko",
) -> int:
    if write_ticket and not _guard_update_unlocked(workspace, "ticket.compose"):
        return 1
    world = resolve_world_selector(workspace, world_selector)
    service = ChangeDraftService(WorldRepository(world.world_id, world.path))
    draft = service.compose(
        title=title,
        add_entity=add_entity,
        add_fact=add_fact,
        add_world_edge=add_edge,
        add_timeline_point=add_timeline,
        accept_candidate=accept_candidate,
        revise_ticket=revise_ticket,
        skip_index=skip_index or [],
        risk=risk,
        compact=compact,
    )
    payload = draft.to_dict()
    if write_ticket:
        ticket = service.write(draft)
        payload["ticket"] = {
            "ticket_id": ticket.ticket_id,
            "ticket_type": ticket.ticket_type,
            "status": ticket.status,
        }
        payload["ticket_mutation_count"] = 1
        payload["mutation_count"] = 1
        payload["side_effect_status"] = "proposed_ticket_created_no_world_mutation"
        payload["next_action"] = _guided_command(
            workspace,
            "next",
            world.display_name,
        )
    else:
        payload["next_action"] = "review_preview_then_repeat_with_--write-ticket"
    if output_format == "json":
        _print_json(payload)
    else:
        _print_draft(payload, language=language)
    return 0


def _parse_split_parts(parts: List[str]) -> List[List[int]]:
    groups: List[List[int]] = []
    for group_number, raw in enumerate(parts, start=1):
        values = [item.strip() for item in raw.split(",")]
        if not values or any(not item for item in values):
            raise ValueError(f"split part {group_number} must contain indexes")
        try:
            groups.append([int(item) for item in values])
        except ValueError as exc:
            raise ValueError(
                f"split part {group_number} must use comma-separated integers"
            ) from exc
    return groups


def run_ticket_split(
    workspace: Path,
    world_selector: str | None,
    source_ticket_id: str,
    parts: List[str],
    *,
    titles: List[str] | None = None,
    write_ticket: bool = False,
    output_format: str = "text",
) -> int:
    if write_ticket and not _guard_update_unlocked(workspace, "ticket.split"):
        return 1
    try:
        world = resolve_world_selector(workspace, world_selector)
        service = TicketRevisionService(
            WorldRepository(world.world_id, world.path)
        )
        preview = service.preview_split(
            source_ticket_id,
            _parse_split_parts(parts),
            titles=titles or None,
        )
        payload = preview.to_dict()
        if write_ticket:
            result = service.write_split(preview)
            payload = result.to_dict()
            payload["preview"] = preview.to_dict()
            payload["next_actions"] = [
                " ".join(
                    [
                        "wsa",
                        "--workspace",
                        shlex.quote(str(workspace)),
                        "ticket",
                        "show",
                        ticket.ticket_id,
                        "--world",
                        shlex.quote(world.display_name),
                    ]
                )
                for ticket in result.child_tickets
            ]
    except (
        InvalidTicketStateError,
        NonApplicableTicketError,
        UnsupportedTicketChangeError,
        KeyError,
        ValueError,
    ) as exc:
        print("ticket_split: blocked")
        print("side_effect_status: no_state_transition")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        _print_json(payload)
        return 0
    print("ticket_split: written" if write_ticket else "ticket_split: preview")
    print(f"source_ticket_id: {source_ticket_id}")
    if write_ticket:
        for ticket in result.child_tickets:
            print(f"child: {ticket.title} ({ticket.ticket_id})")
        for action in payload["next_actions"]:
            print(f"next_action: {action}")
    else:
        for group in preview.groups:
            indexes = ",".join(str(index) for index in group.change_indexes)
            print(f"part_{group.group_index}: {indexes} -> {group.title}")
    print(f"side_effect_status: {payload['side_effect_status']}")
    return 0


def run_ticket_merge(
    workspace: Path,
    world_selector: str | None,
    source_ticket_ids: List[str],
    *,
    title: str | None = None,
    risk: str | None = None,
    compact: bool | None = None,
    write_ticket: bool = False,
    output_format: str = "text",
) -> int:
    if write_ticket and not _guard_update_unlocked(workspace, "ticket.merge"):
        return 1
    try:
        world = resolve_world_selector(workspace, world_selector)
        service = TicketRevisionService(
            WorldRepository(world.world_id, world.path)
        )
        preview = service.preview_merge(
            source_ticket_ids,
            title=title,
            risk=risk,
            compact=compact,
        )
        payload = preview.to_dict()
        if write_ticket:
            result = service.write_merge(preview)
            payload = result.to_dict()
            payload["preview"] = preview.to_dict()
            payload["next_action"] = _guided_command(
                workspace,
                "next",
                world.display_name,
            )
    except (
        InvalidTicketStateError,
        NonApplicableTicketError,
        UnsupportedTicketChangeError,
        KeyError,
        ValueError,
    ) as exc:
        print("ticket_merge: blocked")
        print("side_effect_status: no_state_transition")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        _print_json(payload)
        return 0
    print("ticket_merge: written" if write_ticket else "ticket_merge: preview")
    print(f"source_count: {len(source_ticket_ids)}")
    print(f"title: {preview.title}")
    print(f"change_count: {len(preview.changes)}")
    if write_ticket:
        print(f"merged_ticket_id: {result.merged_ticket_id}")
        print(f"next_action: {payload['next_action']}")
    print(f"side_effect_status: {payload['side_effect_status']}")
    return 0


def run_ticket_review(
    workspace: Path,
    world_id: str,
    ticket_id: str,
    output_format: str = "text",
) -> int:
    if not _guard_update_unlocked(workspace, "ticket.review"):
        return 1
    world = get_world(workspace, world_id)
    try:
        result = review_ticket(
            WorldRepository(world.world_id, world.path),
            ticket_id,
        )
    except (
        InvalidTicketStateError,
        NonApplicableTicketError,
        UnsupportedTicketChangeError,
        KeyError,
    ) as exc:
        print("ticket_review: blocked")
        print(f"ticket_id: {ticket_id}")
        print("side_effect_status: no_world_mutation")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        _print_json(_result_payload("review", result))
    else:
        _print_result("review", result)
    return 0


def run_ticket_apply(
    workspace: Path,
    world_id: str,
    ticket_id: str,
    *,
    allow_proposed_compat: bool = False,
    output_format: str = "text",
) -> int:
    if not _guard_update_unlocked(workspace, "ticket.apply"):
        return 1
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    descriptions = [
        _change_summary(record.payload)
        for record in repo.list_ticket_changes(ticket_id)
    ]
    try:
        result = apply_ticket(
            repo,
            ticket_id,
            allow_proposed_compat=allow_proposed_compat,
        )
    except (
        InvalidTicketStateError,
        NonApplicableTicketError,
        UnsupportedTicketChangeError,
        KeyError,
    ) as exc:
        print("ticket_application: blocked")
        print(f"ticket_id: {ticket_id}")
        print("side_effect_status: no_world_mutation")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        _print_json(_result_payload("application", result, descriptions))
    else:
        _print_result("application", result, descriptions)
    return 0


def run_ticket_materialize(
    workspace: Path,
    world_id: str,
    candidate_ticket_id: str,
    input_path: Path,
    write_ticket: bool,
    output_format: str = "text",
) -> int:
    if write_ticket and not _guard_update_unlocked(workspace, "ticket.materialize"):
        return 1
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    try:
        resolved, changes = _load_change_set(input_path)
        preview = candidate_materialization_preview(
            repo,
            candidate_ticket_id,
            changes,
        )
        payload = preview.to_dict()
        payload["candidate_ticket_id"] = candidate_ticket_id
        payload["input_path"] = str(resolved)
        if write_ticket:
            ticket = write_materialized_candidate_ticket(
                repo,
                candidate_ticket_id,
                preview,
            )
            payload["ticket"] = {
                "ticket_id": ticket.ticket_id,
                "ticket_type": ticket.ticket_type,
                "status": ticket.status,
            }
            payload["side_effect_status"] = (
                "applicable_ticket_created_candidate_converted_no_world_mutation"
            )
            payload["next_action"] = (
                f"wsa ticket review {world_id} {ticket.ticket_id}"
            )
        else:
            payload["next_action"] = "review_preview_then_repeat_with_--write-ticket"
    except (
        OSError,
        json.JSONDecodeError,
        InvalidTicketStateError,
        NonApplicableTicketError,
        UnsupportedTicketChangeError,
        KeyError,
        ValueError,
    ) as exc:
        print("ticket_materialization: blocked")
        print(f"candidate_ticket_id: {candidate_ticket_id}")
        print("side_effect_status: no_world_mutation")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        _print_json(payload)
    else:
        print(f"candidate_ticket_id: {candidate_ticket_id}")
        print(f"change_count: {payload['change_count']}")
        for change in payload["changes"]:
            print(json.dumps(change, ensure_ascii=False, sort_keys=True))
        if payload.get("ticket"):
            print(f"ticket_id: {payload['ticket']['ticket_id']}")
            print(f"ticket_status: {payload['ticket']['status']}")
        print(f"next_action: {payload['next_action']}")
        print(f"side_effect_status: {payload['side_effect_status']}")
    return 0
