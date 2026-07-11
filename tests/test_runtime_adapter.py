import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.application.runtime_loop_service import (
    PrepReviewRequiredError,
    RuntimeLoopService,
)
from wsa.autonomous_orchestrator import AutonomousOrchestrator
from wsa.orchestrator_bridge import OrchestratorBridge
from wsa.runtime_adapter import (
    EXECUTION_MALFORMED_JSON,
    EXECUTION_NO_RUNTIME,
    EXECUTION_TIMEOUT,
    StdioRuntimeAdapter,
)
from wsa.workspace import create_world


class RuntimeAdapterTests(TestCase):
    def test_reference_stdio_round_trip_uses_reviewable_plan_and_bound_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace, run_id = _bridge_run(Path(tmp), prep_review=False)
            secret = "must-not-be-recorded"
            adapter = StdioRuntimeAdapter(
                [sys.executable, str(_reference_adapter())],
                workspace,
                timeout_seconds=10,
                env={"WSA_TEST_SECRET": secret},
            )
            service = RuntimeLoopService(workspace, adapter)
            task_queue = workspace / "hermes" / "task_queue"
            before = list(task_queue.glob("*.json")) if task_queue.exists() else []

            with patch("wsa.runtime_adapter.subprocess.Popen") as popen:
                plan = service.dispatch_plan(run_id)
                popen.assert_not_called()
            plan_payload = plan.to_dict()
            self.assertEqual(plan_payload["side_effect_status"], "read_only_no_process_started")
            self.assertEqual(plan_payload["workdir"], str(workspace.resolve()))
            self.assertTrue(plan_payload["argv"])
            self.assertTrue(plan_payload["route_digest"])
            self.assertEqual(plan_payload["timeout_seconds"], 10.0)
            self.assertNotIn(secret, json.dumps(plan_payload))
            after = list(task_queue.glob("*.json")) if task_queue.exists() else []
            self.assertEqual(before, after)

            result = service.execute(plan)
            self.assertEqual(result.status, "submitted")
            self.assertTrue(result.accepted)
            self.assertIsNotNone(result.callback_path)
            callback = json.loads(result.callback_path.read_text(encoding="utf-8"))
            self.assertEqual(callback["dispatch_receipt"]["turn_id"], plan.turn_id)
            self.assertEqual(
                callback["dispatch_receipt"]["route_digest"],
                plan.route_digest,
            )
            self.assertEqual(
                result.execution.capability_negotiation.state,
                "accepted",
            )
            self.assertNotIn(secret, result.callback_path.read_text(encoding="utf-8"))

            final = AutonomousOrchestrator.load_run(workspace, run_id)
            self.assertEqual(final["execution_status"], "completed_by_hermes")
            self.assertEqual(final["world_mutations"], [])
            self.assertFalse(result.to_dict()["side_effect"]["canon_mutation_performed"])

    def test_timeout_is_reported_without_callback_write(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace, run_id = _bridge_run(Path(tmp), prep_review=False)
            hook = OrchestratorBridge(workspace).next(run_id)["hook"]
            adapter = StdioRuntimeAdapter(
                [sys.executable, "-c", "import time; time.sleep(1)"],
                workspace,
                timeout_seconds=0.05,
            )
            result = adapter.execute(adapter.plan(hook))
            self.assertEqual(result.status, EXECUTION_TIMEOUT)
            self.assertTrue(result.process_started)
            self.assertIsNone(result.callback)

    def test_malformed_stdout_is_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace, run_id = _bridge_run(Path(tmp), prep_review=False)
            hook = OrchestratorBridge(workspace).next(run_id)["hook"]
            adapter = StdioRuntimeAdapter(
                [sys.executable, "-c", "print('not-json')"],
                workspace,
                timeout_seconds=2,
            )
            result = adapter.execute(adapter.plan(hook))
            self.assertEqual(result.status, EXECUTION_MALFORMED_JSON)
            self.assertIsNone(result.callback)

    def test_missing_runtime_is_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace, run_id = _bridge_run(Path(tmp), prep_review=False)
            hook = OrchestratorBridge(workspace).next(run_id)["hook"]
            adapter = StdioRuntimeAdapter(
                [str(Path(tmp) / "missing-runtime")],
                workspace,
                timeout_seconds=2,
            )
            result = adapter.execute(adapter.plan(hook))
            self.assertEqual(result.status, EXECUTION_NO_RUNTIME)
            self.assertFalse(result.process_started)

    def test_prep_review_blocks_before_process_start(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace, run_id = _bridge_run(Path(tmp), prep_review=True)
            adapter = StdioRuntimeAdapter(
                [sys.executable, str(_reference_adapter())],
                workspace,
                timeout_seconds=2,
            )
            service = RuntimeLoopService(workspace, adapter)
            with patch("wsa.runtime_adapter.subprocess.Popen") as popen:
                with self.assertRaises(PrepReviewRequiredError):
                    service.dispatch_plan(run_id)
                popen.assert_not_called()


def _bridge_run(root: Path, *, prep_review: bool):
    workspace = root / "workspace"
    world = create_world(workspace, "Runtime Adapter World")
    run = AutonomousOrchestrator(workspace, world).run(
        workflow="meetup",
        topic="runtime adapter",
        question="Return one bounded candidate.",
        participants=["Observer"],
        rounds=1,
        mode="hermes-bridge",
        prep_review=prep_review,
    )
    return workspace, run.run_id


def _reference_adapter() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "reference_stdio_adapter.py"
