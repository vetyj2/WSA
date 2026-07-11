from __future__ import annotations

import json
import logging
from pathlib import Path

from .application.startup_source_service import StartupSourceService
from .artifact_map import (
    artifact_architecture_map_path,
    write_artifact_architecture_map,
)
from .artifact_diagnostics import diagnose_artifact_source_maps
from .manager import WorldManager
from .migration import (
    MigrationError,
    apply_migrations,
    migration_plan_to_dict,
    migration_result_to_dict,
    plan_migrations,
)
from .startup import (
    StartupProfileManager,
    format_startup_interview,
    format_startup_summary,
    format_startup_status,
    startup_interview_to_dict,
    startup_status_to_dict,
)
from .restore import (
    RestoreError,
    execute_restore_to_new_path,
    plan_restore_to_new_path,
    restore_plan_to_dict,
)
from .update import (
    UpdateLockError,
    assert_update_unlocked,
)
from .workspace import (
    SchemaVersionError,
    WorkspacePathError,
    control_db_path,
    create_world,
    get_world,
    init_workspace,
    list_worlds,
    schema_version,
    sqlite_connection,
    world_db_path,
)


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")


def run_doctor(workspace: Path) -> int:
    print(f"workspace: {workspace}")
    print(f"workspace_exists: {workspace.exists()}")
    db_path = control_db_path(workspace)
    print(f"control_db_exists: {db_path.exists()}")
    print(f"artifact_map_exists: {artifact_architecture_map_path(workspace).exists()}")
    if db_path.exists():
        try:
            with sqlite_connection(db_path, schema_name="control") as conn:
                version = schema_version(conn, "control")
            world_count = 0
            for world in list_worlds(workspace):
                with sqlite_connection(world_db_path(world.path), schema_name="world") as conn:
                    schema_version(conn, "world")
                world_count += 1
        except SchemaVersionError as exc:
            print(f"schema_status: unsupported: {exc}")
            return 1
        except WorkspacePathError as exc:
            print(f"path_status: invalid: {exc}")
            return 1
        migration_plan = plan_migrations(workspace)
        print(f"control_schema_version: {version if version is not None else 'unknown'}")
        print(f"world_count: {world_count}")
        if migration_plan.upgrade_required or migration_plan.blocked:
            migration_status = migration_plan_to_dict(migration_plan)["status"]
            print(f"schema_status: {migration_status}; run wsa migrate --apply")
            return 1
    artifact_diagnostic = diagnose_artifact_source_maps(workspace)
    print(f"artifact_source_map_status: {artifact_diagnostic['status']}")
    print(f"artifact_orphan_exports: {artifact_diagnostic['counts']['orphan_exports']}")
    print("schema_status: ok")
    return 0


def guard_update_unlocked(workspace: Path, operation: str) -> bool:
    try:
        assert_update_unlocked(workspace, operation)
    except UpdateLockError as exc:
        print("update_lock: blocked")
        print(f"operation: {operation}")
        print(f"detail: {exc}")
        return False
    return True


def run_init(workspace: Path) -> int:
    if not guard_update_unlocked(workspace, "init"):
        return 1
    db_path = init_workspace(workspace)
    artifact_map = write_artifact_architecture_map(workspace)
    print(f"workspace_initialized: {workspace}")
    print(f"control_db: {db_path}")
    print(f"artifact_map: {artifact_map}")
    return 0


def run_migrate(workspace: Path, apply: bool, output_format: str) -> int:
    if apply and not guard_update_unlocked(workspace, "migrate"):
        return 1
    try:
        if apply:
            payload = migration_result_to_dict(apply_migrations(workspace))
        else:
            payload = migration_plan_to_dict(plan_migrations(workspace))
    except MigrationError as exc:
        print("migration: blocked")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        print_json(payload)
    else:
        print(f"migration: {payload['status']}")
        print(f"workspace: {workspace}")
        if payload.get("backup_path"):
            print(f"backup_path: {payload['backup_path']}")
        plan = payload.get("plan", payload)
        for step in plan.get("steps", []):
            target = step.get("world_id") or "workspace"
            print(
                f"step: {step['store']}:{target} "
                f"v{step['from_version']}->v{step['to_version']} {step['status']}"
            )
        for item in payload.get("verified", []):
            print(f"verified: {item}")
    return 1 if payload.get("status") == "blocked" else 0


