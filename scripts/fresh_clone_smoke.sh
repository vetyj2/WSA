#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT
workspace="$tmp_root/workspace"

wsa --workspace "$workspace" init >/dev/null
world_output="$(wsa --workspace "$workspace" world create "Smoke World")"
world_id="$(printf '%s\n' "$world_output" | awk -F': ' '/^world_created: / {print $2}')"
test -n "$world_id"

wsa --workspace "$workspace" world startup summary "$world_id" --format json >/dev/null
wsa --workspace "$workspace" ticket compose \
  --title "Add Mina" --add-entity "character|Mina" \
  --add-fact "Mina|role|navigator" --write-ticket >/dev/null
wsa --workspace "$workspace" ticket next >/dev/null
wsa --workspace "$workspace" ticket review-next >/dev/null
wsa --workspace "$workspace" ticket apply-next >/dev/null

wsa --workspace "$workspace" world actor profile "$world_id" Mina \
  --fragment goal --text "Reach the signal tower." --write-ticket >/dev/null
wsa --workspace "$workspace" ticket review-next >/dev/null
wsa --workspace "$workspace" ticket apply-next >/dev/null
wsa --workspace "$workspace" world actor show "$world_id" Mina --format json >/dev/null
wsa --workspace "$workspace" world show "$world_id" --format json >/dev/null
wsa --workspace "$workspace" world home >/dev/null
wsa --workspace "$workspace" report inbox "$world_id" >/dev/null
wsa --workspace "$workspace" manager diagnose >/dev/null
wsa --workspace "$workspace" migrate --format json >/dev/null
python "$root/scripts/check_docs_parity.py" >/dev/null

echo "fresh_clone_smoke: passed"
