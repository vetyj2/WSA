import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.autonomous_orchestrator import AutonomousOrchestrator
from wsa.cli import main
from wsa.repositories import WorldRepository
from wsa.startup import StartupProfileManager
from wsa.workspace import create_world


class GuidedWorkflowCliTests(TestCase):
    def test_no_json_author_flow_previews_reviews_and_applies(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Guided World")
            repo = WorldRepository(world.world_id, world.path)

            preview = StringIO()
            with redirect_stdout(preview):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "compose",
                        "--title",
                        "Add Mina",
                        "--add-entity",
                        "character|Mina",
                        "--add-fact",
                        "Mina|role|navigator",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("변경안 미리보기", preview.getvalue())
            self.assertEqual(repo.list_tickets(), [])
            self.assertEqual(repo.list_entities(), [])

            written = StringIO()
            with redirect_stdout(written):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "compose",
                        "--title",
                        "Add Mina",
                        "--add-entity",
                        "character|Mina",
                        "--add-fact",
                        "Mina|role|navigator",
                        "--write-ticket",
                    ]
                )
            self.assertEqual(code, 0)
            ticket_id = next(
                line.split(": ", 1)[1]
                for line in written.getvalue().splitlines()
                if line.startswith("ticket_id: ")
            )
            self.assertEqual(repo.list_entities(), [])

            shown = StringIO()
            with redirect_stdout(shown):
                show_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "show",
                        ticket_id,
                    ]
                )
            self.assertEqual(show_code, 0)
            self.assertIn("entity character: Mina", shown.getvalue())
            self.assertIn("fact", shown.getvalue())

            transition_output = StringIO()
            with redirect_stdout(transition_output):
                review_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "review",
                        world.world_id,
                        ticket_id,
                    ]
                )
                apply_code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "ticket",
                        "apply",
                        world.world_id,
                        ticket_id,
                    ]
                )
            self.assertEqual(review_code, 0)
            self.assertEqual(apply_code, 0)
            self.assertIn("changed: entity character: Mina", transition_output.getvalue())
            self.assertIn("changed: fact", transition_output.getvalue())
            mina = next(item for item in repo.list_entities() if item.display_name == "Mina")
            facts = repo.list_facts(subject_id=mina.entity_id)
            self.assertEqual(
                [(item.predicate, item.object_value) for item in facts],
                [("role", "navigator")],
            )

    def test_startup_source_followup_reads_only_explicit_current_world_file(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Source World")
            manager = StartupProfileManager(world)
            for question_id, answer in (
                ("0001", "Build a reusable world reference."),
                ("0002", "Use the notes I provide."),
                ("0003", "Keep author review required."),
                ("0004", "Produce a world outline."),
            ):
                manager.answer(question_id, answer)
            source = Path(tmp) / "notes.txt"
            source.write_text("The opening remains in one neighborhood.", encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "startup",
                        "source-followup",
                        world.world_id,
                        "--source",
                        str(source),
                    ]
                )
            rendered = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("why_asked:", rendered)
            self.assertIn(str(source), rendered)
            self.assertIn("read_only_compilation_no_world_mutation", rendered)
            profile = manager.profile_path.read_text(encoding="utf-8")
            self.assertNotIn(str(source), profile)

    def test_startup_source_read_error_has_no_traceback(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Unreadable Source World")
            output = StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "--workspace",
                        str(workspace),
                        "world",
                        "startup",
                        "source-followup",
                        world.world_id,
                        "--source",
                        tmp,
                    ]
                )

            self.assertEqual(code, 1)
            self.assertIn("command: blocked", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())

    def test_runtime_cli_requires_confirmation_then_ingests_one_turn(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Runtime CLI World")
            run = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="runtime cli",
                question="Return one bounded candidate.",
                participants=["Observer"],
                rounds=1,
                mode="hermes-bridge",
                prep_review=False,
            )
            adapter = (
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "reference_stdio_adapter.py"
            )
            base = [
                "--workspace",
                str(workspace),
                "orchestrator",
                "dispatch",
                run.run_id,
                "--timeout",
                "10",
            ]
            callback_dir = workspace / "hermes" / "callbacks"
            callbacks_before = list(callback_dir.glob("*.json"))

            blocked = StringIO()
            with redirect_stdout(blocked):
                blocked_code = main(
                    [*base, "--runtime-command", sys.executable, str(adapter)]
                )
            self.assertEqual(blocked_code, 1)
            self.assertIn("confirmation_required", blocked.getvalue())
            self.assertEqual(list(callback_dir.glob("*.json")), callbacks_before)

            completed = StringIO()
            with redirect_stdout(completed):
                completed_code = main(
                    [
                        *base,
                        "--confirm",
                        "--runtime-command",
                        sys.executable,
                        str(adapter),
                    ]
                )
            self.assertEqual(completed_code, 0)
            self.assertIn("dispatch_result: submitted", completed.getvalue())
            final = AutonomousOrchestrator.load_run(workspace, run.run_id)
            self.assertEqual(final["execution_status"], "completed_by_hermes")
            self.assertEqual(final["world_mutations"], [])
