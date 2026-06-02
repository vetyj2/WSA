from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ContextManager, Dict, List, Optional

from .workspace import (
    SCHEMA_VERSION,
    control_db_path,
    init_world_schema,
    sqlite_connection,
    utc_now,
    world_db_path,
)


Payload = Dict[str, Any]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def encode_payload(payload: Optional[Payload]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def decode_payload(value: str) -> Payload:
    decoded = json.loads(value)
    if isinstance(decoded, dict):
        return decoded
    return {"value": decoded}


def encode_json_value(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_json_value(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def bounded_level(value: int | None, default: int = 1) -> int:
    try:
        candidate = int(value if value is not None else default)
    except (TypeError, ValueError):
        candidate = default
    return max(1, min(5, candidate))


def infer_attribute_value_type(
    value_number: float | None,
    value_text: str | None,
    value_ref_id: str | None,
    value_json: Any,
) -> str:
    if value_number is not None:
        return "number"
    if value_ref_id is not None:
        return "ref"
    if value_json is not None:
        return "json"
    if value_text in {"true", "false"}:
        return "boolean"
    return "text"


@dataclass(frozen=True)
class RuntimeSessionRecord:
    session_id: str
    workspace_id: str
    world_id: Optional[str]
    scene_id: Optional[str]
    role: str
    runtime_target: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class RuntimeMessageRecord:
    message_id: str
    session_id: str
    message_type: str
    sequence: int
    payload: Payload
    status: str


class ControlRepository:
    def __init__(self, workspace: Path, workspace_id: str = "local") -> None:
        self.workspace = workspace
        self.workspace_id = workspace_id

    def _connect(self) -> ContextManager[sqlite3.Connection]:
        return sqlite_connection(control_db_path(self.workspace), schema_name="control")

    def get_runtime_session(self, session_id: str) -> RuntimeSessionRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, workspace_id, world_id, scene_id, role,
                       runtime_target, status, payload
                FROM runtime_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"runtime session not found: {session_id}")
        return RuntimeSessionRecord(
            session_id=row["session_id"],
            workspace_id=row["workspace_id"],
            world_id=row["world_id"],
            scene_id=row["scene_id"],
            role=row["role"],
            runtime_target=row["runtime_target"],
            status=row["status"],
            payload=decode_payload(row["payload"]),
        )

    def create_runtime_session(
        self,
        role: str,
        runtime_target: str = "mock",
        world_id: str | None = None,
        scene_id: str | None = None,
        payload: Optional[Payload] = None,
        status: str = "created",
    ) -> RuntimeSessionRecord:
        session_id = new_id("session")
        now = utc_now()
        encoded = encode_payload(payload)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_sessions (
                    session_id, workspace_id, world_id, scene_id, role,
                    runtime_target, status, payload, schema_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    self.workspace_id,
                    world_id,
                    scene_id,
                    role,
                    runtime_target,
                    status,
                    encoded,
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return RuntimeSessionRecord(
            session_id=session_id,
            workspace_id=self.workspace_id,
            world_id=world_id,
            scene_id=scene_id,
            role=role,
            runtime_target=runtime_target,
            status=status,
            payload=payload or {},
        )

    def update_runtime_session_status(self, session_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runtime_sessions
                SET status = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (status, utc_now(), session_id),
            )
            conn.commit()

    def add_runtime_message(
        self,
        session_id: str,
        role: str,
        message_type: str,
        payload: Optional[Payload] = None,
        world_id: str | None = None,
        scene_id: str | None = None,
        parent_message_id: str | None = None,
        artifact_refs: Optional[List[str]] = None,
        status: str = "queued",
    ) -> RuntimeMessageRecord:
        message_id = new_id("msg")
        with self._connect() as conn:
            current = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM runtime_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            sequence = int(current) + 1
            conn.execute(
                """
                INSERT INTO runtime_messages (
                    message_id, protocol_version, workspace_id, world_id,
                    scene_id, session_id, role, message_type, sequence,
                    parent_message_id, payload, artifact_refs, status,
                    schema_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    1,
                    self.workspace_id,
                    world_id,
                    scene_id,
                    session_id,
                    role,
                    message_type,
                    sequence,
                    parent_message_id,
                    encode_payload(payload),
                    json.dumps(artifact_refs or [], ensure_ascii=False),
                    status,
                    SCHEMA_VERSION,
                    utc_now(),
                ),
            )
            conn.commit()
        return RuntimeMessageRecord(
            message_id=message_id,
            session_id=session_id,
            message_type=message_type,
            sequence=sequence,
            payload=payload or {},
            status=status,
        )

    def list_runtime_messages(self, session_id: str) -> List[RuntimeMessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT message_id, session_id, message_type, sequence, payload, status
                FROM runtime_messages
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            RuntimeMessageRecord(
                message_id=row["message_id"],
                session_id=row["session_id"],
                message_type=row["message_type"],
                sequence=row["sequence"],
                payload=decode_payload(row["payload"]),
                status=row["status"],
            )
            for row in rows
        ]


@dataclass(frozen=True)
class EntityRecord:
    entity_id: str
    entity_type: str
    display_name: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class FactRecord:
    fact_id: str
    subject_id: str
    predicate: str
    object_value: Optional[str]
    authority: str
    status: str
    confidence: float
    payload: Payload


@dataclass(frozen=True)
class DimensionDefinitionRecord:
    dimension_id: str
    dimension_key: str
    display_name: str
    dimension_type: str
    value_type: str
    applies_to: str
    temporal: bool
    missing_policy: str
    authority: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class EntityAttributeSpanRecord:
    attribute_span_id: str
    entity_id: str
    dimension_key: str
    value_number: Optional[float]
    value_text: Optional[str]
    value_ref_id: Optional[str]
    value_json: Any
    valid_from: Optional[str]
    valid_until: Optional[str]
    authority: str
    status: str
    confidence: float
    stability_level: int
    revision_cost_level: int
    payload: Payload


@dataclass(frozen=True)
class WorldEdgeRecord:
    edge_id: str
    subject_type: str
    subject_id: str
    edge_type: str
    object_type: str
    object_id: Optional[str]
    object_value: Optional[str]
    valid_from: Optional[str]
    valid_until: Optional[str]
    authority: str
    status: str
    confidence: float
    stability_level: int
    revision_cost_level: int
    payload: Payload


@dataclass(frozen=True)
class KnowledgeAttributionRecord:
    knowledge_id: str
    actor_entity_id: str
    target_type: str
    target_id: str
    knowledge_state: str
    acquired_at: Optional[str]
    valid_until: Optional[str]
    authority: str
    status: str
    confidence: float
    payload: Payload


@dataclass(frozen=True)
class SceneRecord:
    scene_id: str
    name: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class TicketRecord:
    ticket_id: str
    ticket_type: str
    title: str
    status: str
    risk: str
    payload: Payload


@dataclass(frozen=True)
class TicketChangeRecord:
    ticket_change_id: str
    ticket_id: str
    change_type: str
    target_type: str
    target_id: Optional[str]
    payload: Payload


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    purpose: str
    title: str
    risk: str
    status: str
    payload: Payload
    artifact_ref: Optional[str] = None


@dataclass(frozen=True)
class DiagnosticLogRecord:
    diagnostic_log_id: str
    diagnostic_type: str
    status: str
    payload: Payload


@dataclass(frozen=True)
class ContextPacketRecord:
    context_packet_id: str
    packet_type: str
    status: str
    payload: Payload


class WorldRepository:
    def __init__(self, world_id: str, world_path: Path) -> None:
        self.world_id = world_id
        self.world_path = world_path

    def _connect(self) -> ContextManager[sqlite3.Connection]:
        return sqlite_connection(world_db_path(self.world_path), schema_name="world")

    def _ensure_additive_world_schema(self) -> None:
        """Create additive tables for older v1 world databases without rewriting data."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                  AND name IN (
                    'dimension_definitions',
                    'entity_attribute_spans',
                    'world_edges',
                    'knowledge_attributions'
                  )
                """
            ).fetchall()
            existing = {row["name"] for row in rows}
            required = {
                "dimension_definitions",
                "entity_attribute_spans",
                "world_edges",
                "knowledge_attributions",
            }
            if required.issubset(existing):
                return
            row = conn.execute(
                "SELECT display_name FROM world_metadata WHERE world_id = ?",
                (self.world_id,),
            ).fetchone()
            init_world_schema(
                conn,
                self.world_id,
                row["display_name"] if row is not None else self.world_id,
            )

    def create_entity(
        self,
        entity_type: str,
        display_name: str,
        payload: Optional[Payload] = None,
        status: str = "active",
    ) -> EntityRecord:
        entity_id = new_id("entity")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO entities (
                    entity_id, world_id, entity_type, display_name, status,
                    payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    self.world_id,
                    entity_type,
                    display_name,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return EntityRecord(entity_id, entity_type, display_name, status, payload or {})

    def list_entities(
        self,
        entity_type: str | None = None,
        status: str | None = None,
    ) -> List[EntityRecord]:
        sql = """
            SELECT entity_id, entity_type, display_name, status, payload
            FROM entities
        """
        clauses = []
        params: list[Any] = []
        if entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC"

        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            EntityRecord(
                entity_id=row["entity_id"],
                entity_type=row["entity_type"],
                display_name=row["display_name"],
                status=row["status"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

    def create_fact(
        self,
        subject_id: str,
        predicate: str,
        object_value: str | None = None,
        object_ref_id: str | None = None,
        time_scope: str | None = None,
        location_scope: str | None = None,
        authority: str = "generated",
        status: str = "proposed",
        confidence: float = 1.0,
        source_ref: str | None = None,
        tags: Optional[List[str]] = None,
        payload: Optional[Payload] = None,
    ) -> FactRecord:
        fact_id = new_id("fact")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO facts (
                    fact_id, world_id, subject_id, predicate, object_value,
                    object_ref_id, time_scope, location_scope, authority, status,
                    confidence, source_ref, tags, payload, schema_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    self.world_id,
                    subject_id,
                    predicate,
                    object_value,
                    object_ref_id,
                    time_scope,
                    location_scope,
                    authority,
                    status,
                    confidence,
                    source_ref,
                    json.dumps(tags or [], ensure_ascii=False),
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return FactRecord(
            fact_id=fact_id,
            subject_id=subject_id,
            predicate=predicate,
            object_value=object_value,
            authority=authority,
            status=status,
            confidence=confidence,
            payload=payload or {},
        )

    def list_facts(self, subject_id: str | None = None) -> List[FactRecord]:
        sql = """
            SELECT fact_id, subject_id, predicate, object_value, authority,
                   status, confidence, payload
            FROM facts
        """
        params: tuple[Any, ...] = ()
        if subject_id is not None:
            sql += " WHERE subject_id = ?"
            params = (subject_id,)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            FactRecord(
                fact_id=row["fact_id"],
                subject_id=row["subject_id"],
                predicate=row["predicate"],
                object_value=row["object_value"],
                authority=row["authority"],
                status=row["status"],
                confidence=row["confidence"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

    def define_dimension(
        self,
        dimension_key: str,
        display_name: str | None = None,
        dimension_type: str = "attribute",
        value_type: str = "text",
        applies_to: str = "entity",
        temporal: bool = True,
        missing_policy: str = "gap_report",
        authority: str = "generated",
        status: str = "proposed",
        payload: Optional[Payload] = None,
    ) -> DimensionDefinitionRecord:
        self._ensure_additive_world_schema()
        key = dimension_key.strip()
        if not key:
            raise ValueError("dimension_key is required")
        existing = self.get_dimension_definition(key)
        if existing is not None:
            return existing
        dimension_id = new_id("dimension")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dimension_definitions (
                    dimension_id, world_id, dimension_key, display_name,
                    dimension_type, value_type, applies_to, temporal,
                    missing_policy, authority, status, payload,
                    schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dimension_id,
                    self.world_id,
                    key,
                    display_name or key.replace("_", " "),
                    dimension_type,
                    value_type,
                    applies_to,
                    1 if temporal else 0,
                    missing_policy,
                    authority,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return DimensionDefinitionRecord(
            dimension_id=dimension_id,
            dimension_key=key,
            display_name=display_name or key.replace("_", " "),
            dimension_type=dimension_type,
            value_type=value_type,
            applies_to=applies_to,
            temporal=temporal,
            missing_policy=missing_policy,
            authority=authority,
            status=status,
            payload=payload or {},
        )

    def get_dimension_definition(
        self,
        dimension_key: str,
    ) -> DimensionDefinitionRecord | None:
        key = dimension_key.strip()
        if not key:
            return None
        self._ensure_additive_world_schema()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT dimension_id, dimension_key, display_name, dimension_type,
                       value_type, applies_to, temporal, missing_policy,
                       authority, status, payload
                FROM dimension_definitions
                WHERE world_id = ? AND dimension_key = ?
                """,
                (self.world_id, key),
            ).fetchone()
        if row is None:
            return None
        return DimensionDefinitionRecord(
            dimension_id=row["dimension_id"],
            dimension_key=row["dimension_key"],
            display_name=row["display_name"],
            dimension_type=row["dimension_type"],
            value_type=row["value_type"],
            applies_to=row["applies_to"],
            temporal=bool(row["temporal"]),
            missing_policy=row["missing_policy"],
            authority=row["authority"],
            status=row["status"],
            payload=decode_payload(row["payload"]),
        )

    def list_dimension_definitions(self, status: str | None = None) -> List[DimensionDefinitionRecord]:
        self._ensure_additive_world_schema()
        sql = """
            SELECT dimension_id, dimension_key, display_name, dimension_type,
                   value_type, applies_to, temporal, missing_policy,
                   authority, status, payload
            FROM dimension_definitions
            WHERE world_id = ?
        """
        params: list[Any] = [self.world_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            DimensionDefinitionRecord(
                dimension_id=row["dimension_id"],
                dimension_key=row["dimension_key"],
                display_name=row["display_name"],
                dimension_type=row["dimension_type"],
                value_type=row["value_type"],
                applies_to=row["applies_to"],
                temporal=bool(row["temporal"]),
                missing_policy=row["missing_policy"],
                authority=row["authority"],
                status=row["status"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

    def set_entity_attribute_span(
        self,
        entity_id: str,
        dimension_key: str,
        value_number: float | None = None,
        value_text: str | None = None,
        value_ref_id: str | None = None,
        value_json: Any = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        source_event_id: str | None = None,
        authority: str = "generated",
        status: str = "proposed",
        confidence: float = 1.0,
        stability_level: int | None = None,
        revision_cost_level: int | None = None,
        payload: Optional[Payload] = None,
    ) -> EntityAttributeSpanRecord:
        key = dimension_key.strip()
        if not key:
            raise ValueError("dimension_key is required")
        self.define_dimension(
            key,
            value_type=infer_attribute_value_type(
                value_number,
                value_text,
                value_ref_id,
                value_json,
            ),
        )
        span_id = new_id("attrspan")
        now = utc_now()
        stability = bounded_level(stability_level, default=2 if status == "proposed" else 4)
        revision_cost = bounded_level(revision_cost_level, default=stability)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO entity_attribute_spans (
                    attribute_span_id, world_id, entity_id, dimension_key,
                    value_number, value_text, value_ref_id, value_json,
                    valid_from, valid_until, source_event_id, authority, status,
                    confidence, stability_level, revision_cost_level, payload,
                    schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    span_id,
                    self.world_id,
                    entity_id,
                    key,
                    value_number,
                    value_text,
                    value_ref_id,
                    encode_json_value(value_json),
                    valid_from,
                    valid_until,
                    source_event_id,
                    authority,
                    status,
                    confidence,
                    stability,
                    revision_cost,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return EntityAttributeSpanRecord(
            attribute_span_id=span_id,
            entity_id=entity_id,
            dimension_key=key,
            value_number=value_number,
            value_text=value_text,
            value_ref_id=value_ref_id,
            value_json=value_json,
            valid_from=valid_from,
            valid_until=valid_until,
            authority=authority,
            status=status,
            confidence=confidence,
            stability_level=stability,
            revision_cost_level=revision_cost,
            payload=payload or {},
        )

    def query_entity_attribute_spans(
        self,
        entity_id: str | None = None,
        dimension_key: str | None = None,
        as_of: str | None = None,
        status: str | None = None,
        value_text: str | None = None,
        value_ref_id: str | None = None,
        min_value_number: float | None = None,
        max_value_number: float | None = None,
    ) -> List[EntityAttributeSpanRecord]:
        self._ensure_additive_world_schema()
        sql = """
            SELECT attribute_span_id, entity_id, dimension_key, value_number,
                   value_text, value_ref_id, value_json, valid_from, valid_until,
                   authority, status, confidence, stability_level,
                   revision_cost_level, payload
            FROM entity_attribute_spans
            WHERE world_id = ?
        """
        params: list[Any] = [self.world_id]
        if entity_id is not None:
            sql += " AND entity_id = ?"
            params.append(entity_id)
        if dimension_key is not None:
            sql += " AND dimension_key = ?"
            params.append(dimension_key.strip())
        if as_of is not None:
            sql += " AND (valid_from IS NULL OR valid_from <= ?)"
            sql += " AND (valid_until IS NULL OR valid_until > ?)"
            params.extend([as_of, as_of])
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        if value_text is not None:
            sql += " AND value_text = ?"
            params.append(value_text)
        if value_ref_id is not None:
            sql += " AND value_ref_id = ?"
            params.append(value_ref_id)
        if min_value_number is not None:
            sql += " AND value_number >= ?"
            params.append(min_value_number)
        if max_value_number is not None:
            sql += " AND value_number <= ?"
            params.append(max_value_number)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            EntityAttributeSpanRecord(
                attribute_span_id=row["attribute_span_id"],
                entity_id=row["entity_id"],
                dimension_key=row["dimension_key"],
                value_number=row["value_number"],
                value_text=row["value_text"],
                value_ref_id=row["value_ref_id"],
                value_json=decode_json_value(row["value_json"]),
                valid_from=row["valid_from"],
                valid_until=row["valid_until"],
                authority=row["authority"],
                status=row["status"],
                confidence=row["confidence"],
                stability_level=row["stability_level"],
                revision_cost_level=row["revision_cost_level"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

    def add_world_edge(
        self,
        subject_type: str,
        subject_id: str,
        edge_type: str,
        object_type: str,
        object_id: str | None = None,
        object_value: str | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        source_event_id: str | None = None,
        authority: str = "generated",
        status: str = "proposed",
        confidence: float = 1.0,
        stability_level: int | None = None,
        revision_cost_level: int | None = None,
        payload: Optional[Payload] = None,
    ) -> WorldEdgeRecord:
        self._ensure_additive_world_schema()
        edge_id = new_id("edge")
        now = utc_now()
        stability = bounded_level(stability_level, default=2 if status == "proposed" else 4)
        revision_cost = bounded_level(revision_cost_level, default=stability)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO world_edges (
                    edge_id, world_id, subject_type, subject_id, edge_type,
                    object_type, object_id, object_value, valid_from, valid_until,
                    source_event_id, authority, status, confidence,
                    stability_level, revision_cost_level, payload,
                    schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge_id,
                    self.world_id,
                    subject_type,
                    subject_id,
                    edge_type,
                    object_type,
                    object_id,
                    object_value,
                    valid_from,
                    valid_until,
                    source_event_id,
                    authority,
                    status,
                    confidence,
                    stability,
                    revision_cost,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return WorldEdgeRecord(
            edge_id=edge_id,
            subject_type=subject_type,
            subject_id=subject_id,
            edge_type=edge_type,
            object_type=object_type,
            object_id=object_id,
            object_value=object_value,
            valid_from=valid_from,
            valid_until=valid_until,
            authority=authority,
            status=status,
            confidence=confidence,
            stability_level=stability,
            revision_cost_level=revision_cost,
            payload=payload or {},
        )

    def query_world_edges(
        self,
        subject_type: str | None = None,
        subject_id: str | None = None,
        edge_type: str | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        as_of: str | None = None,
        status: str | None = None,
    ) -> List[WorldEdgeRecord]:
        self._ensure_additive_world_schema()
        sql = """
            SELECT edge_id, subject_type, subject_id, edge_type, object_type,
                   object_id, object_value, valid_from, valid_until, authority,
                   status, confidence, stability_level, revision_cost_level, payload
            FROM world_edges
            WHERE world_id = ?
        """
        params: list[Any] = [self.world_id]
        for column, value in (
            ("subject_type", subject_type),
            ("subject_id", subject_id),
            ("edge_type", edge_type),
            ("object_type", object_type),
            ("object_id", object_id),
            ("status", status),
        ):
            if value is not None:
                sql += f" AND {column} = ?"
                params.append(value)
        if as_of is not None:
            sql += " AND (valid_from IS NULL OR valid_from <= ?)"
            sql += " AND (valid_until IS NULL OR valid_until > ?)"
            params.extend([as_of, as_of])
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            WorldEdgeRecord(
                edge_id=row["edge_id"],
                subject_type=row["subject_type"],
                subject_id=row["subject_id"],
                edge_type=row["edge_type"],
                object_type=row["object_type"],
                object_id=row["object_id"],
                object_value=row["object_value"],
                valid_from=row["valid_from"],
                valid_until=row["valid_until"],
                authority=row["authority"],
                status=row["status"],
                confidence=row["confidence"],
                stability_level=row["stability_level"],
                revision_cost_level=row["revision_cost_level"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

    def add_knowledge_attribution(
        self,
        actor_entity_id: str,
        target_type: str,
        target_id: str,
        knowledge_state: str,
        acquired_at: str | None = None,
        acquired_event_id: str | None = None,
        source_entity_id: str | None = None,
        valid_until: str | None = None,
        authority: str = "generated",
        status: str = "proposed",
        confidence: float = 1.0,
        payload: Optional[Payload] = None,
    ) -> KnowledgeAttributionRecord:
        self._ensure_additive_world_schema()
        knowledge_id = new_id("knowledge")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_attributions (
                    knowledge_id, world_id, actor_entity_id, target_type,
                    target_id, knowledge_state, acquired_at, acquired_event_id,
                    source_entity_id, valid_until, authority, status,
                    confidence, payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    knowledge_id,
                    self.world_id,
                    actor_entity_id,
                    target_type,
                    target_id,
                    knowledge_state,
                    acquired_at,
                    acquired_event_id,
                    source_entity_id,
                    valid_until,
                    authority,
                    status,
                    confidence,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return KnowledgeAttributionRecord(
            knowledge_id=knowledge_id,
            actor_entity_id=actor_entity_id,
            target_type=target_type,
            target_id=target_id,
            knowledge_state=knowledge_state,
            acquired_at=acquired_at,
            valid_until=valid_until,
            authority=authority,
            status=status,
            confidence=confidence,
            payload=payload or {},
        )

    def query_knowledge_attributions(
        self,
        actor_entity_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        knowledge_state: str | None = None,
        as_of: str | None = None,
        status: str | None = None,
    ) -> List[KnowledgeAttributionRecord]:
        self._ensure_additive_world_schema()
        sql = """
            SELECT knowledge_id, actor_entity_id, target_type, target_id,
                   knowledge_state, acquired_at, valid_until, authority,
                   status, confidence, payload
            FROM knowledge_attributions
            WHERE world_id = ?
        """
        params: list[Any] = [self.world_id]
        for column, value in (
            ("actor_entity_id", actor_entity_id),
            ("target_type", target_type),
            ("target_id", target_id),
            ("knowledge_state", knowledge_state),
            ("status", status),
        ):
            if value is not None:
                sql += f" AND {column} = ?"
                params.append(value)
        if as_of is not None:
            sql += " AND (acquired_at IS NULL OR acquired_at <= ?)"
            sql += " AND (valid_until IS NULL OR valid_until > ?)"
            params.extend([as_of, as_of])
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            KnowledgeAttributionRecord(
                knowledge_id=row["knowledge_id"],
                actor_entity_id=row["actor_entity_id"],
                target_type=row["target_type"],
                target_id=row["target_id"],
                knowledge_state=row["knowledge_state"],
                acquired_at=row["acquired_at"],
                valid_until=row["valid_until"],
                authority=row["authority"],
                status=row["status"],
                confidence=row["confidence"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

    def create_scene(
        self,
        name: str,
        timeline_position: str | None = None,
        payload: Optional[Payload] = None,
        status: str = "draft",
    ) -> SceneRecord:
        scene_id = new_id("scene")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scenes (
                    scene_id, world_id, name, timeline_position, status,
                    payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scene_id,
                    self.world_id,
                    name,
                    timeline_position,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return SceneRecord(scene_id, name, status, payload or {})

    def add_scene_event(
        self,
        scene_id: str,
        event_type: str,
        payload: Optional[Payload] = None,
        commit_status: str = "committed",
    ) -> str:
        event_id = new_id("event")
        now = utc_now()
        with self._connect() as conn:
            current = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM scene_events WHERE scene_id = ?",
                (scene_id,),
            ).fetchone()[0]
            sequence = int(current) + 1
            conn.execute(
                """
                INSERT INTO scene_events (
                    event_id, world_id, scene_id, sequence, event_type,
                    commit_status, payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    self.world_id,
                    scene_id,
                    sequence,
                    event_type,
                    commit_status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return event_id

    def create_ticket(
        self,
        title: str,
        ticket_type: str = "pr_packet",
        status: str = "proposed",
        risk: str = "low",
        payload: Optional[Payload] = None,
    ) -> TicketRecord:
        ticket_id = new_id("ticket")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tickets (
                    ticket_id, world_id, ticket_type, title, status, risk,
                    payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    self.world_id,
                    ticket_type,
                    title,
                    status,
                    risk,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return TicketRecord(ticket_id, ticket_type, title, status, risk, payload or {})

    def get_ticket(self, ticket_id: str) -> TicketRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT ticket_id, ticket_type, title, status, risk, payload
                FROM tickets
                WHERE ticket_id = ?
                """,
                (ticket_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"ticket not found: {ticket_id}")
        return TicketRecord(
            ticket_id=row["ticket_id"],
            ticket_type=row["ticket_type"],
            title=row["title"],
            status=row["status"],
            risk=row["risk"],
            payload=decode_payload(row["payload"]),
        )

    def list_tickets(self, status: str | None = None) -> List[TicketRecord]:
        sql = """
            SELECT ticket_id, ticket_type, title, status, risk, payload
            FROM tickets
        """
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            TicketRecord(
                ticket_id=row["ticket_id"],
                ticket_type=row["ticket_type"],
                title=row["title"],
                status=row["status"],
                risk=row["risk"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

    def update_ticket_status(self, ticket_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_id = ?",
                (status, utc_now(), ticket_id),
            )
            conn.commit()

    def add_ticket_change(
        self,
        ticket_id: str,
        change_type: str,
        target_type: str,
        target_id: str | None = None,
        payload: Optional[Payload] = None,
    ) -> TicketChangeRecord:
        ticket_change_id = new_id("change")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ticket_changes (
                    ticket_change_id, world_id, ticket_id, change_type,
                    target_type, target_id, payload, schema_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_change_id,
                    self.world_id,
                    ticket_id,
                    change_type,
                    target_type,
                    target_id,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return TicketChangeRecord(
            ticket_change_id=ticket_change_id,
            ticket_id=ticket_id,
            change_type=change_type,
            target_type=target_type,
            target_id=target_id,
            payload=payload or {},
        )

    def list_ticket_changes(self, ticket_id: str) -> List[TicketChangeRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ticket_change_id, ticket_id, change_type, target_type,
                       target_id, payload
                FROM ticket_changes
                WHERE ticket_id = ?
                ORDER BY created_at ASC
                """,
                (ticket_id,),
            ).fetchall()
        return [
            TicketChangeRecord(
                ticket_change_id=row["ticket_change_id"],
                ticket_id=row["ticket_id"],
                change_type=row["change_type"],
                target_type=row["target_type"],
                target_id=row["target_id"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]

    def create_report(
        self,
        title: str,
        purpose: str,
        risk: str = "low",
        status: str = "inbox",
        payload: Optional[Payload] = None,
        artifact_ref: str | None = None,
    ) -> ReportRecord:
        report_id = new_id("report")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reports (
                    report_id, world_id, purpose, title, risk, status,
                    payload, artifact_ref, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    self.world_id,
                    purpose,
                    title,
                    risk,
                    status,
                    encode_payload(payload),
                    artifact_ref,
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return ReportRecord(report_id, purpose, title, risk, status, payload or {}, artifact_ref)

    def get_report(self, report_id: str) -> ReportRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT report_id, purpose, title, risk, status, payload, artifact_ref
                FROM reports
                WHERE report_id = ?
                """,
                (report_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"report not found: {report_id}")
        return ReportRecord(
            report_id=row["report_id"],
            purpose=row["purpose"],
            title=row["title"],
            risk=row["risk"],
            status=row["status"],
            payload=decode_payload(row["payload"]),
            artifact_ref=row["artifact_ref"],
        )

    def update_report_status(
        self,
        report_id: str,
        status: str,
        artifact_ref: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reports
                SET status = ?,
                    artifact_ref = COALESCE(?, artifact_ref),
                    updated_at = ?
                WHERE report_id = ?
                """,
                (status, artifact_ref, utc_now(), report_id),
            )
            conn.commit()

    def list_reports(self, status: str | None = None) -> List[ReportRecord]:
        sql = """
            SELECT report_id, purpose, title, risk, status, payload, artifact_ref
            FROM reports
        """
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            ReportRecord(
                report_id=row["report_id"],
                purpose=row["purpose"],
                title=row["title"],
                risk=row["risk"],
                status=row["status"],
                payload=decode_payload(row["payload"]),
                artifact_ref=row["artifact_ref"],
            )
            for row in rows
        ]

    def update_fact_status(self, fact_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE facts SET status = ?, updated_at = ? WHERE fact_id = ?",
                (status, utc_now(), fact_id),
            )
            conn.commit()

    def create_diagnostic_log(
        self,
        diagnostic_type: str,
        status: str,
        payload: Optional[Payload] = None,
    ) -> DiagnosticLogRecord:
        diagnostic_log_id = new_id("diag")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO diagnostic_logs (
                    diagnostic_log_id, world_id, diagnostic_type, status,
                    payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    diagnostic_log_id,
                    self.world_id,
                    diagnostic_type,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return DiagnosticLogRecord(
            diagnostic_log_id=diagnostic_log_id,
            diagnostic_type=diagnostic_type,
            status=status,
            payload=payload or {},
        )

    def create_context_packet(
        self,
        packet_type: str,
        payload: Optional[Payload] = None,
        scene_id: str | None = None,
        actor_entity_id: str | None = None,
        status: str = "active",
    ) -> ContextPacketRecord:
        context_packet_id = new_id("context")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO context_packets (
                    context_packet_id, world_id, scene_id, actor_entity_id,
                    packet_type, status, payload, schema_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context_packet_id,
                    self.world_id,
                    scene_id,
                    actor_entity_id,
                    packet_type,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return ContextPacketRecord(
            context_packet_id=context_packet_id,
            packet_type=packet_type,
            status=status,
            payload=payload or {},
        )

    def append_commit(
        self,
        action: str,
        target_type: str,
        target_id: str | None = None,
        payload: Optional[Payload] = None,
    ) -> str:
        commit_id = new_id("commit")
        with self._connect() as conn:
            current = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM commit_log WHERE world_id = ?",
                (self.world_id,),
            ).fetchone()[0]
            sequence = int(current) + 1
            conn.execute(
                """
                INSERT INTO commit_log (
                    commit_id, world_id, action, target_type, target_id,
                    sequence, payload, schema_version, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    commit_id,
                    self.world_id,
                    action,
                    target_type,
                    target_id,
                    sequence,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    utc_now(),
                ),
            )
            conn.commit()
        return commit_id
