from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.artifact_diagnostics import diagnose_artifact_source_maps
from wsa.artifact_map import write_artifact_architecture_map
from wsa.autonomous_orchestrator import AutonomousOrchestrator
from wsa.cli import main
from wsa.report_exports import write_report_export
from wsa.workspace import create_world


class ArtifactDiagnosticTests(TestCase):
    def test_valid_written_export_source_map_passes(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Source Map World")
            write_artifact_architecture_map(workspace)
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="source map check",
                question="Create exportable run.",
                participants=["Auditor"],
                rounds=1,
            )
            write_report_export(world, result.run_id, "human_session_minutes", "txt")

            payload = diagnose_artifact_source_maps(workspace)

            self.assertEqual(payload["schema"], "wsa.artifact.source_map_diagnostic.v1")
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["counts"]["source_maps"], 1)
            self.assertEqual(payload["counts"]["orphan_exports"], 0)

    def test_orphan_export_without_source_map_warns(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Orphan Export World")
            write_artifact_architecture_map(workspace)
            export_dir = (
                world.path
                / "artifacts"
                / "session_logs"
                / "2026-06-05"
                / "session-x"
                / "exports"
            )
            export_dir.mkdir(parents=True)
            (export_dir / "minutes.txt").write_text("orphan\n", encoding="utf-8")

            payload = diagnose_artifact_source_maps(workspace)

            self.assertEqual(payload["status"], "warn")
            self.assertEqual(payload["counts"]["orphan_exports"], 1)
            self.assertEqual(payload["findings"][0]["code"], "missing_source_map_for_export")

    def test_cli_artifact_diagnose_prints_status(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "CLI Source Map World")
            write_artifact_architecture_map(workspace)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(["--workspace", str(workspace), "artifact", "diagnose"])

            self.assertEqual(code, 0)
            self.assertIn("artifact_source_maps: pass", stdout.getvalue())
