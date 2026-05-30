import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.cli import main
from wsa.startup import StartupProfileManager
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

    def test_world_startup_cli_tracks_interview_and_answer(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Startup World")

            status_stdout = StringIO()
            with patch("sys.stdout", status_stdout):
                status_code = main(["--workspace", str(workspace), "world", "startup", "status", world.world_id])

            interview_stdout = StringIO()
            with patch("sys.stdout", interview_stdout):
                interview_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "startup",
                        "interview",
                        world.world_id,
                        "--budget",
                        "2",
                    ]
                )

            answer_stdout = StringIO()
            with patch("sys.stdout", answer_stdout):
                answer_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "startup",
                        "answer",
                        world.world_id,
                        "Q001",
                        "--text",
                        "A magic academy mystery.",
                    ]
                )

            self.assertEqual(status_code, 0)
            self.assertEqual(interview_code, 0)
            self.assertEqual(answer_code, 0)
            self.assertIn("startup_ambiguity: 100%", status_stdout.getvalue())
            self.assertIn("Q001\tasked", interview_stdout.getvalue())
            self.assertIn("startup_ambiguity: 90%", answer_stdout.getvalue())

    def test_world_startup_cli_set_status_can_approve_proposal(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Startup Approval World")
            StartupProfileManager(world).answer(
                "Q001",
                "An agent-suggested premise.",
                answered_by="agent_proposal",
            )
            stdout = StringIO()

            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "startup",
                        "set-status",
                        world.world_id,
                        "Q001",
                        "--status",
                        "approved_by_author",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertIn("startup_status_updated: Q001", stdout.getvalue())
            self.assertIn("startup_ambiguity: 90%", stdout.getvalue())

    def test_meeting_run_cli_creates_non_mutating_report(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Meeting World")
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "meeting",
                        "run",
                        world.world_id,
                        "--topic",
                        "Succession gap",
                        "--question",
                        "What should be proposed?",
                        "--participant",
                        "Council",
                    ]
                )

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("meeting_id:", output)
            self.assertIn("transcript_path:", output)
            self.assertIn("report_id:", output)

    def test_meeting_decide_cli_approves_candidate_report(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CLI Meeting Decision World")
            run_stdout = StringIO()
            with patch("sys.stdout", run_stdout):
                main(
                    [
                        "--workspace",
                        str(workspace),
                        "meeting",
                        "run",
                        world.world_id,
                        "--topic",
                        "Candidate district",
                    ]
                )
            report_id = ""
            for line in run_stdout.getvalue().splitlines():
                if line.startswith("report_id: "):
                    report_id = line.split(": ", 1)[1]

            decide_stdout = StringIO()
            with patch("sys.stdout", decide_stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "meeting",
                        "decide",
                        world.world_id,
                        report_id,
                        "--decision",
                        "approve",
                    ]
                )

            output = decide_stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("meeting_decision: approve", output)
            self.assertIn("report_status: approved", output)
            self.assertIn("ticket_type: meeting_candidate", output)

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
            self.assertIn("command_registry:", example_stdout.getvalue())
            self.assertTrue(
                (
                    workspace
                    / "hermes"
                    / "adapter_config"
                    / "hermes_commands.example.json"
                ).exists()
            )
            self.assertIn("hermes_task_created:", task_stdout.getvalue())
            self.assertIn("command_preview: wsa-hermes-cli run-task", task_stdout.getvalue())

    def test_hermes_commands_cli_lists_and_writes_registry(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"

            text_stdout = StringIO()
            with patch("sys.stdout", text_stdout):
                text_code = main(["--workspace", str(workspace), "hermes", "commands"])

            json_stdout = StringIO()
            with patch("sys.stdout", json_stdout):
                json_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "hermes",
                        "commands",
                        "--format",
                        "json",
                    ]
                )

            write_stdout = StringIO()
            with patch("sys.stdout", write_stdout):
                write_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "hermes",
                        "commands",
                        "--write-example",
                    ]
                )

            payload = json.loads(json_stdout.getvalue())
            commands = {item["command"]: item for item in payload["commands"]}

            self.assertEqual(text_code, 0)
            self.assertEqual(json_code, 0)
            self.assertEqual(write_code, 0)
            self.assertIn("/wsa_easystart", text_stdout.getvalue())
            self.assertIn("/wsa-easystart", text_stdout.getvalue())
            self.assertIn("/wsa_easystart", commands)
            self.assertIn("/wsa-easystart", commands["/wsa_easystart"]["aliases"])
            self.assertEqual(commands["/wsa_autogen"]["safety"], "proposal_only")
            self.assertTrue(
                (
                    workspace
                    / "hermes"
                    / "adapter_config"
                    / "hermes_commands.example.json"
                ).exists()
            )

    def test_hermes_doctor_passes_with_available_wrapper_command(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            with patch("sys.stdout", StringIO()):
                main(["--workspace", str(workspace), "hermes", "init-example"])

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "hermes",
                        "doctor",
                        "--command",
                        "python3",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertIn("hermes_ready: yes", stdout.getvalue())
            self.assertIn("ok\tcommand_available\tpython3", stdout.getvalue())
            self.assertIn("ok\tcommand_registry", stdout.getvalue())

    def test_hermes_doctor_fails_when_wrapper_command_is_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            with patch("sys.stdout", StringIO()):
                main(["--workspace", str(workspace), "hermes", "init-example"])

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "hermes",
                        "doctor",
                        "--command",
                        "wsa-missing-hermes-wrapper",
                    ]
                )

            self.assertEqual(code, 1)
            self.assertIn("hermes_ready: no", stdout.getvalue())
            self.assertIn("fail\tcommand_available", stdout.getvalue())

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
