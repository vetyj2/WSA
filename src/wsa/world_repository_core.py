from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, ContextManager, List, Optional

from .repository_common import (
    Payload,
    decode_payload,
    encode_payload,
    new_id,
)
from .repository_records import (
    EntityRecord,
    FactRecord,
    TimelinePointRecord,
)
from .workspace import (
    SCHEMA_VERSION,
    ensure_current_schema,
    sqlite_connection,
    utc_now,
    world_db_path,
)

class WorldCoreRepositoryMixin:
    def __init__(self, world_id: str, world_path: Path) -> None:
        self.world_id = world_id
        self.world_path = world_path


    def _connect(self) -> ContextManager[sqlite3.Connection]:
        return sqlite_connection(world_db_path(self.world_path), schema_name="world")


    def _ensure_additive_world_schema(self) -> None:
        """Verify that explicit migrations installed the current world schema."""

        with self._connect() as conn:
            ensure_current_schema(conn, "world")
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
            if not required.issubset(existing):
                missing = ", ".join(sorted(required - existing))
                raise RuntimeError(
                    f"world schema {self.world_id} is incomplete after migration: {missing}"
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


    def get_entity(self, entity_id: str) -> EntityRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT entity_id, entity_type, display_name, status, payload
                FROM entities
                WHERE entity_id = ? AND world_id = ?
                """,
                (entity_id, self.world_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"entity not found: {entity_id}")
        return EntityRecord(
            entity_id=row["entity_id"],
            entity_type=row["entity_type"],
            display_name=row["display_name"],
            status=row["status"],
            payload=decode_payload(row["payload"]),
        )


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
            object_ref_id=object_ref_id,
            time_scope=time_scope,
            location_scope=location_scope,
            source_ref=source_ref,
            tags=tuple(tags or []),
        )


    def list_facts(self, subject_id: str | None = None) -> List[FactRecord]:
        sql = """
            SELECT fact_id, subject_id, predicate, object_value, object_ref_id,
                   time_scope, location_scope, authority, status, confidence,
                   source_ref, tags, payload
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
                object_ref_id=row["object_ref_id"],
                time_scope=row["time_scope"],
                location_scope=row["location_scope"],
                source_ref=row["source_ref"],
                tags=tuple(json.loads(row["tags"] or "[]")),
            )
            for row in rows
        ]


    def get_fact(self, fact_id: str) -> FactRecord:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT fact_id, subject_id, predicate, object_value, object_ref_id,
                       time_scope, location_scope, authority, status, confidence,
                       source_ref, tags, payload
                FROM facts
                WHERE fact_id = ? AND world_id = ?
                """,
                (fact_id, self.world_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"fact not found: {fact_id}")
        return FactRecord(
            fact_id=row["fact_id"],
            subject_id=row["subject_id"],
            predicate=row["predicate"],
            object_value=row["object_value"],
            authority=row["authority"],
            status=row["status"],
            confidence=row["confidence"],
            payload=decode_payload(row["payload"]),
            object_ref_id=row["object_ref_id"],
            time_scope=row["time_scope"],
            location_scope=row["location_scope"],
            source_ref=row["source_ref"],
            tags=tuple(json.loads(row["tags"] or "[]")),
        )


    def list_timeline_points(self) -> List[TimelinePointRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timeline_point_id, label, sort_key, payload
                FROM timeline_points
                WHERE world_id = ?
                ORDER BY sort_key ASC, created_at ASC
                """,
                (self.world_id,),
            ).fetchall()
        return [
            TimelinePointRecord(
                timeline_point_id=row["timeline_point_id"],
                label=row["label"],
                sort_key=row["sort_key"],
                payload=decode_payload(row["payload"]),
            )
            for row in rows
        ]


    def create_timeline_point(
        self,
        label: str,
        sort_key: str,
        payload: Optional[Payload] = None,
    ) -> TimelinePointRecord:
        if not label.strip() or not sort_key.strip():
            raise ValueError("timeline point label and sort_key are required")
        timeline_point_id = new_id("time")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO timeline_points (
                    timeline_point_id, world_id, label, sort_key, payload,
                    schema_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timeline_point_id,
                    self.world_id,
                    label.strip(),
                    sort_key.strip(),
                    encode_payload(payload),
                    SCHEMA_VERSION,
                    now,
                    now,
                ),
            )
            conn.commit()
        return TimelinePointRecord(
            timeline_point_id=timeline_point_id,
            label=label.strip(),
            sort_key=sort_key.strip(),
            payload=payload or {},
        )
