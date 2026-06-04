import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.autonomous_orchestrator import AutonomousOrchestrator
from wsa.cli import main
from wsa.report_exports import build_report_export
from wsa.workspace import create_world


class ReportExportTests(TestCase):
    def test_builds_text_export_from_orchestrator_run(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Export World")
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="exportable council minutes",
                question="Package the session for review.",
                participants=["Council"],
                rounds=1,
            )

            payload = build_report_export(
                world,
                result.run_id,
                "human_session_minutes",
                "txt",
            )

            self.assertEqual(payload["schema"], "wsa.report.export.v1")
            self.assertEqual(payload["side_effect_status"], "read_only_until_write_requested")
            self.assertIn("# WSA Session Minutes", payload["content"])
            self.assertIn("exportable council minutes", payload["content"])
            self.assertEqual(payload["source_of_truth"], "orchestrator_run_json")

    def test_cli_writes_html_export_and_source_map(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Export CLI World")
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="scene_generation",
                topic="scene export",
                question="Prepare draft export.",
                participants=["Narrator"],
                rounds=1,
                skill="scene_start",
            )

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "report",
                        "export",
                        world.world_id,
                        "--run-id",
                        result.run_id,
                        "--artifact-type",
                        "draft_output",
                        "--format",
                        "html",
                        "--write",
                    ]
                )

            self.assertEqual(code, 0)
            output = stdout.getvalue()
            self.assertIn("report_export: ready", output)
            self.assertIn("artifact_ref:", output)
            artifact_ref = _line_value(output, "artifact_ref")
            manifest_ref = _line_value(output, "manifest_ref")
            artifact_path = world.path / artifact_ref
            manifest_path = world.path / manifest_ref

            self.assertTrue(artifact_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertIn("<!doctype html>", artifact_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "wsa.reporting.artifact_manifest.v1")
            self.assertEqual(manifest["run_id"], result.run_id)
            self.assertEqual(manifest["exports"][0]["artifact_type"], "draft_output")


def _line_value(output: str, key: str) -> str:
    prefix = f"{key}: "
    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    raise AssertionError(f"missing output key: {key}")
