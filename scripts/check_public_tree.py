from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TRACKED_PREFIXES = (
    ".env",
    "SESSION_HANDOFF.md",
    "local_admin/",
    "workspace/",
    "hermes/",
    "manager/",
    "reports/",
    "user_profile/",
    "worlds/",
)
FORBIDDEN_TRACKED_BASENAMES = {
    "hermes_commands.local.json",
}
FORBIDDEN_TRACKED_SUFFIXES = (
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def main() -> int:
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    findings: list[str] = []
    for relative in filter(None, tracked):
        if relative == "scripts/check_public_tree.py":
            continue
        path = ROOT / relative
        name = path.name.casefold()
        if (
            relative.startswith(FORBIDDEN_TRACKED_PREFIXES)
            or name == ".env"
            or name.startswith(".env.")
            or ("handoff" in name and name.endswith(".md"))
            or name in FORBIDDEN_TRACKED_BASENAMES
            or name.endswith(FORBIDDEN_TRACKED_SUFFIXES)
            or (
                "operation_policy" in name
                and name.endswith(".json")
                and not name.endswith(".example.json")
            )
        ):
            findings.append(f"forbidden tracked path: {relative}")
            continue
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                findings.append(f"secret-like tracked content: {relative} ({pattern.pattern})")
    if findings:
        print("public_tree_check: failed")
        for finding in findings:
            print(finding)
        return 1
    print(f"public_tree_check: passed ({len(list(filter(None, tracked)))} tracked paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
