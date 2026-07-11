from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from wsa.run_store import (
    ConcurrentRunUpdateError,
    ProjectionWriteError,
    RunStore,
)
from wsa.workflow_engine import (
    DeterministicMockRunner,
    ExternalCallbackRunner,
    WorkflowEngine,
)
from wsa.workspace import create_world


class WorkflowEngineTests(TestCase):
    def test_mock_and_callback_runners_share_run_state_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Workflow World")
            engine = WorkflowEngine(workspace)
            cases = (
                (
                    "run_mock",
                    "awaiting_author_review",
                    DeterministicMockRunner(),
                    "author_review",
                ),
                (
                    "run_callback",
                    "awaiting_callback",
                    ExternalCallbackRunner(),
                    "run_next_hermes_hook",
                ),
            )

            for run_id, status, runner, next_action in cases:
                run_path = world.path / "orchestrator_runs" / run_id / "run.json"
                record = engine.register(
                    {
                        "run_id": run_id,
                        "world_id": world.world_id,
                        "workflow": "meetup",
                        "status": status,
                    },
                    run_path,
                    runner,
                )

                self.assertEqual(record.payload["workflow_state"]["schema"], "wsa.workflow.state.v1")
                self.assertEqual(record.payload["workflow_state"]["next_action"], next_action)
                self.assertEqual(record.projection_status, "current")
                self.assertTrue(run_path.exists())

    def test_interrupt_resume_and_close_preserve_pending_run(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Resume World")
            engine = WorkflowEngine(workspace)
            run_path = world.path / "orchestrator_runs" / "run_resume" / "run.json"
            engine.register(
                {
                    "run_id": "run_resume",
                    "world_id": world.world_id,
                    "workflow": "meetup",
                    "status": "awaiting_callback",
                    "pending_hooks": [{"turn_id": "turn-1"}],
                },
                run_path,
                ExternalCallbackRunner(),
            )

            interrupted = engine.interrupt("run_resume", "maintenance")
            resumed = engine.resume("run_resume")
            closed = engine.close("run_resume", "done")

            self.assertEqual(interrupted.status, "interrupted")
            self.assertEqual(resumed.status, "awaiting_callback")
            self.assertEqual(resumed.payload["pending_hooks"][0]["turn_id"], "turn-1")
            self.assertEqual(closed.status, "closed")
            self.assertEqual(closed.payload["close_reason"], "done")

    def test_stale_run_revision_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "CAS World")
            engine = WorkflowEngine(workspace)
            record = engine.register(
                {
                    "run_id": "run_cas",
                    "world_id": world.world_id,
                    "workflow": "meetup",
                    "status": "awaiting_callback",
                },
                world.path / "orchestrator_runs" / "run_cas" / "run.json",
                ExternalCallbackRunner(),
            )
            payload = dict(record.payload)
            engine.update(payload, expected_revision=record.revision)

            with self.assertRaises(ConcurrentRunUpdateError):
                RunStore(workspace).save(
                    "run_cas",
                    payload,
                    expected_revision=record.revision,
                )

    def test_projection_failure_is_repairable_from_sqlite_state(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Projection World")
            store = RunStore(workspace)
            run_path = world.path / "orchestrator_runs" / "run_projection" / "run.json"
            payload = {
                "run_id": "run_projection",
                "world_id": world.world_id,
                "workflow": "meetup",
                "status": "awaiting_callback",
            }

            with patch("wsa.run_store.atomic_write_json", side_effect=OSError("disk full")):
                with self.assertRaises(ProjectionWriteError):
                    store.register(payload, run_path, ExternalCallbackRunner())

            failed = store.get("run_projection")
            self.assertEqual(failed.projection_status, "failed")
            self.assertEqual(failed.payload["status"], "awaiting_callback")
            repaired = store.repair_projection("run_projection")
            self.assertEqual(repaired.projection_status, "current")
            self.assertTrue(run_path.exists())

    def test_callback_receipt_blocks_replay_even_without_projection_state(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Callback Receipt World")
            engine = WorkflowEngine(workspace)
            engine.register(
                {
                    "run_id": "run_callback_receipt",
                    "world_id": world.world_id,
                    "workflow": "meetup",
                    "status": "awaiting_callback",
                },
                world.path / "orchestrator_runs" / "receipt" / "run.json",
                ExternalCallbackRunner(),
            )
            store = RunStore(workspace)
            callback = {"callback_id": "callback-1", "output": {"position": "one"}}
            store.claim_callback(
                "callback-1",
                "hermes/callbacks/callback-1.json",
                "run_callback_receipt",
                "turn-1",
                callback,
            )

            with self.assertRaises(ValueError):
                store.claim_callback(
                    "callback-1",
                    "hermes/callbacks/callback-1-copy.json",
                    "run_callback_receipt",
                    "turn-1",
                    callback,
                )