def run_restore(
    workspace: Path,
    backup_root: Path,
    destination: Path,
    *,
    execute: bool,
    output_format: str,
) -> int:
    try:
        plan = plan_restore_to_new_path(workspace, backup_root, destination)
        payload = execute_restore_to_new_path(plan) if execute else restore_plan_to_dict(plan)
    except RestoreError as exc:
        print("restore: blocked")
        print("side_effect_status: no_live_workspace_overwrite")
        print(f"detail: {exc}")
        return 1
    if output_format == "json":
        print_json(payload)
    else:
        print(f"restore: {payload['status']}")
        print(f"destination: {payload['destination']}")
        print(f"overwrite_live_workspace: {str(payload['overwrite_live_workspace']).lower()}")
        for item in payload.get("verified_sources", payload.get("verified", [])):
            print(f"verified: {item}")
        if payload.get("receipt_path"):
            print(f"receipt_path: {payload['receipt_path']}")
        print(f"side_effect_status: {payload['side_effect_status']}")
    return 0


def run_world_create(workspace: Path, name: str) -> int:
    if not guard_update_unlocked(workspace, "world.create"):
        return 1
    record = create_world(workspace, name)
    write_artifact_architecture_map(workspace)
    print(f"world_created: {record.world_id}")
    print(f"display_name: {record.display_name}")
    print(f"path: {record.path}")
    return 0


