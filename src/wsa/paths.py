from __future__ import annotations

from pathlib import Path


class UnsafePathError(ValueError):
    """Raised when a requested artifact path would escape its base directory."""


def safe_child_path(base: Path, *parts: str) -> Path:
    """Return a child path under base, rejecting absolute or traversal paths."""

    if not parts:
        raise UnsafePathError("at least one path part is required")

    for part in parts:
        candidate = Path(part)
        if candidate.is_absolute():
            raise UnsafePathError(f"absolute paths are not allowed: {part}")
        if ".." in candidate.parts:
            raise UnsafePathError(f"path traversal is not allowed: {part}")

    base_resolved = base.resolve()
    path = base_resolved.joinpath(*parts).resolve()
    try:
        path.relative_to(base_resolved)
    except ValueError as exc:
        raise UnsafePathError(f"path escapes base directory: {path}") from exc
    return path
