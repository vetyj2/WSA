from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Dict

from .orchestrator_contract import build_orchestrator_session_contract
from .orchestrator_workflows import build_workflow_profile
from .reporting_contract import build_reporting_artifact_contract
from .scene_modes import build_scene_mode_disclosure


CONTRACT_REFERENCE_SCHEMA = "wsa.contract.reference.v1"
COMPACT_RUN_SCHEMA = "wsa.orchestrator.run_projection.v2"
COMPACT_PLAN_SCHEMA = "wsa.orchestrator.plan_projection.v2"


def contract_reference(
    contract_id: str,
    payload: Dict[str, Any],
    parameters: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema": CONTRACT_REFERENCE_SCHEMA,
        "contract_id": contract_id,
        "version": 1,
        "digest": _digest(payload),
        "parameters": parameters,
        "source": "installed_wsa_contract_builder",
    }


def build_run_contract_references(payload: Dict[str, Any]) -> Dict[str, Any]:
    refs: Dict[str, Any] = {}
    workflow = str(payload.get("workflow") or "meetup")
    workflow_requested = str(payload.get("workflow_requested") or workflow)
    skill = str(payload.get("skill") or workflow)
    plan = dict(payload.get("plan") or {})

    if isinstance(payload.get("workflow_profile"), dict):
        refs["workflow_profile"] = contract_reference(
            "orchestrator.workflow_profile",
            payload["workflow_profile"],
            {"workflow_requested": workflow_requested, "skill": skill},
        )
    if isinstance(payload.get("reporting_artifact_contract"), dict):
        refs["reporting_artifact_contract"] = contract_reference(
            "reporting.artifact_contract",
            payload["reporting_artifact_contract"],
            {"workflow": workflow, "skill": skill},
        )
    if isinstance(payload.get("scene_mode_disclosure"), dict):
        disclosure = payload["scene_mode_disclosure"]
        refs["scene_mode_disclosure"] = contract_reference(
            "scene.mode_disclosure",
            disclosure,
            {
                "workflow": workflow,
                "skill": skill,
                "requested_mode": disclosure.get("requested_mode"),
            },
        )
    if isinstance(payload.get("session_contract"), dict):
        params = {
            "run_id": payload.get("run_id"),
            "world_id": payload.get("world_id"),
            "workflow": workflow,
            "skill_name": skill,
            "mode": plan.get("mode", payload.get("subsession_execution_mode", "agent")),
            "max_queue_turns": (payload.get("queue_limits") or {}).get("max_queue_turns"),
            "max_concurrent_subsessions": (payload.get("concurrency_policy") or {}).get(
                "max_concurrent_subsessions"
            ),
            "max_subsession_calls": (payload.get("queue_limits") or {}).get(
                "max_subsession_calls"
            ),
            "context_policy": (payload.get("context_continuity") or {}).get("policy"),
            "plan_frame": payload.get("plan_frame", {}),
            "termination_contract": payload.get("termination_policy", {}),
            "session_cleanup": payload.get("session_cleanup", {}),
            "workflow_requested": workflow_requested,
        }
        refs["session_contract"] = contract_reference(
            "orchestrator.session_contract",
            payload["session_contract"],
            params,
        )
    return refs


def expand_contract_reference(reference: Dict[str, Any]) -> Dict[str, Any]:
    contract_id = reference.get("contract_id")
    parameters = dict(reference.get("parameters") or {})
    if contract_id == "orchestrator.workflow_profile":
        expanded = build_workflow_profile(
            str(parameters["workflow_requested"]),
            str(parameters["skill"]),
        )
    elif contract_id == "reporting.artifact_contract":
        expanded = build_reporting_artifact_contract(
            workflow=parameters.get("workflow"),
            skill=parameters.get("skill"),
        )
    elif contract_id == "scene.mode_disclosure":
        expanded = build_scene_mode_disclosure(
            str(parameters["workflow"]),
            str(parameters["skill"]),
            parameters.get("requested_mode"),
        )
    elif contract_id == "orchestrator.session_contract":
        workflow_profile = build_workflow_profile(
            str(parameters["workflow_requested"]),
            str(parameters["skill_name"]),
        )
        expanded = build_orchestrator_session_contract(
            str(parameters["run_id"]),
            str(parameters["world_id"]),
            str(parameters["workflow"]),
            str(parameters["skill_name"]),
            str(parameters["mode"]),
            int(parameters["max_queue_turns"]),
            int(parameters["max_concurrent_subsessions"]),
            int(parameters["max_subsession_calls"]),
            str(parameters["context_policy"]),
            dict(parameters["plan_frame"]),
            dict(parameters["termination_contract"]),
            dict(parameters["session_cleanup"]),
            workflow_profile,
        )
    else:
        raise KeyError(f"unknown contract reference: {contract_id}")
    if _digest(expanded) != reference.get("digest"):
        raise ValueError(f"contract digest mismatch after expansion: {contract_id}")
    return expanded


