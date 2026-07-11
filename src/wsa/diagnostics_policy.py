from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping


DIAGNOSTICS_POLICY_SCHEMA = "wsa.diagnostics.policy.v1"
DIAGNOSTICS_POLICY_FILENAME = "diagnostics_policy.json"
BUILTIN_POLICY_SOURCE = f"builtin:{DIAGNOSTICS_POLICY_SCHEMA}"

CARDINALITY_SINGLETON = "singleton"
CARDINALITY_MULTI = "multi"
INTERVAL_POLICY_OVERLAP = "overlap"
INTERVAL_POLICY_ALL_TIME = "all_time"
VALID_SEVERITIES = {"info", "warning", "error"}

_EDGE_POLICY_KEYS = ("edge_policies", "edge_rules", "edges")
_CARDINALITY_ALIASES = {
    "singleton": CARDINALITY_SINGLETON,
    "single": CARDINALITY_SINGLETON,
    "one": CARDINALITY_SINGLETON,
    "max_one": CARDINALITY_SINGLETON,
    "multi": CARDINALITY_MULTI,
    "multiple": CARDINALITY_MULTI,
    "many": CARDINALITY_MULTI,
}
_INTERVAL_POLICY_ALIASES = {
    "overlap": INTERVAL_POLICY_OVERLAP,
    "overlapping": INTERVAL_POLICY_OVERLAP,
    "overlap_only": INTERVAL_POLICY_OVERLAP,
    "overlapping_only": INTERVAL_POLICY_OVERLAP,
    "active_overlap": INTERVAL_POLICY_OVERLAP,
    "all_time": INTERVAL_POLICY_ALL_TIME,
    "all": INTERVAL_POLICY_ALL_TIME,
    "ignore_intervals": INTERVAL_POLICY_ALL_TIME,
    "regardless_of_interval": INTERVAL_POLICY_ALL_TIME,
}
_SEVERITY_ALIASES = {"warn": "warning"}


class DiagnosticsPolicyValidationError(ValueError):
    """Raised when an inspectable world diagnostics policy is malformed."""


@dataclass(frozen=True)
class EdgeDiagnosticsPolicy:
    cardinality: str
    severity: str
    interval_policy: str
    policy_source: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "cardinality": self.cardinality,
            "severity": self.severity,
            "interval_policy": self.interval_policy,
            "policy_source": self.policy_source,
        }


@dataclass(frozen=True)
class DiagnosticsPolicy:
    schema: str
    edge_policies: Mapping[str, EdgeDiagnosticsPolicy]
    policy_source: str

    def edge_policy(self, edge_type: str) -> EdgeDiagnosticsPolicy | None:
        return self.edge_policies.get(edge_type)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "edge_policies": {
                edge_type: rule.to_dict()
                for edge_type, rule in sorted(self.edge_policies.items())
            },
            "policy_source": self.policy_source,
        }


@dataclass(frozen=True)
class DiagnosticsPolicyIssue:
    code: str
    detail: str
    why_it_matters: str
    suggested_action: str


@dataclass(frozen=True)
class DiagnosticsPolicyLoadResult:
    policy: DiagnosticsPolicy
    path: Path
    status: str
    issue: DiagnosticsPolicyIssue | None = None

    @property
    def loaded(self) -> bool:
        return self.status == "loaded"


def diagnostics_policy_path(world_path: Path) -> Path:
    return world_path / "diagnostics" / DIAGNOSTICS_POLICY_FILENAME


def default_diagnostics_policy() -> DiagnosticsPolicy:
    return DiagnosticsPolicy(
        schema=DIAGNOSTICS_POLICY_SCHEMA,
        edge_policies={
            "located_at": EdgeDiagnosticsPolicy(
                cardinality=CARDINALITY_SINGLETON,
                severity="error",
                interval_policy=INTERVAL_POLICY_OVERLAP,
                policy_source=BUILTIN_POLICY_SOURCE,
            )
        },
        policy_source=BUILTIN_POLICY_SOURCE,
    )


def load_diagnostics_policy(world_path: Path) -> DiagnosticsPolicyLoadResult:
    """Load optional world policy without creating or modifying world artifacts."""

    canonical_path = diagnostics_policy_path(world_path)
    candidates = (
        canonical_path,
        world_path / "diagnostics" / "policy.json",
        world_path / DIAGNOSTICS_POLICY_FILENAME,
    )
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        return DiagnosticsPolicyLoadResult(
            policy=default_diagnostics_policy(),
            path=canonical_path,
            status="absent",
        )
    if len(existing) > 1:
        paths = ", ".join(str(path) for path in existing)
        return _invalid_result(
            canonical_path,
            f"multiple diagnostics policy files found: {paths}",
        )

    path = existing[0]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        policy = parse_diagnostics_policy(payload, policy_source=str(path))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _invalid_result(path, f"cannot read valid JSON: {exc}")
    except DiagnosticsPolicyValidationError as exc:
        return _invalid_result(path, str(exc))
    return DiagnosticsPolicyLoadResult(
        policy=policy,
        path=path,
        status="loaded",
    )


