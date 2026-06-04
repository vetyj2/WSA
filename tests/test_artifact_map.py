import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.artifact_map import (
    ARTIFACT_ARCHITECTURE_MAP_SCHEMA,
    artifact_architecture_map_path,
    build_artifact_architecture_map,
    validate_artifact_architecture_map,
    write_artifact_architecture_map,
)
from wsa.workspace import create_world


class ArtifactMapTests(TestCase):
    def test_artifact_map_declares_sources_artifacts_and_external_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Artifact Map World")

            payload = build_artifact_architecture_map(workspace)

            self.assertEqual(payload["schema"], ARTIFACT_ARCHITECTURE_MAP_SCHEMA)
            self.assertEqual(payload["directory_base"], "manager/artifact_map/")
            self.assertIn(
                "worlds/{world_id}/world.sqlite",
                [item["path_template"] for item in payload["source_of_truth_zones"]],
            )
            self.assertIn(
                "reports/{inbox|pending_review|approved|rejected|archived|telegram_queue}/",
                [item["path_template"] for item in payload["managed_artifact_zones"]],
            )
            self.assertTrue(payload["external_artifact_boundary"]["source_map_required"])
            self.assertEqual(payload["concrete_worlds"][0]["world_id"], world.world_id)

    def test_artifact_map_write_and_validate_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "Artifact Map Write World")

            path = write_artifact_architecture_map(workspace)
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(path, artifact_architecture_map_path(workspace))
            self.assertEqual(payload["schema"], ARTIFACT_ARCHITECTURE_MAP_SCHEMA)
            self.assertEqual(validate_artifact_architecture_map(workspace), [])