def compact_run_projection(payload: Dict[str, Any]) -> Dict[str, Any]:
    compact = deepcopy(payload)
    compact["projection_schema"] = COMPACT_RUN_SCHEMA
    compact["projection_policy"] = {
        "source_of_truth": "control.sqlite.workflow_runs.payload",
        "contracts": "digest_refs_expandable_by_installed_wsa",
        "full_view_command": "wsa orchestrator status <run_id> --format json --expand-contracts",
    }
    compact["contract_refs"] = build_run_contract_references(payload)
    compact["plan_ref"] = "plan.json"
    for key in (
        "plan",
        "session_contract",
        "workflow_profile",
        "reporting_artifact_contract",
        "subagent_prompt_packets",
        "round_prompt_packets",
        "runtime_hook_packets",
        "context_continuity",
        "floor_continuity",
        "progress_report_policy",
        "prompt_coordination",
        "micro_turn_policy",
        "quality_gate",
        "termination_policy",
        "session_cleanup",
        "concurrency_policy",
        "start_preflight",
    ):
        compact.pop(key, None)
    compact["context_packets"] = [
        _compact_context_packet(item)
        for item in payload.get("context_packets", [])
        if isinstance(item, dict)
    ]
    disclosure = compact.get("scene_mode_disclosure")
    if isinstance(disclosure, dict):
        disclosure.pop("mode_contracts", None)
    runtime_contract = compact.get("runtime_bridge_contract")
    if isinstance(runtime_contract, dict):
        runtime_contract.pop("reporting_artifact_contract", None)
        runtime_contract["reporting_contract_ref"] = compact["contract_refs"].get(
            "reporting_artifact_contract"
        )
    return compact


def compact_plan_projection(plan: Dict[str, Any]) -> Dict[str, Any]:
    synthetic = {
        **plan,
        "plan": plan,
        "status": "awaiting_callback",
        "reporting_artifact_contract": build_reporting_artifact_contract(
            plan.get("workflow"), plan.get("skill")
        ),
    }
    refs = build_run_contract_references(synthetic)
    keep = (
        "run_id",
        "workflow",
        "workflow_requested",
        "skill",
        "world_id",
        "topic",
        "question",
        "trigger",
        "execution",
        "subsession_execution_mode",
        "real_subagent_execution",
        "execution_owner",
        "wsa_role",
        "mode",
        "round_budget",
        "rounds_scheduled",
        "queue_limits",
        "subsession_policy",
        "canon_policy",
        "approval",
        "close_on",
        "participants",
        "scene_filter_contract",
        "prep_review_policy",
        "plan_frame",
    )
    compact = {key: deepcopy(plan[key]) for key in keep if key in plan}
    compact.update(
        {
            "schema": COMPACT_PLAN_SCHEMA,
            "contract_refs": refs,
            "projection_policy": "dynamic_values_inline_static_contracts_by_digest_ref",
        }
    )
    return compact


def concise_run_view(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": "wsa.orchestrator.run_summary.v1",
        "run_id": payload.get("run_id"),
        "world_id": payload.get("world_id"),
        "workflow": payload.get("workflow"),
        "skill": payload.get("skill"),
        "status": payload.get("status"),
        "execution_status": payload.get("execution_status"),
        "next_action": payload.get("next_action", "author_review"),
        "topic": payload.get("topic"),
        "queue_limits": payload.get("queue_limits", {}),
        "pending_hook_count": len(payload.get("pending_hooks", [])),
        "accepted_output_count": len(payload.get("subsession_outputs", [])),
        "report_id": payload.get("report_id"),
        "world_mutation_count": len(payload.get("world_mutations", [])),
        "contract_refs": build_run_contract_references(payload),
    }


def _compact_context_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    compact = {
        key: deepcopy(value)
        for key, value in packet.items()
        if key
        not in {
            "prompt_packet",
            "scene_mode_contract",
            "scene_generation_mode",
        }
    }
    compact["prompt_packet_ref"] = {
        "participant_id": packet.get("participant_id"),
        "source": "pending_hooks_or_sqlite_run_state",
    }
    return compact


def _digest(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
