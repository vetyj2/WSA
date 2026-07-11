from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.application.selection_service import (
    AmbiguousWorldSelectionError,
    resolve_world_selector,
)
from wsa.workspace import create_world


class WorldSelectionTests(TestCase):
    def test_single_world_can_be_selected_without_copying_id(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Only World")

            self.assertEqual(resolve_world_selector(workspace, None).world_id, world.world_id)
            self.assertEqual(
                resolve_world_selector(workspace, "only world").world_id,
                world.world_id,
            )

    def test_multiple_worlds_require_explicit_unambiguous_selection(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            first = create_world(workspace, "First")
            create_world(workspace, "Second")

            with self.assertRaises(AmbiguousWorldSelectionError):
                resolve_world_selector(workspace, None)
            self.assertEqual(
                resolve_world_selector(workspace, first.world_id).world_id,
                first.world_id,
            )

    def test_missing_selector_produces_recovery_instruction(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "Known")

            with self.assertRaisesRegex(KeyError, "wsa world list"):
                resolve_world_selector(workspace, "Missing")
