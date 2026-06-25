import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.artifact_map import build_artifact_architecture_map
from wsa.artifact_routing import (
    ARTIFACT_ROUTING_RECOMMENDATION_SCHEMA,
    build_artifact_route_recommendation,
)
from wsa.cli import main
from wsa.workspace import create_world


class ArtifactRoutingTests(TestCase):
    def test_artifact_map_includes_creation_time_routing_policy(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "Routing Map World")

            payload = build_artifact_architecture_map(workspace)

            policy = payload["artifact_routing_policy"]
            self.assertEqual(policy["schema"], "wsa.artifact.routing_policy.v1")
            self.assertTrue(policy["default_policy"]["prefer_managed_workspace_roots"])
            self.assertEqual(
                policy["default_policy"]["unknown_artifact_type"],
                "route_as_custom_wsa_artifact_not_error",
            )
            self.assertEqual(
                policy["default_policy"]["external_runtime_namespace"],
                "prefer_wsa_marker_in_directory_or_filename",
            )
            self.assertTrue(
                policy["external_runtime_naming_policy"][
                    "warning_when_external_path_lacks_wsa_marker"
                ]
            )
            self.assertIn(
                "draft_output",
                [item["artifact_type"] for item in policy["artifact_families"]],
            )

    def test_standard_report_export_routes_inside_session_log_exports(self) -> None:
        payload = build_artifact_route_recommendation(
            Path("/tmp/workspace"),
            "draft_output",
            world_id="world-1",
            session_id="sess-1",
            filename="draft.html",
            date="2026-06-07",
        )

        self.assertEqual(payload["schema"], ARTIFACT_ROUTING_RECOMMENDATION_SCHEMA)
        self.assertEqual(payload["artifact_type"], "draft_output")
        self.assertEqual(payload["classification"], "managed_artifact")
        self.assertEqual(
            payload["workspace_relative_path"],
            "worlds/world-1/artifacts/session_logs/2026-06-07/sess-1/exports/draft.html",
        )
        self.assertTrue(payload["source_map_required"])
        self.assertEqual(payload["unresolved_placeholders"], [])

    def test_unknown_artifact_type_routes_as_custom_without_failing(self) -> None:
        payload = build_artifact_route_recommendation(
            Path("/tmp/workspace"),
            "local-user-beta-special-report",
            date="2026-06-07",
        )

        self.assertEqual(payload["artifact_type"], "custom_wsa_artifact")
        self.assertEqual(payload["classification"], "managed_artifact")
        self.assertIn("{world_id}", payload["unresolved_placeholders"])
        self.assertIn("{session_id}", payload["unresolved_placeholders"])
        self.assertTrue(payload["source_map_required"])
        self.assertTrue(
            any("world_id missing" in item for item in payload["warnings"])
        )

    def test_external_and_runtime_owned_routes_do_not_claim_wsa_delete_ownership(self) -> None:
        external = build_artifact_route_recommendation(
            Path("/tmp/workspace"),
            "media_attachment",
            filename="wsa-scene.png",
            external_path="/opt/data/media-attachments/wsa-scene.png",
        )
        runtime_owned = build_artifact_route_recommendation(
            Path("/tmp/workspace"),
            "hermes_skill",
        )

        self.assertEqual(external["artifact_type"], "external_runtime_artifact")
        self.assertEqual(external["classification"], "external_artifact")
        self.assertEqual(external["managed_by"], "user_hermes_runtime")
        self.assertTrue(external["source_map_required"])
        self.assertFalse(external["safe_to_delete_with_session"])
        self.assertTrue(external["wsa_namespace_recommended"])
        self.assertTrue(external["wsa_namespace_detected"])
        self.assertEqual(runtime_owned["classification"], "runtime_owned")
        self.assertEqual(runtime_owned["managed_by"], "user_hermes_runtime")
        self.assertFalse(runtime_owned["source_map_required"])
        self.assertTrue(runtime_owned["wsa_namespace_detected"])

    def test_external_route_warns_when_runtime_path_lacks_wsa_marker(self) -> None:
        payload = build_artifact_route_recommendation(
            Path("/tmp/workspace"),
            "external",
            filename="scene.png",
            external_path="/opt/data/media-attachments/scene.png",
        )

        self.assertEqual(payload["artifact_type"], "external_runtime_artifact")
        self.assertFalse(payload["wsa_namespace_detected"])
        self.assertTrue(
            any("external_path_lacks_wsa_marker" in item for item in payload["warnings"])
        )

    def test_external_route_default_filename_uses_wsa_marker(self) -> None:
        payload = build_artifact_route_recommendation(
            Path("/tmp/workspace"),
            "external",
        )

        self.assertEqual(payload["workspace_relative_path"], "external:wsa-external-runtime-artifact")
        self.assertTrue(payload["wsa_namespace_detected"])

    def test_cli_artifact_route_outputs_json(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "artifact",
                        "route",
                        "round_report",
                        "--world-id",
                        "world-1",
                        "--session-id",
                        "sess-1",
                        "--date",
                        "2026-06-07",
                        "--format",
                        "json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["artifact_type"], "round_orchestration_report")
            self.assertEqual(
                payload["workspace_relative_path"],
                "worlds/world-1/artifacts/session_logs/2026-06-07/sess-1/exports/round_orchestration_report.txt",
            )
