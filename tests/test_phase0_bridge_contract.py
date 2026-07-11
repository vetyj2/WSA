import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.orchestrator_bridge import OrchestratorBridge, initialize_bridge_payload
from wsa.orchestrator_turns import build_initial_floor_state
from wsa.orchestrator_workflows import build_workflow_profile, profile_expected_output_fields
from wsa.transport import RuntimeTransport
from wsa.workflow_engine import ExternalCallbackRunner, WorkflowEngine
from wsa.workspace import create_world, utc_now


class Phase0BridgeContractTests(TestCase):
    def test_generated_argv_reference_collect_and_submit_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace, world, run_id = _bridge_fixture(Path(tmp))
            bridge = OrchestratorBridge(workspace)
            next_payload = bridge.next(run_id)
            hook = next_payload["hook"]
            argv = hook["terminal_command"]["argv"]

            self.assertEqual(argv[argv.index("--role") + 1], "orchestrator_subsession")
            task_input = json.loads(argv[argv.index("--input-json") + 1])
            self.assertEqual(task_input["run_id"], run_id)
            self.assertEqual(task_input["turn_id"], hook["turn_id"])
            self.assertEqual(task_input["session_id"], hook["session_id"])
            self.assertEqual(task_input["expected_callback_route"], hook["expected_callback_route"])

            next_path = workspace / "hermes" / "reference_next.json"
            callback_path = workspace / "hermes" / "callbacks" / "reference.json"
            next_path.write_text(json.dumps(next_payload), encoding="utf-8")
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
                env=_cli_env(workspace),
            )

            callback = json.loads(callback_path.read_text(encoding="utf-8"))
            task_path = workspace / "hermes" / "task_archive" / f"{callback['task_id']}.json"
            task = json.loads(task_path.read_text(encoding="utf-8"))
            self.assertEqual(callback["dispatch_receipt"], task["dispatch_receipt"])
            self.assertTrue(callback_path.exists(), "collect must not pre-archive bridge callbacks")

            submitted = bridge.submit(run_id, callback_path)
            self.assertTrue(submitted["accepted"])
            with self.assertRaisesRegex(ValueError, "already submitted"):
                bridge.submit(run_id, callback_path)

    def test_wrong_task_turn_world_and_session_preserve_pending_hook(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace, world, run_id = _bridge_fixture(Path(tmp))
            bridge = OrchestratorBridge(workspace)
            hook = bridge.next(run_id)["hook"]
            task = _dispatch_generated_task(workspace, hook)
            valid = _callback(task, hook)
            cases = (
                ("wrong_task", lambda value: value.update(task_id="forged_task"), "task_id"),
                (
                    "wrong_turn",
                    lambda value: value["payload"].update(turn_id="wrong-turn"),
                    "turn_id",
                ),
                (
                    "wrong_world",
                    lambda value: value["route"].update(world_id="wrong-world"),
                    "world_id",
                ),
                (
                    "wrong_session",
                    lambda value: value["route"].update(session_id="wrong-session"),
                    "session_id",
                ),
            )
            for name, mutate, message in cases:
                callback = json.loads(json.dumps(valid))
                callback["callback_id"] = f"callback_{name}"
                mutate(callback)
                path = workspace / "hermes" / "callbacks" / f"{name}.json"
                path.write_text(json.dumps(callback), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    bridge.submit(run_id, path)
                current = bridge.next(run_id)
                self.assertEqual(current["hook"]["turn_id"], hook["turn_id"])
                self.assertEqual(current["hermes_bridge"]["turn_retry_counts"], {})


def _bridge_fixture(root: Path):
    workspace = root / "workspace"
    world = create_world(workspace, "Phase Zero Bridge World")
    run_id = "orun_phase0_bridge"
    transport = RuntimeTransport(workspace)
    manager_session_id = transport.start_session(
        role="orchestrator_manager",
        world_id=world.world_id,
    )
    session_id = transport.start_session(
        role="orchestrator_subsession",
        world_id=world.world_id,
    )
    profile = build_workflow_profile("meetup", "meetup")
    context = {
        "run_id": run_id,
        "participant_id": "P001",
        "represents": "Observer",
        "session_id": session_id,
        "workflow": "meetup",
        "skill": "meetup",
        "topic": "bridge binding",
        "question": "Return one bounded proposal.",
        "expected_output": profile_expected_output_fields(profile),
    }
    participants = [
        {
            "participant_id": "P001",
            "label": "Observer",
            "role": "representative_voice",
            "workflow_role": "meetup",
        }
    ]
    payload = {
        "schema": "wsa.orchestrator.run.v1",
        "run_id": run_id,
        "status": "awaiting_callback",
        "world_id": world.world_id,
        "workspace_id": "local",
        "workflow": "meetup",
        "skill": "meetup",
        "workflow_profile": profile,
        "topic": context["topic"],
        "question": context["question"],
        "participants": participants,
        "context_packets": [context],
        "queue_limits": {"queue_turns_used": 1, "planned_subsession_calls": 1},
        "prep_review_policy": {"required": False},
        "floor_state": build_initial_floor_state(
            profile,
            context["topic"],
            context["question"],
            participants,
        ),
        "manager_session_id": manager_session_id,
        "subsession_session_ids": [session_id],
        "lifecycle": [{"state": "requested", "at": utc_now()}],
        "world_mutations": [],
        "report_id": None,
    }
    initialize_bridge_payload(payload, world.world_id)
    run_path = world.path / "orchestrator_runs" / run_id / "run.json"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    WorkflowEngine(workspace).register(payload, run_path, ExternalCallbackRunner())
    return workspace, world, run_id


def _dispatch_generated_task(workspace: Path, hook: dict) -> dict:
    argv = hook["terminal_command"]["argv"]
    result = subprocess.run(
        [sys.executable, "-m", "wsa", *argv[1:]],
        cwd=workspace,
        env=_cli_env(workspace),
        check=True,
        capture_output=True,
        text=True,
    )
    task_ref = next(
        line.split(": ", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("task_path: ")
    )
    return json.loads((workspace / task_ref).read_text(encoding="utf-8"))


def _callback(task: dict, hook: dict) -> dict:
    output = {
        "position": "Bound reference position.",
        "stance": "provisional",
        "answer": "Bound reference answer.",
        "new_claims": [],
        "objections": ["Keep proposal-only."],
        "dependencies": ["Author review."],
        "conflicts": [],
        "worldbuilding_use": "candidate",
        "confidence": "medium",
        "next_actor_suggestion": "none",
        "uncertainty": "medium",
        "gaps": ["Needs review."],
        "proposals": ["Review this callback."],
    }
    return {
        "schema": "wsa.hermes.callback.v1",
        "callback_id": "callback_valid",
        "task_id": task["task_id"],
        "workspace_id": task["workspace"]["workspace_id"],
        "created_at": utc_now(),
        "status": "completed",
        "route": task["route"],
        "dispatch_receipt": task["dispatch_receipt"],
        "payload": {"run_id": hook["run_id"], "turn_id": hook["turn_id"], "output": output},
        "artifact_refs": [],
    }


def _cli_env(workspace: Path) -> dict:
    env = dict(os.environ)
    env["WSA_WORKSPACE"] = str(workspace)
    source = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (source, env.get("PYTHONPATH", "")) if item
    )
    return env
