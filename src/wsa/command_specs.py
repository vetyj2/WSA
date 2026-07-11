from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PublicCommandSpec:
    key: str
    label: str
    primary_command: str | None
    modes: tuple[str, ...]
    current_routes: tuple[str, ...]
    intent: str
    parser_smoke_argv: tuple[str, ...]
    status: str = "implemented"
    notes: tuple[str, ...] = ()

    def menu_entry(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("key")
        payload.pop("parser_smoke_argv")
        payload["modes"] = list(self.modes)
        payload["current_routes"] = list(self.current_routes)
        payload["notes"] = list(self.notes)
        if self.status == "implemented":
            payload.pop("status")
        if not self.notes:
            payload.pop("notes")
        return payload


PUBLIC_COMMAND_SPECS = (
    PublicCommandSpec(
        key="startup",
        label="Startup",
        primary_command="/wsa_startup",
        modes=("open", "easy"),
        current_routes=("/wsa_startup", "/wsa_easystartup", "/wsa_answer", "/wsa_pick"),
        intent="initial_world_setup_and_interview_progress",
        parser_smoke_argv=("world", "startup", "interview", "world_demo"),
        notes=("Easystartup is an easy-pick Startup mode, not a separate product surface.",),
    ),
    PublicCommandSpec(
        key="meetup",
        label="Meetup",
        primary_command="/wsa_orchestrator",
        modes=("meetup", "retry", "fill_the_rest", "decision_meeting"),
        current_routes=(
            "/wsa_orchestrator",
            "/wsa_meeting",
            "/fill_the_rest",
            "/filltherest_plan",
            "/filltherest_start",
        ),
        intent="non_canon_worldbuilding_discussion_and_candidate_generation",
        parser_smoke_argv=(
            "orchestrator",
            "run",
            "world_demo",
            "--workflow",
            "meetup",
            "--topic",
            "demo",
        ),
        notes=("Meetup output remains proposal-only until an explicit change ticket is applied.",),
    ),
    PublicCommandSpec(
        key="scene",
        label="Scene",
        primary_command="/wsa_scene_start",
        modes=("prep", "actor_assignment", "viewpoint_filter", "draft_boundary"),
        current_routes=("/wsa_scene_start",),
        intent="scene_prep_scene_data_logs_actor_context_and_localized_viewpoint_work",
        parser_smoke_argv=("scene", "start", "world_demo", "--topic", "demo"),
    ),
    PublicCommandSpec(
        key="patrol",
        label="Patrol",
        primary_command=None,
        modes=("scheduled", "world_health", "gap_scan", "stale_work_review"),
        current_routes=("/wsa_autogen", "/filltherest_plan"),
        intent="reactive_and_periodic_world_hygiene_patrol",
        parser_smoke_argv=("manager", "diagnose"),
        status="route_group_no_single_command_yet",
    ),
    PublicCommandSpec(
        key="doctor",
        label="Doctor",
        primary_command="/wsa_doctor",
        modes=("readiness", "update_preflight", "runtime_contract", "template_check"),
        current_routes=("/wsa_doctor", "/wsa_update", "/wsa_update_backup"),
        intent="installation_runtime_update_and_contract_diagnostics",
        parser_smoke_argv=("doctor",),
    ),
    PublicCommandSpec(
        key="database",
        label="Database",
        primary_command=None,
        modes=("query", "reports", "review_queue", "tickets", "facts", "export", "migration"),
        current_routes=(
            "/wsa_worlds",
            "/wsa_reports",
            "/wsa_review_queue",
            "/wsa_review_cleanup",
            "/wsa_tickets",
            "/wsa_approve_ticket",
        ),
        intent="world_data_inspection_review_and_structural_management",
        parser_smoke_argv=("world", "show", "world_demo"),
        status="route_group_no_single_command_yet",
    ),
)


def canonical_menu_surface() -> dict[str, Any]:
    return {
        "schema": "wsa.hermes.canonical_menu_surface.v2",
        "purpose": "Keep the visible command surface small while compatibility routes remain available.",
        "max_visible_entrypoints": len(PUBLIC_COMMAND_SPECS),
        "entries": [spec.menu_entry() for spec in PUBLIC_COMMAND_SPECS],
        "compatibility_policy": {
            "keep_existing_commands_available": True,
            "do_not_expand_visible_menu_for_every_new_feature": True,
            "new_capability_rule": "Attach behavior to an existing entrypoint before adding a new command.",
            "telegram_menu_policy": "show_entrypoints_or_primary_commands_only",
            "free_form_alias_policy": "hyphenated_and_legacy_aliases_may_remain_for_parsing",
        },
        "hierarchy": ["entrypoint", "workflow", "mode", "scope", "target", "action"],
    }
