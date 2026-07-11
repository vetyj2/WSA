from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Dict

from .application.deep_authoring_service import (
    DeepAuthoringService,
    actor_memory_change,
    actor_profile_change,
    knowledge_attribution_change,
    lifecycle_revision_change,
    temporal_attribute_change,
)
from .application.proposal_service import (
    ProposalPreview,
    edge_proposal_preview,
    entity_proposal_preview,
    fact_proposal_preview,
    portable_import_preview,
    startup_proposal_preview,
    write_proposal_ticket,
)
from .application.selection_service import resolve_world_selector
from .application.world_home_service import WorldHomeService, format_world_home
from .application.world_fork_service import WorldForkService
from .application.world_service import WorldInspectionService
from .repositories import WorldRepository
from .workspace import get_world


def run_world_home(
    workspace: Path,
    selector: str | None,
    output_format: str = "text",
    language: str = "ko",
) -> int:
    try:
        world = resolve_world_selector(workspace, selector)
        payload = WorldHomeService(workspace, world).snapshot()
    except (KeyError, ValueError) as exc:
        print("월드_홈: 차단" if language == "ko" else "world_home: blocked")
        print(f"detail: {exc}")
        print(
            "변경_상태: 변경_없음"
            if language == "ko"
            else "side_effect_status: no_mutation"
        )
        return 1
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_world_home(payload, language=language):
            print(line)
    return 0


def run_world_continue(
    workspace: Path,
    selector: str | None,
    output_format: str = "text",
    language: str = "ko",
) -> int:
    try:
        world = resolve_world_selector(workspace, selector)
        payload = WorldHomeService(workspace, world).snapshot()
    except (KeyError, ValueError) as exc:
        print("월드_계속: 차단" if language == "ko" else "world_continue: blocked")
        print(f"detail: {exc}")
        return 1
    reason = payload["next_action"]["reason"]
    commands = _continuation_commands(workspace, world.world_id, payload)
    result = {
        "schema": "wsa.world.continue.v1",
        "world": payload["world"],
        "reason": reason,
        "commands": commands,
        "side_effect_status": "read_only_no_world_mutation",
    }
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if language == "ko":
        print(f"월드_계속: {world.display_name}")
        print(f"다음_이유: {reason}")
        for command in commands:
            print(f"실행_명령: {' '.join(command['argv'])}")
            print(f"효과: {command['side_effect']}")
        print("변경_상태: 읽기_전용")
    else:
        print(f"world_continue: {world.display_name}")
        print(f"next_reason: {reason}")
        for command in commands:
            print(f"command: {' '.join(command['argv'])}")
            print(f"effect: {command['side_effect']}")
        print("side_effect_status: read_only")
    return 0


def _continuation_commands(
    workspace: Path,
    world_id: str,
    home: Dict[str, Any],
) -> list[Dict[str, Any]]:
    prefix = ["wsa", "--workspace", str(workspace)]
    reason = home["next_action"]["reason"]
    if reason == "complete_minimum_startup_frame":
        return [{
            "argv": prefix + ["world", "startup", "interview", world_id],
            "side_effect": "records_question_state_only_no_world_mutation",
        }]
    if reason == "review_pending_items":
        return [{
            "argv": prefix + ["report", "inbox", world_id],
            "side_effect": "read_only_review_inbox",
        }]
    if reason == "continue_or_review_active_run":
        run_id = home["pending"]["runs"][0]["run_id"]
        return [{
            "argv": prefix + ["orchestrator", "status", run_id],
            "side_effect": "read_only_run_status",
        }]
    if reason == "review_blocking_conflicts":
        return [{
            "argv": prefix + ["manager", "diagnose"],
            "side_effect": "read_only_diagnostics",
        }]
    if reason == "create_first_world_item":
        return [{
            "argv": prefix + ["ticket", "compose", "--world", world_id, "--help"],
            "side_effect": "read_only_guided_change_help",
        }]
    return [{
        "argv": prefix + ["world", "show", world_id],
        "side_effect": "read_only_world_inspection",
    }]


def run_world_inspection(
    workspace: Path,
    world_id: str,
    resource: str,
    item_id: str | None = None,
    entity_type: str | None = None,
    subject_id: str | None = None,
    edge_type: str | None = None,
    status: str | None = None,
    output_format: str = "text",
) -> int:
    world = get_world(workspace, world_id)
    service = WorldInspectionService(world)
    try:
        if resource == "summary":
            payload = service.summary()
        elif resource == "entities":
            payload = (
                service.entity(item_id)
                if item_id
                else service.entities(entity_type=entity_type, status=status)
            )
        elif resource == "facts":
            payload = service.fact(item_id) if item_id else service.facts(subject_id)
        elif resource == "edges":
            payload = service.edges(subject_id, edge_type, status)
        elif resource == "timeline":
            payload = service.timeline()
        elif resource == "export":
            payload = service.export_data()
        else:
            raise ValueError(f"unsupported world inspection resource: {resource}")
    except KeyError as exc:
        print("world_inspection: blocked")
        print(f"detail: {exc}")
        return 1
    _print_payload(payload, output_format)
    return 0


