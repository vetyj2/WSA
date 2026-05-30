from __future__ import annotations

import re
import uuid


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "world"


def new_world_id(display_name: str) -> str:
    slug = slugify(display_name)
    suffix = uuid.uuid4().hex[:10]
    return f"{slug}-{suffix}"
