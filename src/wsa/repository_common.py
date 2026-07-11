from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional


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
