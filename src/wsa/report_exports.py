from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .autonomous_orchestrator import normalize_execution_payload
from .paths import safe_child_path
from .reporting_contract import (
    REPORTING_ARTIFACT_MANIFEST_SCHEMA,
    SUPPORTED_REPORT_EXPORT_FORMATS,
    build_reporting_artifact_manifest,
)
from .run_store import RunStore
from .workspace import WorldRecord, utc_now


REPORT_EXPORT_SCHEMA = "wsa.report.export.v1"
REPORT_EXPORT_ARTIFACT_TYPES = {
    "human_session_minutes",
    "draft_output",
    "round_orchestration_report",
}


def build_report_export(
    world: WorldRecord,
    run_id: str,
    artifact_type: str,
    export_format: str,
) -> Dict[str, Any]:
    _validate_export_request(artifact_type, export_format)
    run_path, raw_payload = _load_run(world, run_id)
    payload = normalize_execution_payload(raw_payload)
    lines = _lines_for_artifact(payload, artifact_type)
    content = "\n".join(lines).rstrip() + "\n"
    if export_format == "html":
        content = _html_document(payload, artifact_type, lines)
    return {
        "schema": REPORT_EXPORT_SCHEMA,
        "created_at": utc_now(),
        "world_id": world.world_id,
        "run_id": run_id,
        "artifact_type": artifact_type,
        "format": export_format,
        "source_ref": _relative_to_world(world, run_path),
        "source_of_truth": "control_sqlite_workflow_runs",
        "execution_mode": payload["execution_mode"],
        "execution_provenance": payload["execution_provenance"],
        "content": content,
        "side_effect_status": "read_only_until_write_requested",
    }


def write_report_export(
    world: WorldRecord,
    run_id: str,
    artifact_type: str,
    export_format: str,
) -> Dict[str, Any]:
    export = build_report_export(world, run_id, artifact_type, export_format)
    export_dir = _export_dir(world, run_id, export["created_at"])
    export_dir.mkdir(parents=True, exist_ok=True)
    output_path = safe_child_path(export_dir, f"{artifact_type}.{export_format}")
    output_path.write_text(export["content"], encoding="utf-8")
    manifest_path = safe_child_path(export_dir, "artifact_source_map.json")
    run_path, raw_run_payload = _load_run(world, run_id)
    run_payload = normalize_execution_payload(raw_run_payload)
    manifest = build_reporting_artifact_manifest(
        session_id=run_id,
        world_id=world.world_id,
        run_id=run_id,
        workflow=run_payload.get("workflow"),
        skill=run_payload.get("skill"),
        session_log_ref=_relative_to_world(world, run_path),
        exports=[
            {
                "artifact_type": artifact_type,
                "format": export_format,
                "path": _relative_to_world(world, output_path),
                "managed_by": "wsa_report_export",
                "cleanup_hint": "safe_to_delete_with_export_session_when_runtime_policy_allows",
                "safe_to_delete_with_session": True,
            }
        ],
    )
    manifest["external_artifacts"] = []
    manifest["source_map_schema"] = REPORTING_ARTIFACT_MANIFEST_SCHEMA
    manifest["execution_mode"] = run_payload["execution_mode"]
    manifest["execution_provenance"] = run_payload["execution_provenance"]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    export.update(
        {
            "side_effect_status": "workspace_mutating_export_written",
            "artifact_ref": _relative_to_world(world, output_path),
            "manifest_ref": _relative_to_world(world, manifest_path),
        }
    )
    return export


def format_report_export_result(payload: Dict[str, Any]) -> List[str]:
    lines = [
        "report_export: ready",
        f"world_id: {payload['world_id']}",
        f"run_id: {payload['run_id']}",
        f"artifact_type: {payload['artifact_type']}",
        f"format: {payload['format']}",
        f"execution_mode: {payload['execution_mode']}",
        f"source_ref: {payload['source_ref']}",
        f"side_effect_status: {payload['side_effect_status']}",
    ]
    if payload.get("artifact_ref"):
        lines.append(f"artifact_ref: {payload['artifact_ref']}")
    if payload.get("manifest_ref"):
        lines.append(f"manifest_ref: {payload['manifest_ref']}")
    return lines


