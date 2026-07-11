import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.autonomous_orchestrator import AutonomousOrchestrator
from wsa.contract_registry import expand_contract_reference
from wsa.workspace import create_world


class ContractRegistryTests(TestCase):
    def test_compact_scene_run_reduces_artifacts_and_refs_expand_exactly(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Compact Contract World")
            result = AutonomousOrchestrator(workspace, world).run(
                workflow="scene_generation",
                topic="blank",
                question="prepare",
                participants=["Observer"],
                rounds=1,
                mode="hermes-bridge",
                prep_review=False,
            )
            projection = json.loads(result.run_path.read_text(encoding="utf-8"))
            full = AutonomousOrchestrator.load_run(workspace, result.run_id)
            total_bytes = sum(path.stat().st_size for path in result.run_dir.glob("*.json"))

            self.assertEqual(
                projection["projection_schema"],
                "wsa.orchestrator.run_projection.v2",
            )
            self.assertLess(total_bytes, 64 * 1024)
            self.assertNotIn("session_contract", projection)
            self.assertNotIn("plan", projection)
            self.assertEqual(
                expand_contract_reference(projection["contract_refs"]["session_contract"]),
                full["session_contract"],
            )
            self.assertEqual(
                expand_contract_reference(projection["contract_refs"]["workflow_profile"]),
                full["workflow_profile"],
            )
            self.assertEqual(
                expand_contract_reference(
                    projection["contract_refs"]["reporting_artifact_contract"]
                ),
                full["reporting_artifact_contract"],
            )
            self.assertEqual(
                expand_contract_reference(projection["contract_refs"]["scene_mode_disclosure"]),
                full["scene_mode_disclosure"],
            )
