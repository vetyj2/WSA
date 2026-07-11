# Recommended Usage

This guide describes the default author workflow and safety boundary. Human output defaults to Korean; JSON fields remain stable English. Manual review and proposal-only writes are the safe defaults.

## Workflow

```text
author intent and explicit current-world sources
-> neutral questions, context, hooks, or typed change previews
-> optional external agent runtime
-> report/candidate/concrete ticket in the review inbox
-> inspect/revise/hold/reject/review
-> apply reviewed concrete tickets only
```

WSA core does not search for or store API keys, OAuth tokens, SSH keys, or remote URLs.

## First Workspace

```bash
wsa --workspace ./workspace init
wsa --workspace ./workspace world create "My World"
wsa --workspace ./workspace world home
```

With exactly one world, `world home`, `world continue`, and `ticket compose/next/review-next/apply-next` can omit a world selector. Multiple worlds require a unique display name or world ID.

## Startup

Collect the neutral minimum frame first:

```bash
wsa --workspace ./workspace world startup interview <world_id> --budget 4
wsa --workspace ./workspace world startup answer <world_id> 0001 \
  --text "Organize my existing notes into a world reference."
wsa --workspace ./workspace world startup summary <world_id>
```

After the minimum frame is ready, compile questions from files explicitly supplied for this world:

```bash
wsa --workspace ./workspace world startup source-followup <world_id> \
  --source ./notes/opening.txt
```

Questions include `why_asked` and `source_refs`. Source contents are not persisted by this command. Other worlds, beta memory, manager memory, and user profile data are not implicit inputs.

## JSON-free Changes

```bash
wsa --workspace ./workspace ticket compose \
  --title "Add harbor cast" \
  --add-entity "character|Mina" \
  --add-entity "location|Harbor" \
  --add-fact "Mina|role|navigator" \
  --add-edge "Mina|located_at|Harbor"
```

The default is a read-only preview. Repeat with `--write-ticket`, then inspect, review, and apply:

```bash
wsa --workspace ./workspace ticket next
wsa --workspace ./workspace ticket review-next
wsa --workspace ./workspace ticket apply-next
```

Each guided command selects only one eligible concrete ticket. It stops and lists choices when more than one is eligible; the low-level `ticket show/review/apply` commands remain available for explicit ID selection.

Accept, skip, and replace structured candidate items:

```bash
wsa --workspace ./workspace ticket compose \
  --accept-candidate <candidate_ticket_id> \
  --skip-index 2 \
  --add-fact "Mina|mood|focused"
```

Amend an existing ticket while preserving lineage:

```bash
wsa --workspace ./workspace ticket amend <source_ticket_id> \
  --skip-index 1 --add-fact "Mina|role|harbor pilot" --write-ticket
```

Split one ticket into an exact partition, or merge concrete tickets in caller order:

```bash
wsa --workspace ./workspace ticket split <source_ticket_id> \
  --part 1,3 --part 2
wsa --workspace ./workspace ticket merge <ticket_a> <ticket_b> \
  --title "Combined change"
# Inspect either preview, then repeat with --write-ticket.
```

Split and merge retain the original tickets and changes, atomically supersede their sources on write, and preserve lineage.

## Unified Review

```bash
wsa --workspace ./workspace report inbox <world_id>
wsa --workspace ./workspace report show <world_id> <item_id>
wsa --workspace ./workspace report decide <world_id> <item_id> \
  --decision hold --note "Needs evidence"
```

The inbox combines reports, prep, orchestrator runs, candidates, concrete tickets, and callbacks routed to the current world.

## Deep Actor Authoring

All actor writes reuse preview -> ticket -> review -> apply.

```bash
wsa --workspace ./workspace world actor profile <world_id> Mina \
  --fragment goal --text "Reach the signal tower." --write-ticket

wsa --workspace ./workspace world actor attribute <world_id> Mina \
  --dimension condition --value-text wounded \
  --valid-from 002 --valid-until 004 --write-ticket

wsa --workspace ./workspace world actor knowledge <world_id> Mina \
  --target-type fact --target-id <fact_id> --state known \
  --acquired-at 002 --write-ticket

wsa --workspace ./workspace world actor memory <world_id> Mina \
  --time-scope 002 --text "Heard the first shot." --write-ticket

wsa --workspace ./workspace world actor show <world_id> Mina

wsa --workspace ./workspace world actor profile <world_id> Mina \
  --fragment goal --text "Escort the envoy." \
  --replace-record <actor_profile_id> --replace-at 005 --write-ticket

wsa --workspace ./workspace world actor revise <world_id> Mina \
  --record-type actor_profile --record-id <actor_profile_id> \
  --status deprecated --write-ticket
```

`revise` supports profile, entity attribute span, knowledge attribution, and memory packet records. Status/interval revisions and replacements preserve existing `_wsa` provenance and append lifecycle history. Hidden facts and secret profiles are excluded from another viewpoint unless an explicit knowledge attribution allows them. A time-valid `forbidden` attribution overrides known state.

## External Runtime

Inspect a read-only plan:

```bash
wsa --workspace ./workspace orchestrator dispatch-plan <run_id> \
  --runtime-command python3 scripts/reference_stdio_adapter.py
```

Execute and ingest one confirmed turn:

```bash
wsa --workspace ./workspace orchestrator dispatch <run_id> --confirm \
  --runtime-command python3 scripts/reference_stdio_adapter.py
```

`--runtime-command` must be the last option. WSA uses `shell=False`, a minimal environment allowlist, bounded input/output, and a timeout. Do not pass secrets in argv; let the external runtime own its local credential boundary.

Rejected callback text never enters accepted actor/floor context. Retry hooks carry bounded failure reason and correction scope only.

## Diagnostics, Restore, and Fork Planning

```bash
wsa --workspace ./workspace manager diagnose --format json
wsa --workspace ./workspace manager diagnose --record-findings
wsa --workspace ./workspace manager diagnose --repair-safe-artifacts

wsa --workspace ./workspace migrate --apply --format json
wsa --workspace ./workspace migrate restore-plan <backup_root> <new_path>
wsa --workspace ./workspace migrate restore <backup_root> <new_path>

wsa --workspace ./workspace world export <world_id> \
  --entity <entity_id> --format json
wsa --workspace ./workspace world fork-plan <world_id> \
  --name "Alternative World" --entity <entity_id> --format json
```

Restore writes only to a new path. Selective exports include outgoing entity dependencies and exclude runtime messages, callbacks, local overlays, and report HTML. Fork planning is read-only.

## Public Repository Boundary

Do not commit `.env*`, `SESSION_HANDOFF.md`, `local_admin/`, live workspace/SQLite data, task or callback queues, runtime sessions, local command overlays, operation policies, or private remote/SSH paths.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONWARNINGS=error::ResourceWarning PYTHONPATH=src \
  python3 -m unittest discover -s tests
python scripts/check_docs_parity.py
bash scripts/fresh_clone_smoke.sh
```
