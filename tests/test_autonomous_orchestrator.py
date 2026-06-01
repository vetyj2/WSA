import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.autonomous_orchestrator import AutonomousOrchestrator
from wsa.hermes_adapter import HERMES_CALLBACK_SCHEMA
from wsa.orchestrator_bridge import OrchestratorBridge
from wsa.repositories import ControlRepository, WorldRepository
from wsa.workspace import create_world, utc_now


class AutonomousOrchestratorTests(TestCase):
    def test_manual_trigger_runs_autonomous_subsessions_to_review_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Orchestrator World")
            repo = WorldRepository(world.world_id, world.path)
            university = repo.create_entity("institution", "North University")
            repo.create_fact(
                university.entity_id,
                "teaches",
                "contract magic",
                authority="user_explicit",
                status="canon",
            )

            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="seven universities and the three major magic schools",
                question="Map tensions and candidate structures.",
                participants=["North University", "Unregistered School"],
                rounds=3,
            )
            payload = json.loads(result.run_path.read_text(encoding="utf-8"))
            control = ControlRepository(workspace)

            self.assertEqual(payload["schema"], "wsa.orchestrator.run.v1")
            self.assertEqual(payload["status"], "awaiting_author_review")
            self.assertEqual(payload["execution"], "autonomous_until_boundary")
            self.assertEqual(payload["subsession_execution_mode"], "local_simulated_outputs")
            self.assertEqual(payload["execution_owner"], "user_hermes_runtime")
            self.assertEqual(
                payload["wsa_role"],
                "orchestration_contract_and_audit_artifacts_only",
            )
            self.assertEqual(payload["skill"], "meetup")
            self.assertEqual(payload["workflow_profile"]["workflow"], "meetup")
            self.assertTrue(payload["workflow_profile"]["dynamic_facilitation_hooks"])
            self.assertIn("floor_state", payload)
            self.assertEqual(payload["floor_state"]["workflow"], "meetup")
            self.assertTrue(
                any(
                    item["turn_type"] == "orchestrator_turn"
                    for item in payload["turn_records"]
                )
            )
            self.assertTrue(
                any(item["turn_type"] == "actor_turn" for item in payload["turn_records"])
            )
            self.assertEqual(
                payload["session_contract"]["active_facilitation"][
                    "may_pause_actor_for_manager_check"
                ],
                True,
            )
            self.assertEqual(payload["plan"]["round_budget"], 3)
            self.assertEqual(payload["plan_frame"]["source"], "default_guardrail")
            self.assertEqual(payload["start_preflight"]["status"], "ready")
            self.assertEqual(payload["queue_limits"]["max_queue_turns"], 12)
            self.assertEqual(payload["queue_limits"]["max_subsession_calls"], 48)
            self.assertEqual(payload["queue_limits"]["planned_subsession_calls"], 6)
            self.assertEqual(payload["queue_limits"]["queue_turns_used"], 3)
            self.assertEqual(
                payload["session_contract"]["skill_scope"]["isolation"],
                "per_orchestrator_run",
            )
            self.assertEqual(
                payload["floor_continuity"]["model"],
                "live_meeting_floor",
            )
            self.assertEqual(
                payload["micro_turn_policy"]["utterance_target"],
                "one_sentence_or_requested_fields",
            )
            self.assertTrue(payload["accepted_outputs_only"])
            self.assertTrue(
                payload["context_continuity"]["carry_forward_between_queue_turns"]
            )
            self.assertEqual(len(payload["context_packets"]), 2)
            self.assertIn("prompt_packet", payload["context_packets"][0])
            self.assertEqual(len(payload["compressed_context_snapshots"]), 3)
            self.assertEqual(len(payload["round_prompt_packets"]), 6)
            self.assertEqual(len(payload["runtime_hook_packets"]), 6)
            self.assertIn("terminal_command", payload["runtime_hook_packets"][0])
            self.assertIn("--task-type", payload["runtime_hook_packets"][0]["terminal_command"]["argv"])
            self.assertEqual(len(payload["subsession_outputs"]), 6)
            self.assertTrue(
                all(
                    output["quality_gate"]["accepted"]
                    for output in payload["subsession_outputs"]
                )
            )
            self.assertEqual(payload["world_mutations"], [])
            self.assertTrue(payload["approval_options"])
            self.assertEqual(repo.get_report(result.report_id).purpose, "orchestrator_run")
            self.assertEqual(repo.list_tickets(), [])
            for session_id in result.subsession_session_ids:
                self.assertEqual(control.get_runtime_session(session_id).status, "closed")

    def test_hermes_bridge_next_submit_loop_reaches_author_review(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Bridge World")
            repo = WorldRepository(world.world_id, world.path)

            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="council bridge pass",
                question="Collect Hermes-backed participant output.",
                participants=["Council"],
                rounds=2,
                mode="hermes-bridge",
            )
            bridge = OrchestratorBridge(workspace)
            first_next = bridge.next(result.run_id)

            self.assertEqual(result.report_id, "")
            self.assertEqual(first_next["status"], "awaiting_callback")
            self.assertEqual(first_next["execution_status"], "waiting_for_hermes")
            self.assertEqual(first_next["hook"]["round"], 1)
            self.assertEqual(first_next["hook"]["participant_id"], "P001")

            first_callback = _write_bridge_callback(
                workspace,
                world.world_id,
                first_next["hook"],
                "Bridge output round one.",
                uncertainty="medium",
            )
            first_submit = bridge.submit(result.run_id, first_callback)
            second_next = bridge.next(result.run_id)

            self.assertTrue(first_submit["accepted"])
            self.assertEqual(first_submit["status"], "awaiting_callback")
            self.assertEqual(second_next["hook"]["round"], 2)
            self.assertIn("Bridge round 1 accepted", second_next["hook"]["prompt"])

            second_callback = _write_bridge_callback(
                workspace,
                world.world_id,
                second_next["hook"],
                "Bridge output round two.",
                uncertainty="low",
            )
            second_submit = bridge.submit(result.run_id, second_callback)
            final_payload = AutonomousOrchestrator.load_run(workspace, result.run_id)

            self.assertTrue(second_submit["accepted"])
            self.assertEqual(second_submit["status"], "awaiting_author_review")
            self.assertEqual(second_submit["execution_status"], "completed_by_hermes")
            self.assertEqual(final_payload["subsession_execution_mode"], "hermes_bridge_pending_callbacks")
            self.assertEqual(final_payload["execution_status"], "completed_by_hermes")
            self.assertEqual(len(final_payload["subsession_outputs"]), 2)
            self.assertEqual(len(final_payload["submitted_callbacks"]), 2)
            self.assertEqual(final_payload["pending_hooks"], [])
            self.assertTrue(final_payload["report_id"])
            self.assertEqual(repo.get_report(final_payload["report_id"]).purpose, "orchestrator_run")
            self.assertEqual(repo.list_facts(), [])
            control = ControlRepository(workspace)
            for session_id in result.subsession_session_ids:
                self.assertEqual(control.get_runtime_session(session_id).status, "closed")
            self.assertEqual(
                control.get_runtime_session(result.manager_session_id).status,
                "awaiting_author_review",
            )

    def test_hermes_bridge_rejects_external_callback_path(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Bridge Path World")
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="path check",
                question="Check callback path.",
                participants=["Council"],
                rounds=1,
                mode="hermes-bridge",
            )
            outside = Path(tmp) / "outside.json"
            outside.write_text("{}", encoding="utf-8")

            with self.assertRaises(ValueError):
                OrchestratorBridge(workspace).submit(result.run_id, outside)

    def test_hermes_bridge_requires_callback_world_route(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Bridge Route World")
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="route check",
                question="Check callback route.",
                participants=["Council"],
                rounds=1,
                mode="hermes-bridge",
            )
            bridge = OrchestratorBridge(workspace)
            next_payload = bridge.next(result.run_id)
            callback = _write_bridge_callback(
                workspace,
                world.world_id,
                next_payload["hook"],
                "Route test output.",
            )
            payload = json.loads(callback.read_text(encoding="utf-8"))
            payload.pop("route")
            callback.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                bridge.submit(result.run_id, callback)

    def test_hermes_bridge_rejected_callback_keeps_hook_pending(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Bridge Reject World")
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="quality check",
                question="Check rejected callback.",
                participants=["Council"],
                rounds=1,
                mode="hermes-bridge",
            )
            bridge = OrchestratorBridge(workspace)
            next_payload = bridge.next(result.run_id)
            callback = _write_bridge_callback(
                workspace,
                world.world_id,
                next_payload["hook"],
                "Rejected output.",
                uncertainty="unlabeled",
            )

            submitted = bridge.submit(result.run_id, callback)
            run_payload = AutonomousOrchestrator.load_run(workspace, result.run_id)

            self.assertFalse(submitted["accepted"])
            self.assertEqual(submitted["execution_status"], "callback_retry_required")
            self.assertEqual(submitted["pending_hook_count"], 1)
            self.assertEqual(run_payload["subsession_outputs"], [])
            self.assertEqual(run_payload["pending_hooks"][0]["turn_id"], next_payload["hook"]["turn_id"])
            self.assertEqual(run_payload["rejected_callbacks"][0]["turn_id"], next_payload["hook"]["turn_id"])
            self.assertIsNone(run_payload["report_id"])

    def test_scene_generation_workflow_records_scene_prep_lifecycle(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Scene Prep World")

            result = AutonomousOrchestrator(workspace, world).run(
                workflow="scene_start",
                topic="opening scene at the flooded station",
                question="Prepare actor packets and scene-prep decisions.",
                participants=["Narrator", "Crowd extras"],
                rounds=2,
                skill="scene_start",
            )
            payload = json.loads(result.run_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["workflow"], "scene_generation")
            self.assertEqual(payload["workflow_requested"], "scene_start")
            self.assertEqual(payload["workflow_profile"]["workflow"], "scene_generation")
            self.assertIn("actor_session_policy", payload["workflow_profile"])
            self.assertEqual(payload["floor_state"]["workflow"], "scene_generation")
            self.assertEqual(payload["floor_state"]["conclusion_status"], "author_review_ready")
            self.assertTrue(
                any(
                    item["phase_id"] == "actor_assignment"
                    for item in payload["workflow_profile"]["phase_model"]
                )
            )
            self.assertIn(
                "role_isolation",
                payload["context_packets"][0]["expected_output"],
            )
            self.assertIn(
                "model_thinking_recommendation",
                payload["subsession_outputs"][0],
            )
            self.assertIn(
                "orchestrator_scene_generation_actor_turn",
                payload["runtime_hook_packets"][0]["terminal_command"]["argv"],
            )
            self.assertTrue(
                any(
                    item["turn_type"] == "manager_check_turn"
                    for item in payload["turn_records"]
                )
            )

    def test_max_queue_turns_caps_autonomous_rounds_and_returns_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Orchestrator Queue World")

            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                skill="scene_start",
                topic="new frontier district",
                question="Find useful candidate details.",
                participants=["District Voice"],
                rounds=5,
                max_queue_turns=2,
                max_subsession_calls=10,
            )
            payload = json.loads(result.run_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["skill"], "scene_start")
            self.assertEqual(payload["queue_limits"]["rounds_requested"], 5)
            self.assertEqual(payload["queue_limits"]["max_queue_turns"], 2)
            self.assertEqual(payload["queue_limits"]["max_subsession_calls"], 10)
            self.assertEqual(payload["queue_limits"]["queue_turns_used"], 2)
            self.assertTrue(payload["queue_limits"]["budget_exhausted"])
            self.assertEqual(len(payload["subsession_outputs"]), 2)
            self.assertEqual(len(payload["compressed_context_snapshots"]), 2)
            self.assertIn(
                "max_queue_turns_reached_before_requested_rounds",
                payload["conflict_gap_diagnosis"]["author_boundary_reasons"],
            )

    def test_user_frame_and_concurrency_limits_are_recorded(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Orchestrator Frame World")

            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="council factions",
                question="Find a frame.",
                participants=["A", "B", "C"],
                rounds=2,
                frame_plan="Use only council agenda items already named by the author.",
                max_concurrent_subsessions=2,
            )
            payload = json.loads(result.run_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["plan_frame"]["source"], "user_defined")
            self.assertTrue(payload["concurrency_policy"]["batching_required"])
            self.assertEqual(payload["concurrency_policy"]["max_concurrent_subsessions"], 2)
            self.assertEqual(payload["concurrency_policy"]["batches"], [["P001", "P002"], ["P003"]])
            self.assertEqual(
                payload["session_cleanup"]["ephemeral_session_policy"],
                "no_abandoned_open_subsessions",
            )

    def test_approving_orchestrator_run_creates_candidate_ticket_only(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Orchestrator Decision World")
            repo = WorldRepository(world.world_id, world.path)
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="academy factions",
                question="Draft options.",
                participants=["Council"],
                rounds=1,
            )

            decision = AutonomousOrchestrator.decide(
                workspace,
                result.run_id,
                decision="approve",
                option="option-a",
            )

            tickets = repo.list_tickets()
            self.assertEqual(decision.report_status, "approved")
            self.assertEqual(decision.ticket, tickets[0])
            self.assertEqual(tickets[0].ticket_type, "orchestrator_candidate")
            self.assertEqual(tickets[0].payload["apply_policy"], "requires_explicit_change_ticket")
            self.assertEqual(repo.list_facts(), [])

    def test_orchestrator_rejects_unsupported_canon_policy(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Orchestrator Policy World")

            with self.assertRaises(ValueError):
                AutonomousOrchestrator(workspace, world).run(
                    workflow="meetup",
                    topic="academy factions",
                    question="Draft options.",
                    participants=["Council"],
                    canon_policy="approval-to-canon",
                )

    def test_orchestrator_blocks_when_participants_exceed_call_limit(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Orchestrator Limit World")

            with self.assertRaises(ValueError):
                AutonomousOrchestrator(workspace, world).run(
                    workflow="meetup",
                    topic="too many voices",
                    question="Draft options.",
                    participants=["A", "B", "C"],
                    rounds=1,
                    max_subsession_calls=2,
                )

    def test_approve_requires_known_option(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Orchestrator Option World")
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="academy factions",
                question="Draft options.",
                participants=["Council"],
                rounds=1,
            )

            with self.assertRaises(ValueError):
                AutonomousOrchestrator.decide(
                    workspace,
                    result.run_id,
                    decision="approve",
                )

            with self.assertRaises(ValueError):
                AutonomousOrchestrator.decide(
                    workspace,
                    result.run_id,
                    decision="approve",
                    option="unknown-option",
                )

    def test_close_marks_run_closed_without_canon_mutation(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Orchestrator Close World")
            repo = WorldRepository(world.world_id, world.path)
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="subsession",
                topic="magic tool economy",
                question="Find gaps.",
                participants=[],
                rounds=1,
            )

            closed = AutonomousOrchestrator.close(workspace, result.run_id, reason="done")

            self.assertEqual(closed["status"], "closed")
            self.assertEqual(closed["close_reason"], "done")
            self.assertEqual(repo.list_facts(), [])


def _write_bridge_callback(
    workspace: Path,
    world_id: str,
    hook: dict,
    position: str,
    uncertainty: str = "medium",
) -> Path:
    callbacks_dir = workspace / "hermes" / "callbacks"
    callbacks_dir.mkdir(parents=True, exist_ok=True)
    path = callbacks_dir / f"{hook['turn_id'].replace(':', '_')}.json"
    payload = {
        "schema": HERMES_CALLBACK_SCHEMA,
        "callback_id": f"callback_{hook['turn_id'].replace(':', '_')}",
        "task_id": f"task_{hook['turn_id'].replace(':', '_')}",
        "workspace_id": "local",
        "created_at": utc_now(),
        "status": "completed",
            "route": {
                "world_id": world_id,
                "scene_id": None,
                "session_id": hook["session_id"],
                "role": "orchestrator_subsession",
            },
        "payload": {
            "turn_id": hook["turn_id"],
            "output": {
                "position": position,
                "stance": "support_with_conditions",
                "answer": position,
                "new_claims": [],
                "objections": ["Keep this proposal-only."],
                "dependencies": ["Author approval."],
                "conflicts": [],
                "worldbuilding_use": "candidate material",
                "confidence": "medium",
                "next_actor_suggestion": "none",
                "proposals": ["Carry this into the review package."],
                "gaps": ["Needs author review."],
                "uncertainty": uncertainty,
            },
        },
        "artifact_refs": [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
