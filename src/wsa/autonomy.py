from __future__ import annotations

from typing import Any, Dict


DISCRETION_LEVEL_DETAILS: Dict[int, Dict[str, Any]] = {
    0: {
        "label": "author_only",
        "summary": "Hermes asks before filling any world detail.",
        "agent_may": ["organize answers", "surface contradictions", "ask follow-up questions"],
        "agent_must_not": ["invent canon candidates without explicit request"],
        "cron_allowed": False,
    },
    1: {
        "label": "ask_before_filling",
        "summary": "Hermes may propose small options, then waits for author selection.",
        "agent_may": ["draft alternatives", "recommend one option with reasons"],
        "agent_must_not": ["fill missing details as if accepted"],
        "cron_allowed": False,
    },
    2: {
        "label": "small_gaps_allowed",
        "summary": "Hermes may fill minor connective details as candidates.",
        "agent_may": ["fill names, placeholders, and low-risk connective tissue"],
        "agent_must_not": ["change major premise, faction power, or protagonist frame"],
        "cron_allowed": False,
    },
    3: {
        "label": "balanced_fill",
        "summary": "Hermes may prefill ordinary supporting details and report assumptions.",
        "agent_may": ["draft institutions, locations, customs, and scene hooks"],
        "agent_must_not": ["canonize generated material without review"],
        "cron_allowed": False,
    },
    4: {
        "label": "broad_agent_fill",
        "summary": "Hermes may generate broad lower-layer world material as candidate sets.",
        "agent_may": ["run larger fill passes", "prepare candidate reports for approval"],
        "agent_must_not": ["run unattended cron loops without a level-5 agreement"],
        "cron_allowed": False,
    },
    5: {
        "label": "challenge_world_autonomy",
        "summary": "Hermes may run cron-capable autonomous fill loops toward a destination checkpoint.",
        "agent_may": [
            "prepare recurring lower-layer generation",
            "stop when the destination checkpoint is met",
            "perform a quality gate before completion",
        ],
        "agent_must_not": [
            "start without a destination checkpoint",
            "continue after the checkpoint is met",
            "canonize generated material without approval",
        ],
        "cron_allowed": True,
        "requires_destination_checkpoint": True,
        "completion_policy": "stop_cron_then_report_quality_and_request_approval",
    },
}

DISCRETION_LEVELS = {
    level: detail["label"] for level, detail in DISCRETION_LEVEL_DETAILS.items()
}


def discretion_scale_contract() -> Dict[str, Dict[str, Any]]:
    return {str(level): detail for level, detail in DISCRETION_LEVEL_DETAILS.items()}


def fill_the_rest_contract() -> Dict[str, Any]:
    return {
        "schema": "wsa.hermes.fill_the_rest_contract.v1",
        "owner": "user_hermes_runtime",
        "purpose": "Prepare lower-layer autonomous candidate generation until a destination checkpoint.",
        "candidate_scope": "lower_layer_information",
        "canon_policy": "generated_material_requires_user_or_policy_approval",
        "available_anytime": True,
        "requires_destination_checkpoint": True,
        "cron_capable_at_discretion_level": 5,
        "cron_owner": "user_hermes_runtime",
        "must_stop_when_destination_met": True,
        "completion_must_state_cron_stopped": True,
        "quality_gate": {
            "required_before_completion": True,
            "checks": [
                "destination_checkpoint_satisfied",
                "internal_consistency_reviewed",
                "duplicate_or_low_value_fill_removed",
                "approval_report_created",
            ],
        },
        "approval_flow": "report_candidates_then_request_user_approval",
    }
