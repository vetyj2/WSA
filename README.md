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
- Easy Startup interview protocol with startup ambiguity scoring
- CLI-first Hermes adapter template using task and callback JSON files
- Non-mutating meeting mode for representative diagnosis and proposal gathering
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
73 tests OK
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

Start a worldbuilding interview without exhausting the author:

```bash
PYTHONPATH=src python3 -m wsa world startup status <world_id>
PYTHONPATH=src python3 -m wsa world startup interview <world_id> --budget 8
PYTHONPATH=src python3 -m wsa world startup answer <world_id> Q001 --text "A scholarship mage enters the capital academy."
```

Easy Startup separates startup-blocking ambiguity from deeper optional lore. A startup ambiguity score of `0%` means the required opening-world questions are answered or author-approved enough to start early scenes; it does not mean the entire fictional universe is complete.

Authors may also choose high-autonomy or fully autonomous random world generation as a creative constraint. WSA does not forbid `100%` autonomy; it recommends that the user's Hermes runtime and the author agree on natural-language checkpoints such as "until 100 characters exist" or "until three regions have factions, conflicts, and opening hooks." Generated material should still be reported as candidates and committed to canon only through the user's chosen review policy.

Run a non-mutating meeting before committing world changes:

```bash
PYTHONPATH=src python3 -m wsa meeting run <world_id> \
  --topic "Harbor succession gap" \
  --question "Which factions should be consulted before canon changes?" \
  --participant "Harbor Guild" \
  --participant "Unregistered Council"
```

After reviewing the meeting report, record the user's decision:

```bash
PYTHONPATH=src python3 -m wsa meeting decide <world_id> <report_id> --decision approve
PYTHONPATH=src python3 -m wsa meeting decide <world_id> <report_id> --decision retry
PYTHONPATH=src python3 -m wsa meeting decide <world_id> <report_id> --decision hold
```

## Hermes Shortcuts

Hermes chat adapters can load a public-safe shortcut registry after installing this repository:

```bash
PYTHONPATH=src python3 -m wsa hermes commands
PYTHONPATH=src python3 -m wsa hermes commands --format json
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-smoke hermes commands --write-example
```

The canonical command names use underscores, which are safer for bot command menus. Hyphenated forms such as `/wsa-easystart` are included as aliases for Hermes runtimes that parse free-form chat text.

Recommended first shortcuts:

```text
/wsa_help              Show the WSA shortcut menu.
/wsa_doctor            Run WSA and Hermes readiness diagnostics.
/wsa_worlds            List worlds.
/wsa_create_world      Create a new isolated world after confirmation.
/wsa_easystart         Start or continue the Easy Startup interview.
/wsa_answer            Record an author-approved startup answer.
/wsa_autogen           Generate candidates until a natural-language checkpoint.
/wsa_meeting           Run a non-mutating representative meeting.
/wsa_meeting_decide    Approve, retry, or hold a meeting report.
/wsa_reports           List reports for review.
/wsa_tickets           List tickets for review.
/wsa_approve_ticket    Apply a ticket after explicit confirmation.
/wsa_snapshot          Request a version-control snapshot through Hermes policy.
```

`examples/hermes_command_registry.example.json` is the public reference manifest. `wsa hermes init-example` also writes it into `workspace/hermes/adapter_config/` next to the Hermes CLI adapter example.

## Hermes Adapter Template

The Hermes adapter in this repository is a CLI/file-contract template. It writes task JSON files and collects callback JSON files. It does not start Docker, run Telegram bots, open sockets, or store raw secrets.

WSA does not execute Hermes, approve operations, deliver external chat messages, or manage live Hermes profiles. Those responsibilities belong to the user's Hermes runtime, wrapper, and local policy executor. WSA's role is to produce reviewable task contracts, collect validated callbacks, preserve reports, and keep world-state mutation behind explicit tickets or user decisions.

Real Hermes deployments should keep runtime credentials, gateway routing, profile memory, provider settings, approval policy, delivery policy, and long-running process management outside the public template repository.

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

Durable task status is written under `workspace/hermes/task_state/`. Callback validation failures are recorded as metadata under `workspace/hermes/quarantine/`; the quarantine record stores the callback reference and error, not a copied payload.

Task packets and command previews use paths relative to the workspace root. A Hermes runtime should set its working directory to the workspace root, or set `WSA_WORKSPACE` explicitly, then treat packet paths as relative to that root. The example config includes an `agent_harness` contract describing allowed write roots and the policy that Hermes should not directly mutate world databases or world files.

The `agent_harness` also includes an autonomy policy. Autonomy level and random-generation scope belong to the user and Hermes runtime dialogue, not to WSA enforcement. Fully autonomous generation is a valid mode when the user wants a challenge world, but WSA recommends explicit checkpoints and reviewable candidate reports before canon mutation.

Callbacks are collected from:

```text
workspace/hermes/callbacks/
```

By default, `wsa hermes collect-callback` only accepts callback JSON files under the workspace's `hermes/callbacks/` directory. Local automation that needs to import a trusted external file must opt in with `--allow-external-callback`.

Hermes runtimes can implement optional operation requests from the task packet's `operation_contract`. For example, a runtime may map `version_control.snapshot` to `none`, `local_commit`, `remote_push`, or a custom local command. The template declares the action contract only; each user's Hermes adapter owns the actual command mapping and approval policy.

Callback `operation_requests` are accepted only when their action and mode match the published operation contract. Unsupported action names or execution modes are rejected during callback collection.

See `examples/hermes_operation_policy.example.json` for a public-safe policy shape that a user's Hermes runtime can copy into local configuration. Real remote URLs, key paths, tokens, and deployment policy should stay outside the repository.

`examples/wsa_hermes_cli_reference.py` is a safe reference wrapper. It reads a WSA task JSON and writes a callback JSON without starting Hermes, executing shell operations, sending gateway messages, or performing version-control actions. Use it as a contract example, not as a production Hermes runtime.

## Meeting Mode

`wsa meeting run` creates a representative meeting transcript, runtime session messages, and an inbox report. It is intended for Hermes manager and sub-agent work where characters, groups, factions, or loose viewpoints can discuss gaps before anything becomes canon.

Meeting mode is proposal-only: it does not create facts, scene events, tickets, or commits. Unknown participants are represented as unbound viewpoints so the transcript can ask what they should represent instead of silently creating new world entities.

`wsa meeting decide` records the user-facing decision. `approve` marks the report approved and creates a `meeting_candidate` ticket for later explicit conversion into world changes. `retry` rejects the report so Hermes can run another meeting pass. `hold` keeps the report in pending review. None of these decisions directly writes canon facts.

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
