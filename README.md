# World Scene Actors

World Scene Actors is a local-first prototype for managing fictional worlds, scene work, reports, and reviewable world-state changes.

The project is designed as a template. It does not include live agent credentials, Telegram/Docker runtime state, or real deployment data.

## Current MVP

- Workspace and per-world SQLite scaffolding
- Repository layer for worlds, facts, scenes, reports, tickets, diagnostics, and runtime messages
- Filesystem-backed runtime inbox/outbox
- Mock scene orchestration and mock actor runtime
- Static HTML report mailbox
- PR packet ticket creation and approval flow
- Explicit fact conflict diagnostics
- CLI-first Hermes adapter template using task and callback JSON files
- Template readiness checks for copied runtime instances

## Install For Local Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

You can also run directly from source:

```bash
PYTHONPATH=src python3 -m wsa --help
```

## Run Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected for this version:

```text
38 tests OK
```

## Quick Smoke Run

```bash
export WSA_WORKSPACE=/tmp/wsa-smoke
PYTHONPATH=src python3 -m wsa init
PYTHONPATH=src python3 -m wsa world create DemoWorld
```

Use the printed `world_created` value:

```bash
PYTHONPATH=src python3 -m wsa scene mock <world_id> Opening \
  --goal "Reach the sealed door" \
  --actor Mina \
  --actor Sol
```

Inspect generated state:

```bash
PYTHONPATH=src python3 -m wsa ticket list <world_id>
PYTHONPATH=src python3 -m wsa report list <world_id>
PYTHONPATH=src python3 -m wsa manager diagnose
```

## Hermes Adapter Template

The Hermes adapter in this repository is a CLI/file-contract template. It writes task JSON files and collects callback JSON files. It does not start Docker, run Telegram bots, open sockets, or store raw secrets.

Create example adapter config in a local workspace:

```bash
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-smoke hermes init-example
```

Create a task packet:

```bash
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-smoke hermes task <world_id> \
  --title "Initial diagnostic" \
  --instruction "Inspect this workspace and return a short callback report."
```

The generated task packet is written under:

```text
workspace/hermes/task_queue/
```

Callbacks are collected from:

```text
workspace/hermes/callbacks/
```

## Template Readiness

Before copying this project into a live runtime instance, verify a clean workspace shape:

```bash
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-template-check template check --write-missing
```

Expected first line:

```text
template_ready: yes
```

## Public Repo Safety

This repository intentionally ignores local workspaces, SQLite databases, runtime queues, callback files, logs, environment files, secrets, and session handoff notes.

Keep real runtime credentials outside the repository. Use environment variables or external secret files managed by your deployment/runtime layer.
