from pathlib import Path
from unittest import TestCase

from wsa.config import load_config, resolve_workspace


class ConfigTests(TestCase):
    def test_default_workspace_is_under_cwd(self) -> None:
        cwd = Path("/tmp/example")
        self.assertEqual(resolve_workspace(cwd=cwd), Path("/tmp/example/workspace").resolve())

    def test_explicit_workspace_wins(self) -> None:
        self.assertEqual(
            load_config(workspace="/tmp/custom").workspace,
            Path("/tmp/custom").resolve(),
        )
