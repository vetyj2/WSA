from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.cli import main
from wsa.hermes_commands import (
    HERMES_LOCAL_COMMAND_REGISTRY_FILENAME,
    build_hermes_command_registry,
    merge_hermes_command_registries,
)
from wsa.template import TemplateChecker
from wsa.update import backup_workspace, run_update_preflight, update_preflight_to_dict
from wsa.workspace import create_world


def write_local_registry(
    path: Path,
    command: str = "/local_ping",
    safety: str = "read_only",
    extra: dict | None = None,
) -> None:
    command_payload = {
        "command": command,
        "aliases": [command.replace("_", "-")],
        "title": "Local ping.",
        "intent": "local_ping",
        "category": "local",
        "safety": safety,
        "arguments": [],
        "cli_templates": [],
    }
    if extra:
        command_payload.update(extra)
    path.write_text(
        json.dumps(
            {
                "schema": "wsa.hermes.command_registry.local.v1",
                "schema_version": 1,
                "owner": "user_hermes_runtime",
                "commands": [command_payload],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


class UpdatePreflightTests(TestCase):
    def test_preflight_passes_with_valid_local_overlay_and_warns_for_live_data(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            TemplateChecker(workspace).run(write_missing=True)
            create_world(workspace, "Live Update World")
            local_path = workspace / "hermes" / "adapter_config" / HERMES_LOCAL_COMMAND_REGISTRY_FILENAME
            write_local_registry(local_path)

            report = run_update_preflight(workspace, source_root=Path(tmp))
            payload = update_preflight_to_dict(report)
            checks = {item["name"]: item for item in payload["checks"]}

            self.assertFalse(report.blocked)
            self.assertFalse(payload["blocked"])
            self.assertTrue(payload["warnings"])
            self.assertEqual(checks["local_command_overlay"]["status"], "ok")
            self.assertEqual(checks["backup_required"]["status"], "warn")
            self.assertIn(
                "hermes/adapter_config/hermes_commands.local.json",
                payload["protected_paths"],
            )

    def test_preflight_blocks_pending_runtime_files_and_active_task_state(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            TemplateChecker(workspace).run(write_missing=True)
            (workspace / "hermes" / "task_queue" / "task.json").write_text("{}\n", encoding="utf-8")
            (workspace / "hermes" / "task_state" / "state.json").write_text(
                '{"status": "running"}\n',
                encoding="utf-8",
            )

            report = run_update_preflight(workspace)
            payload = update_preflight_to_dict(report)
            checks = {item["name"]: item for item in payload["checks"]}

            self.assertTrue(report.blocked)
            self.assertEqual(checks["task_queue_empty"]["status"], "block")
            self.assertEqual(checks["task_state_active"]["status"], "block")

    def test_preflight_blocks_local_command_overlay_collision(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            TemplateChecker(workspace).run(write_missing=True)
            local_path = workspace / "hermes" / "adapter_config" / HERMES_LOCAL_COMMAND_REGISTRY_FILENAME
            write_local_registry(local_path, command="/wsa_help")

            report = run_update_preflight(workspace)
            checks = {check.name: check for check in report.checks}

            self.assertTrue(report.blocked)
            self.assertEqual(checks["local_command_overlay"].status, "block")
            self.assertIn("collides with base", checks["local_command_overlay"].detail)

    def test_preflight_blocks_reserved_local_command_namespace(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            TemplateChecker(workspace).run(write_missing=True)
            local_path = workspace / "hermes" / "adapter_config" / HERMES_LOCAL_COMMAND_REGISTRY_FILENAME
            write_local_registry(local_path, command="/wsa_custom")

            report = run_update_preflight(workspace)
            checks = {check.name: check for check in report.checks}

            self.assertTrue(report.blocked)
            self.assertEqual(checks["local_command_overlay"].status, "block")
            self.assertIn("reserved WSA namespace", checks["local_command_overlay"].detail)

    def test_preflight_warns_for_mutating_local_command_without_briefing_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            TemplateChecker(workspace).run(write_missing=True)
            local_path = workspace / "hermes" / "adapter_config" / HERMES_LOCAL_COMMAND_REGISTRY_FILENAME
            write_local_registry(local_path, command="/my_mutation", safety="workspace_mutating")

            report = run_update_preflight(workspace)
            payload = update_preflight_to_dict(report)
            checks = {check.name: check for check in report.checks}

            self.assertFalse(report.blocked)
            self.assertTrue(report.warnings)
            self.assertEqual(checks["local_command_overlay"].status, "warn")
            self.assertIn("mutating_without_confirmation_metadata", checks["local_command_overlay"].detail)
            self.assertIn("local Hermes mutating-command metadata", " ".join(payload["recommended_actions"]))

    def test_command_registry_merge_preserves_non_colliding_local_commands(self) -> None:
        base = build_hermes_command_registry()
        local = {
            "schema": "wsa.hermes.command_registry.local.v1",
            "owner": "user_hermes_runtime",
            "commands": [
                {
                    "command": "/local_ping",
                    "aliases": ["/local-ping"],
                    "title": "Local ping.",
                    "intent": "local_ping",
                    "category": "local",
                    "safety": "read_only",
                    "arguments": [],
                    "cli_templates": [],
                }
            ],
        }

        merged = merge_hermes_command_registries(base, local)
        commands = {item["command"] for item in merged["commands"]}

        self.assertIn("/wsa_help", commands)
        self.assertIn("/local_ping", commands)
        self.assertEqual(merged["local_overlay"]["command_count"], 1)
        self.assertEqual(merged["local_overlay"]["validation"]["status"], "pass")

    def test_update_preflight_cli_returns_nonzero_when_blocked(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            TemplateChecker(workspace).run(write_missing=True)
            (workspace / "hermes" / "callbacks" / "callback.json").write_text(
                "{}\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "update",
                        "preflight",
                        "--source-root",
                        str(Path(tmp)),
                        "--format",
                        "json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 1)
            self.assertEqual(payload["status"], "blocked")
            self.assertTrue(any(item["name"] == "callbacks_empty" for item in payload["checks"]))

    def test_update_backup_copies_workspace_and_sqlite_databases(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            output_dir = Path(tmp) / "backups"
            TemplateChecker(workspace).run(write_missing=True)
            world = create_world(workspace, "Backup World")
            (workspace / "hermes" / "quarantine" / "note.json").write_text(
                '{"status": "kept"}\n',
                encoding="utf-8",
            )

            result = backup_workspace(workspace, output_dir, source_root=Path(tmp))

            self.assertTrue(result.backup_path.is_dir())
            self.assertTrue((result.backup_path / "control.sqlite").exists())
            self.assertTrue((result.backup_path / "worlds" / world.world_id / "world.sqlite").exists())
            self.assertTrue((result.backup_path / "hermes" / "quarantine" / "note.json").exists())
            self.assertTrue(result.metadata_path.exists())

    def test_update_lock_blocks_mutating_cli_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            TemplateChecker(workspace).run(write_missing=True)
            (workspace / "hermes" / "maintenance" / "update.lock").write_text(
                "locked\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "create",
                        "Blocked World",
                    ]
                )

            self.assertEqual(code, 1)
            self.assertIn("update_lock: blocked", stdout.getvalue())

            world = create_world(workspace, "Startup Lock World")
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "startup",
                        "status",
                        world.world_id,
                    ]
                )

            self.assertEqual(code, 1)
            self.assertIn("update_lock: blocked", stdout.getvalue())
