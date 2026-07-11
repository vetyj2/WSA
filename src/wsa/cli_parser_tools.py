from __future__ import annotations


from .orchestrator_contract import (
    DEFAULT_CONTEXT_POLICY,
    DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
    DEFAULT_MAX_QUEUE_TURNS,
    DEFAULT_MAX_SUBSESSION_CALLS,
    DEFAULT_TERMINATION_POLICY,
)


from typing import Any

def add_tool_parsers(subparsers: Any) -> None:
    artifact_parser = subparsers.add_parser("artifact", help="Inspect artifact architecture.")
    artifact_subparsers = artifact_parser.add_subparsers(dest="artifact_command")
    artifact_map = artifact_subparsers.add_parser(
        "map",
        help="Print or write the workspace artifact architecture map.",
    )
    artifact_map.add_argument(
        "--write",
        action="store_true",
        help="Write the generated map to manager/artifact_map/artifact_architecture_map.json.",
    )
    artifact_map.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    artifact_diagnose = artifact_subparsers.add_parser(
        "diagnose",
        help="Read-only source-map diagnostics for managed report exports.",
    )
    artifact_diagnose.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    artifact_route = artifact_subparsers.add_parser(
        "route",
        help="Recommend a managed path and classification for a WSA-related artifact.",
    )
    artifact_route.add_argument(
        "artifact_type",
        help="Artifact type or local label. Unknown labels route as custom WSA artifacts.",
    )
    artifact_route.add_argument("--world-id", help="World ID for world-scoped artifacts.")
    artifact_route.add_argument("--session-id", help="Session ID for date-scoped artifacts.")
    artifact_route.add_argument("--run-id", help="Orchestrator run ID when relevant.")
    artifact_route.add_argument("--filename", help="Preferred output filename.")
    artifact_route.add_argument(
        "--date",
        help="Date bucket for session artifacts. Defaults to current UTC date.",
    )
    artifact_route.add_argument(
        "--external-path",
        help="Runtime path when the artifact must be created outside the WSA workspace.",
    )
    artifact_route.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    artifact_uninstall_plan = artifact_subparsers.add_parser(
        "uninstall-plan",
        help="Dry-run uninstall ownership and cleanup boundary plan.",
    )
    artifact_uninstall_plan.add_argument(
        "--write",
        action="store_true",
        help="Write the dry-run plan under manager/uninstall_plans/.",
    )
    artifact_uninstall_plan.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    artifact_uninstall_discover = artifact_subparsers.add_parser(
        "uninstall-discover",
        help="Read-only discovery of WSA-adjacent paths under explicit scan roots.",
    )
    artifact_uninstall_discover.add_argument(
        "--scan-root",
        action="append",
        default=[],
        help="Root directory to scan for WSA-adjacent files or directories. Repeatable.",
    )
    artifact_uninstall_discover.add_argument(
        "--exclude-root",
        action="append",
        default=[],
        help="Root directory to preserve and exclude from candidate traversal. Repeatable.",
    )
    artifact_uninstall_discover.add_argument(
        "--max-depth",
        type=int,
        default=4,
        help="Maximum directory depth to inspect under each scan root.",
    )
    artifact_uninstall_discover.add_argument(
        "--max-candidates",
        type=int,
        default=500,
        help="Maximum candidate records to return.",
    )
    artifact_uninstall_discover.add_argument(
        "--write",
        action="store_true",
        help="Write the discovery manifest under manager/uninstall_plans/.",
    )
    artifact_uninstall_discover.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    artifact_maintenance_scan = artifact_subparsers.add_parser(
        "maintenance-scan",
        help="Dry-run storage hygiene scan for logs, reports, callbacks, and archives.",
    )
    artifact_maintenance_scan.add_argument(
        "--write",
        action="store_true",
        help="Write the scan JSON under manager/maintenance_plans/.",
    )
    artifact_maintenance_scan.add_argument(
        "--top",
        type=int,
        default=10,
        help="Maximum largest roots to include in text/json summaries.",
    )
    artifact_maintenance_scan.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    scene_parser = subparsers.add_parser("scene", help="Run scene orchestration utilities.")
    scene_subparsers = scene_parser.add_subparsers(dest="scene_command")
    scene_start = scene_subparsers.add_parser(
        "start",
        aliases=["prep"],
        help="Start a bounded Hermes-bridge scene prep run.",
    )
    scene_start.add_argument("world_id", help="World ID.")
    scene_start.add_argument("--topic", required=True, help="Scene or scene-prep topic.")
    scene_start.add_argument(
        "--question",
        default=(
            "Prepare scene facts, actor assignments, role isolation, "
            "model/thinking guidance, and approval choices."
        ),
        help="Scene-prep question to resolve before drafting.",
    )
    scene_start.add_argument("--rounds", type=int, default=3, help="Internal round budget.")
    scene_start.add_argument(
        "--max-queue-turns",
        type=int,
        default=DEFAULT_MAX_QUEUE_TURNS,
        help=f"Maximum autonomous queue turns before stopping. Default: {DEFAULT_MAX_QUEUE_TURNS}.",
    )
    scene_start.add_argument(
        "--max-concurrent-subsessions",
        type=int,
        default=DEFAULT_MAX_CONCURRENT_SUBSESSIONS,
        help=(
            "Maximum subsessions Hermes should run at the same time. "
            f"Default: {DEFAULT_MAX_CONCURRENT_SUBSESSIONS}."
        ),
    )
    scene_start.add_argument(
        "--max-subsession-calls",
        type=int,
        default=DEFAULT_MAX_SUBSESSION_CALLS,
        help=(
            "Maximum total subsession calls before returning a partial package. "
            f"Default: {DEFAULT_MAX_SUBSESSION_CALLS}."
        ),
    )
    scene_start.add_argument(
        "--context-policy",
        default=DEFAULT_CONTEXT_POLICY,
        help=f"Context carry-forward policy. Default: {DEFAULT_CONTEXT_POLICY}.",
    )
    scene_start.add_argument(
        "--frame-plan",
        help="Optional scene frame, viewpoint, location, timeframe, or guardrail.",
    )
    scene_start.add_argument(
        "--termination-policy",
        default=DEFAULT_TERMINATION_POLICY,
        help=f"Termination policy label. Default: {DEFAULT_TERMINATION_POLICY}.",
    )
    scene_start.add_argument("--time-scope", help="Optional scene time scope.")
    scene_start.add_argument("--location-scope", help="Optional scene location scope.")
    scene_start.add_argument("--viewpoint", help="Optional viewpoint or POV scope.")
    scene_start.add_argument(
        "--generation-mode",
        choices=("auto", "fact-audit-synthesis", "writing-room-line-build"),
        default="auto",
        help=(
            "Scene generation mode disclosure. Default: auto, letting Hermes/profile/natural "
            "language resolve the final execution mode."
        ),
    )
    scene_start.add_argument(
        "--condition",
        action="append",
        default=[],
        help="Optional scene selection condition. Can be repeated.",
    )
    scene_start.add_argument(
        "--participant",
        action="append",
        default=[],
        help="Actor, narrator, crowd, continuity role, or scene-prep viewpoint. Can be repeated.",
    )
    scene_start.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    scene_start.add_argument(
        "--no-prep-review",
        action="store_true",
        help="Opt out of the default prep review hook before first Hermes actor call.",
    )
    scene_mock = scene_subparsers.add_parser("mock", help="Run a mock scene vertical slice.")
    scene_mock.add_argument("world_id", help="World ID.")
    scene_mock.add_argument("name", help="Scene name.")
    scene_mock.add_argument("--goal", required=True, help="Scene goal.")
    scene_mock.add_argument(
        "--actor",
        action="append",
        default=[],
        help="Actor display name. Can be provided multiple times.",
    )
