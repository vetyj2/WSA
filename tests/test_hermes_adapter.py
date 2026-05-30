import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.hermes_adapter import (
    HermesAdapterError,
    HermesAdapterRouteError,
    HermesCliTemplateAdapter,
    build_template_callback,
)
from wsa.repositories import WorldRepository
from wsa.transport import RuntimeTransport
from wsa.workspace import create_world


class HermesAdapterTests(TestCase):
    def test_example_config_is_written_without_secret_values(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            adapter = HermesCliTemplateAdapter(workspace)

            path = adapter.write_example_config()
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(payload["adapter"], "cli")
            self.assertEqual(payload["secret_env"], ["HERMES_BOT_TOKEN", "OPENAI_API_KEY"])
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
            inbox = RuntimeTransport(workspace).list_envelopes(task.session_id, "inbox")

            self.assertEqual(task_payload["schema"], "wsa.hermes.task.v1")
            self.assertEqual(task_payload["route"]["world_id"], world.world_id)
            self.assertEqual(task_payload["adapter"]["command_preview"][0], "wsa-hermes-cli")
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

            self.assertTrue(callback.report_id)
            self.assertEqual(repo.get_report(callback.report_id or "").purpose, "hermes_callback")
            self.assertEqual([item.message_type for item in outbox], ["final_report"])
            self.assertEqual(outbox[0].payload["report_id"], callback.report_id)
            self.assertEqual(
                outbox[0].payload["operation_requests"][0]["mode"],
                "local_commit",
            )

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
