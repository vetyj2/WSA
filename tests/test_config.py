import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from wsa.config import WORKSPACE_ENV_VAR, load_config, resolve_workspace


class ConfigTests(TestCase):
    def test_default_workspace_is_under_cwd(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(WORKSPACE_ENV_VAR, None)
            cwd = Path("/tmp/example")
            self.assertEqual(resolve_workspace(cwd=cwd), Path("/tmp/example/workspace").resolve())

    def test_env_workspace_wins_over_cwd_default(self) -> None:
        with patch.dict(os.environ, {WORKSPACE_ENV_VAR: "/tmp/from-env"}, clear=False):
            self.assertEqual(
                load_config(cwd=Path("/tmp/example")).workspace,
                Path("/tmp/from-env").resolve(),
            )

    def test_explicit_workspace_wins(self) -> None:
        with patch.dict(os.environ, {WORKSPACE_ENV_VAR: "/tmp/from-env"}, clear=False):
            self.assertEqual(
                load_config(workspace="/tmp/custom").workspace,
                Path("/tmp/custom").resolve(),
            )
