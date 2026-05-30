from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.template import TemplateChecker, format_template_readiness


class TemplateTests(TestCase):
    def test_template_check_can_write_missing_workspace_files(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"

            readiness = TemplateChecker(workspace).run(write_missing=True)
            lines = format_template_readiness(readiness)

            self.assertTrue(readiness.ok)
            self.assertEqual(lines[0], "template_ready: yes")
            self.assertTrue((workspace / "control.sqlite").exists())
            self.assertTrue(
                (workspace / "hermes" / "adapter_config" / "hermes_cli.example.json").exists()
            )
            self.assertTrue(
                (
                    workspace
                    / "hermes"
                    / "adapter_config"
                    / "hermes_commands.example.json"
                ).exists()
            )

    def test_template_check_rejects_live_adapter_config(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            TemplateChecker(workspace).run(write_missing=True)
            (workspace / "hermes" / "adapter_config" / "hermes_live.json").write_text(
                '{"bot_token": "real-value"}\n',
                encoding="utf-8",
            )

            readiness = TemplateChecker(workspace).run()
            checks = {check.name: check for check in readiness.checks}

            self.assertFalse(readiness.ok)
            self.assertEqual(checks["live_adapter_config"].status, "fail")

    def test_template_check_rejects_runtime_queue_files(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            TemplateChecker(workspace).run(write_missing=True)
            (workspace / "hermes" / "task_queue" / "task.json").write_text(
                "{}\n",
                encoding="utf-8",
            )

            readiness = TemplateChecker(workspace).run()
            checks = {check.name: check for check in readiness.checks}

            self.assertFalse(readiness.ok)
            self.assertEqual(checks["task_queue_clean"].status, "fail")
