from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.artifact_map import load_artifact_architecture_map
from wsa.cli_core import run_doctor, run_init, run_world_create


class Phase0FirstRunTests(TestCase):
    def test_init_creates_derived_artifact_map_and_doctor_is_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"

            with redirect_stdout(StringIO()):
                self.assertEqual(run_init(workspace), 0)
            payload = load_artifact_architecture_map(workspace)

            self.assertIsNotNone(payload)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(run_doctor(workspace), 0)
            self.assertIn("artifact_map_exists: True", output.getvalue())
            self.assertIn("artifact_source_map_status: pass", output.getvalue())
            self.assertIn("schema_status: ok", output.getvalue())

    def test_world_create_refreshes_artifact_map_world_list(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"

            with redirect_stdout(StringIO()):
                self.assertEqual(run_init(workspace), 0)
                self.assertEqual(run_world_create(workspace, "Fresh World"), 0)
            payload = load_artifact_architecture_map(workspace)

            self.assertIsNotNone(payload)
            self.assertEqual(len(payload["concrete_worlds"]), 1)
            self.assertEqual(payload["concrete_worlds"][0]["display_name"], "Fresh World")
