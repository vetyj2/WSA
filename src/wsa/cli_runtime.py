from __future__ import annotations

import json
from pathlib import Path

from .hermes_adapter import (
    HermesCliTemplateAdapter,
    build_delivery_contract,
    build_runtime_target,
    build_sensitivity_contract,
)
from .hermes_commands import (
    HERMES_COMMAND_REGISTRY_FILENAME,
    HERMES_LOCAL_COMMAND_REGISTRY_FILENAME,
    build_hermes_command_registry,
    empty_local_command_overlay_report,
    format_local_command_overlay_report,
    format_hermes_commands,
    merge_hermes_command_registries,
    validate_local_command_registry_report,
    write_hermes_command_registry,
    write_hermes_local_command_registry_template,
)
from .hermes_doctor import HermesDoctor, format_hermes_doctor
from .report_exports import (
    build_report_export,
    format_report_export_result,
    write_report_export,
)
from .template import TemplateChecker, format_template_readiness
from .update import (
    UpdateBackupError,
    backup_result_to_dict,
    backup_workspace,
    format_backup_result,
    format_update_preflight,
    run_update_preflight,
    update_preflight_to_dict,
)
from .workspace import (
    get_world,
)


from .cli_core import guard_update_unlocked

def run_report_export(
    workspace: Path,
    world_id: str,
    run_id: str,
    artifact_type: str,
    export_format: str,
    write: bool,
) -> int:
    if write and not guard_update_unlocked(workspace, "report.export.write"):
        return 1
    world = get_world(workspace, world_id)
    try:
        payload = (
            write_report_export(world, run_id, artifact_type, export_format)
            if write
            else build_report_export(world, run_id, artifact_type, export_format)
        )
    except (FileNotFoundError, ValueError) as exc:
        print("report_export: blocked")
        print(f"detail: {exc}")
        return 1
    if write:
        for line in format_report_export_result(payload):
            print(line)
    else:
        print(payload["content"], end="")
    return 0
def run_hermes_init_example(
    workspace: Path,
    adapter_name: str,
    command: str,
    overwrite: bool,
) -> int:
    if not guard_update_unlocked(workspace, "hermes.init_example"):
        return 1
    adapter = HermesCliTemplateAdapter(workspace, adapter_name=adapter_name, command=command)
    path = adapter.write_example_config(overwrite=overwrite)
    registry_path = write_hermes_command_registry(
        adapter.adapter_config_dir() / HERMES_COMMAND_REGISTRY_FILENAME,
        overwrite=overwrite,
    )
    print(f"example_config: {path}")
    print(f"command_registry: {registry_path}")
    return 0