def run_world_selective_export(
    workspace: Path,
    world_id: str,
    entity_ids: list[str],
    *,
    include_timeline: bool = False,
    output_format: str = "text",
) -> int:
    world = get_world(workspace, world_id)
    payload = WorldForkService(world).selective_export(
        entity_ids,
        include_timeline=include_timeline,
    )
    _print_payload(payload, output_format)
    return 0


def run_world_fork_plan(
    workspace: Path,
    world_id: str,
    target_display_name: str,
    entity_ids: list[str],
    *,
    include_timeline: bool = False,
    output_format: str = "text",
) -> int:
    world = get_world(workspace, world_id)
    payload = WorldForkService(world).fork_plan(
        target_display_name,
        entity_ids,
        include_timeline=include_timeline,
    )
    _print_payload(payload, output_format)
    return 0


def run_world_actor_show(
    workspace: Path,
    world_id: str,
    actor_selector: str,
    output_format: str = "text",
    language: str = "ko",
) -> int:
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    actor_id = _resolve_actor_id(repo, actor_selector)
    payload = WorldInspectionService(world).actor_authoring(actor_id)
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("액터 저작 상태" if language == "ko" else "actor authoring state")
    print(f"actor: {payload['actor']['display_name']}")
    print(f"entity_id: {actor_id}")
    for section in (
        "profiles",
        "temporal_attributes",
        "knowledge_attributions",
        "memories",
    ):
        label = {
            "profiles": "프로필",
            "temporal_attributes": "시간_속성",
            "knowledge_attributions": "지식_귀속",
            "memories": "메모리",
        }.get(section, section) if language == "ko" else section
        print(f"{label}: {len(payload[section])}")
        for item in payload[section]:
            print(json.dumps(item, ensure_ascii=False, sort_keys=True))
    print(f"side_effect_status: {payload['side_effect_status']}")
    return 0


