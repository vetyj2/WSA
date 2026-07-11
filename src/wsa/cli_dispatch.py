from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .cli_artifacts import (
    run_artifact_diagnose,
    run_artifact_maintenance_scan,
    run_artifact_map,
    run_artifact_route,
    run_artifact_uninstall_discover,
    run_artifact_uninstall_plan,
)
from .cli_reports import (
    run_report_decide,
    run_report_inbox,
    run_report_archive_callbacks,
    run_report_list,
    run_report_show,
    run_report_reject_pending,
    run_report_triage,
)
from .cli_dispatch_tickets import dispatch_ticket_command
from .cli_runtime_loop import run_orchestrator_runtime_dispatch
from .cli_world import (
    run_world_actor_authoring,
    run_world_actor_show,
    run_world_continue,
    run_world_fork_plan,
    run_world_home,
    run_world_import_preview,
    run_world_inspection,
    run_world_proposal,
    run_world_selective_export,
)
from .config import load_config


from .cli_parser import build_parser
from .cli_core import (
    configure_logging,
    run_doctor,
    guard_update_unlocked,
    run_init,
    run_migrate,
    run_restore,
    run_world_create,
    run_world_list,
    run_world_startup_status,
    run_world_startup_summary,
    run_world_startup_source_followup,
    run_world_startup_interview,
    run_world_startup_answer,
    run_world_startup_batch_answer,
    run_world_startup_set_status,
    run_world_startup_set_discretion,
    run_manager_diagnose,
)
from .cli_orchestration import (
    run_scene_mock,
    run_scene_start,
    run_meeting,
    run_meeting_decide,
    run_orchestrator,
    run_orchestrator_status,
    run_orchestrator_report,
    run_orchestrator_hooks,
    run_orchestrator_next,
    run_orchestrator_prep_approve,
    run_orchestrator_submit,
    run_orchestrator_decide,
    run_orchestrator_close,
    run_orchestrator_interrupt,
    run_orchestrator_resume,
    run_orchestrator_repair_projection,
)
from .cli_runtime import (
    run_report_export,
    run_hermes_init_example,
    run_hermes_commands,
    run_hermes_doctor,
    run_hermes_task_create,
    run_hermes_collect_callback,
    run_template_check,
    run_update_preflight_cli,
    run_update_backup_cli,
)