def run_hermes_commands(
    workspace: Path,
    output_format: str,
    write_example: bool,
    write_local_template: bool,
    validate_local_overlay: bool,
    merged: bool,
    local_overlay_path: str | None,
    output_path: str | None,
    overwrite: bool,
    compact: bool = False,
) -> int:
    registry = build_hermes_command_registry(compact=compact)
    local_path = (
        Path(local_overlay_path).expanduser()
        if local_overlay_path
        else HermesCliTemplateAdapter(workspace).adapter_config_dir() / HERMES_LOCAL_COMMAND_REGISTRY_FILENAME
    )

    if write_local_template:
        if not guard_update_unlocked(workspace, "hermes.commands.write"):
            return 1
        path = Path(output_path).expanduser() if output_path else local_path
        written = write_hermes_local_command_registry_template(path, overwrite=overwrite)
        print(f"local_command_overlay_template: {written}")
        return 0

    if write_example or (output_path and not validate_local_overlay and not merged):
        if not guard_update_unlocked(workspace, "hermes.commands.write"):
            return 1
        if output_path:
            path = Path(output_path).expanduser()
        else:
            adapter = HermesCliTemplateAdapter(workspace)
            adapter.ensure_layout()
            path = adapter.adapter_config_dir() / HERMES_COMMAND_REGISTRY_FILENAME
        written = write_hermes_command_registry(
            path,
            overwrite=overwrite,
            compact=compact or write_example,
        )
        print(f"command_registry: {written}")
        return 0

    local_registry = None
    if local_path.exists():
        try:
            local_registry = json.loads(local_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report = {
                "schema": "wsa.hermes.command_overlay_report.v1",
                "status": "blocked",
                "blocked": True,
                "warnings": False,
                "path": str(local_path),
                "command_count": 0,
                "finding_counts": {"block": 1, "warn": 0, "info": 0},
                "findings": [
                    {
                        "severity": "block",
                        "code": "invalid_json",
                        "message": f"invalid local overlay JSON: {exc}",
                        "recommendation": "Fix the JSON before update or live command execution.",
                    }
                ],
                "recommended_actions": ["repair local command overlay JSON"],
            }
            if output_format == "json":
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                for line in format_local_command_overlay_report(report):
                    print(line)
            return 1

    if validate_local_overlay:
        report = (
            validate_local_command_registry_report(local_registry, registry, local_path)
            if local_registry is not None
            else empty_local_command_overlay_report(local_path)
        )
        if output_format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            for line in format_local_command_overlay_report(report):
                print(line)
        return 1 if report["blocked"] else 0

    if merged:
        if local_registry is not None:
            report = validate_local_command_registry_report(local_registry, registry, local_path)
            if report["blocked"]:
                if output_format == "json":
                    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                else:
                    for line in format_local_command_overlay_report(report):
                        print(line)
                return 1
            registry = merge_hermes_command_registries(registry, local_registry)
        if output_path:
            if not guard_update_unlocked(workspace, "hermes.commands.write"):
                return 1
            path = Path(output_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not overwrite:
                print(f"command_registry: {path}")
                return 0
            path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"command_registry: {path}")
            return 0
        if output_format == "json":
            print(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            for line in format_hermes_commands(registry):
                print(line)
        return 0

    if output_format == "json":
        print(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    for line in format_hermes_commands(registry):
        print(line)
    return 0


def run_hermes_doctor(
    workspace: Path,
    command: str,
    config_path: str | None,
    operation_policy_path: str | None,
    source_root: str | None,
) -> int:
    report = HermesDoctor(
        workspace,
        command=command,
        config_path=Path(config_path).expanduser() if config_path else None,
        operation_policy_path=(
            Path(operation_policy_path).expanduser() if operation_policy_path else None
        ),
        source_root=Path(source_root).expanduser() if source_root else None,
    ).run()
    for line in format_hermes_doctor(report):
        print(line)
    return 0 if report.ok else 1


def run_hermes_task_create(
    workspace: Path,
    world_id: str,
    title: str,
    instruction: str,
    task_type: str,
    role: str,
    session_id: str | None,
    adapter_name: str,
    command: str,
    input_json: str | None,
    runtime_profile: str,
    runtime_source: str,
    session_mode: str,
    runtime_workdir: str,
    interactive: bool,
    background: bool,
    toolsets: list[str],
    skills: list[str],
    delivery_target: str,
    safe_for_chat: bool,
    sensitivity_level: str,
) -> int:
    if not guard_update_unlocked(workspace, "hermes.task"):
        return 1
    payload = {}
    if input_json:
        parsed = json.loads(input_json)
        if not isinstance(parsed, dict):
            raise ValueError("--input-json must be a JSON object")
        payload = parsed

    adapter = HermesCliTemplateAdapter(workspace, adapter_name=adapter_name, command=command)
    runtime_target = build_runtime_target(
        profile=runtime_profile,
        source=runtime_source,
        session_mode=session_mode,
        workdir=runtime_workdir,
        interactive=interactive,
        background=background,
        toolsets=toolsets,
        skills=skills,
    )
    delivery = build_delivery_contract(
        target=delivery_target,
        safe_for_chat=safe_for_chat,
    )
    sensitivity = build_sensitivity_contract(level=sensitivity_level)
    task = adapter.create_task(
        world_id=world_id,
        title=title,
        instruction=instruction,
        task_type=task_type,
        role=role,
        session_id=session_id,
        payload=payload,
        runtime_target=runtime_target,
        delivery=delivery,
        sensitivity=sensitivity,
    )
    print(f"hermes_task_created: {task.task_id}")
    print(f"task_path: {task.task_ref}")
    print(f"session_id: {task.session_id}")
    print(f"world_id: {task.world_id}")
    print(f"command_preview: {command} run-task {task.task_ref}")
    return 0


def run_hermes_collect_callback(
    workspace: Path,
    callback_path: str,
    adapter_name: str,
    command: str,
    allow_external_callback: bool,
) -> int:
    if not guard_update_unlocked(workspace, "hermes.collect_callback"):
        return 1
    adapter = HermesCliTemplateAdapter(workspace, adapter_name=adapter_name, command=command)
    callback = adapter.collect_callback(
        Path(callback_path),
        allow_external_path=allow_external_callback,
    )
    print(f"hermes_callback_collected: {callback.callback_id}")
    print(f"task_id: {callback.task_id}")
    print(f"session_id: {callback.session_id}")
    print(f"world_id: {callback.world_id}")
    print(f"message_id: {callback.runtime_envelope.message_id}")
    if callback.report_id:
        print(f"report_id: {callback.report_id}")
    return 0


def run_template_check(workspace: Path, write_missing: bool) -> int:
    if write_missing and not guard_update_unlocked(workspace, "template.check.write_missing"):
        return 1
    readiness = TemplateChecker(workspace).run(write_missing=write_missing)
    for line in format_template_readiness(readiness):
        print(line)
    return 0 if readiness.ok else 1


def run_update_preflight_cli(
    workspace: Path,
    source_root: str | None,
    output_format: str,
) -> int:
    report = run_update_preflight(
        workspace,
        source_root=Path(source_root).expanduser().resolve() if source_root else None,
    )
    if output_format == "json":
        print(json.dumps(update_preflight_to_dict(report), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_update_preflight(report):
            print(line)
    return 1 if report.blocked else 0


def run_update_backup_cli(
    workspace: Path,
    output_dir: str,
    source_root: str | None,
    output_format: str,
) -> int:
    try:
        result = backup_workspace(
            workspace,
            Path(output_dir),
            source_root=Path(source_root).expanduser().resolve() if source_root else None,
        )
    except UpdateBackupError as exc:
        print("update_backup: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        print(json.dumps(backup_result_to_dict(result), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in format_backup_result(result):
            print(line)
    return 0