def run_world_actor_authoring(
    workspace: Path,
    world_id: str,
    actor_selector: str,
    authoring_type: str,
    *,
    title: str | None,
    source_ref: str,
    write_ticket: bool,
    output_format: str = "text",
    language: str = "ko",
    **values: Any,
) -> int:
    world = get_world(workspace, world_id)
    repo = WorldRepository(world.world_id, world.path)
    actor_id = _resolve_actor_id(repo, actor_selector)
    replace_record = values.get("replace_record")
    replace_at = values.get("replace_at")
    if replace_record and replace_at:
        start_field = {
            "profile": "valid_from",
            "attribute": "valid_from",
            "knowledge": "acquired_at",
            "memory": "time_scope",
        }.get(authoring_type)
        if start_field is not None:
            current_start = values.get(start_field)
            if current_start is None:
                values[start_field] = replace_at
            elif current_start != replace_at:
                raise ValueError(
                    f"--replace-at must match --{start_field.replace('_', '-')}"
                )
    if authoring_type == "profile":
        change = actor_profile_change(
            actor_id,
            values["fragment"],
            {"summary": values["text"]},
            source_ref=source_ref,
            valid_from=values.get("valid_from"),
            valid_until=values.get("valid_until"),
        )
        default_title = f"Update {actor_selector} {values['fragment']} profile"
    elif authoring_type == "attribute":
        change = temporal_attribute_change(
            actor_id,
            values["dimension"],
            value_text=values.get("value_text"),
            value_number=values.get("value_number"),
            value_ref_id=values.get("value_ref_id"),
            valid_from=values.get("valid_from"),
            valid_until=values.get("valid_until"),
            source_ref=source_ref,
        )
        default_title = f"Set {actor_selector} {values['dimension']} over time"
    elif authoring_type == "knowledge":
        change = knowledge_attribution_change(
            actor_id,
            values["target_type"],
            values["target_id"],
            values["state"],
            acquired_at=values.get("acquired_at"),
            valid_until=values.get("valid_until"),
            source_ref=source_ref,
        )
        default_title = f"Set {actor_selector} knowledge boundary"
    elif authoring_type == "memory":
        change = actor_memory_change(
            actor_id,
            values["time_scope"],
            {"summary": values["text"]},
            source_ref=source_ref,
        )
        default_title = f"Add {actor_selector} memory"
    elif authoring_type == "revise":
        if values.get("valid_until") is not None and values.get(
            "clear_valid_until"
        ):
            raise ValueError(
                "--valid-until and --clear-valid-until cannot be used together"
            )
        revision_values = {
            key: values[key]
            for key in (
                "status",
                "valid_from",
                "acquired_at",
                "time_scope",
            )
            if values.get(key) is not None
        }
        if values.get("clear_valid_until"):
            revision_values["valid_until"] = None
        elif values.get("valid_until") is not None:
            revision_values["valid_until"] = values["valid_until"]
        _assert_actor_record_owner(
            repo,
            actor_id,
            values["record_type"],
            values["record_id"],
        )
        change = lifecycle_revision_change(
            values["record_type"],
            values["record_id"],
            source_ref=source_ref,
            **revision_values,
        )
        default_title = f"Revise {actor_selector} {values['record_type']}"
    else:
        raise ValueError(f"unsupported actor authoring type: {authoring_type}")

    changes = [change]
    if replace_record:
        record_type = {
            "profile": "actor_profile",
            "attribute": "entity_attribute_span",
            "knowledge": "knowledge_attribution",
            "memory": "actor_memory_packet",
        }[authoring_type]
        _assert_actor_record_owner(repo, actor_id, record_type, replace_record)
        boundary = replace_at or values.get(
            {
                "profile": "valid_from",
                "attribute": "valid_from",
                "knowledge": "acquired_at",
                "memory": "time_scope",
            }[authoring_type]
        )
        revision_values = (
            {"valid_until": boundary}
            if boundary is not None
            else {"status": "deprecated"}
        )
        changes.insert(
            0,
            lifecycle_revision_change(
                record_type,
                replace_record,
                source_ref=source_ref,
                **revision_values,
            ),
        )
        default_title = f"Replace {actor_selector} {record_type}"

    service = DeepAuthoringService(repo)
    preview = service.preview(
        title or default_title,
        changes,
        source_ref=source_ref,
    )
    payload = preview.to_dict()
    if write_ticket:
        ticket = service.write_ticket(preview)
        payload["ticket"] = {
            "ticket_id": ticket.ticket_id,
            "ticket_type": ticket.ticket_type,
            "status": ticket.status,
        }
        payload["side_effect_status"] = "proposed_ticket_created_no_world_mutation"
        payload["next_action"] = " ".join(
            [
                "wsa",
                "--workspace",
                shlex.quote(str(workspace)),
                "ticket",
                "next",
                "--world",
                shlex.quote(world.display_name),
            ]
        )
    else:
        payload["next_action"] = "review_preview_then_repeat_with_--write-ticket"
    if output_format == "json":
        _print_payload(payload, output_format)
        return 0
    print("액터 변경안 미리보기" if language == "ko" else "actor change preview")
    print(f"world_id: {world.world_id}")
    print(f"actor: {actor_selector}")
    print(f"change_type: {authoring_type}")
    print(f"title: {payload['title']}")
    print(f"change_count: {payload['change_count']}")
    if payload.get("ticket"):
        print(f"ticket_id: {payload['ticket']['ticket_id']}")
        print(f"ticket_status: {payload['ticket']['status']}")
    print(f"side_effect_status: {payload['side_effect_status']}")
    print(f"next_action: {payload['next_action']}")
    return 0


def _assert_actor_record_owner(
    repo: WorldRepository,
    actor_id: str,
    record_type: str,
    record_id: str,
) -> None:
    if record_type == "actor_profile":
        identifiers = {
            item.actor_profile_id for item in repo.list_actor_profiles(actor_id)
        }
    elif record_type == "entity_attribute_span":
        identifiers = {
            item.attribute_span_id
            for item in repo.query_entity_attribute_spans(entity_id=actor_id)
        }
    elif record_type == "knowledge_attribution":
        identifiers = {
            item.knowledge_id
            for item in repo.query_knowledge_attributions(actor_entity_id=actor_id)
        }
    elif record_type == "actor_memory_packet":
        identifiers = {
            item.memory_packet_id
            for item in repo.list_actor_memory_packets(actor_id)
        }
    else:
        raise ValueError(f"unsupported actor record type: {record_type}")
    if record_id not in identifiers:
        raise ValueError(
            f"{record_type} does not belong to the selected actor: {record_id}"
        )


def _resolve_actor_id(repo: WorldRepository, selector: str) -> str:
    try:
        return repo.get_entity(selector).entity_id
    except KeyError:
        pass
    matches = [
        item
        for item in repo.list_entities()
        if item.display_name.casefold() == selector.casefold()
    ]
    if len(matches) == 1:
        return matches[0].entity_id
    if len(matches) > 1:
        raise ValueError(f"actor display name is ambiguous: {selector}; use entity ID")
    raise KeyError(f"actor not found: {selector}")