def run_world_list(workspace: Path) -> int:
    worlds = list_worlds(workspace)
    if not worlds:
        print("worlds: none")
        return 0

    for world in worlds:
        print(
            "\t".join(
                [
                    world.world_id,
                    world.display_name,
                    world.status,
                    str(world.path),
                ]
            )
        )
    return 0


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def run_world_startup_status(
    workspace: Path,
    world_id: str,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.status"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).status(mode=mode)
    if output_format == "json":
        print_json(startup_status_to_dict(status))
        return 0
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_summary(
    workspace: Path,
    world_id: str,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.summary"):
        return 1
    world = get_world(workspace, world_id)
    summary = StartupProfileManager(world).summary(mode=mode)
    if output_format == "json":
        print_json(summary)
        return 0
    for line in format_startup_summary(summary):
        print(line)
    return 0


def run_world_startup_source_followup(
    workspace: Path,
    world_id: str,
    source_paths: list[str],
    *,
    source_type: str = "notes",
    max_questions: int = 5,
    mode: str = "startup",
    output_format: str = "text",
    language: str = "ko",
) -> int:
    world = get_world(workspace, world_id)
    summary = StartupProfileManager(world).summary(mode=mode)
    source_records = []
    for index, source_value in enumerate(source_paths, start=1):
        source_path = Path(source_value).expanduser().resolve()
        try:
            if source_path.stat().st_size > 1024 * 1024:
                raise ValueError(f"startup source exceeds 1 MiB: {source_value}")
            excerpt = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                f"cannot read startup source as UTF-8 text: {source_value}: {exc}"
            ) from exc
        source_records.append(
            {
                "source_id": f"source-file-{index:03d}",
                "world_id": world.world_id,
                "source_type": source_type,
                "source_ref": source_value,
                "excerpt": excerpt,
                "provenance": {"user_supplied": True},
            }
        )
    result = StartupSourceService(max_questions=max_questions).compile(
        summary,
        source_records,
    )
    if output_format == "json":
        print_json(result)
        return 0

    korean = language == "ko"
    print("현재 월드 자료 기반 후속 질문" if korean else "current-world source follow-ups")
    print(f"world_id: {result['world_id']}")
    print(f"mode: {result['mode']}")
    print(f"minimum_frame_ready: {str(result['minimum_frame_ready']).lower()}")
    print(f"accepted_sources: {len(result['sources']['accepted'])}")
    questions = result["follow_up_questions"]
    if not questions:
        print("questions: none")
    for question in questions:
        print(f"{question['question_id']}. {question['question']}")
        print(f"   why_asked: {question['why_asked']}")
        print(f"   source_refs: {', '.join(question['source_refs'])}")
    print(f"side_effect_status: {result['side_effect_status']}")
    return 0


def run_world_startup_interview(
    workspace: Path,
    world_id: str,
    budget: int,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.interview"):
        return 1
    world = get_world(workspace, world_id)
    round_ = StartupProfileManager(world).interview(budget=budget, mode=mode)
    if output_format == "json":
        print_json(startup_interview_to_dict(round_))
        return 0
    for line in format_startup_interview(round_):
        print(line)
    return 0


def run_world_startup_answer(
    workspace: Path,
    world_id: str,
    question_id: str,
    text: str,
    choice: str | None = None,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.answer"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).answer(question_id, text, choice=choice, mode=mode)
    if output_format == "json":
        print_json(
            {
                "startup_answer_recorded": question_id,
                "status": startup_status_to_dict(status),
            }
        )
        return 0
    print(f"startup_answer_recorded: {question_id}")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_batch_answer(
    workspace: Path,
    world_id: str,
    text: str,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.batch_answer"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).answer_batch(text, mode=mode)
    if output_format == "json":
        print_json(
            {
                "startup_batch_answer_recorded": True,
                "status": startup_status_to_dict(status),
            }
        )
        return 0
    print("startup_batch_answer_recorded: yes")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_set_status(
    workspace: Path,
    world_id: str,
    question_id: str,
    status_value: str,
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, "world.startup.set_status"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).set_status(question_id, status_value)
    if output_format == "json":
        print_json(
            {
                "startup_status_updated": question_id,
                "question_status": status_value,
                "status": startup_status_to_dict(status),
            }
        )
        return 0
    print(f"startup_status_updated: {question_id}")
    print(f"question_status: {status_value}")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_world_startup_set_discretion(
    workspace: Path,
    world_id: str,
    level: int,
    mode: str = "startup",
    output_format: str = "text",
) -> int:
    if not guard_update_unlocked(workspace, f"world.{mode}.set_discretion"):
        return 1
    world = get_world(workspace, world_id)
    status = StartupProfileManager(world).set_discretion(level, mode=mode)
    if output_format == "json":
        print_json(
            {
                "startup_discretion_updated": level,
                "status": startup_status_to_dict(status),
            }
        )
        return 0
    print(f"startup_discretion_updated: {level}")
    for line in format_startup_status(status):
        print(line)
    return 0


def run_manager_diagnose(
    workspace: Path,
    fix: bool = False,
    record_findings: bool = False,
    repair_safe_artifacts: bool = False,
    output_format: str = "text",
) -> int:
    if (
        fix or record_findings or repair_safe_artifacts
    ) and not guard_update_unlocked(workspace, "manager.diagnose.write"):
        return 1
    findings = WorldManager(workspace).run_diagnostics(
        fix=fix,
        record_findings=record_findings,
        repair_safe_artifacts=repair_safe_artifacts,
    )
    if output_format == "json":
        print_json(
            {
                "schema": "wsa.manager.diagnostics.v1",
                "finding_count": len(findings),
                "side_effects": {
                    "record_findings": bool(fix or record_findings),
                    "repair_safe_artifacts": bool(fix or repair_safe_artifacts),
                    "canon_mutation": False,
                },
                "findings": [finding.to_dict() for finding in findings],
            }
        )
        return 0
    if not findings:
        print("diagnostics: clean")
        return 0
    for finding in findings:
        print(
            "\t".join(
                [
                    finding.world_id,
                    finding.severity,
                    finding.finding_type,
                    finding.path or "",
                    finding.detail,
                ]
            )
        )
    return 0
