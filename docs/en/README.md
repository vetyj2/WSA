# World Scene Actors

World Scene Actors (WSA) is a local-first harness for fiction and worldbuilding. It provides per-world SQLite stores, neutral Startup interviews, viewpoint/time-aware context, report and ticket review, proposal-only scene/meetup orchestration, and Hermes-compatible callback contracts.

Korean is the default human-output language. JSON fields and schemas remain stable English.

## Responsibility Boundary

WSA core does not choose a provider or read/store API keys, OAuth tokens, SSH keys, or remote URLs. The external runtime selected by the user owns provider credentials, billing, and real agent/subagent/session execution.

WSA owns workspace state, task/hook contracts, callback route validation, report inboxes, reviewed change tickets, diagnostics, migration, and portable export. External runtimes own shell or remote permissions, private commands, delivery channels, deployment, Docker, and cron policy.

`orchestrator dispatch` starts exactly one shell-free process only after the user supplies argv/workdir and passes `--confirm`. WSA neither discovers credentials nor selects a command automatically.

## Current Capabilities

| Area | Status |
| --- | --- |
| Workspace and world isolation | Implemented |
| Neutral Startup and source-grounded follow-up | Implemented |
| World Home and unified review inbox | Implemented |
| JSON-free ticket composition, amendment, split, and merge | Implemented |
| Actor profile, temporal, knowledge, and memory lifecycle | Implemented |
| Mock/external-waiting/external-confirmed provenance | Implemented |
| Provider-neutral stdio dispatch and callback ingest | Implemented |
| Migration backup and restore-to-new-path | Implemented |
| Diagnostics policy, token budget, and selective fork plan | Implemented |

## Install

Python 3.9 or newer is required. The project is installed from a clone, not PyPI.

```bash
git clone <repository-url>
cd <repository-directory>
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

Run from source when needed:

```bash
PYTHONPATH=src python3 -m wsa --help
```

## First Reviewed Change

```bash
wsa --workspace ./workspace init
wsa --workspace ./workspace world create "My World"
wsa --workspace ./workspace world home

wsa --workspace ./workspace ticket compose \
  --title "Add Mina" \
  --add-entity "character|Mina" \
  --add-fact "Mina|role|navigator"

# Inspect the preview, then repeat compose with --write-ticket.
wsa --workspace ./workspace ticket next
wsa --workspace ./workspace ticket review-next
wsa --workspace ./workspace ticket apply-next
```

Preview and review do not mutate world canon. Only `ticket apply-next` applies a reviewed concrete change. Guided commands select only one eligible ticket and stop on ambiguity. Candidate revision and ticket amend/split/merge are covered in the [recommended usage guide](USAGE_GUIDE.md).

Actor profile, temporal state, knowledge boundaries, and memory use the same review/apply path.

```bash
wsa --workspace ./workspace world actor profile <world_id> Mina \
  --fragment goal --text "Reach the signal tower." --write-ticket
wsa --workspace ./workspace world actor show <world_id> Mina
```

## External Runtime

Preview a read-only dispatch plan:

```bash
wsa --workspace ./workspace orchestrator dispatch-plan <run_id> \
  --runtime-command python3 scripts/reference_stdio_adapter.py
```

After reviewing command and workdir, execute and ingest one turn:

```bash
wsa --workspace ./workspace orchestrator dispatch <run_id> --confirm \
  --runtime-command python3 scripts/reference_stdio_adapter.py
```

The reference adapter and a real external runtime use the same stdin hook to stdout callback protocol. Callback ingest never auto-applies canon changes.

## Diagnostics and Recovery

```bash
wsa --workspace ./workspace manager diagnose
wsa --workspace ./workspace manager diagnose --record-findings
wsa --workspace ./workspace manager diagnose --repair-safe-artifacts
wsa --workspace ./workspace migrate --apply --format json
wsa --workspace ./workspace migrate restore-plan <backup> <new-path>
```

`manager diagnose` is read-only by default. Migration apply creates backups and verifies integrity; restore never overwrites the existing workspace path.

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python scripts/check_docs_parity.py
bash scripts/fresh_clone_smoke.sh
```

## Public Repository Safety

Ignore `.env*`, `local_admin/`, `SESSION_HANDOFF.md`, live workspace/SQLite data, task and callback queues, runtime sessions, local command overlays, and operation policies. Public examples should contain schemas and disabled shapes, never real secrets or private remote details.

See [SECURITY.md](SECURITY.md) for reporting and scope, and [MIT License](../../LICENSE) for terms.

## Documentation

- [Recommended usage](USAGE_GUIDE.md)
- [Architecture](ARCHITECTURE.md)
- [Runtime boundaries](RUNTIME_BOUNDARIES.md)
- [Release and migration](RELEASE_AND_MIGRATION.md)
- [Contributing](CONTRIBUTING.md)
- [Korean usage guide](../USAGE_GUIDE.md)
