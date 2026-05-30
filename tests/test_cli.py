from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.cli import main
from wsa.workspace import (
    SCHEMA_VERSION,
    control_db_path,
    create_world,
    sqlite_connection,
    world_db_path,
)


class CliTests(TestCase):
    def test_help_returns_zero(self) -> None:
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("World Scene Actors", stdout.getvalue())

    def test_doctor_returns_workspace(self) -> None:
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            code = main(["--workspace", "/tmp/wsa-test", "doctor"])
        self.assertEqual(code, 0)
        self.assertIn(f"workspace: {Path('/tmp/wsa-test').resolve()}", stdout.getvalue())

    def test_doctor_rejects_newer_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Future Doctor")
            with sqlite_connection(world_db_path(world.path)) as conn:
                conn.execute(
                    "UPDATE schema_info SET version = ? WHERE name = 'world'",
                    (SCHEMA_VERSION + 1,),
                )

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(["--workspace", str(workspace), "doctor"])

            self.assertEqual(code, 1)
            self.assertIn("schema_status: unsupported", stdout.getvalue())

    def test_doctor_rejects_invalid_world_path(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Path Doctor")
            with sqlite_connection(control_db_path(workspace)) as conn:
                conn.execute(
                    "UPDATE worlds SET path = ? WHERE world_id = ?",
                    (str(Path(tmp) / "outside-world"), world.world_id),
                )

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(["--workspace", str(workspace), "doctor"])

            self.assertEqual(code, 1)
            self.assertIn("path_status: invalid", stdout.getvalue())

    def test_world_list_without_workspace_is_empty(self) -> None:
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            code = main(["--workspace", "/tmp/wsa-missing-for-list", "world", "list"])
        self.assertEqual(code, 0)
        self.assertIn("worlds: none", stdout.getvalue())

    def test_scene_mock_cli_runs_vertical_slice(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Scene World")
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "scene",
                        "mock",
                        world.world_id,
                        "CLI Opening",
                        "--goal",
                        "test goal",
                        "--actor",
                        "Kai",
                    ]
                )

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("scene_id:", output)
            self.assertIn("ticket_id:", output)
            self.assertIn("report_id:", output)

    def test_manager_diagnose_cli_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_world(workspace, "CLI Manager World")
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(["--workspace", str(workspace), "manager", "diagnose"])

            self.assertEqual(code, 0)
            self.assertIn("diagnostics: clean", stdout.getvalue())

    def test_report_and_ticket_list_cli_after_mock_scene(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Inspect World")
            with patch("sys.stdout", StringIO()):
                main(
                    [
                        "--workspace",
                        str(workspace),
                        "scene",
                        "mock",
                        world.world_id,
                        "Inspect Scene",
                        "--goal",
                        "inspect goal",
                        "--actor",
                        "Lee",
                    ]
                )

            ticket_stdout = StringIO()
            with patch("sys.stdout", ticket_stdout):
                ticket_code = main(["--workspace", str(workspace), "ticket", "list", world.world_id])

            report_stdout = StringIO()
            with patch("sys.stdout", report_stdout):
                report_code = main(["--workspace", str(workspace), "report", "list", world.world_id])

            self.assertEqual(ticket_code, 0)
            self.assertEqual(report_code, 0)
            self.assertIn("Scene result PR", ticket_stdout.getvalue())
            self.assertIn("Final scene report", report_stdout.getvalue())

    def test_ticket_approve_cli_applies_mock_scene_ticket(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Approve World")
            scene_stdout = StringIO()
            with patch("sys.stdout", scene_stdout):
                main(
                    [
                        "--workspace",
                        str(workspace),
                        "scene",
                        "mock",
                        world.world_id,
                        "Approve Scene",
                        "--goal",
                        "approve goal",
                        "--actor",
                        "Noa",
                    ]
                )

            ticket_id = ""
            for line in scene_stdout.getvalue().splitlines():
                if line.startswith("ticket_id: "):
                    ticket_id = line.split(": ", 1)[1]
            self.assertTrue(ticket_id)

            approve_stdout = StringIO()
            with patch("sys.stdout", approve_stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "approve",
                        world.world_id,
                        ticket_id,
                    ]
                )

            self.assertEqual(code, 0)
            self.assertIn(f"ticket_approved: {ticket_id}", approve_stdout.getvalue())

    def test_hermes_cli_writes_example_and_task_packet(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Hermes World")

            example_stdout = StringIO()
            with patch("sys.stdout", example_stdout):
                example_code = main(["--workspace", str(workspace), "hermes", "init-example"])

            task_stdout = StringIO()
            with patch("sys.stdout", task_stdout):
                task_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "hermes",
                        "task",
                        world.world_id,
                        "--title",
                        "Inspect world",
                        "--instruction",
                        "Inspect pending reports and tickets.",
                    ]
                )

            self.assertEqual(example_code, 0)
            self.assertEqual(task_code, 0)
            self.assertIn("example_config:", example_stdout.getvalue())
            self.assertIn("hermes_task_created:", task_stdout.getvalue())
            self.assertIn("command_preview: wsa-hermes-cli run-task", task_stdout.getvalue())

    def test_template_check_cli_can_initialize_template_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            stdout = StringIO()

            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "template",
                        "check",
                        "--write-missing",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertIn("template_ready: yes", stdout.getvalue())
            self.assertIn("ok\tworkspace_initialized", stdout.getvalue())
