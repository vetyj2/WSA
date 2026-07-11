import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.autonomous_orchestrator import AutonomousOrchestrator
from wsa.hermes_adapter import HERMES_CALLBACK_SCHEMA
from wsa.meeting import MeetingOrchestrator
from wsa.orchestrator_bridge import OrchestratorBridge
from wsa.report_exports import REPORT_EXPORT_ARTIFACT_TYPES, build_report_export
from wsa.repositories import WorldRepository
from wsa.scene_modes import build_scene_mode_disclosure
from wsa.transport import RuntimeTransport
from wsa.workspace import create_world, utc_now


class Phase0ExecutionProvenanceTests(TestCase):
    def test_meeting_mock_is_explicit_in_result_transcript_report_and_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Meeting Provenance World")
            repo = WorldRepository(world.world_id, world.path)

            result = MeetingOrchestrator(workspace, world).run_meeting(
                topic="Mock disclosure",
                question="What produced this meeting?",
                participants=["Council"],
            )
            transcript = json.loads(result.transcript_path.read_text(encoding="utf-8"))
            report = repo.get_report(result.report_id)
            summary = RuntimeTransport(workspace).list_envelopes(
                result.manager_session_id,
                "outbox",
            )[0]

            self.assertEqual(result.runtime_target, "meeting:mock")
            self.assertEqual(result.execution_mode, "deterministic_mock")
            self.assertEqual(transcript["runtime_target"], "meeting:mock")
            self.assertEqual(transcript["execution_mode"], "deterministic_mock")
            self.assertTrue(transcript["execution_provenance"]["local_simulated_output"])
            self.assertEqual(report.payload["runtime_target"], "meeting:mock")
            self.assertEqual(report.payload["execution_mode"], "deterministic_mock")
            self.assertEqual(summary.payload["runtime_target"], "meeting:mock")
            self.assertEqual(summary.payload["execution_mode"], "deterministic_mock")

    def test_default_orchestrator_discloses_deterministic_local_outputs_everywhere(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Local Provenance World")
            repo = WorldRepository(world.world_id, world.path)

            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="Local execution",
                question="Where did these outputs come from?",
                participants=["Council"],
                rounds=1,
            )
            payload = AutonomousOrchestrator.load_run(workspace, result.run_id)
            report = repo.get_report(result.report_id)
            projection = json.loads(result.run_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["subsession_execution_mode"], "local_simulated_outputs")
            self.assertEqual(payload["execution_mode"], "deterministic_mock")
            self.assertEqual(
                payload["execution_provenance"]["legacy_execution_mode"],
                "local-simulated",
            )
            self.assertEqual(
                payload["execution_provenance"]["output_origin"],
                "wsa_local_deterministic_simulation",
            )
            self.assertIn("deterministic mock", payload["synthesis"]["summary"])
            self.assertEqual(
                payload["actor_contribution_summary"]["execution_mode"],
                "deterministic_mock",
            )
            self.assertEqual(report.payload["execution_mode"], "deterministic_mock")
            self.assertEqual(projection["execution_mode"], "deterministic_mock")
            self.assertEqual(result.execution_mode, "deterministic_mock")

            for artifact_type in REPORT_EXPORT_ARTIFACT_TYPES:
                export = build_report_export(world, result.run_id, artifact_type, "txt")
                self.assertEqual(export["execution_mode"], "deterministic_mock")
                self.assertIn("Execution mode: deterministic_mock", export["content"])

    def test_external_mode_waits_until_a_real_callback_is_recorded(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "External Provenance World")
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="meetup",
                topic="External execution",
                question="Has an external callback arrived?",
                participants=["Council"],
                rounds=1,
                mode="hermes-bridge",
                prep_review=False,
            )
            waiting = AutonomousOrchestrator.load_run(workspace, result.run_id)

            self.assertEqual(waiting["execution_mode"], "external_waiting")
            self.assertFalse(waiting["execution_provenance"]["external_runtime_confirmed"])
            self.assertEqual(result.execution_mode, "external_waiting")

            bridge = OrchestratorBridge(workspace)
            hook = bridge.next(result.run_id)["hook"]
            callback_path = _write_callback(workspace, world.world_id, hook)
            submitted = bridge.submit(result.run_id, callback_path)
            confirmed = AutonomousOrchestrator.load_run(workspace, result.run_id)
            export = build_report_export(
                world,
                result.run_id,
                "human_session_minutes",
                "txt",
            )

            self.assertTrue(submitted["accepted"])
            self.assertEqual(confirmed["execution_mode"], "external_confirmed")
            self.assertTrue(confirmed["execution_provenance"]["external_runtime_confirmed"])
            self.assertEqual(
                confirmed["execution_provenance"]["external_confirmation_basis"],
                "submitted_callback_records",
            )
            self.assertEqual(export["execution_mode"], "external_confirmed")
            self.assertIn("Execution mode: external_confirmed", export["content"])

    def test_scene_auto_records_wsa_fixed_fallback_as_the_effective_source(self) -> None:
        disclosure = build_scene_mode_disclosure(
            "scene_generation",
            "scene_start",
            "auto",
        )

        self.assertEqual(
            disclosure["mode_resolution_source"],
            "fallback_until_hermes_or_profile_reports_mode",
        )
        self.assertEqual(disclosure["mode_resolution_source_normalized"], "fixed_fallback")
        self.assertEqual(disclosure["effective_mode_source"], "fixed_fallback")
        self.assertEqual(disclosure["mode_resolution_owner"], "wsa_fixed_fallback_policy")
        self.assertFalse(disclosure["hermes_or_profile_selected"])
        self.assertEqual(disclosure["fallback_mode"], "fact_audit_synthesis")


def _write_callback(workspace: Path, world_id: str, hook: dict) -> Path:
    callback_dir = workspace / "hermes" / "callbacks"
    callback_dir.mkdir(parents=True, exist_ok=True)
    callback_id = hook["turn_id"].replace(":", "_")
    path = callback_dir / f"callback_{callback_id}.json"
    position = "External callback supplied a bounded proposal."
    payload = {
        "schema": HERMES_CALLBACK_SCHEMA,
        "callback_id": f"callback_{callback_id}",
        "task_id": f"task_{callback_id}",
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
                "uncertainty": "medium",
            },
        },
        "artifact_refs": [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
