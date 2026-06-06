import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.cli import main
from wsa.uninstall import (
    build_uninstall_discovery_manifest,
    build_uninstall_dry_run_plan,
)
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
            self.assertTrue(
                any("Hermes doctor" in item for item in payload["recommended_order"])
            )

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

    def test_discovery_classifies_external_candidates_and_preserves_excludes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "scan"
            workspace = Path(tmp) / "workspace"
            source = root / "WSA"
            live = root / "wsa-world-live"
            backup = root / "wsa-world-live-backups"
            media = root / "media-attachments"
            skill = root / "skills" / "software-development" / "wsa-chat-shortcuts"
            source.mkdir(parents=True)
            (source / "src" / "wsa").mkdir(parents=True)
            (source / "pyproject.toml").write_text(
                '[project]\nname = "world-scene-actors"\n',
                encoding="utf-8",
            )
            live.mkdir(parents=True)
            (live / "control.sqlite").write_text("", encoding="utf-8")
            (live / "worlds" / "world-a").mkdir(parents=True)
            (live / "worlds" / "world-a" / "world.sqlite").write_text("", encoding="utf-8")
            backup.mkdir(parents=True)
            media.mkdir(parents=True)
            for index in range(3):
                (media / f"wsa-meetup-report-{index}.txt").write_text(
                    "report\n",
                    encoding="utf-8",
                )
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("WSA shortcut rules\n", encoding="utf-8")

            payload = build_uninstall_discovery_manifest(
                workspace,
                [root],
                exclude_roots=[backup],
            )
            by_class = _paths_by_class(payload)

            self.assertEqual(payload["schema"], "wsa.uninstall.discovery_manifest.v1")
            self.assertFalse(payload["delete_performed"])
            self.assertFalse(payload["archive_performed"])
            self.assertIn(str(source.resolve()), by_class["source_checkout"])
            self.assertIn(str(live.resolve()), by_class["wsa_workspace"])
            self.assertIn(str(backup.resolve()), by_class["excluded_root"])
            self.assertIn(str(skill.resolve()), by_class["runtime_overlay"])
            self.assertIn(str(media.resolve()), by_class["external_artifact_collection"])
            self.assertTrue(
                all(
                    not item["deletion_allowed_without_explicit_manifest"]
                    for item in payload["candidates"]
                )
            )
            self.assertTrue(
                any("Hermes doctor" in item for item in payload["recommended_next_step"])
            )

    def test_cli_writes_discovery_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "scan"
            workspace = Path(tmp) / "workspace"
            candidate = root / "wsa-report.txt"
            root.mkdir(parents=True)
            candidate.write_text("report\n", encoding="utf-8")

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "artifact",
                        "uninstall-discover",
                        "--scan-root",
                        str(root),
                        "--write",
                        "--format",
                        "json",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["side_effect_status"], "workspace_mutating_manifest_written")
            self.assertIn("discovery_ref", payload)
            self.assertTrue((workspace / payload["discovery_ref"]).exists())
            self.assertTrue(candidate.exists())


def _paths_by_class(payload: dict) -> dict[str, set[str]]:
    by_class: dict[str, set[str]] = {}
    for item in payload["candidates"]:
        by_class.setdefault(item["classification"], set()).add(item["path"])
    return by_class