def _dispatch(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    config = load_config(args.workspace)

    if args.command == "doctor":
        return run_doctor(config.workspace)
    if args.command == "init":
        return run_init(config.workspace)
    if args.command == "migrate":
        if args.migrate_command in {"restore-plan", "restore"}:
            return run_restore(
                config.workspace,
                Path(args.backup_root),
                Path(args.destination),
                execute=args.migrate_command == "restore",
                output_format=args.format,
            )
        return run_migrate(config.workspace, args.apply, args.format)
    if args.command == "world":
        if args.world_command == "create":
            return run_world_create(config.workspace, args.name)
        if args.world_command == "list":
            return run_world_list(config.workspace)
        if args.world_command == "home":
            return run_world_home(
                config.workspace,
                args.world_selector,
                output_format=args.format,
                language=args.lang,
            )
        if args.world_command == "continue":
            return run_world_continue(
                config.workspace,
                args.world_selector,
                output_format=args.format,
                language=args.lang,
            )
        if args.world_command == "show":
            return run_world_inspection(
                config.workspace,
                args.world_id,
                "summary",
                output_format=args.format,
            )
        if args.world_command == "entity":
            if args.world_entity_command == "list":
                return run_world_inspection(
                    config.workspace,
                    args.world_id,
                    "entities",
                    entity_type=args.entity_type,
                    status=args.status,
                    output_format=args.format,
                )
            if args.world_entity_command == "show":
                return run_world_inspection(
                    config.workspace,
                    args.world_id,
                    "entities",
                    item_id=args.entity_id,
                    output_format=args.format,
                )
            parser.parse_args(["world", "entity", "--help"])
        if args.world_command == "fact":
            if args.world_fact_command == "list":
                return run_world_inspection(
                    config.workspace,
                    args.world_id,
                    "facts",
                    subject_id=args.subject_id,
                    output_format=args.format,
                )
            if args.world_fact_command == "show":
                return run_world_inspection(
                    config.workspace,
                    args.world_id,
                    "facts",
                    item_id=args.fact_id,
                    output_format=args.format,
                )
            parser.parse_args(["world", "fact", "--help"])
        if args.world_command == "edge":
            if args.world_edge_command == "list":
                return run_world_inspection(
                    config.workspace,
                    args.world_id,
                    "edges",
                    subject_id=args.subject_id,
                    edge_type=args.edge_type,
                    status=args.status,
                    output_format=args.format,
                )
            parser.parse_args(["world", "edge", "--help"])
        if args.world_command == "timeline":
            if args.world_timeline_command == "list":
                return run_world_inspection(
                    config.workspace,
                    args.world_id,
                    "timeline",
                    output_format=args.format,
                )
            parser.parse_args(["world", "timeline", "--help"])
        if args.world_command == "actor":
            if args.world_actor_command == "show":
                return run_world_actor_show(
                    config.workspace,
                    args.world_id,
                    args.actor,
                    args.format,
                    language=args.lang,
                )
            if args.world_actor_command in {
                "profile",
                "attribute",
                "knowledge",
                "memory",
                "revise",
            }:
                if args.write_ticket and not guard_update_unlocked(
                    config.workspace,
                    f"world.actor.{args.world_actor_command}",
                ):
                    return 1
                actor_keys = {
                    "fragment",
                    "text",
                    "valid_from",
                    "valid_until",
                    "dimension",
                    "value_text",
                    "value_number",
                    "value_ref_id",
                    "target_type",
                    "target_id",
                    "state",
                    "acquired_at",
                    "time_scope",
                    "replace_record",
                    "replace_at",
                    "record_type",
                    "record_id",
                    "status",
                    "clear_valid_until",
                }
                values = {
                    key: value
                    for key, value in vars(args).items()
                    if key in actor_keys
                }
                return run_world_actor_authoring(
                    config.workspace,
                    args.world_id,
                    args.actor,
                    args.world_actor_command,
                    title=args.title,
                    source_ref=args.source_ref,
                    write_ticket=args.write_ticket,
                    output_format=args.format,
                    language=args.lang,
                    **values,
                )
            parser.parse_args(["world", "actor", "--help"])
        if args.world_command == "export":
            if args.entity:
                return run_world_selective_export(
                    config.workspace,
                    args.world_id,
                    args.entity,
                    include_timeline=args.include_timeline,
                    output_format=args.format,
                )
            return run_world_inspection(
                config.workspace,
                args.world_id,
                "export",
                output_format=args.format,
            )
        if args.world_command == "fork-plan":
            return run_world_fork_plan(
                config.workspace,
                args.world_id,
                args.name,
                args.entity,
                include_timeline=args.include_timeline,
                output_format=args.format,
            )
        if args.world_command == "import-preview":
            if args.write_ticket and not guard_update_unlocked(
                config.workspace,
                "world.import_preview",
            ):
                return 1
            return run_world_import_preview(
                config.workspace,
                args.world_id,
                Path(args.input_path),
                args.write_ticket,
                output_format=args.format,
            )
        if args.world_command == "proposal":
            if args.write_ticket and not guard_update_unlocked(
                config.workspace,
                f"world.proposal.{args.world_proposal_command}",
            ):
                return 1
            proposal_keys = {
                "display_name",
                "entity_type",
                "subject_type",
                "subject_id",
                "predicate",
                "object_value",
                "object_ref_id",
                "edge_type",
                "object_type",
                "object_id",
                "valid_from",
                "valid_until",
                "time_scope",
                "location_scope",
            }
            values = {
                key: value
                for key, value in vars(args).items()
                if key in proposal_keys
            }
            return run_world_proposal(
                config.workspace,
                args.world_id,
                args.world_proposal_command,
                args.write_ticket,
                output_format=args.format,
                **values,
            )
        if args.world_command == "startup":
            if args.world_startup_command == "status":
                return run_world_startup_status(
                    config.workspace,
                    args.world_id,
                    mode="startup",
                    output_format=args.format,
                )
            if args.world_startup_command == "summary":
                return run_world_startup_summary(
                    config.workspace,
                    args.world_id,
                    mode="startup",
                    output_format=args.format,
                )
            if args.world_startup_command == "source-followup":
                return run_world_startup_source_followup(
                    config.workspace,
                    args.world_id,
                    args.source,
                    source_type=args.source_type,
                    max_questions=args.max_questions,
                    mode="startup",
                    output_format=args.format,
                    language=args.lang,
                )
            if args.world_startup_command == "interview":
                return run_world_startup_interview(
                    config.workspace,
                    args.world_id,
                    args.budget,
                    mode="startup",
                    output_format=args.format,
                )
            if args.world_startup_command == "answer":
                return run_world_startup_answer(
                    config.workspace,
                    args.world_id,
                    args.question_id,
                    args.text,
                    choice=args.choice,
                    mode="startup",
                    output_format=args.format,
                )
            if args.world_startup_command == "batch-answer":
                return run_world_startup_batch_answer(
                    config.workspace,
                    args.world_id,
                    args.text,
                    mode="startup",
                    output_format=args.format,
                )
            if args.world_startup_command == "set-status":
                return run_world_startup_set_status(
                    config.workspace,
                    args.world_id,
                    args.question_id,
                    args.status,
                    output_format=args.format,
                )
            if args.world_startup_command == "set-discretion":
                return run_world_startup_set_discretion(
                    config.workspace,
                    args.world_id,
                    args.level,
                    mode="startup",
                    output_format=args.format,
                )
            parser.parse_args(["world", "startup", "--help"])
        if args.world_command == "easystartup":
            if args.world_easystartup_command == "status":
                return run_world_startup_status(
                    config.workspace,
                    args.world_id,
                    mode="easystartup",
                    output_format=args.format,
                )
            if args.world_easystartup_command == "summary":
                return run_world_startup_summary(
                    config.workspace,
                    args.world_id,
                    mode="easystartup",
                    output_format=args.format,
                )
            if args.world_easystartup_command == "interview":
                return run_world_startup_interview(
                    config.workspace,
                    args.world_id,
                    args.budget,
                    mode="easystartup",
                    output_format=args.format,
                )
            if args.world_easystartup_command == "answer":
                return run_world_startup_answer(
                    config.workspace,
                    args.world_id,
                    args.question_id,
                    args.text,
                    choice=args.choice,
                    mode="easystartup",
                    output_format=args.format,
                )
            if args.world_easystartup_command == "batch-answer":
                return run_world_startup_batch_answer(
                    config.workspace,
                    args.world_id,
                    args.text,
                    mode="easystartup",
                    output_format=args.format,
                )
            if args.world_easystartup_command == "set-discretion":
                return run_world_startup_set_discretion(
                    config.workspace,
                    args.world_id,
                    args.level,
                    mode="easystartup",
                    output_format=args.format,
                )
            parser.parse_args(["world", "easystartup", "--help"])
        parser.parse_args(["world", "--help"])
    if args.command == "manager":
        if args.manager_command == "diagnose":
            return run_manager_diagnose(
                config.workspace,
                args.fix,
                args.record_findings,
                args.repair_safe_artifacts,
                args.format,
            )
        parser.parse_args(["manager", "--help"])
    if args.command == "meeting":
        if args.meeting_command == "run":
            return run_meeting(
                config.workspace,
                args.world_id,
                args.topic,
                args.question,
                args.participant,
            )
        if args.meeting_command == "decide":
            return run_meeting_decide(
                config.workspace,
                args.world_id,
                args.report_id,
                args.decision,
                args.note,
            )
        parser.parse_args(["meeting", "--help"])
    if args.command == "orchestrator":
        if args.orchestrator_command == "run":
            return run_orchestrator(
                config.workspace,
                args.world_id,
                args.workflow,
                args.skill,
                args.topic,
                args.question,
                args.mode,
                args.rounds,
                args.max_queue_turns,
                args.max_concurrent_subsessions,
                args.max_subsession_calls,
                args.context_policy,
                args.frame_plan,
                args.termination_policy,
                args.participant,
                args.subsession_policy,
                args.canon_policy,
                args.approval,
                args.close_on,
                not args.no_prep_review,
            )
        if args.orchestrator_command == "status":
            return run_orchestrator_status(
                config.workspace,
                args.run_id,
                args.format,
                args.expand_contracts,
            )
        if args.orchestrator_command == "report":
            return run_orchestrator_report(
                config.workspace,
                args.run_id,
                args.format,
                args.expand_contracts,
            )
        if args.orchestrator_command == "hooks":
            return run_orchestrator_hooks(config.workspace, args.run_id, args.format)
        if args.orchestrator_command == "next":
            return run_orchestrator_next(config.workspace, args.run_id, args.format)
        if args.orchestrator_command == "prep-approve":
            return run_orchestrator_prep_approve(config.workspace, args.run_id, args.format)
        if args.orchestrator_command == "submit":
            return run_orchestrator_submit(
                config.workspace,
                args.run_id,
                args.callback,
                args.format,
            )
        if args.orchestrator_command == "decide":
            return run_orchestrator_decide(
                config.workspace,
                args.run_id,
                args.decision,
                args.option,
                args.note,
            )
        if args.orchestrator_command == "close":
            return run_orchestrator_close(config.workspace, args.run_id, args.reason)
        if args.orchestrator_command == "interrupt":
            return run_orchestrator_interrupt(config.workspace, args.run_id, args.reason)
        if args.orchestrator_command == "resume":
            return run_orchestrator_resume(config.workspace, args.run_id, args.format)
        if args.orchestrator_command == "repair-projection":
            return run_orchestrator_repair_projection(config.workspace, args.run_id)
        if args.orchestrator_command in {"dispatch-plan", "dispatch"}:
            return run_orchestrator_runtime_dispatch(
                config.workspace,
                args.run_id,
                args.runtime_argv,
                workdir=args.workdir,
                timeout_seconds=args.timeout,
                execute=args.orchestrator_command == "dispatch",
                confirmed=getattr(args, "confirm", False),
                output_format=args.format,
                language=args.lang,
            )
        parser.parse_args(["orchestrator", "--help"])
    if args.command == "scene":
        if args.scene_command in {"start", "prep"}:
            return run_scene_start(
                config.workspace,
                args.world_id,
                args.topic,
                args.question,
                args.rounds,
                args.max_queue_turns,
                args.max_concurrent_subsessions,
                args.max_subsession_calls,
                args.context_policy,
                args.frame_plan,
                args.termination_policy,
                args.time_scope,
                args.location_scope,
                args.viewpoint,
                args.condition,
                args.participant,
                args.format,
                not args.no_prep_review,
                args.generation_mode,
            )
        if args.scene_command == "mock":
            return run_scene_mock(
                config.workspace,
                args.world_id,
                args.name,
                args.goal,
                args.actor,
            )
        parser.parse_args(["scene", "--help"])
    if args.command == "report":
        if args.report_command == "list":
            return run_report_list(config.workspace, args.world_id, args.status)
        if args.report_command == "inbox":
            return run_report_inbox(
                config.workspace,
                args.world_id,
                args.format,
                language=args.lang,
            )
        if args.report_command == "show":
            return run_report_show(
                config.workspace,
                args.world_id,
                args.item_id,
                args.format,
            )
        if args.report_command == "decide":
            return run_report_decide(
                config.workspace,
                args.world_id,
                args.item_id,
                args.decision,
                args.option,
                args.note,
                args.format,
            )
        if args.report_command == "triage":
            return run_report_triage(config.workspace, args.world_id, args.format)
        if args.report_command == "reject-pending":
            return run_report_reject_pending(
                config.workspace,
                args.world_id,
                args.reason,
                args.archive_callbacks,
                args.format,
            )
        if args.report_command == "archive-callbacks":
            return run_report_archive_callbacks(
                config.workspace,
                args.world_id,
                args.reason,
                args.format,
            )
        if args.report_command == "export":
            return run_report_export(
                config.workspace,
                args.world_id,
                args.run_id,
                args.artifact_type,
                args.format,
                args.write,
            )
        parser.parse_args(["report", "--help"])
    if args.command == "ticket":
        return dispatch_ticket_command(
            args,
            config.workspace,
            args.lang,
            parser,
        )
    if args.command == "artifact":
        if args.artifact_command == "map":
            return run_artifact_map(config.workspace, args.write, args.format)
        if args.artifact_command == "diagnose":
            return run_artifact_diagnose(config.workspace, args.format)
        if args.artifact_command == "route":
            return run_artifact_route(
                config.workspace,
                args.artifact_type,
                args.world_id,
                args.session_id,
                args.run_id,
                args.filename,
                args.date,
                args.external_path,
                args.format,
            )
        if args.artifact_command == "uninstall-plan":
            return run_artifact_uninstall_plan(config.workspace, args.write, args.format)
        if args.artifact_command == "uninstall-discover":
            return run_artifact_uninstall_discover(
                config.workspace,
                args.scan_root,
                args.exclude_root,
                args.max_depth,
                args.max_candidates,
                args.write,
                args.format,
            )
        if args.artifact_command == "maintenance-scan":
            return run_artifact_maintenance_scan(
                config.workspace,
                args.write,
                args.format,
                args.top,
            )
        parser.parse_args(["artifact", "--help"])
    if args.command == "hermes":
        if args.hermes_command == "init-example":
            return run_hermes_init_example(
                config.workspace,
                args.adapter_name,
                args.adapter_command,
                args.overwrite,
            )
        if args.hermes_command == "commands":
            return run_hermes_commands(
                config.workspace,
                args.format,
                args.write_example,
                args.write_local_template,
                args.validate_local_overlay,
                args.merged,
                args.local_overlay,
                args.output,
                args.overwrite,
                args.compact,
            )
        if args.hermes_command == "doctor":
            return run_hermes_doctor(
                config.workspace,
                args.adapter_command,
                args.config,
                args.operation_policy,
                args.source_root,
            )
        if args.hermes_command == "task":
            return run_hermes_task_create(
                config.workspace,
                args.world_id,
                args.title,
                args.instruction,
                args.task_type,
                args.role,
                args.session_id,
                args.adapter_name,
                args.adapter_command,
                args.input_json,
                args.runtime_profile,
                args.runtime_source,
                args.session_mode,
                args.runtime_workdir,
                args.interactive,
                args.background,
                args.toolset,
                args.skill,
                args.delivery_target,
                args.safe_for_chat,
                args.sensitivity,
            )
        if args.hermes_command == "collect-callback":
            return run_hermes_collect_callback(
                config.workspace,
                args.callback_path,
                args.adapter_name,
                args.adapter_command,
                args.allow_external_callback,
            )
        parser.parse_args(["hermes", "--help"])
    if args.command == "template":
        if args.template_command == "check":
            return run_template_check(config.workspace, args.write_missing)
        parser.parse_args(["template", "--help"])
    if args.command == "update":
        if args.update_command == "preflight":
            return run_update_preflight_cli(
                config.workspace,
                args.source_root,
                args.format,
            )
        if args.update_command == "backup":
            return run_update_backup_cli(
                config.workspace,
                args.output_dir,
                args.source_root,
                args.format,
            )
        parser.parse_args(["update", "--help"])

    parser.print_help()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _dispatch(argv)
    except (KeyError, ValueError, FileNotFoundError, PermissionError) as exc:
        print("command: blocked")
        print("side_effect_status: no_additional_mutation")
        print(f"detail: {exc}")
        print("recovery: inspect the referenced world/run/item and retry the explicit command")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
