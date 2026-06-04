import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.cli import main
from wsa.uninstall import build_uninstall_dry_run_plan
from wsa.workspace import create_world


class UninstallPlanTests(TestCase):
    def test_uninstall_dry_run_preserves_world_data(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Uninstall World")

            payload = build_uninstall_dry_run_plan(workspace)

            self.assertEqual(payload["schema"], "wsa.uninstall.dry_run_plan.v1")
            self.assertEqual(payload["mode"], "dry_run")
            self.assertFalse(payload["automatic_delete_performed"])
            self.assertTrue(payload["requires_explicit_user_approval_for_delete"])
            preserve_paths = {item["path"] for item in payload["preserve"]}
            self.assertIn("control.sqlite", preserve_paths)
            self.assertIn(f"worlds/{world.world_id}/world.sqlite", preserve_paths)
            self.assertTrue((world.path / "world.sqlite").exists())

    def test_cli_writes_uninstall_plan_without_deleting(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Uninstall CLI World")

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "artifact",
                        "uninstall-plan",
                        "--write",
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["side_effect_status"], "workspace_mutating_plan_written")
            self.assertIn("plan_ref", payload)
            self.assertTrue((workspace / payload["plan_ref"]).exists())
            self.assertTrue((world.path / "world.sqlite").exists())
            self.assertFalse(payload["automatic_delete_performed"])
