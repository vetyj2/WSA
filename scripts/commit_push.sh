#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

message="${1:-v0.3.1: SOL refactor and workflow hardening}"
branch="$(git branch --show-current)"

if [[ -z "$branch" || "$branch" == "HEAD" ]]; then
  echo "commit_push: detached HEAD is not supported" >&2
  exit 1
fi

echo "commit_push: running public-safe verification"
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONWARNINGS=error::ResourceWarning PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/check_docs_parity.py
python3 scripts/check_public_tree.py
git diff --check

git add -A

python3 scripts/check_public_tree.py
git diff --cached --check

if git diff --cached --quiet; then
  echo "commit_push: no staged changes"
  exit 0
fi

git commit -m "$message"
git push origin "$branch"
echo "commit_push: pushed $branch"
