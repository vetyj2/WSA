from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any, ContextManager, List, Optional

from .repository_common import (
    Payload,
    bounded_level,
    decode_json_value,
    decode_payload,
    encode_json_value,
    encode_payload,
    infer_attribute_value_type,
    new_id,
)
from .repository_records import (
    ActorMemoryPacketRecord,
    ActorProfileRecord,
    DimensionDefinitionRecord,
    EntityAttributeSpanRecord,
    KnowledgeAttributionRecord,
    WorldEdgeRecord,
)
from .workspace import (
    SCHEMA_VERSION,
    utc_now,
)

class WorldGraphRepositoryMixin:
    if TYPE_CHECKING:
        world_id: str

        def _connect(self) -> ContextManager[sqlite3.Connection]: ...

        def _ensure_additive_world_schema(self) -> None: ...

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
            source_event_id=source_event_id,
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
                   source_event_id,
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
                source_event_id=row["source_event_id"],
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
            source_event_id=source_event_id,
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
                   object_id, object_value, valid_from, valid_until, source_event_id,
                   authority,
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
                source_event_id=row["source_event_id"],
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
            acquired_event_id=acquired_event_id,
            source_entity_id=source_entity_id,
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
                   knowledge_state, acquired_at, acquired_event_id,
                   source_entity_id, valid_until, authority,
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
                acquired_event_id=row["acquired_event_id"],
                source_entity_id=row["source_entity_id"],
            )
            for row in rows
        ]


    def create_actor_profile(
        self,
        entity_id: str,
        fragment_type: str,
        payload: Optional[Payload] = None,
        status: str = "active",
    ) -> ActorProfileRecord:
        if not entity_id.strip() or not fragment_type.strip():
            raise ValueError("actor profile entity_id and fragment_type are required")
        actor_profile_id = new_id("profile")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO actor_profiles (
                    actor_profile_id, world_id, entity_id, fragment_type,
                    status, payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    actor_profile_id,
                    self.world_id,
                    entity_id,
                    fragment_type,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return ActorProfileRecord(
            actor_profile_id=actor_profile_id,
            entity_id=entity_id,
            fragment_type=fragment_type,
            status=status,
            payload=payload or {},
        )


    def list_actor_profiles(
        self,
        entity_id: str,
        status: str | None = None,
    ) -> List[ActorProfileRecord]:
        sql = """
            SELECT actor_profile_id, entity_id, fragment_type, status, payload
            FROM actor_profiles
            WHERE world_id = ? AND entity_id = ?
        """
        params: list[Any] = [self.world_id, entity_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            ActorProfileRecord(
                actor_profile_id=row["actor_profile_id"],
                entity_id=row["entity_id"],
                fragment_type=row["fragment_type"],
                status=row["status"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]


    def create_actor_memory_packet(
        self,
        entity_id: str,
        time_scope: str,
        payload: Optional[Payload] = None,
        status: str = "active",
    ) -> ActorMemoryPacketRecord:
        if not entity_id.strip() or not time_scope.strip():
            raise ValueError("actor memory entity_id and time_scope are required")
        memory_packet_id = new_id("memory")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO actor_memory_packets (
                    memory_packet_id, world_id, entity_id, time_scope, status,
                    payload, schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_packet_id,
                    self.world_id,
                    entity_id,
                    time_scope,
                    status,
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return ActorMemoryPacketRecord(
            memory_packet_id=memory_packet_id,
            entity_id=entity_id,
            time_scope=time_scope,
            status=status,
            payload=payload or {},
        )


    def list_actor_memory_packets(
        self,
        entity_id: str,
        as_of: str | None = None,
        status: str | None = None,
    ) -> List[ActorMemoryPacketRecord]:
        sql = """
            SELECT memory_packet_id, entity_id, time_scope, status, payload
            FROM actor_memory_packets
            WHERE world_id = ? AND entity_id = ?
        """
        params: list[Any] = [self.world_id, entity_id]
        if as_of is not None:
            sql += " AND time_scope <= ?"
            params.append(as_of)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY time_scope ASC, created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            ActorMemoryPacketRecord(
                memory_packet_id=row["memory_packet_id"],
                entity_id=row["entity_id"],
                time_scope=row["time_scope"],
                status=row["status"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]
