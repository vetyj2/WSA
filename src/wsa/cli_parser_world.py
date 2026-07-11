from __future__ import annotations

import argparse

from .application.startup_source_service import ALLOWED_SOURCE_TYPES
from .startup import (
    QUESTION_STATUSES,
)


from typing import Any

def add_world_parsers(subparsers: Any) -> None:
    world_parser = subparsers.add_parser("world", help="Manage worlds.")
    world_subparsers = world_parser.add_subparsers(dest="world_command")

    def add_startup_output_format(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Output format.",
        )

    world_create = world_subparsers.add_parser("create", help="Create a new isolated world.")
    world_create.add_argument("name", help="Human-readable world name.")

    world_subparsers.add_parser("list", help="List registered worlds.")
    world_home = world_subparsers.add_parser(
        "home",
        help="Show one read-only operational world home and its canonical next action.",
    )
    world_home.add_argument(
        "world_selector",
        nargs="?",
        help="World ID or unique display name. Omit when exactly one world exists.",
    )
    add_startup_output_format(world_home)
    world_continue = world_subparsers.add_parser(
        "continue",
        help="Resolve and explain the next safe action for a world.",
    )
    world_continue.add_argument(
        "world_selector",
        nargs="?",
        help="World ID or unique display name. Omit when exactly one world exists.",
    )
    add_startup_output_format(world_continue)
    world_show = world_subparsers.add_parser(
        "show",
        help="Show a read-only world data summary.",
    )
    world_show.add_argument("world_id", help="World ID.")
    add_startup_output_format(world_show)

    world_entity = world_subparsers.add_parser("entity", help="Inspect world entities.")
    world_entity_subparsers = world_entity.add_subparsers(dest="world_entity_command")
    world_entity_list = world_entity_subparsers.add_parser("list", help="List entities.")
    world_entity_list.add_argument("world_id", help="World ID.")
    world_entity_list.add_argument("--type", dest="entity_type", help="Entity type filter.")
    world_entity_list.add_argument("--status", help="Entity status filter.")
    add_startup_output_format(world_entity_list)
    world_entity_show = world_entity_subparsers.add_parser("show", help="Show one entity.")
    world_entity_show.add_argument("world_id", help="World ID.")
    world_entity_show.add_argument("entity_id", help="Entity ID.")
    add_startup_output_format(world_entity_show)

    world_fact = world_subparsers.add_parser("fact", help="Inspect world facts.")
    world_fact_subparsers = world_fact.add_subparsers(dest="world_fact_command")
    world_fact_list = world_fact_subparsers.add_parser("list", help="List facts.")
    world_fact_list.add_argument("world_id", help="World ID.")
    world_fact_list.add_argument("--subject-id", help="Subject ID filter.")
    add_startup_output_format(world_fact_list)
    world_fact_show = world_fact_subparsers.add_parser("show", help="Show one fact.")
    world_fact_show.add_argument("world_id", help="World ID.")
    world_fact_show.add_argument("fact_id", help="Fact ID.")
    add_startup_output_format(world_fact_show)

    world_edge = world_subparsers.add_parser("edge", help="Inspect temporal world edges.")
    world_edge_subparsers = world_edge.add_subparsers(dest="world_edge_command")
    world_edge_list = world_edge_subparsers.add_parser("list", help="List world edges.")
    world_edge_list.add_argument("world_id", help="World ID.")
    world_edge_list.add_argument("--subject-id", help="Subject ID filter.")
    world_edge_list.add_argument("--edge-type", help="Edge type filter.")
    world_edge_list.add_argument("--status", help="Edge status filter.")
    add_startup_output_format(world_edge_list)

    world_timeline = world_subparsers.add_parser("timeline", help="Inspect timeline points.")
    world_timeline_subparsers = world_timeline.add_subparsers(dest="world_timeline_command")
    world_timeline_list = world_timeline_subparsers.add_parser(
        "list",
        help="List timeline points.",
    )
    world_timeline_list.add_argument("world_id", help="World ID.")
    add_startup_output_format(world_timeline_list)

    world_actor = world_subparsers.add_parser(
        "actor",
        help="Inspect or propose typed actor profile, time, knowledge, and memory data.",
    )
    world_actor_subparsers = world_actor.add_subparsers(dest="world_actor_command")

    def add_actor_target(target: argparse.ArgumentParser) -> None:
        target.add_argument("world_id", help="World ID.")
        target.add_argument("actor", help="Actor entity ID or unique display name.")

    def add_actor_write_common(target: argparse.ArgumentParser) -> None:
        add_actor_target(target)
        target.add_argument("--title", help="Review ticket title.")
        target.add_argument(
            "--source-ref",
            default="user_cli",
            help="Inspectable provenance reference. Default: user_cli.",
        )
        target.add_argument(
            "--write-ticket",
            action="store_true",
            help="Create a proposed ticket after the read-only preview.",
        )
        add_startup_output_format(target)

    def add_actor_replacement(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--replace-record",
            help="Deep record ID to close or deprecate in the same review ticket.",
        )
        target.add_argument(
            "--replace-at",
            help="Validity boundary shared by the old and new records.",
        )

    world_actor_show = world_actor_subparsers.add_parser(
        "show",
        help="Show typed authoring records for one actor.",
    )
    add_actor_target(world_actor_show)
    add_startup_output_format(world_actor_show)

    world_actor_profile = world_actor_subparsers.add_parser(
        "profile",
        help="Preview an actor core, goal, secret, speech, or style fragment.",
    )
    add_actor_write_common(world_actor_profile)
    world_actor_profile.add_argument(
        "--fragment",
        required=True,
        choices=("core", "goal", "secret", "speech", "style"),
    )
    world_actor_profile.add_argument("--text", required=True)
    world_actor_profile.add_argument("--valid-from")
    world_actor_profile.add_argument("--valid-until")
    add_actor_replacement(world_actor_profile)

    world_actor_attribute = world_actor_subparsers.add_parser(
        "attribute",
        help="Preview a time-bounded typed actor attribute.",
    )
    add_actor_write_common(world_actor_attribute)
    world_actor_attribute.add_argument("--dimension", required=True)
    attribute_value = world_actor_attribute.add_mutually_exclusive_group(required=True)
    attribute_value.add_argument("--value-text")
    attribute_value.add_argument("--value-number", type=float)
    attribute_value.add_argument("--value-ref-id")
    world_actor_attribute.add_argument("--valid-from")
    world_actor_attribute.add_argument("--valid-until")
    add_actor_replacement(world_actor_attribute)

    world_actor_knowledge = world_actor_subparsers.add_parser(
        "knowledge",
        help="Preview a known, discovered, witnessed, unknown, or forbidden attribution.",
    )
    add_actor_write_common(world_actor_knowledge)
    world_actor_knowledge.add_argument(
        "--target-type",
        required=True,
        choices=("fact", "actor_profile", "entity", "world_edge", "scene_event"),
    )
    world_actor_knowledge.add_argument("--target-id", required=True)
    world_actor_knowledge.add_argument(
        "--state",
        required=True,
        choices=("known", "discovered", "witnessed", "unknown", "forbidden"),
    )
    world_actor_knowledge.add_argument("--acquired-at")
    world_actor_knowledge.add_argument("--valid-until")
    add_actor_replacement(world_actor_knowledge)

    world_actor_memory = world_actor_subparsers.add_parser(
        "memory",
        help="Preview a durable actor memory packet.",
    )
    add_actor_write_common(world_actor_memory)
    world_actor_memory.add_argument("--time-scope", required=True)
    world_actor_memory.add_argument("--text", required=True)
    add_actor_replacement(world_actor_memory)

    world_actor_revise = world_actor_subparsers.add_parser(
        "revise",
        help="Preview a status or validity revision for an existing actor record.",
    )
    add_actor_write_common(world_actor_revise)
    world_actor_revise.add_argument(
        "--record-type",
        required=True,
        choices=(
            "actor_profile",
            "entity_attribute_span",
            "knowledge_attribution",
            "actor_memory_packet",
        ),
    )
    world_actor_revise.add_argument("--record-id", required=True)
    world_actor_revise.add_argument(
        "--status",
        choices=(
            "active",
            "approved",
            "canon",
            "accepted",
            "deprecated",
            "rejected",
        ),
    )
    world_actor_revise.add_argument("--valid-from")
    world_actor_revise.add_argument("--valid-until")
    world_actor_revise.add_argument(
        "--clear-valid-until",
        action="store_true",
        help="Remove an existing validity end instead of setting a new value.",
    )
    world_actor_revise.add_argument("--acquired-at")
    world_actor_revise.add_argument("--time-scope")

    world_export = world_subparsers.add_parser(
        "export",
        help="Print a portable read-only world data export.",
    )
    world_export.add_argument("world_id", help="World ID.")
    world_export.add_argument(
        "--entity",
        action="append",
        default=[],
        help="Select an entity and outgoing reference dependencies. Repeatable.",
    )
    world_export.add_argument(
        "--include-timeline",
        action="store_true",
        help="Include timeline points in a selective export.",
    )
    add_startup_output_format(world_export)
    world_fork_plan = world_subparsers.add_parser(
        "fork-plan",
        help="Build a read-only selective world fork plan.",
    )
    world_fork_plan.add_argument("world_id", help="Source world ID.")
    world_fork_plan.add_argument("--name", required=True, help="Target world display name.")
    world_fork_plan.add_argument(
        "--entity",
        action="append",
        default=[],
        help="Select an entity and outgoing reference dependencies. Repeatable.",
    )
    world_fork_plan.add_argument("--include-timeline", action="store_true")
    add_startup_output_format(world_fork_plan)
    world_import_preview = world_subparsers.add_parser(
        "import-preview",
        help="Preview a portable world JSON import and optionally create a ticket.",
    )
    world_import_preview.add_argument("world_id", help="Destination world ID.")
    world_import_preview.add_argument("input_path", help="Portable export JSON path.")
    world_import_preview.add_argument(
        "--write-ticket",
        action="store_true",
        help="Create a proposed import ticket after preview.",
    )
    add_startup_output_format(world_import_preview)

    world_proposal = world_subparsers.add_parser(
        "proposal",
        help="Preview user-direct world changes and optionally create a ticket.",
    )
    world_proposal_subparsers = world_proposal.add_subparsers(dest="world_proposal_command")

    def add_proposal_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("world_id", help="World ID.")
        target.add_argument(
            "--write-ticket",
            action="store_true",
            help="Create a proposed concrete change ticket after preview.",
        )
        add_startup_output_format(target)

    world_proposal_startup = world_proposal_subparsers.add_parser(
        "startup",
        help="Preview resolved Startup answers as user-direct facts.",
    )
    add_proposal_common(world_proposal_startup)
    world_proposal_entity = world_proposal_subparsers.add_parser(
        "entity",
        help="Preview a user-direct entity addition.",
    )
    add_proposal_common(world_proposal_entity)
    world_proposal_entity.add_argument(
        "--name",
        required=True,
        dest="display_name",
        help="Entity name.",
    )
    world_proposal_entity.add_argument(
        "--type",
        required=True,
        dest="entity_type",
        help="Entity type.",
    )
    world_proposal_fact = world_proposal_subparsers.add_parser(
        "fact",
        help="Preview a user-direct fact addition.",
    )
    add_proposal_common(world_proposal_fact)
    world_proposal_fact.add_argument("--subject-id", required=True, help="Fact subject ID.")
    world_proposal_fact.add_argument("--predicate", required=True, help="Fact predicate.")
    world_proposal_fact.add_argument("--value", dest="object_value", help="Text object value.")
    world_proposal_fact.add_argument("--object-ref-id", help="Referenced object ID.")
    world_proposal_fact.add_argument("--time-scope", help="Optional time scope.")
    world_proposal_fact.add_argument("--location-scope", help="Optional location scope.")
    world_proposal_edge = world_proposal_subparsers.add_parser(
        "edge",
        help="Preview a user-direct temporal edge addition.",
    )
    add_proposal_common(world_proposal_edge)
    world_proposal_edge.add_argument("--subject-type", required=True)
    world_proposal_edge.add_argument("--subject-id", required=True)
    world_proposal_edge.add_argument("--edge-type", required=True)
    world_proposal_edge.add_argument("--object-type", required=True)
    world_proposal_edge.add_argument("--object-id")
    world_proposal_edge.add_argument("--object-value")
    world_proposal_edge.add_argument("--valid-from")
    world_proposal_edge.add_argument("--valid-until")
    world_startup = world_subparsers.add_parser(
        "startup",
        help="Run open-ended startup interview utilities.",
    )
    world_startup_subparsers = world_startup.add_subparsers(dest="world_startup_command")
    world_startup_status = world_startup_subparsers.add_parser(
        "status",
        help="Show startup ambiguity score.",
    )
    world_startup_status.add_argument("world_id", help="World ID.")
    add_startup_output_format(world_startup_status)
    world_startup_summary = world_startup_subparsers.add_parser(
        "summary",
        help="Summarize recorded startup intent without mutating world data.",
    )
    world_startup_summary.add_argument("world_id", help="World ID.")
    add_startup_output_format(world_startup_summary)
    world_startup_followup = world_startup_subparsers.add_parser(
        "source-followup",
        help="Compile follow-up questions from explicit current-world source files.",
    )
    world_startup_followup.add_argument("world_id", help="Current world ID.")
    world_startup_followup.add_argument(
        "--source",
        action="append",
        required=True,
        help="User-supplied text source path. Repeatable; content is not persisted.",
    )
    world_startup_followup.add_argument(
        "--source-type",
        choices=sorted(ALLOWED_SOURCE_TYPES),
        default="notes",
        help="Source provenance category. Default: notes.",
    )
    world_startup_followup.add_argument(
        "--max-questions",
        type=int,
        default=5,
        help="Maximum source-grounded questions.",
    )
    add_startup_output_format(world_startup_followup)
    world_startup_interview = world_startup_subparsers.add_parser(
        "interview",
        help="Generate a limited numbered startup interview round.",
    )
    world_startup_interview.add_argument("world_id", help="World ID.")
    world_startup_interview.add_argument(
        "--budget",
        type=int,
        default=4,
        help="Maximum questions in this round.",
    )
    add_startup_output_format(world_startup_interview)
    world_startup_answer = world_startup_subparsers.add_parser(
        "answer",
        help="Record an author answer for a startup question.",
    )
    world_startup_answer.add_argument("world_id", help="World ID.")
    world_startup_answer.add_argument("question_id", help="Question ID such as 0001.")
    world_startup_answer.add_argument("--text", required=True, help="Author answer text.")
    world_startup_answer.add_argument("--choice", help="Optional choice label a-i.")
    add_startup_output_format(world_startup_answer)
    world_startup_batch = world_startup_subparsers.add_parser(
        "batch-answer",
        help="Record parallel answers such as '0001a 0002b plus notes'.",
    )
    world_startup_batch.add_argument("world_id", help="World ID.")
    world_startup_batch.add_argument("--text", required=True, help="Answer code text.")
    add_startup_output_format(world_startup_batch)
    world_startup_set_status = world_startup_subparsers.add_parser(
        "set-status",
        help="Set a startup question status without changing its answer.",
    )
    world_startup_set_status.add_argument("world_id", help="World ID.")
    world_startup_set_status.add_argument("question_id", help="Question ID such as 0001.")
    world_startup_set_status.add_argument(
        "--status",
        required=True,
        choices=sorted(QUESTION_STATUSES),
        help="Question status.",
    )
    add_startup_output_format(world_startup_set_status)
    world_startup_discretion = world_startup_subparsers.add_parser(
        "set-discretion",
        help="Set Hermes discretion level from 0 to 5.",
    )
    world_startup_discretion.add_argument("world_id", help="World ID.")
    world_startup_discretion.add_argument(
        "--level",
        type=int,
        required=True,
        choices=range(0, 6),
        help="Discretion level from 0 author-only to 5 challenge autonomy.",
    )
    add_startup_output_format(world_startup_discretion)

    world_easystartup = world_subparsers.add_parser(
        "easystartup",
        help="Run easy-pick startup interview utilities.",
    )
    world_easystartup_subparsers = world_easystartup.add_subparsers(
        dest="world_easystartup_command"
    )
    world_easystartup_status = world_easystartup_subparsers.add_parser(
        "status",
        help="Show startup ambiguity score.",
    )
    world_easystartup_status.add_argument("world_id", help="World ID.")
    add_startup_output_format(world_easystartup_status)
    world_easystartup_summary = world_easystartup_subparsers.add_parser(
        "summary",
        help="Summarize recorded startup intent without mutating world data.",
    )
    world_easystartup_summary.add_argument("world_id", help="World ID.")
    add_startup_output_format(world_easystartup_summary)
    world_easystartup_interview = world_easystartup_subparsers.add_parser(
        "interview",
        help="Generate an easy-pick numbered startup interview round.",
    )
    world_easystartup_interview.add_argument("world_id", help="World ID.")
    world_easystartup_interview.add_argument(
        "--budget",
        type=int,
        default=8,
        help="Maximum questions in this round.",
    )
    add_startup_output_format(world_easystartup_interview)
    world_easystartup_answer = world_easystartup_subparsers.add_parser(
        "answer",
        help="Record an author answer for an easy-pick startup question.",
    )
    world_easystartup_answer.add_argument("world_id", help="World ID.")
    world_easystartup_answer.add_argument("question_id", help="Question ID such as 0001.")
    world_easystartup_answer.add_argument("--text", required=True, help="Author answer text.")
    world_easystartup_answer.add_argument("--choice", help="Optional choice label a-i.")
    add_startup_output_format(world_easystartup_answer)
    world_easystartup_batch = world_easystartup_subparsers.add_parser(
        "batch-answer",
        help="Record parallel answers such as '0001a 0002b plus notes'.",
    )
    world_easystartup_batch.add_argument("world_id", help="World ID.")
    world_easystartup_batch.add_argument("--text", required=True, help="Answer code text.")
    add_startup_output_format(world_easystartup_batch)
    world_easystartup_discretion = world_easystartup_subparsers.add_parser(
        "set-discretion",
        help="Set Hermes discretion level from 0 to 5.",
    )
    world_easystartup_discretion.add_argument("world_id", help="World ID.")
    world_easystartup_discretion.add_argument(
        "--level",
        type=int,
        required=True,
        choices=range(0, 6),
        help="Discretion level from 0 author-only to 5 challenge autonomy.",
    )
    add_startup_output_format(world_easystartup_discretion)
