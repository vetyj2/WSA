import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.hermes_adapter import (
    HermesAdapterError,
    HermesAdapterRouteError,
    HermesCliTemplateAdapter,
    build_template_callback,
)
from wsa.hermes_commands import build_hermes_command_registry
from wsa.repositories import WorldRepository
from wsa.transport import RuntimeTransport
from wsa.workspace import create_world


class HermesAdapterTests(TestCase):
    def test_public_command_registry_example_matches_generator(self) -> None:
        example = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "hermes_command_registry.example.json"
        )
        generated = (
            json.dumps(
                build_hermes_command_registry(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

        self.assertEqual(example.read_text(encoding="utf-8"), generated)

    def test_example_config_is_written_without_secret_values(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            adapter = HermesCliTemplateAdapter(workspace)

            path = adapter.write_example_config()
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(payload["adapter"], "cli")
            self.assertEqual(payload["secret_env"], ["HERMES_BOT_TOKEN", "OPENAI_API_KEY"])
            self.assertEqual(payload["workspace"]["path_policy"], "relative_to_workspace_root")
            self.assertEqual(
                payload["command_registry"],
                "hermes/adapter_config/hermes_commands.example.json",
            )
            self.assertFalse(payload["agent_harness"]["world_state_policy"]["direct_db_writes"])
            self.assertEqual(payload["runtime_target"]["profile"], "default")
            self.assertEqual(payload["delivery"]["target"], "origin")
            self.assertEqual(payload["sensitivity"]["level"], "internal")
            self.assertIn("hermes/quarantine", payload["agent_harness"]["write_roots"])
            self.assertTrue(
                payload["agent_harness"]["autonomy_policy"][
                    "fully_autonomous_generation_allowed"
                ]
            )
            self.assertTrue(
                payload["agent_harness"]["autonomy_policy"]["checkpoint_policy"][
                    "natural_language_allowed"
                ]
            )
            self.assertTrue(payload["agent_harness"]["autonomy_policy"]["discretion_customizable"])
            self.assertTrue(
                payload["agent_harness"]["autonomy_policy"]["discretion_scale"]["5"][
                    "cron_allowed"
                ]
            )
            self.assertTrue(
                payload["agent_harness"]["autonomy_policy"]["fill_the_rest"][
                    "completion_must_state_cron_stopped"
                ]
            )
            self.assertEqual(
                payload["operation_contract"]["actions"][0]["modes"],
                ["none", "local_commit", "remote_push", "custom"],
            )
            self.assertNotIn("token_value", path.read_text(encoding="utf-8"))

    def test_cli_template_task_writes_queue_packet_and_runtime_inbox(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Hermes Task World")
            adapter = HermesCliTemplateAdapter(workspace)

            task = adapter.create_task(
                world.world_id,
                title="Run diagnostics",
                instruction="Inspect pending reports and tickets.",
            )
            task_payload = json.loads(task.task_path.read_text(encoding="utf-8"))
            state_path = adapter.task_state_dir() / f"{task.task_id}.json"
            task_state = json.loads(state_path.read_text(encoding="utf-8"))
            inbox = RuntimeTransport(workspace).list_envelopes(task.session_id, "inbox")

            self.assertEqual(task_payload["schema"], "wsa.hermes.task.v1")
            self.assertEqual(task_state["status"], "queued")
            self.assertEqual(task_payload["route"]["world_id"], world.world_id)
            self.assertEqual(task_payload["adapter"]["command_preview"][0], "wsa-hermes-cli")
            self.assertEqual(task_payload["adapter"]["command_preview"][2], task.task_ref)
            self.assertFalse(task_payload["adapter"]["command_preview"][2].startswith("/"))
            self.assertEqual(task_payload["workspace"]["path_policy"], "relative_to_workspace_root")
            self.assertEqual(task_payload["runtime_target"]["session_mode"], "callback_only")
            self.assertEqual(task_payload["delivery"]["target"], "origin")
            self.assertEqual(task_payload["sensitivity"]["level"], "internal")
            self.assertEqual(
                task_payload["runtime_target"]["callback_policy"]["quarantine_dir"],
                "hermes/quarantine",
            )
            self.assertFalse(
                task_payload["agent_harness"]["world_state_policy"]["direct_world_file_mutation"]
            )
            self.assertEqual(
                task_payload["agent_harness"]["autonomy_policy"]["owner"],
                "user_hermes_runtime_dialogue",
            )
            self.assertEqual(
                task_payload["operation_contract"]["actions"][0]["action"],
                "version_control.snapshot",
            )
            self.assertEqual([item.message_type for item in inbox], ["intent_request"])

    def test_template_callback_uses_task_workspace_id(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Hermes Workspace World")
            adapter = HermesCliTemplateAdapter(workspace, workspace_id="customer-runtime")
            task = adapter.create_task(
                world.world_id,
                title="Run diagnostics",
                instruction="Inspect pending reports and tickets.",
            )

            callback_payload = build_template_callback(task)
            callback_path = adapter.callbacks_dir() / f"{callback_payload['callback_id']}.json"
            callback_path.write_text(
                json.dumps(callback_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            callback = adapter.collect_callback(callback_path)

            self.assertEqual(callback.world_id, world.world_id)

    def test_callback_collection_validates_route_and_creates_report(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Hermes Callback World")
            adapter = HermesCliTemplateAdapter(workspace)
            task = adapter.create_task(
                world.world_id,
                title="Run diagnostics",
                instruction="Inspect pending reports and tickets.",
            )
            callback_payload = build_template_callback(task)
            callback_payload["operation_requests"] = [
                {
                    "action": "version_control.snapshot",
                    "mode": "local_commit",
                    "summary": "Record Hermes callback state.",
                    "approval_prompt": {
                        "exact_command": "git commit",
                        "meaning": "Create a local snapshot.",
                        "why_needed": "Preserve the report result.",
                        "risks": ["Could include unintended files."],
                        "rollback": "Review before push.",
                    },
                }
            ]
            callback_path = adapter.callbacks_dir() / f"{callback_payload['callback_id']}.json"
            callback_path.write_text(
                json.dumps(callback_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            callback = adapter.collect_callback(callback_path)
            repo = WorldRepository(world.world_id, world.path)
            outbox = RuntimeTransport(workspace).list_envelopes(task.session_id, "outbox")
            task_state = json.loads(
                (adapter.task_state_dir() / f"{task.task_id}.json").read_text(encoding="utf-8")
            )

            self.assertTrue(callback.report_id)
            self.assertEqual(task_state["status"], "completed")
            self.assertEqual(task_state["payload"]["callback_id"], callback.callback_id)
            self.assertFalse(task.task_path.exists())
            self.assertFalse(callback_path.exists())
            self.assertTrue(
                (
                    adapter.task_archive_dir()
                    / f"{task.task_id}.json"
                ).exists()
            )
            self.assertTrue(callback.callback_path.exists())
            self.assertIn("task_archive_ref", task_state["payload"]["archive_refs"])
            self.assertIn("callback_archive_ref", task_state["payload"]["archive_refs"])
            self.assertEqual(repo.get_report(callback.report_id or "").purpose, "hermes_callback")
            self.assertEqual([item.message_type for item in outbox], ["final_report"])
            self.assertEqual(outbox[0].payload["report_id"], callback.report_id)
            self.assertEqual(
                outbox[0].payload["operation_requests"][0]["mode"],
                "local_commit",
            )
            self.assertEqual(
                outbox[0].payload["operation_requests"][0]["approval_prompt"]["meaning"],
                "Create a local snapshot.",
            )
            self.assertEqual(outbox[0].payload["delivery"]["target"], "origin")
            self.assertEqual(outbox[0].payload["sensitivity"]["level"], "internal")

    def test_callback_operation_request_rejects_unsupported_mode(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Hermes Operation Guard World")
            adapter = HermesCliTemplateAdapter(workspace)
            task = adapter.create_task(
                world.world_id,
                title="Run diagnostics",
                instruction="Inspect pending reports and tickets.",
            )
            callback_payload = build_template_callback(task)
            callback_payload["operation_requests"] = [
                {
                    "action": "version_control.snapshot",
                    "mode": "shell",
                    "summary": "Try unsupported execution mode.",
                }
            ]
            callback_path = adapter.callbacks_dir() / f"{callback_payload['callback_id']}.json"
            callback_path.write_text(
                json.dumps(callback_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(HermesAdapterError):
                adapter.collect_callback(callback_path)

    def test_callback_rejects_invalid_delivery_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Hermes Delivery Guard World")
            adapter = HermesCliTemplateAdapter(workspace)
            task = adapter.create_task(
                world.world_id,
                title="Run diagnostics",
                instruction="Inspect pending reports and tickets.",
            )
            callback_payload = build_template_callback(task)
            callback_payload["delivery"] = {"target": "unsafe-channel"}
            callback_path = adapter.callbacks_dir() / f"{callback_payload['callback_id']}.json"
            callback_path.write_text(
                json.dumps(callback_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(HermesAdapterError):
                adapter.collect_callback(callback_path)

    def test_callback_route_mismatch_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Hermes Route World")
            other_world = create_world(workspace, "Hermes Other World")
            adapter = HermesCliTemplateAdapter(workspace)
            task = adapter.create_task(
                world.world_id,
                title="Run diagnostics",
                instruction="Inspect pending reports and tickets.",
            )
            callback_payload = build_template_callback(task)
            callback_payload["route"]["world_id"] = other_world.world_id
            callback_path = adapter.callbacks_dir() / f"{callback_payload['callback_id']}.json"
            callback_path.write_text(
                json.dumps(callback_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(HermesAdapterRouteError):
                adapter.collect_callback(callback_path)

            quarantine_files = list(adapter.quarantine_dir().glob("*.json"))
            task_state = json.loads(
                (adapter.task_state_dir() / f"{task.task_id}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(quarantine_files), 1)
            self.assertEqual(task_state["status"], "quarantined")

    def test_callback_path_is_restricted_to_callbacks_dir_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Hermes Path World")
            adapter = HermesCliTemplateAdapter(workspace)
            task = adapter.create_task(
                world.world_id,
                title="Run diagnostics",
                instruction="Inspect pending reports and tickets.",
            )
            callback_payload = build_template_callback(task)
            external_path = Path(tmp) / "external_callback.json"
            external_path.write_text(
                json.dumps(callback_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(HermesAdapterError):
                adapter.collect_callback(external_path)

            callback = adapter.collect_callback(external_path, allow_external_path=True)

            self.assertEqual(callback.task_id, task.task_id)

    def test_reference_wrapper_writes_collectable_callback(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Hermes Wrapper World")
            adapter = HermesCliTemplateAdapter(workspace)
            task = adapter.create_task(
                world.world_id,
                title="Reference wrapper task",
                instruction="Return a callback.",
            )
            script = Path(__file__).resolve().parents[1] / "examples" / "wsa_hermes_cli_reference.py"

            result = subprocess.run(
                [sys.executable, str(script), "run-task", task.task_ref],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
            )
            callback_ref = result.stdout.strip().split(": ", 1)[1]
            callback = adapter.collect_callback(Path(callback_ref))

            self.assertEqual(callback.task_id, task.task_id)
            self.assertTrue(callback.report_id)

    def test_reference_wrapper_quarantines_invalid_task(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            adapter = HermesCliTemplateAdapter(workspace)
            adapter.ensure_layout()
            script = Path(__file__).resolve().parents[1] / "examples" / "wsa_hermes_cli_reference.py"

            result = subprocess.run(
                [sys.executable, str(script), "run-task", "missing-task.json"],
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("quarantine_path:", result.stderr)
            self.assertEqual(len(list(adapter.quarantine_dir().glob("*.json"))), 1)
