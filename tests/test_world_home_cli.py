import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.cli import main
from wsa.workspace import create_world


class WorldHomeCliTests(TestCase):
    def test_single_world_home_needs_no_id_and_defaults_to_korean(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "한 개의 월드")
            output = StringIO()

            with patch("sys.stdout", output):
                code = main(["--workspace", str(workspace), "world", "home"])

            self.assertEqual(code, 0)
            self.assertIn("월드_홈: 한 개의 월드", output.getvalue())
            self.assertIn("다음_행동:", output.getvalue())

    def test_continue_json_returns_one_executable_command(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Continue World")
            output = StringIO()

            with patch("sys.stdout", output):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "continue",
                        world.world_id,
                        "--format",
                        "json",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(len(payload["commands"]), 1)
            self.assertEqual(payload["commands"][0]["argv"][-3:-1], ["startup", "interview"])
            self.assertEqual(payload["side_effect_status"], "read_only_no_world_mutation")