def run_world_proposal(
    workspace: Path,
    world_id: str,
    proposal_type: str,
    write_ticket: bool,
    output_format: str = "text",
    **kwargs: Any,
) -> int:
    world = get_world(workspace, world_id)
    try:
        preview = _build_preview(world, proposal_type, kwargs)
        payload = preview.to_dict()
        if write_ticket:
            repo = WorldRepository(world.world_id, world.path)
            ticket = write_proposal_ticket(repo, preview)
            payload["ticket"] = {
                "ticket_id": ticket.ticket_id,
                "ticket_type": ticket.ticket_type,
                "status": ticket.status,
            }
            payload["side_effect_status"] = "proposal_ticket_created_no_world_mutation"
            payload["next_action"] = f"wsa ticket review {world_id} {ticket.ticket_id}"
        else:
            payload["next_action"] = "review_preview_then_repeat_with_--write-ticket"
    except ValueError as exc:
        print("world_proposal: blocked")
        print("side_effect_status: no_world_mutation")
        print(f"detail: {exc}")
        return 1
    _print_payload(payload, output_format)
    return 0


def run_world_import_preview(
    workspace: Path,
    world_id: str,
    input_path: Path,
    write_ticket: bool,
    output_format: str = "text",
) -> int:
    world = get_world(workspace, world_id)
    try:
        resolved = input_path.expanduser().resolve()
        if resolved.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("portable import JSON exceeds 4 MiB preview limit")
        value = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("portable import must be a JSON object")
        preview = portable_import_preview(world, value)
        payload = preview.to_dict()
        payload["input_path"] = str(resolved)
        if write_ticket:
            ticket = write_proposal_ticket(
                WorldRepository(world.world_id, world.path),
                preview,
            )
            payload["ticket"] = {
                "ticket_id": ticket.ticket_id,
                "ticket_type": ticket.ticket_type,
                "status": ticket.status,
            }
            payload["side_effect_status"] = "proposal_ticket_created_no_world_mutation"
            payload["next_action"] = f"wsa ticket review {world_id} {ticket.ticket_id}"
        else:
            payload["next_action"] = "review_preview_then_repeat_with_--write-ticket"
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print("world_import_preview: blocked")
        print("side_effect_status: no_world_mutation")
        print(f"detail: {exc}")
        return 1
    _print_payload(payload, output_format)
    return 0


def _build_preview(
    world: Any,
    proposal_type: str,
    values: Dict[str, Any],
) -> ProposalPreview:
    if proposal_type == "startup":
        return startup_proposal_preview(world)
    if proposal_type == "entity":
        return entity_proposal_preview(
            world,
            values["display_name"],
            values["entity_type"],
        )
    if proposal_type == "fact":
        return fact_proposal_preview(
            world,
            values["subject_id"],
            values["predicate"],
            values.get("object_value"),
            values.get("object_ref_id"),
            values.get("time_scope"),
            values.get("location_scope"),
        )
    if proposal_type == "edge":
        return edge_proposal_preview(
            world,
            values["subject_type"],
            values["subject_id"],
            values["edge_type"],
            values["object_type"],
            values.get("object_id"),
            values.get("object_value"),
            values.get("valid_from"),
            values.get("valid_until"),
        )
    raise ValueError(f"unsupported proposal type: {proposal_type}")


def _print_payload(payload: Dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"schema: {payload['schema']}")
    if payload.get("world_id"):
        print(f"world_id: {payload['world_id']}")
    if payload.get("world"):
        world = payload["world"]
        print(f"world_id: {world['world_id']}")
        print(f"display_name: {world['display_name']}")
    if payload.get("counts"):
        for key, value in payload["counts"].items():
            print(f"{key}: {value}")
    if "count" in payload:
        print(f"count: {payload['count']}")
    if payload.get("items") is not None:
        for item in payload["items"]:
            print(json.dumps(item, ensure_ascii=False, sort_keys=True))
    if payload.get("item") is not None:
        print(json.dumps(payload["item"], ensure_ascii=False, sort_keys=True))
    if payload.get("changes") is not None:
        print(f"change_count: {payload['change_count']}")
        for change in payload["changes"]:
            print(json.dumps(change, ensure_ascii=False, sort_keys=True))
    if payload.get("warnings"):
        print("warnings:")
        for warning in payload["warnings"]:
            print(f"\t{warning}")
    if payload.get("ticket"):
        print(f"ticket_id: {payload['ticket']['ticket_id']}")
        print(f"ticket_status: {payload['ticket']['status']}")
    if payload.get("next_action"):
        print(f"next_action: {payload['next_action']}")
    print(f"side_effect_status: {payload['side_effect_status']}")
