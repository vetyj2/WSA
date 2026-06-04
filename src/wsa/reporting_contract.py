from __future__ import annotations

from typing import Any, Dict, List


REPORTING_ARTIFACT_CONTRACT_SCHEMA = "wsa.reporting.artifact_contract.v1"
REPORTING_ARTIFACT_MANIFEST_SCHEMA = "wsa.reporting.artifact_manifest.v1"
SUPPORTED_REPORT_EXPORT_FORMATS = ["txt", "html"]


def build_reporting_artifact_contract(
    workflow: str | None = None,
    skill: str | None = None,
) -> Dict[str, Any]:
    """Describe recommended report exports without forcing runtime delivery behavior."""

    return {
        "schema": REPORTING_ARTIFACT_CONTRACT_SCHEMA,
        "workflow": workflow,
        "skill": skill,
        "owner": "user_runtime",
        "delivery_owner": "user_hermes_runtime",
        "wsa_role": "declare_recommended_artifact_shapes_and_session_log_storage_policy",
        "storage_policy": {
            "primary_storage": "date_scoped_session_log",
            "managed_artifact_roots": [
                "worlds/{world_id}/artifacts/",
                "worlds/{world_id}/meetings/",
                "worlds/{world_id}/orchestrator_runs/",
                "worlds/{world_id}/scenes/",
                "reports/",
                "hermes/reports_outbox/",
            ],
            "session_log_root_template": "worlds/{world_id}/artifacts/session_logs/{YYYY-MM-DD}/{session_id}/",
            "session_log_is_source_of_truth": True,
            "exports_are_derivable_from_session_log": True,
            "store_every_export_by_default": False,
            "export_on_demand": True,
            "out_of_contract_artifact_policy": {
                "allowed_only_when_runtime_or_user_requires_external_path": True,
                "source_map_required": True,
                "source_map_filename": "artifact_source_map.json",
                "source_map_schema": REPORTING_ARTIFACT_MANIFEST_SCHEMA,
                "required_fields": [
                    "artifact_id",
                    "artifact_type",
                    "originating_command_or_run_id",
                    "absolute_or_runtime_path",
                    "managed_by",
                    "cleanup_hint",
                    "safe_to_delete_with_session",
                ],
                "install_uninstall_goal": (
                    "Every external artifact must be traceable back to the WSA session so "
                    "operators can remove, archive, or migrate it without searching manually."
                ),
            },
            "delete_policy": {
                "user_can_delete_session_log_directory": True,
                "delete_exports_with_session_log_when_runtime_policy_allows": True,
                "keep_world_db_and_canon_separate": True,
                "source_map_drives_external_cleanup": True,
            },
        },
        "recommended_exports": [
            {
                "artifact_type": "human_session_minutes",
                "label": "회의록",
                "purpose": (
                    "Human-readable real session log for meetup or scene-generation work. "
                    "Shows what actors/runtime steps actually did."
                ),
                "formats": SUPPORTED_REPORT_EXPORT_FORMATS,
                "audience": "author_operator",
                "source": "date_scoped_session_log",
                "default_auto_generate": False,
            },
            {
                "artifact_type": "draft_output",
                "label": "원고초안",
                "purpose": (
                    "Meetup conclusion, scene draft, or other authored result produced from "
                    "the session. It must not imply canon approval by itself."
                ),
                "formats": SUPPORTED_REPORT_EXPORT_FORMATS,
                "audience": "author_operator",
                "source": "accepted_session_outputs_or_synthesis",
                "default_auto_generate": False,
            },
            {
                "artifact_type": "round_orchestration_report",
                "label": "라운드별 오케스트레이션 보고서",
                "purpose": (
                    "Round/checkpoint-level orchestration trace: scheduling, actor roles, "
                    "quality gates, rejected outputs, rollback triggers, and stop reasons."
                ),
                "formats": SUPPORTED_REPORT_EXPORT_FORMATS,
                "audience": "operator_or_debugger",
                "source": "turn_records_and_floor_state",
                "default_auto_generate": False,
            },
        ],
        "mode_disclosure_required": [
            "requested_mode",
            "resolved_mode",
            "mode_resolution_source",
            "mode_confidence",
            "what_actors_actually_did",
            "what_was_not_performed",
        ],
        "actor_contribution_accounting": {
            "recommended_labels": [
                "observer",
                "constraint_panel",
                "sql_auditor",
                "co_writer",
                "validator",
                "rollback_trigger",
            ],
            "recommended_counts": [
                "callback_total",
                "callback_accepted",
                "callback_rejected",
                "rollback_event_count",
                "sql_or_fact_lookup_performed",
                "actor_authored_sentence_count",
                "adopted_actor_proposal_count",
                "final_synthesizer",
            ],
        },
        "runtime_customization": {
            "automatic_export_policy": "user_or_hermes_profile_custom",
            "default_delivery": "none_until_runtime_requests_export",
            "allowed_custom_outputs": True,
            "wsa_does_not_send_chat_or_store_runtime_delivery_preferences": True,
        },
        "privacy_policy": {
            "session_logs_may_contain_private_world_or_user_data": True,
            "do_not_commit_session_logs_to_public_template_repo": True,
            "runtime_should_make_deletion_easy": True,
        },
    }


def build_reporting_artifact_manifest(
    session_id: str,
    world_id: str,
    run_id: str | None,
    workflow: str | None,
    skill: str | None,
    session_log_ref: str,
    exports: List[Dict[str, Any]] | None = None,
    external_artifacts: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "schema": REPORTING_ARTIFACT_MANIFEST_SCHEMA,
        "session_id": session_id,
        "world_id": world_id,
        "run_id": run_id,
        "workflow": workflow,
        "skill": skill,
        "session_log_ref": session_log_ref,
        "exports": exports or [],
        "external_artifacts": external_artifacts or [],
        "source_of_truth": "session_log_ref",
        "source_map_required_for_external_artifacts": bool(external_artifacts),
        "delete_hint": "delete or archive the session log directory according to runtime policy",
        "external_cleanup_hint": (
            "Use external_artifacts cleanup_hint fields before uninstalling or archiving a runtime."
        ),
        "canon_write_performed": False,
    }