def _validate_export_request(artifact_type: str, export_format: str) -> None:
    if artifact_type not in REPORT_EXPORT_ARTIFACT_TYPES:
        allowed = ", ".join(sorted(REPORT_EXPORT_ARTIFACT_TYPES))
        raise ValueError(f"unsupported artifact_type: {artifact_type}; expected one of {allowed}")
    if export_format not in SUPPORTED_REPORT_EXPORT_FORMATS:
        allowed = ", ".join(SUPPORTED_REPORT_EXPORT_FORMATS)
        raise ValueError(f"unsupported format: {export_format}; expected one of {allowed}")


def _run_json_path(world: WorldRecord, run_id: str) -> Path:
    workspace = world.path.parent.parent
    try:
        return RunStore(workspace).get(run_id).run_path
    except KeyError:
        pass
    root = safe_child_path(world.path, "orchestrator_runs")
    direct = safe_child_path(root, run_id, "run.json")
    if direct.exists():
        return direct
    if root.exists():
        for path in sorted(root.glob("*/run.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if payload.get("run_id") == run_id:
                return path
    return direct


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_run(world: WorldRecord, run_id: str) -> tuple[Path, Dict[str, Any]]:
    workspace = world.path.parent.parent
    try:
        record = RunStore(workspace).get(run_id)
        return record.run_path, record.payload
    except KeyError:
        path = _run_json_path(world, run_id)
        return path, _load_json(path)


def _export_dir(world: WorldRecord, run_id: str, created_at: str) -> Path:
    day = created_at[:10] if len(created_at) >= 10 else utc_now()[:10]
    return safe_child_path(
        world.path,
        "artifacts",
        "session_logs",
        day,
        run_id,
        "exports",
    )


def _lines_for_artifact(payload: Dict[str, Any], artifact_type: str) -> List[str]:
    if artifact_type == "human_session_minutes":
        return _human_session_minutes(payload)
    if artifact_type == "draft_output":
        return _draft_output(payload)
    return _round_orchestration_report(payload)


def _human_session_minutes(payload: Dict[str, Any]) -> List[str]:
    lines = [
        "# WSA Session Minutes",
        "",
        f"Run ID: {payload.get('run_id', '')}",
        f"World ID: {payload.get('world_id', '')}",
        f"Workflow: {payload.get('workflow', '')}",
        f"Skill: {payload.get('skill', '')}",
        f"Status: {payload.get('status', '')}",
        f"Topic: {payload.get('topic', '')}",
        f"Question: {payload.get('question', '')}",
        "",
        "## Runtime Boundary",
        *_runtime_boundary_lines(payload),
        "",
        "## Participants",
    ]
    actor_states = payload.get("actor_states", {})
    if actor_states:
        for actor_id, state in sorted(actor_states.items()):
            lines.append(
                f"- {actor_id}: {state.get('represents') or state.get('role_identity') or ''} "
                f"(turns: {state.get('turn_count', 0)})"
            )
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Session Summary"])
    for line in _summary_lines(payload):
        lines.append(f"- {line}")
    lines.extend(["", "## Approval Options"])
    approval_options = payload.get("approval_options", [])
    if approval_options:
        for option in approval_options:
            if isinstance(option, dict):
                lines.append(f"- {option.get('id', '')}: {option.get('label') or option.get('description') or option}")
            else:
                lines.append(f"- {option}")
    else:
        lines.append("- none recorded")
    return lines


def _draft_output(payload: Dict[str, Any]) -> List[str]:
    lines = [
        "# WSA Draft Output",
        "",
        f"Run ID: {payload.get('run_id', '')}",
        f"Workflow: {payload.get('workflow', '')}",
        f"Mode: {_get_nested(payload, 'scene_mode_disclosure', 'resolved_mode') or payload.get('workflow', '')}",
        "",
        "## Runtime Boundary",
        *_runtime_boundary_lines(payload),
        "",
        "## Draft Options",
    ]
    draft_options = payload.get("draft_options", [])
    if draft_options:
        for option in draft_options:
            if isinstance(option, dict):
                lines.append(f"- {option.get('option_id') or option.get('id') or 'option'}: {option.get('summary') or option.get('title') or option}")
            else:
                lines.append(f"- {option}")
    else:
        lines.append("- no draft options recorded")

    line_ledger = payload.get("line_build_ledger", {})
    entries = line_ledger.get("entries", []) if isinstance(line_ledger, dict) else []
    adopted_lines = [
        str(entry.get("candidate_text") or entry.get("line") or "")
        for entry in entries
        if entry.get("adopted_into_draft") and (entry.get("candidate_text") or entry.get("line"))
    ]
    if adopted_lines:
        lines.extend(["", "## Adopted Line-Build Text"])
        lines.extend(adopted_lines)

    synthesis = payload.get("synthesis", {})
    if isinstance(synthesis, dict) and synthesis:
        lines.extend(["", "## Synthesis Notes"])
        for key in ("summary", "recommendation", "stop_reason"):
            if synthesis.get(key):
                lines.append(f"- {key}: {synthesis[key]}")
    lines.extend(["", "## Boundary"])
    lines.append("This export is a proposal/draft artifact. It does not canonize world data by itself.")
    return lines


def _round_orchestration_report(payload: Dict[str, Any]) -> List[str]:
    lines = [
        "# WSA Round Orchestration Report",
        "",
        f"Run ID: {payload.get('run_id', '')}",
        f"Workflow: {payload.get('workflow', '')}",
        f"Status: {payload.get('status', '')}",
        f"Stop/close reason: {payload.get('close_reason') or payload.get('stop_reason') or ''}",
        "",
        "## Runtime Boundary",
        *_runtime_boundary_lines(payload),
        "",
        "## Counts",
    ]
    turn_records = payload.get("turn_records", [])
    outputs = payload.get("subsession_outputs", [])
    rejected = payload.get("rejected_callbacks", [])
    lines.extend(
        [
            f"- turn_records: {len(turn_records)}",
            f"- subsession_outputs: {len(outputs)}",
            f"- rejected_callbacks: {len(rejected)}",
            f"- runtime_hook_packets: {len(payload.get('runtime_hook_packets', []))}",
        ]
    )
    summary = payload.get("actor_contribution_summary", {})
    if isinstance(summary, dict):
        lines.append(f"- callback_total: {summary.get('callback_total', 0)}")
        lines.append(f"- callback_rejected: {summary.get('callback_rejected', 0)}")
        lines.append(f"- rollback_event_count: {summary.get('rollback_event_count', 0)}")
        lines.append(f"- line_build_ledger_entry_count: {summary.get('line_build_ledger_entry_count', 0)}")

    lines.extend(["", "## Turns"])
    if turn_records:
        for turn in turn_records[:120]:
            lines.append(_format_turn(turn))
    else:
        lines.append("- no turn records")
    lines.extend(["", "## Quality And Verification"])
    for line in _quality_lines(payload):
        lines.append(f"- {line}")
    return lines


def _summary_lines(payload: Dict[str, Any]) -> List[str]:
    summary = payload.get("actor_contribution_summary", {})
    lines = [
        f"execution mode: {payload.get('execution_mode', '')}",
        f"output origin: {_get_nested(payload, 'execution_provenance', 'output_origin') or ''}",
        f"turn records: {len(payload.get('turn_records', []))}",
        f"subsession outputs: {len(payload.get('subsession_outputs', []))}",
        f"callback total: {summary.get('callback_total', 0) if isinstance(summary, dict) else 0}",
        f"callback rejected: {summary.get('callback_rejected', 0) if isinstance(summary, dict) else 0}",
        f"line-build ledger entries: {summary.get('line_build_ledger_entry_count', 0) if isinstance(summary, dict) else 0}",
    ]
    disclosure = payload.get("scene_mode_disclosure", {})
    if isinstance(disclosure, dict) and disclosure:
        lines.append(f"scene mode: {disclosure.get('resolved_mode', '')}")
        lines.append(f"actors actually did: {disclosure.get('what_actors_actually_did', '')}")
    return lines


def _runtime_boundary_lines(payload: Dict[str, Any]) -> List[str]:
    provenance = payload.get("execution_provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}
    return [
        f"Execution mode: {payload.get('execution_mode', '')}",
        f"Output origin: {provenance.get('output_origin', '')}",
        (
            "External callback confirmed: "
            f"{str(provenance.get('external_runtime_confirmed', False)).lower()}"
        ),
        f"Callback evidence count: {provenance.get('callback_evidence_count', 0)}",
        f"Real subagent execution: {payload.get('real_subagent_execution', '')}",
        f"Canon policy: {payload.get('canon_policy', 'proposal_only_until_author_approval')}",
        f"World mutations: {len(payload.get('world_mutations', []))}",
    ]


def _quality_lines(payload: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    floor = payload.get("floor_state", {})
    if isinstance(floor, dict):
        queue = floor.get("verification_queue", [])
        lines.append(f"verification_queue_items: {len(queue) if isinstance(queue, list) else 0}")
    evidence = payload.get("fact_audit_evidence_summary", {})
    if isinstance(evidence, dict):
        lines.append(f"fact_audit_evidence_available: {str(evidence.get('evidence_available', False)).lower()}")
    ledger = payload.get("line_build_ledger", {})
    if isinstance(ledger, dict):
        lines.append(f"line_build_ledger_entries: {ledger.get('entry_count', 0)}")
    mode = payload.get("scene_mode_disclosure", {})
    if isinstance(mode, dict) and mode.get("warnings"):
        lines.append(f"mode_warnings: {', '.join(str(item) for item in mode['warnings'])}")
    if not lines:
        lines.append("no quality metadata recorded")
    return lines


def _format_turn(turn: Dict[str, Any]) -> str:
    fields = [
        f"turn={turn.get('turn') or turn.get('turn_id') or ''}",
        f"type={turn.get('turn_type', '')}",
    ]
    for key in ("round", "participant_id", "actor_id", "scheduler_reason", "status"):
        if turn.get(key) not in (None, ""):
            fields.append(f"{key}={turn[key]}")
    if turn.get("summary"):
        fields.append(f"summary={turn['summary']}")
    return "- " + "; ".join(fields)


def _html_document(payload: Dict[str, Any], artifact_type: str, lines: Iterable[str]) -> str:
    title = artifact_type.replace("_", " ").title()
    body = "\n".join(_html_line(line) for line in lines)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} - {html.escape(str(payload.get('run_id', '')))}</title>
  <style>
    body {{ margin: 0; background: #f6f7f9; color: #17202a; font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ width: min(980px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 48px; }}
    section {{ background: #fff; border: 1px solid #d9dee7; border-radius: 8px; padding: 22px; }}
    h1, h2 {{ line-height: 1.15; }}
    p {{ margin: 8px 0; }}
    code {{ background: #eef1f5; border-radius: 5px; padding: 2px 5px; }}
    ul {{ padding-left: 22px; }}
  </style>
</head>
<body>
  <main>
    <section>
{body}
    </section>
  </main>
</body>
</html>
"""


def _html_line(line: str) -> str:
    if line.startswith("# "):
        return f"      <h1>{html.escape(line[2:])}</h1>"
    if line.startswith("## "):
        return f"      <h2>{html.escape(line[3:])}</h2>"
    if line.startswith("- "):
        return f"      <p>&bull; {html.escape(line[2:])}</p>"
    if line == "":
        return "      <br>"
    return f"      <p>{html.escape(line)}</p>"


def _get_nested(payload: Dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _relative_to_world(world: WorldRecord, path: Path) -> str:
    try:
        return str(path.relative_to(world.path))
    except ValueError:
        return str(path)
