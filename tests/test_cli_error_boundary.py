from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.cli import main
from wsa.workspace import create_world


class CliErrorBoundaryTests(TestCase):
    def test_missing_run_is_a_recoverable_cli_error_without_traceback(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "Error World")
            output = StringIO()

            with patch("sys.stdout", output):
                code = main([
                    "--workspace",
                    str(workspace),
                    "orchestrator",
                    "status",
                    "orun_missing",
                ])

            self.assertEqual(code, 1)
            self.assertIn("command: blocked", output.getvalue())
            self.assertIn("side_effect_status: no_additional_mutation", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())
