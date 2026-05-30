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

## Install From A Clone

This project is not published to PyPI. Install it from a local Git clone:

```bash
git clone <repository-url>
cd <repository-directory>
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install .
```

For development, use editable install so local source edits take effect immediately:

```bash
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
53 tests OK
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

By default, `wsa hermes collect-callback` only accepts callback JSON files under the workspace's `hermes/callbacks/` directory. Local automation that needs to import a trusted external file must opt in with `--allow-external-callback`.

Hermes runtimes can implement optional operation requests from the task packet's `operation_contract`. For example, a runtime may map `version_control.snapshot` to `none`, `local_commit`, `remote_push`, or a custom local command. The template declares the action contract only; each user's Hermes adapter owns the actual command mapping and approval policy.

Callback `operation_requests` are accepted only when their action and mode match the published operation contract. Unsupported action names or execution modes are rejected during callback collection.

See `examples/hermes_operation_policy.example.json` for a public-safe policy shape that a user's Hermes runtime can copy into local configuration. Real remote URLs, key paths, tokens, and deployment policy should stay outside the repository.

## Template Readiness

Before copying this project into a live runtime instance, verify a clean workspace shape:

```bash
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-template-check template check --write-missing
```

Expected first line:

```text
template_ready: yes
```

## Pre-Use Diagnostic

After cloning and installing the repository, run a short pre-use diagnostic before connecting any live Hermes runtime:

```bash
python3 -m unittest discover -s tests
wsa --workspace /tmp/wsa-template-check template check --write-missing
wsa --workspace /tmp/wsa-template-check doctor
wsa --workspace /tmp/wsa-template-check manager diagnose
python3 -m json.tool examples/hermes_cli.example.json >/dev/null
python3 -m json.tool examples/hermes_operation_policy.example.json >/dev/null
```

If you have not installed the package and are running directly from the clone, prefix Python and WSA commands with `PYTHONPATH=src`.

Confirm that local admin files, private env files, handoff notes, credentials, tokens, SQLite runtime state, and live workspace artifacts are absent from the clone. The example Hermes files should contain only public-safe schemas, environment variable names, and policy shapes.

`wsa manager diagnose` is read-only by default. Use `--fix` only when you want safe local cleanups and diagnostic log writes.

## Safe Updates

Persistent workspaces can contain live SQLite databases, reports, runtime queues, and agent artifacts. Before pulling template updates into an instance that has live state, back up the workspace directory outside the repository, update the source, run tests against a temporary workspace, and run `wsa doctor` against the live workspace before resuming automation.

WSA refuses to operate on workspace databases with a schema version newer than this build supports. If `wsa doctor` reports an unsupported schema, stop and use a compatible WSA version or an explicit migration path.

## Public Repo Safety

This repository intentionally ignores local workspaces, SQLite databases, runtime queues, callback files, logs, environment files, secrets, and session handoff notes.

Keep real runtime credentials outside the repository. Use environment variables or external secret files managed by your deployment/runtime layer. Treat local workspace contents as potentially sensitive: reports, runtime payloads, and SQLite rows may contain user or world-state data even when the template repository itself is public-safe.
