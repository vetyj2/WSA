import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.artifact_map import write_artifact_architecture_map
from wsa.cli import main
from wsa.maintenance import build_maintenance_scan
from wsa.workspace import create_world, init_workspace


class MaintenanceScanTests(TestCase):
    def test_scan_reports_pending_callbacks_without_mutation(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "Maintenance World")
            write_artifact_architecture_map(workspace)
            callbacks = workspace / "hermes" / "callbacks"
            callbacks.mkdir(parents=True, exist_ok=True)
            callback = callbacks / "callback.json"
            callback.write_text("{}", encoding="utf-8")

            payload = build_maintenance_scan(workspace, top=3)

            self.assertEqual(payload["schema"], "wsa.maintenance.storage_scan.v1")
            self.assertEqual(payload["side_effect_status"], "read_only")
            self.assertFalse(payload["delete_performed"])
            self.assertFalse(payload["archive_performed"])
            self.assertGreaterEqual(payload["totals"]["files"], 1)
            self.assertIn(
                "ingest, reject, or archive pending Hermes callbacks before cleanup",
                payload["recommended_actions"],
            )
            self.assertTrue(callback.exists())

    def test_cli_writes_maintenance_scan(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            init_workspace(workspace)
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "artifact",
                        "maintenance-scan",
                        "--write",
                        "--format",
                        "json",
                        "--top",
                        "2",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["side_effect_status"], "workspace_mutating_scan_written")
            self.assertIn("scan_ref", payload)
            self.assertTrue((workspace / payload["scan_ref"]).exists())
            self.assertFalse(payload["delete_performed"])
            self.assertFalse(payload["archive_performed"])