def parse_diagnostics_policy(
    payload: object,
    *,
    policy_source: str = "provided:diagnostics_policy",
) -> DiagnosticsPolicy:
    if not isinstance(payload, dict):
        raise DiagnosticsPolicyValidationError("policy root must be a JSON object")
    if payload.get("schema") != DIAGNOSTICS_POLICY_SCHEMA:
        raise DiagnosticsPolicyValidationError(
            "schema must equal " + DIAGNOSTICS_POLICY_SCHEMA
        )

    unknown_root_fields = set(payload) - {"schema", *_EDGE_POLICY_KEYS}
    if unknown_root_fields:
        raise DiagnosticsPolicyValidationError(
            "unsupported policy field(s): " + ", ".join(sorted(unknown_root_fields))
        )
    present_edge_keys = [key for key in _EDGE_POLICY_KEYS if key in payload]
    if len(present_edge_keys) > 1:
        raise DiagnosticsPolicyValidationError(
            "use only one edge policy field: edge_policies"
        )
    edge_payload = payload.get(present_edge_keys[0], {}) if present_edge_keys else {}
    if not isinstance(edge_payload, dict):
        raise DiagnosticsPolicyValidationError("edge_policies must be a JSON object")

    rules = dict(default_diagnostics_policy().edge_policies)
    for edge_type, raw_rule in edge_payload.items():
        if not isinstance(edge_type, str) or not edge_type.strip():
            raise DiagnosticsPolicyValidationError(
                "edge_policies keys must be non-empty strings"
            )
        normalized_edge_type = edge_type.strip()
        if normalized_edge_type != edge_type:
            raise DiagnosticsPolicyValidationError(
                f"edge_policies.{edge_type!r} must not contain surrounding whitespace"
            )
        rules[normalized_edge_type] = _parse_edge_policy(
            normalized_edge_type,
            raw_rule,
            rules.get(normalized_edge_type),
            policy_source,
        )

    return DiagnosticsPolicy(
        schema=DIAGNOSTICS_POLICY_SCHEMA,
        edge_policies=rules,
        policy_source=policy_source,
    )


def _parse_edge_policy(
    edge_type: str,
    raw_rule: object,
    fallback: EdgeDiagnosticsPolicy | None,
    policy_source: str,
) -> EdgeDiagnosticsPolicy:
    field_path = f"edge_policies.{edge_type}"
    if not isinstance(raw_rule, dict):
        raise DiagnosticsPolicyValidationError(f"{field_path} must be a JSON object")
    allowed_fields = {
        "cardinality",
        "severity",
        "interval_policy",
        "overlap_policy",
    }
    unknown_fields = set(raw_rule) - allowed_fields
    if unknown_fields:
        raise DiagnosticsPolicyValidationError(
            f"{field_path} has unsupported field(s): "
            + ", ".join(sorted(unknown_fields))
        )
    if "cardinality" not in raw_rule:
        raise DiagnosticsPolicyValidationError(f"{field_path}.cardinality is required")
    if "interval_policy" in raw_rule and "overlap_policy" in raw_rule:
        raise DiagnosticsPolicyValidationError(
            f"{field_path} must use only interval_policy"
        )

    cardinality = _normalized_value(
        raw_rule["cardinality"],
        _CARDINALITY_ALIASES,
        f"{field_path}.cardinality",
        sorted({CARDINALITY_SINGLETON, CARDINALITY_MULTI}),
    )
    raw_severity = raw_rule.get(
        "severity",
        fallback.severity if fallback is not None else "warning",
    )
    if not isinstance(raw_severity, str):
        raise DiagnosticsPolicyValidationError(f"{field_path}.severity must be a string")
    severity = _SEVERITY_ALIASES.get(raw_severity, raw_severity)
    if severity not in VALID_SEVERITIES:
        raise DiagnosticsPolicyValidationError(
            f"{field_path}.severity must be one of: "
            + ", ".join(sorted(VALID_SEVERITIES))
        )

    interval_field = (
        "interval_policy" if "interval_policy" in raw_rule else "overlap_policy"
    )
    raw_interval_policy = raw_rule.get(
        interval_field,
        fallback.interval_policy if fallback is not None else INTERVAL_POLICY_OVERLAP,
    )
    interval_policy = _normalized_value(
        raw_interval_policy,
        _INTERVAL_POLICY_ALIASES,
        f"{field_path}.interval_policy",
        sorted({INTERVAL_POLICY_OVERLAP, INTERVAL_POLICY_ALL_TIME}),
    )
    return EdgeDiagnosticsPolicy(
        cardinality=cardinality,
        severity=severity,
        interval_policy=interval_policy,
        policy_source=policy_source,
    )


def _normalized_value(
    value: object,
    aliases: Mapping[str, str],
    field_path: str,
    valid_values: list[str],
) -> str:
    if not isinstance(value, str):
        raise DiagnosticsPolicyValidationError(f"{field_path} must be a string")
    normalized = aliases.get(value)
    if normalized is None:
        raise DiagnosticsPolicyValidationError(
            f"{field_path} must be one of: " + ", ".join(valid_values)
        )
    return normalized


def _invalid_result(path: Path, detail: str) -> DiagnosticsPolicyLoadResult:
    return DiagnosticsPolicyLoadResult(
        policy=default_diagnostics_policy(),
        path=path,
        status="invalid",
        issue=DiagnosticsPolicyIssue(
            code="invalid_diagnostics_policy",
            detail=f"invalid diagnostics policy ignored: {detail}",
            why_it_matters=(
                "World-specific cardinality and interval expectations were not applied; "
                "detectors used the built-in safe defaults."
            ),
            suggested_action=(
                f"Fix {path} to use schema {DIAGNOSTICS_POLICY_SCHEMA} and valid "
                "edge_policies cardinality, severity, and interval_policy values; "
                "the diagnostics run did not rewrite the file."
            ),
        ),
    )
