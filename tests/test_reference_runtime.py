import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.atomic_io import atomic_write_json
from wsa.autonomous_orchestrator import AutonomousOrchestrator
from wsa.orchestrator_bridge import OrchestratorBridge
from wsa.workspace import create_world


class ReferenceRuntimeTests(TestCase):
    def test_no_network_reference_runtime_completes_bridge_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Reference Runtime World")
            run = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="reference bridge",
                question="Return one bounded candidate.",
                participants=["Observer"],
                rounds=1,
                mode="hermes-bridge",
                prep_review=False,
            )
            bridge = OrchestratorBridge(workspace)
            next_path = workspace / "hermes" / "reference_next.json"
            callback_path = workspace / "hermes" / "callbacks" / "reference.json"
            atomic_write_json(next_path, bridge.next(run.run_id))

            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "scripts" / "reference_callback_runner.py"),
                    "--next-json",
                    str(next_path),
                    "--output",
                    str(callback_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            submitted = bridge.submit(run.run_id, callback_path)
            final = AutonomousOrchestrator.load_run(workspace, run.run_id)

            self.assertTrue(submitted["accepted"])
            self.assertEqual(submitted["status"], "awaiting_author_review")
            self.assertEqual(final["execution_status"], "completed_by_hermes")
            self.assertEqual(len(final["subsession_outputs"]), 1)
            self.assertEqual(final["world_mutations"], [])
