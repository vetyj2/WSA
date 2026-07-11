from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    korean = (ROOT / "README.md").read_text(encoding="utf-8").casefold()
    english = (ROOT / "docs" / "en" / "README.md").read_text(encoding="utf-8").casefold()
    korean_usage = (ROOT / "docs" / "USAGE_GUIDE.md").read_text(
        encoding="utf-8"
    ).casefold()
    english_usage = (ROOT / "docs" / "en" / "USAGE_GUIDE.md").read_text(
        encoding="utf-8"
    ).casefold()
    shared_markers = (
        "workspace",
        "hermes",
        "callback",
        "proposal",
        "startup",
        "ticket apply",
        "ticket review",
        "migrate --apply",
        "python 3.9",
        "--record-findings",
        "--repair-safe-artifacts",
        "security.md",
        "license",
    )
    workflow_markers = (
        "world home",
        "source-followup",
        "ticket compose",
        "ticket next",
        "ticket split",
        "report inbox",
        "world actor profile",
        "world actor revise",
        "dispatch-plan",
        "--confirm",
        "restore-plan",
        "fork-plan",
    )
    missing = [
        marker
        for marker in shared_markers
        if marker not in korean or marker not in english
    ]
    missing.extend(
        marker
        for marker in workflow_markers
        if marker not in korean_usage or marker not in english_usage
    )
    if missing:
        print(f"docs_parity: failed; missing shared markers: {', '.join(missing)}")
        return 1
    print(
        "docs_parity: passed "
        f"({len(shared_markers) + len(workflow_markers)} shared markers)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
