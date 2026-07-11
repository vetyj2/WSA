import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.autonomous_orchestrator import AutonomousOrchestrator
from wsa.hermes_adapter import HERMES_CALLBACK_SCHEMA
from wsa.orchestrator_bridge import OrchestratorBridge
from wsa.orchestrator_turns import choose_participant_contexts
from wsa.workspace import create_world, utc_now


class Phase2ContinuityTests(TestCase):
    def test_rejection_exposes_bounded_retry_guidance_on_same_hook(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world, result = _start_bridge(workspace, ["Council"])
            bridge = OrchestratorBridge(workspace)
            first = bridge.next(result.run_id)
            rejected_text = "REJECTED_OUTPUT_MUST_NOT_REENTER_CONTEXT"
            callback = _write_callback(
                workspace,
                world.world_id,
                first["hook"],
                rejected_text,
                suffix="rejected",
                uncertainty="unlabeled",
                remove_fields=("proposals",),
            )

            submitted = bridge.submit(result.run_id, callback)
            retry = bridge.next(result.run_id)
            context = retry["hook"]["retry_context"]

            self.assertFalse(submitted["accepted"])
            self.assertEqual(retry["next_action"], "retry_current_hermes_hook")
            self.assertEqual(retry["hook"]["turn_id"], first["hook"]["turn_id"])
            self.assertEqual(context["attempt"], 1)
            self.assertEqual(
                context["reason_codes"],
                [
                    "missing_required_fields",
                    "missing_workflow_expected_fields",
                    "unlabeled_uncertainty",
                ],
            )
            self.assertEqual(context["missing_fields"], ["proposals"])
            self.assertEqual(context["missing_required_fields"], ["proposals"])
            self.assertEqual(
                context["missing_expected_fields"],
                ["proposals"],
            )
            self.assertEqual(context["correction_scope"]["supply_fields"], ["proposals"])
            self.assertEqual(
                context["correction_scope"]["set_uncertainty_to_one_of"],
                ["low", "medium", "high"],
            )
            self.assertEqual(
                context["rejected_callback_ref"],
                f"hermes/callbacks/{callback.name}",
            )
            self.assertFalse(context["rejected_output_included"])
            self.assertLess(len(json.dumps(context)), 2000)
            self.assertNotIn(rejected_text, json.dumps(retry))

    def test_retry_context_survives_interrupt_and_resume(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world, result = _start_bridge(workspace, ["Council"])
            bridge = OrchestratorBridge(workspace)
            first = bridge.next(result.run_id)
            rejected_text = "INTERRUPTED_REJECTED_OUTPUT"
            callback = _write_callback(
                workspace,
                world.world_id,
                first["hook"],
                rejected_text,
                suffix="interrupt-reject",
                uncertainty="unlabeled",
            )
            bridge.submit(result.run_id, callback)
            retry_context = bridge.next(result.run_id)["hook"]["retry_context"]

            interrupted = AutonomousOrchestrator.interrupt(
                workspace,
                result.run_id,
                reason="runtime maintenance",
            )
            interrupted_next = bridge.next(result.run_id)
            resumed = AutonomousOrchestrator.resume(workspace, result.run_id)
            resumed_next = bridge.next(result.run_id)

            self.assertEqual(interrupted_next["next_action"], "resume")
            self.assertIsNone(interrupted_next["hook"])
            self.assertEqual(
                interrupted["pending_hooks"][0]["retry_context"],
                retry_context,
            )
            self.assertEqual(
                resumed["pending_hooks"][0]["retry_context"],
                retry_context,
            )
            self.assertEqual(resumed["next_action"], "retry_current_hermes_hook")
            self.assertEqual(
                resumed_next["next_action"],
                "retry_current_hermes_hook",
            )
            self.assertEqual(resumed_next["hook"]["retry_context"], retry_context)
            self.assertNotIn(rejected_text, json.dumps(resumed_next))

    def test_corrected_accept_clears_retry_and_updates_accepted_state_only(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world, result = _start_bridge(workspace, ["Council", "Guild"])
            bridge = OrchestratorBridge(workspace)
            first = bridge.next(result.run_id)
            initial = AutonomousOrchestrator.load_run(workspace, result.run_id)
            rejected_text = "REJECTED_STATE_LEAK_SENTINEL"
            rejected = _write_callback(
                workspace,
                world.world_id,
                first["hook"],
                rejected_text,
                suffix="rejected-state",
                uncertainty="unlabeled",
            )
            bridge.submit(result.run_id, rejected)
            after_reject = AutonomousOrchestrator.load_run(workspace, result.run_id)

            self.assertEqual(after_reject["actor_states"], initial["actor_states"])
            self.assertEqual(after_reject["floor_state"], initial["floor_state"])
            self.assertEqual(after_reject["subsession_outputs"], [])
            self.assertEqual(after_reject["compressed_context_snapshots"], [])

            corrected_text = "Accepted corrected council position."
            corrected = _write_callback(
                workspace,
                world.world_id,
                first["hook"],
                corrected_text,
                suffix="corrected",
            )
            submitted = bridge.submit(result.run_id, corrected)
            after_accept = AutonomousOrchestrator.load_run(workspace, result.run_id)
            next_payload = bridge.next(result.run_id)
            accepted_state = {
                "actor_states": after_accept["actor_states"],
                "floor_state": after_accept["floor_state"],
                "compressed_context_snapshots": after_accept[
                    "compressed_context_snapshots"
                ],
                "subsession_outputs": after_accept["subsession_outputs"],
                "pending_hooks": after_accept["pending_hooks"],
            }

            self.assertTrue(submitted["accepted"])
            self.assertEqual(
                after_accept["actor_states"]["P001"]["last_position"],
                corrected_text,
            )
            self.assertEqual(after_accept["subsession_outputs"][0]["position"], corrected_text)
            self.assertNotIn("retry_context", json.dumps(after_accept))
            self.assertNotIn(rejected_text, json.dumps(accepted_state))
            self.assertEqual(next_payload["next_action"], "run_hermes_hook")
            self.assertEqual(next_payload["hook"]["participant_id"], "P002")
            self.assertNotIn("retry_context", next_payload["hook"])

    def test_participant_chooser_selects_each_supported_signal(self) -> None:
        contexts = _participant_contexts(4)
        cases = [
            (
                "verification",
                {},
                {
                    "verification_queue": [
                        {"participant_id": "P004", "required": True}
                    ]
                },
                "P004",
            ),
            (
                "targeted objection",
                {"P003": {"objections_received": ["Answer the blocking objection."]}},
                {},
                "P003",
            ),
            (
                "owner",
                {},
                {"active_question_owner": {"participant_id": "P002"}},
                "P002",
            ),
            (
                "unanswered question",
                {"P001": {"unanswered_questions": ["Resolve the open question."]}},
                {},
                "P001",
            ),
        ]
        for label, actor_states, floor_state, expected in cases:
            with self.subTest(signal=label):
                selected = choose_participant_contexts(
                    contexts,
                    actor_states,
                    floor_state,
                )
                self.assertEqual(_participant_ids(selected), [expected])

    def test_participant_chooser_uses_stable_priority_order(self) -> None:
        contexts = _participant_contexts(5)
        selected = choose_participant_contexts(
            contexts,
            {"P003": {"objections_received": ["blocking"]}},
            {
                "verification_queue": [{"participant_id": "P004", "required": True}],
                "active_question_owner": "P002",
                "unanswered_questions": [{"participant_id": "P001"}],
            },
        )

        self.assertEqual(_participant_ids(selected), ["P004"])

    def test_participant_chooser_defaults_to_all_participants(self) -> None:
        contexts = _participant_contexts(3)

        no_signal = choose_participant_contexts(contexts, {}, {})
        advisory_only = choose_participant_contexts(
            contexts,
            {},
            {
                "verification_queue": [
                    {
                        "participant_id": "P002",
                        "status": "verification_or_manager_check_recommended",
                    }
                ]
            },
        )

        self.assertEqual(_participant_ids(no_signal), ["P001", "P002", "P003"])
        self.assertEqual(_participant_ids(advisory_only), ["P001", "P002", "P003"])

    def test_local_loop_reduces_calls_for_targeted_metadata(self) -> None:
        class TargetedLocalOrchestrator(AutonomousOrchestrator):
            def _subsession_output(self, context_packet, round_index):
                output = super()._subsession_output(context_packet, round_index)
                if round_index == 1:
                    output["gaps"] = [
                        {
                            "question": "Resolve the shared targeted question.",
                            "owner_participant_id": "P002",
                        }
                    ]
                return output

        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Targeted Local World")
            result = TargetedLocalOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="targeted local selection",
                question="Call only the identified participant on follow-up.",
                participants=["A", "B", "C"],
                rounds=2,
            )
            payload = AutonomousOrchestrator.load_run(workspace, result.run_id)

            self.assertEqual(
                _participant_ids(payload["round_prompt_packets"]),
                ["P001", "P002", "P003", "P002"],
            )
            self.assertEqual(len(payload["subsession_outputs"]), 4)
            self.assertEqual(payload["actor_states"]["P001"]["turn_count"], 1)
            self.assertEqual(payload["actor_states"]["P002"]["turn_count"], 2)
            self.assertEqual(payload["actor_states"]["P003"]["turn_count"], 1)

    def test_bridge_loop_reduces_calls_for_targeted_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world, result = _start_bridge(workspace, ["A", "B", "C"], rounds=2)
            bridge = OrchestratorBridge(workspace)
            next_payload = bridge.next(result.run_id)
            targeted_gap = [
                {
                    "question": "Resolve the shared targeted question.",
                    "owner_participant_id": "P002",
                }
            ]

            for expected in ("P001", "P002", "P003"):
                self.assertEqual(next_payload["hook"]["participant_id"], expected)
                callback = _write_callback(
                    workspace,
                    world.world_id,
                    next_payload["hook"],
                    f"Accepted {expected} position.",
                    suffix=f"round-1-{expected}",
                    extra_output={"gaps": targeted_gap},
                )
                bridge.submit(result.run_id, callback)
                next_payload = bridge.next(result.run_id)

            self.assertEqual(next_payload["hook"]["round"], 2)
            self.assertEqual(next_payload["hook"]["participant_id"], "P002")
            final_callback = _write_callback(
                workspace,
                world.world_id,
                next_payload["hook"],
                "Accepted focused follow-up.",
                suffix="round-2-P002",
                extra_output={"gaps": targeted_gap},
            )
            bridge.submit(result.run_id, final_callback)
            payload = AutonomousOrchestrator.load_run(workspace, result.run_id)

            self.assertEqual(payload["status"], "awaiting_author_review")
            self.assertEqual(
                _participant_ids(payload["round_prompt_packets"]),
                ["P001", "P002", "P003", "P002"],
            )
            self.assertEqual(len(payload["subsession_outputs"]), 4)


def _start_bridge(workspace: Path, participants, rounds: int = 1):
    world = create_world(workspace, "Phase 2 Bridge World")
    result = AutonomousOrchestrator(workspace, world).run(
        workflow="meetup",
        topic="phase 2 continuity",
        question="Preserve accepted-only continuity.",
        participants=participants,
        rounds=rounds,
        mode="hermes-bridge",
        prep_review=False,
    )
    return world, result


def _participant_contexts(count: int):
    return [
        {"participant_id": f"P{index:03d}", "represents": f"Participant {index}"}
        for index in range(1, count + 1)
    ]


def _participant_ids(items):
    return [item["participant_id"] for item in items]


def _write_callback(
    workspace: Path,
    world_id: str,
    hook: dict,
    position: str,
    *,
    suffix: str,
    uncertainty: str = "medium",
    extra_output=None,
    remove_fields=(),
) -> Path:
    callbacks_dir = workspace / "hermes" / "callbacks"
    callbacks_dir.mkdir(parents=True, exist_ok=True)
    callback_stem = f"{hook['turn_id'].replace(':', '_')}_{suffix}"
    callback_path = callbacks_dir / f"{callback_stem}.json"
    output = {
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
    }
    if extra_output:
        output.update(extra_output)
    for field in remove_fields:
        output.pop(field, None)
    callback = {
        "schema": HERMES_CALLBACK_SCHEMA,
        "callback_id": f"callback_{callback_stem}",
        "task_id": f"task_{callback_stem}",
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
            "output": output,
        },
        "artifact_refs": [],
    }
    callback_path.write_text(
        json.dumps(callback, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return callback_path
