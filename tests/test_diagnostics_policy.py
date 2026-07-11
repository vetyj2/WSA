import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from wsa.diagnostics import run_world_detectors
from wsa.diagnostics_policy import (
    DIAGNOSTICS_POLICY_SCHEMA,
    DiagnosticsPolicyValidationError,
    diagnostics_policy_path,
    load_diagnostics_policy,
    parse_diagnostics_policy,
)
from wsa.manager import WorldManager
from wsa.repositories import WorldRepository
from wsa.workspace import create_world, sqlite_connection, world_db_path


class DiagnosticsPolicyTests(TestCase):
    def test_fresh_world_has_no_policy_or_conflict_false_positive(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Fresh Policy World")
            repo = WorldRepository(world.world_id, world.path)

            load_result = load_diagnostics_policy(world.path)

            self.assertEqual(load_result.status, "absent")
            self.assertIsNone(load_result.issue)
            self.assertFalse(load_result.path.exists())
            self.assertEqual(run_world_detectors(repo, policy=load_result.policy), [])

    def test_multi_affiliation_is_allowed_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Multi Affiliation World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")
            for faction in ("A", "B"):
                repo.add_world_edge(
                    "entity",
                    actor.entity_id,
                    "affiliated_with",
                    "faction",
                    object_value=faction,
                    status="canon",
                )

            findings = run_world_detectors(repo)

            self.assertNotIn(
                "affiliated_with",
                {finding.predicate for finding in findings},
            )
    def test_world_policy_can_make_affiliation_a_warning_singleton(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Singleton Affiliation World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")
            for faction in ("A", "B"):
                repo.add_world_edge(
                    "entity",
                    actor.entity_id,
                    "affiliated_with",
                    "faction",
                    object_value=faction,
                    status="canon",
                )
            policy_path = diagnostics_policy_path(world.path)
            policy_path.write_text(
                json.dumps(
                    {
                        "schema": DIAGNOSTICS_POLICY_SCHEMA,
                        "edge_policies": {
                            "affiliated_with": {
                                "cardinality": "singleton",
                                "severity": "warning",
                                "interval_policy": "overlap",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            findings = WorldManager(workspace).run_diagnostics()
            conflict = next(
                finding
                for finding in findings
                if finding.finding_type == "singleton_edge_overlap"
            )

            self.assertEqual(conflict.severity, "warning")
            self.assertEqual(conflict.policy_source, str(policy_path))
            self.assertTrue(conflict.why_it_matters)
            self.assertTrue(conflict.suggested_action)
            self.assertTrue(conflict.fingerprint)
            self.assertTrue(conflict.summary)

    def test_invalid_policy_is_actionable_and_never_persisted(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Invalid Policy World")
            policy_path = diagnostics_policy_path(world.path)
            original = {
                "schema": DIAGNOSTICS_POLICY_SCHEMA,
                "edge_policies": {
                    "affiliated_with": {
                        "cardinality": "singleton",
                        "severity": "urgent",
                        "interval_policy": "overlap",
                    }
                },
            }
            policy_path.write_text(json.dumps(original), encoding="utf-8")
            original_bytes = policy_path.read_bytes()

            findings = WorldManager(workspace).run_diagnostics(record_findings=True)
            invalid = next(
                finding
                for finding in findings
                if finding.finding_type == "invalid_diagnostics_policy"
            )
            with sqlite_connection(world_db_path(world.path)) as conn:
                diagnostic_count = conn.execute(
                    "SELECT COUNT(*) FROM diagnostic_logs"
                ).fetchone()[0]

            self.assertEqual(invalid.severity, "warning")
            self.assertIn("ignored", invalid.detail)
            self.assertIn(str(policy_path), invalid.suggested_action)
            self.assertEqual(invalid.policy_source, str(policy_path))
            self.assertEqual(policy_path.read_bytes(), original_bytes)
            self.assertEqual(diagnostic_count, 0)

    def test_policy_validation_checks_schema_cardinality_severity_and_interval(self) -> None:
        valid_rule = {
            "cardinality": "singleton",
            "severity": "warning",
            "interval_policy": "overlap",
        }
        invalid_payloads = [
            {
                "schema": "wsa.diagnostics.policy.v0",
                "edge_policies": {"affiliated_with": valid_rule},
            },
            {
                "schema": DIAGNOSTICS_POLICY_SCHEMA,
                "edge_policies": {
                    "affiliated_with": {**valid_rule, "cardinality": "sometimes"}
                },
            },
            {
                "schema": DIAGNOSTICS_POLICY_SCHEMA,
                "edge_policies": {
                    "affiliated_with": {**valid_rule, "severity": "urgent"}
                },
            },
            {
                "schema": DIAGNOSTICS_POLICY_SCHEMA,
                "edge_policies": {
                    "affiliated_with": {**valid_rule, "interval_policy": "touching"}
                },
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(DiagnosticsPolicyValidationError):
                    parse_diagnostics_policy(payload)

    def test_root_grouping_and_correction_preview_are_ticket_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            world = create_world(workspace, "Actionable Conflict World")
            repo = WorldRepository(world.world_id, world.path)
            actor = repo.create_entity("character", "Nia")
            repo.create_fact(actor.entity_id, "location", "north", status="canon")
            repo.create_fact(actor.entity_id, "location", "south", status="proposed")

            conflict = next(
                finding
                for finding in WorldManager(workspace).run_diagnostics()
                if finding.finding_type == "explicit_contradiction"
            )
            assert conflict.correction_preview is not None
            option = conflict.correction_preview["options"][0]

            self.assertEqual(
                option["change_set"]["schema"],
                "wsa.ticket.changes.v1",
            )
            self.assertEqual(option["change_set"]["changes"], option["changes"])
            self.assertEqual(option["ticket_input"]["changes"], option["changes"])
            self.assertEqual(
                option["ticket_input"]["source_ref"],
                f"diagnostic:{conflict.fingerprint}",
            )
