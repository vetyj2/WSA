# World Scene Actors

World Scene Actors is a local-first prototype for managing fictional worlds, scene work, reports, and reviewable world-state changes.

The project is designed as a template. It does not include live agent credentials, Telegram/Docker runtime state, or real deployment data.

## Harness Target

WSA aims to be a compact agent harness template, not a heavy runtime. The template should give Hermes enough structure to do high-quality work with minimal code and minimal operator friction: clear goals, bounded queues, small prompt packets, explicit review boundaries, durable audit artifacts, and no hidden canon mutation. Live agent execution, scheduling, delivery, credentials, and provider-specific optimization belong to the user's Hermes runtime.

The public template should stay world-neutral. Author preferences, naming tastes, active world direction, and live Hermes customizations belong in user profile data, world databases, or local runtime overlays. WSA keeps reusable workflow contracts, safety rules, and example shapes in the repository.

## Current MVP

- Workspace and per-world SQLite scaffolding
- Repository layer for worlds, facts, scenes, reports, tickets, diagnostics, and runtime messages
- Filesystem-backed runtime inbox/outbox
- Mock scene orchestration and mock actor runtime
- Static HTML report mailbox
- PR packet ticket creation and approval flow
- Explicit fact conflict diagnostics
- Startup and Easy Startup interview protocols with ambiguity scoring
- CLI-first Hermes adapter template using task and callback JSON files
- Non-mutating meeting mode for representative diagnosis and proposal gathering
- Manual-trigger autonomous orchestrator lifecycle for meetup/subsession review packages
- Runtime bridge hooks with actor_state and floor_state continuity
- Review queue triage and proposal/callback cleanup audit workflow
- Artifact architecture map for source/export/uninstall boundaries
- Template readiness checks for copied runtime instances

## Architecture Snapshot

WSA is a public-safe local harness template. It owns workspace state, task/callback contracts, diagnostics, reports, tickets, and proposal-only orchestration. It does not run Hermes, store provider keys, approve shell operations, or manage live delivery channels.

| Area | Main Modules | Responsibility |
| --- | --- | --- |
| CLI and workspace | `cli.py`, `workspace.py`, `template.py` | Commands, workspace layout, template readiness |
| Persistence | `repositories.py` | SQLite world data, reports, tickets, temporal graph |
| Diagnostics and updates | `manager.py`, `update.py`, `hermes_doctor.py`, `artifact_map.py` | Doctor checks, update preflight, runtime checks, artifact boundary map |
| Hermes contract | `hermes_adapter.py`, `hermes_commands.py` | Task packets, callback collection, command registry |
| Orchestration | `autonomous_orchestrator.py`, `orchestrator_*`, `orchestrator_bridge.py` | Meetup/scene runs, hook packets, callback turns |
| Review workflows | `meeting.py`, `startup.py`, `reports.py`, `review_cleanup.py`, `tickets.py` | Proposal gathering, interviews, reports, review cleanup, approval tickets |

For a fuller module map, see [ARCHITECTURE.md](ARCHITECTURE.md). For the runtime trust boundary, see [RUNTIME_BOUNDARIES.md](RUNTIME_BOUNDARIES.md).

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
131 tests OK
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

`scene mock` is a deterministic demo path. It is useful for checking the local vertical slice, but it is not a Hermes-backed scene prep run.

For live Hermes-owned scene prep, use the bounded bridge path:

```bash
PYTHONPATH=src python3 -m wsa scene start <world_id> \
  --topic "arrival at a contested transit hub" \
  --time-scope "day 3" \
  --location-scope "central station" \
  --viewpoint "newcomer" \
  --condition "combat_power >= 500" \
  --participant "Narrator" \
  --format json
```

This creates a `scene_generation` / `scene_start` orchestrator run in `hermes-bridge` mode and returns a prep review report by default. WSA does not call actors itself; Hermes reviews the prepared requirement parse, selected context bundles, selector result, gap diagnostics, participant plan, actor-state seeds, and queue limits. If the prep is acceptable, Hermes or the user advances with `wsa orchestrator prep-approve <run_id>`, receives the first actor hook, adapts that hook to its actor/subagent runtime, writes callback JSON under `hermes/callbacks`, then advances the run with `wsa orchestrator submit`.

Pass `--no-prep-review` only when the user's Hermes runtime already performed equivalent prep approval and should open the first actor hook immediately.

Scene start is proposal-only. It prepares actor packets, hidden/visible fact filters, role isolation notes, model/thinking recommendations, risk flags, and a `scene_prep_package`. It does not draft script prose, create canon facts, or mutate the world without later author approval.

Scene generation mode is disclosed rather than forced. `--generation-mode auto` lets the user's Hermes runtime, profile, or natural-language interpretation choose the practical mode; explicit values are `fact-audit-synthesis` and `writing-room-line-build`. Run artifacts record `requested_mode`, `resolved_mode`, `mode_resolution_source`, `mode_confidence`, what actors actually did, and what was not performed. Actor contribution accounting also records callback counts, rejected/rollback events, fact-audit evidence, actor-authored sentence counts, adopted actor proposals, final synthesizer, and actor function labels such as `observer`, `constraint_panel`, `sql_auditor`, `co_writer`, `validator`, and `rollback_trigger`.

`fact-audit-synthesis` is treated as deep fact-audit only when callbacks provide evidence fields such as `source_refs`, `fact_lookup_queries`, `checked_tables`, `checked_reports`, `conflicts_found`, or `deferred_claims`. `writing-room-line-build` is treated as collaborative drafting only when a `line_build_ledger` records candidate text or beats, PASS/FAIL/HOLD/RETRY decisions, rollback reasons, and adopted markers.

Hook packets include a `mode_aware_turn_contract` for the current workflow and scene mode. Meetup turns ask for useful constraints, objections, dependencies, or proposal movement rather than shallow agreement. Fact-audit scene turns ask for evidence and deferred/unchecked claims. Line-build scene turns ask for 1-3 candidate lines or beats plus a validator decision.

Scene and meetup reporting should follow the shared `wsa.reporting.artifact_contract.v1` contract. WSA recommends keeping one date-scoped session log as the source of truth, then exporting human-facing artifacts on demand rather than storing every possible format by default:

- `human_session_minutes`: readable meetup or scene-generation session minutes in TXT/HTML.
- `draft_output`: meetup conclusion, scene draft, or manuscript-style output in TXT/HTML.
- `round_orchestration_report`: round/checkpoint orchestration report in TXT/HTML for scheduling, quality gates, rejected outputs, rollback triggers, and stop reasons.

Automatic export and delivery remain user/Hermes profile choices. The contract exists so Hermes can consistently generate, skip, delete, or re-export artifacts without WSA owning chat delivery or runtime preferences.

Artifacts produced while using the harness should stay inside the managed workspace architecture whenever possible: world `artifacts/`, `meetings/`, `orchestrator_runs/`, `scenes/`, report mailboxes, or `hermes/reports_outbox/`. If a runtime must create files outside those roots, it should write an `artifact_source_map.json` manifest using the reporting contract's source-map fields. That manifest should record the origin run/session, artifact type, path, manager, cleanup hint, and whether the file is safe to delete with the session. This keeps install, migration, archive, and uninstall operations tractable.

The workspace can also store a compact artifact architecture map at `manager/artifact_map/artifact_architecture_map.json`. This file is not another data lake; it is the bounded directory map that distinguishes source-of-truth zones such as `control.sqlite`, `worlds/{world_id}/world.sqlite`, startup profiles, orchestrator run logs, and session logs from managed artifact zones such as report mailboxes, world artifacts, scene/meeting folders, and Hermes archive/outbox paths. The default policy is dry-run, archive-before-delete, and warn-only for unknown external artifacts.

```bash
PYTHONPATH=src python3 -m wsa artifact map
PYTHONPATH=src python3 -m wsa artifact map --write --format json
```

Scene filters are connected to a sparse temporal graph foundation. A world can define its own dynamic dimensions such as `combat_power`, `current_location`, `political_influence`, or any other label the author and Hermes agree to use. Existing entities are not required to have every dimension. Missing dimensions or missing values are reported as scene-prep gaps instead of crashing the run.

The thin graph layer is additive and world-local:

- `dimension_definitions` stores user/world-defined dimensions and their value policy.
- `entity_attribute_spans` stores values that can change over time, such as location, status, capability, or affiliation.
- `world_edges` stores flexible relationships between entities, facts, scenes, events, or other world objects.
- `knowledge_attributions` stores who knows, believes, suspects, or misunderstands a target fact at a given time.

This layer does not replace canon facts. It gives Doctor, Patrol, Meetup, and Scene a compact place to inspect sparse data, suggest gap-filling meetups, and prepare viewpoint-safe scene context.

When a simple operator condition can be resolved locally, `scene start` also returns a bounded `selector_result`. For example, if `combat_power` and `current_location` spans exist, a request such as `--time-scope "day 3" --location-scope "central station" --condition "combat_power >= 500"` can return matching entity IDs and compact display names for Hermes to use as scene-prep candidates. Unsupported natural-language conditions and missing dimensions remain gap diagnostics for Doctor, Patrol, or Meetup instead of blocking the run.

Inspect generated state:

```bash
PYTHONPATH=src python3 -m wsa ticket list <world_id>
PYTHONPATH=src python3 -m wsa report list <world_id>
PYTHONPATH=src python3 -m wsa manager diagnose
```

When a live workspace has accumulated pending proposal reports, review-bound orchestrator runs, or callback residue, keep cleanup under the `report` lifecycle instead of deleting files manually:

```bash
PYTHONPATH=src python3 -m wsa report triage <world_id>
PYTHONPATH=src python3 -m wsa report reject-pending <world_id> \
  --reason "author rejected pending proposals" \
  --archive-callbacks
PYTHONPATH=src python3 -m wsa report archive-callbacks <world_id> \
  --reason "completed callback residue"
```

`report triage` is read-only. `reject-pending` changes only pending proposal reports and author-review orchestrator runs, then writes an audit JSON under `reports/archived/`. Callback cleanup moves JSON files to `hermes/callback_archive/`; it does not raw-delete them. Approved reports, canon facts, tickets, startup profile data, and DB schema are excluded from this cleanup path.

Start a worldbuilding interview without exhausting the author. `startup` is the open-ended author-facing mode: it gives minimal framing, at most three choices per question, and expects longer free-text answers where the author wants control.

```bash
PYTHONPATH=src python3 -m wsa world startup status <world_id>
PYTHONPATH=src python3 -m wsa world startup status <world_id> --format json
PYTHONPATH=src python3 -m wsa world startup interview <world_id> --budget 4
PYTHONPATH=src python3 -m wsa world startup answer <world_id> 0001 --text "A newcomer enters a contested institution."
```

`easystartup` is the easy-pick mode: it gives 5-8 tagged recommendations per item, keeps questions more closed, and lets Hermes fill details according to the selected discretion level.

```bash
PYTHONPATH=src python3 -m wsa world easystartup set-discretion <world_id> --level 3
PYTHONPATH=src python3 -m wsa world easystartup status <world_id> --format json
PYTHONPATH=src python3 -m wsa world easystartup interview <world_id> --budget 8
PYTHONPATH=src python3 -m wsa world easystartup batch-answer <world_id> --text "0001a 0002b 0003e plus any free note"
```

Interview questions use four-digit IDs and lettered choices so Hermes can keep collecting answers even if the conversation wanders. A user can answer several at once, for example `0001a 0002b 0003e`, then add free text after the codes. WSA stores the active question list in `worlds/<world_id>/startup/startup_profile.json`; Hermes should keep returning the current progress percentage and a next question until the user explicitly stops the interview.

Startup ambiguity separates startup-blocking ambiguity from deeper optional lore. A startup ambiguity score of `0%` means the required opening-world questions are answered or author-approved enough to start early scenes; it does not mean the entire fictional universe is complete.

Authors may also choose high-autonomy or fully autonomous random world generation as a creative constraint. WSA does not forbid `100%` autonomy; it recommends that the user's Hermes runtime and the author agree on natural-language checkpoints such as "until 100 characters exist" or "until three regions have factions, conflicts, and opening hooks." Generated material should still be reported as candidates and canonized only through the user's chosen review policy.

The default discretion scale is customizable by the user's Hermes runtime:

```text
0  author_only                 Hermes asks before filling any world detail.
1  ask_before_filling          Hermes proposes small options, then waits.
2  small_gaps_allowed          Hermes fills minor connective details as candidates.
3  balanced_fill               Hermes pre-fills ordinary supporting details and reports assumptions.
4  broad_agent_fill            Hermes runs larger lower-layer candidate passes.
5  challenge_world_autonomy    Hermes may prepare cron-capable fill loops toward a destination checkpoint.
```

At level `5`, Hermes should ask for the destination checkpoint before starting automation, stop when that checkpoint is met, explicitly report that the cron job stopped, run a quality gate against the stated condition, and then request user approval before canon conversion.

Hermes runtimes can also expose `/fill-the-rest` or `/filltherest` for anytime lower-layer filling. This is proposal-only by default: it prepares candidate generation for remaining details until a user-defined destination, then performs quality diagnosis before asking for approval. Runtimes that support automation should treat `/filltherest-plan` as the read-only planning step and `/filltherest-start` as the explicit-approval step that may start cron-capable work.

```text
/fill-the-rest world=<world_id> destination="until every region has factions and hooks" discretion_level=5
/filltherest world=<world_id> destination="until the central institution has mentors, rivals, rituals, and scene hooks"
/filltherest-plan world=<world_id> destination="until the trade district has factions, conflicts, and scene hooks"
/filltherest-start world=<world_id> destination="until the trade district has factions, conflicts, and scene hooks" cron_schedule="daily"
```

Run a non-mutating meeting before applying world-state changes:

```bash
PYTHONPATH=src python3 -m wsa meeting run <world_id> \
  --topic "Trade district succession gap" \
  --question "Which factions should be consulted before canon changes?" \
  --participant "Local Guild" \
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

The user-facing command surface should stay compact even as WSA gains more workflows. Hermes adapters should expose a small menu of entrypoints, then route internally by workflow, mode, scope, target, and action.

Recommended visible entrypoints:

```text
Startup   Initial world setup. Easystartup is Startup with easy-pick mode.
Meetup    Non-canon working meetings, worldbuilding candidates, fill work, and re-meetups.
Scene     Scene prep, scene data logs, actor packets, viewpoint filtering, and localized scene scope.
Patrol    Periodic or reactive world hygiene checks, stale work review, and gap scanning.
Doctor    Installation, update, runtime contract, template, and adapter diagnostics.
Database  World data inspection, reports, tickets, facts, export, import, and migration.
```

Compatibility commands such as `/wsa_easystartup`, `/wsa_scene_start`, `/fill_the_rest`, `/wsa_reports`, and `/wsa_update` remain available as parser routes or aliases. They should not all be exposed as top-level menu items unless a specific Hermes runtime wants an expert-mode menu. The registry publishes this as `canonical_menu_surface`.

The canonical command names use underscores, which are safer for bot command menus. Hyphenated forms such as `/wsa-easystartup` and `/wsa-easystart` are included as aliases for Hermes runtimes that parse free-form chat text.

Hermes command adapters should treat the registry as an argv/template contract, not as shell text. This keeps Docker, VPS services, and local shells aligned:

- Register canonical underscore commands in Telegram menus; treat hyphenated commands as free-form aliases.
- Parse chat input into named arguments, then run CLI templates as argv arrays. Do not join templates into a shell string.
- Omit optional flags when the user leaves them blank. For repeatable arguments such as meeting participants, repeat the flag once per value.
- For commands with `input_json_template`, resolve placeholders into an object, JSON-serialize that object, and pass it as the `--input-json` argv value.
- Set the working directory to the workspace root or set `WSA_WORKSPACE`; task packet paths are relative to the workspace root.
- Prefer JSON outputs for startup/easystartup command handling, then summarize them for chat.

Existing slash commands in the registry are compatibility and implementation routes for those entrypoints. New features should first attach to an existing entrypoint with a workflow or mode before adding another user-visible command.

`/wsa_startup` and `/wsa_easystartup` are not pure read-only commands. They may create or update the active interview profile so progress can resume later; Hermes should not run them while `hermes/maintenance/update.lock` exists.

`examples/hermes_command_registry.example.json` is the public reference manifest. `wsa hermes init-example` also writes it into `workspace/hermes/adapter_config/` next to the Hermes CLI adapter example.

Runtime-specific shortcuts should live in `workspace/hermes/adapter_config/hermes_commands.local.json`, using the shape in `examples/hermes_command_registry.local.example.json`. Base updates may replace the generated example registry, but must preserve the local overlay. Local commands must not reuse a base command name or alias; `wsa update preflight` blocks that collision so a stale override cannot hide a new WSA command.

WSA should not upstream every live user's Hermes shortcuts into the official registry. User/path/world-specific aliases belong in the local overlay. The official template provides the compatibility layer: write a local template, validate it, and preview the merged registry:

```bash
wsa --workspace <live-workspace> hermes commands --write-local-template
wsa --workspace <live-workspace> hermes commands --validate-local-overlay --format json
wsa --workspace <live-workspace> hermes commands --merged --format json
```

Hermes should run local overlay validation before and after source updates. Blocking findings mean a local command or alias collides with the official registry or reserved `/wsa_`/`/filltherest` namespace. Warning findings usually mean a mutating local command is missing confirmation, side-effect, or rollback metadata; Hermes can continue only after briefing the user and recommending cleanup.

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

Durable task status is written under `workspace/hermes/task_state/`. After a callback is collected successfully, WSA moves the completed task packet and callback file into `workspace/hermes/task_archive/` and `workspace/hermes/callback_archive/` so update preflight does not keep seeing normal completed work as pending runtime work. Callback validation failures are recorded as metadata under `workspace/hermes/quarantine/`; the quarantine record stores the callback reference and error, not a copied payload.

Task packets and command previews use paths relative to the workspace root. A Hermes runtime should set its working directory to the workspace root, or set `WSA_WORKSPACE` explicitly, then treat packet paths as relative to that root. The example config includes an `agent_harness` contract describing allowed write roots and the policy that Hermes should not directly mutate world databases or world files.

The `agent_harness` also includes an autonomy policy. Autonomy level and random-generation scope belong to the user and Hermes runtime dialogue, not to WSA enforcement. Fully autonomous generation is a valid mode when the user wants a challenge world, but WSA recommends explicit checkpoints and reviewable candidate reports before canon mutation.

Callbacks are collected from:

```text
workspace/hermes/callbacks/
```

By default, `wsa hermes collect-callback` only accepts callback JSON files under the workspace's `hermes/callbacks/` directory. Local automation that needs to import a trusted external file must opt in with `--allow-external-callback`.

Callback validation is structural and route-based. It is not cryptographic authentication or OAuth-style authorization. Keep `hermes/callbacks/` writable only by the trusted local Hermes runtime or operator automation, and do not expose it as an untrusted upload surface.

Hermes runtimes can implement optional operation requests from the task packet's `operation_contract`. For example, a runtime may map `version_control.snapshot` to `none`, `local_commit`, `remote_push`, or a custom local command. The template declares the action contract only; each user's Hermes adapter owns the actual command mapping and approval policy.

Callback `operation_requests` are accepted only when their action and mode match the published operation contract. Unsupported action names or execution modes are rejected during callback collection.

See `examples/hermes_operation_policy.example.json` for a public-safe policy shape that a user's Hermes runtime can copy into local configuration. Real remote URLs, key paths, tokens, and deployment policy should stay outside the repository.

`examples/wsa_hermes_cli_reference.py` is a safe reference wrapper. It reads a WSA task JSON and writes a callback JSON without starting Hermes, executing shell operations, sending gateway messages, or performing version-control actions. Use it as a contract example, not as a production Hermes runtime.

## Meeting Mode

`wsa meeting run` creates a lightweight representative meeting transcript, runtime session messages, and an inbox report. It is intended for simple Hermes manager checks where characters, groups, factions, or loose viewpoints can discuss gaps before anything becomes canon. This is the cheap/static meeting path, not the full autonomous orchestrator lifecycle.

Meeting mode is proposal-only: it does not create facts, scene events, tickets, or commits. Unknown participants are represented as unbound viewpoints so the transcript can ask what they should represent instead of silently creating new world entities.

`wsa meeting decide` records the user-facing decision. `approve` marks the report approved and creates a `meeting_candidate` ticket for later explicit conversion into world changes. `retry` rejects the report so Hermes can run another meeting pass. `hold` keeps the report in pending review. None of these decisions directly writes canon facts.

## Autonomous Orchestrator

For full meetup/subsession work, use `wsa orchestrator run`. This is the manual-trigger/autonomous-execution workflow:

```text
manual trigger -> isolated orchestration session -> plan subagents -> carry compressed context -> run queue turns -> synthesize -> diagnose -> close subsessions -> await author review
```

Hermes may already know how to call subagents. WSA does not replace that runtime. WSA defines the durable protocol for using those calls as one continuing meeting floor: it records the isolated run scope, plan/frame, participant prompt packets, compressed context snapshots, queue limits, output quality gates, synthesis, and approval package. Hermes owns actual subagent invocation, delivery, scheduling, and user-facing execution policy. The template CLI creates deterministic local simulated subsession outputs so the contract can be tested before a live Hermes runtime is wired in.

The meeting floor should feel like a real meeting or shooting set. Until the chair/author closes the session, a conclusion is reached, or a hard limit is hit, every participant should receive compressed continuity from the same floor. To control token use, subsession and sub-subsession prompts should be short and exact: usually one sentence or the specific requested field. WSA records only quality-gated outputs as accumulated meeting material.

Every meetup or scene-start style run needs a plan/frame and hard limits before it begins. If the user has not customized them, WSA supplies conservative defaults: bounded queue turns, bounded total subsession calls, a maximum concurrency recommendation, explicit cleanup of ephemeral sessions, and partial-report behavior when no conclusion is reached. A runtime that cannot identify a frame, termination policy, cleanup policy, and concurrency limit should not start the run.

Example:

```bash
wsa orchestrator run <world_id> \
  --workflow meetup \
  --skill meetup \
  --topic "rival institutions and their power traditions" \
  --frame-plan "Compare institutional pressures without canonizing new claims." \
  --rounds 3 \
  --max-queue-turns 12 \
  --max-concurrent-subsessions 4 \
  --max-subsession-calls 48 \
  --context-policy compressed-continuity \
  --participant "Northern Institute" \
  --participant "Southern Guild"
```

The orchestrator creates a durable audit artifact under `worlds/<world_id>/orchestrator_runs/`, starts temporary runtime session records for participant viewpoints, gives each only the relevant context and prompt packet, runs up to the configured queue limit, carries a compressed meeting summary between turns, collects outputs, asks internal follow-up questions when uncertainty is high, diagnoses conflicts and gaps, closes temporary subsessions, and returns a synthesized report package. It does not canonize generated material.

There are two primary entrypoint profiles:

- `meetup`: a representative meeting for worldbuilding facts, startup candidates, scene-prep questions, conflict diagnosis, or a specific creative objective. It emphasizes participant expansion, objections, grievances, compromise/fault-line discovery, manager checks, and approval choices.
- `scene_generation` / `scene_start`: scene prep before script-like generation. It filters facts, history, memory, viewpoint knowledge, hidden truths, actor assignments, multi-role isolation, parallel actor/session recommendations, model/thinking guidance, and prep-complete checks before any draft or canon mutation.

Each run records `workflow_profile`, `floor_state`, mixed `turn_records`, and `runtime_hook_packets`. Hook packets contain a Hermes-owned terminal command shape plus the bounded prompt that Hermes can adapt into its own subagent/session syntax. This keeps WSA as the state, prompt, audit, quality-gate, and approval harness while leaving actual actor/subagent calls to the user's Hermes runtime.

`--max-queue-turns` and `--max-subsession-calls` are infinite-loop and cost guards. `--max-concurrent-subsessions` tells Hermes when to batch work instead of running too many perspectives at once. If the requested round budget exceeds the limits, the run stops at the limit, closes or marks temporary sessions, and returns a partial review package instead of continuing indefinitely. Skills such as meetup or scene start can use the same orchestrator contract while keeping their run memory isolated to that specific task.

Inspect or decide a package:

```bash
wsa orchestrator status <run_id> --format json
wsa orchestrator report <run_id>
wsa orchestrator hooks <run_id> --format json
wsa orchestrator decide <run_id> --decision approve --option option-a
wsa orchestrator decide <run_id> --decision retry
wsa orchestrator close <run_id> --reason "superseded"
```

For a Hermes-owned live loop, start the run with bridge mode. WSA still does not execute Hermes; it returns the next hook packet, waits for a callback file under `hermes/callbacks`, quality-gates that callback, updates `floor_state`, and then exposes the next hook.

```bash
wsa orchestrator run <world_id> --workflow meetup --topic "..." --mode hermes-bridge
wsa scene start <world_id> --topic "..." --format json
wsa orchestrator next <run_id> --format json
wsa orchestrator prep-approve <run_id> --format json
wsa orchestrator submit <run_id> --callback hermes/callbacks/<callback>.json --format json
```

The bridge loop uses the same compact command surface. Hermes does not need a new user-visible slash command for `next`, `prep-approve`, or `submit`; those are internal CLI routes for the active Meetup or Scene session. Prep review is default-on so the user can approve or refine the selected context before actor calls spend tokens. Callback files must stay under `hermes/callbacks`, match the pending hook route, and pass the bounded output quality gate before the run advances.

Before a live user resumes Hermes after a source update, run:

```bash
wsa update preflight --format json
wsa doctor
wsa manager diagnose
```

If preflight recommends or requires it, make a workspace backup before starting scene work. Scene start refuses to run while `hermes/maintenance/update.lock` exists.

Long meetup or scene-prep runs also publish an optional `progress_report_policy`. It is disabled by default and is only a Hermes/user opt-in delivery contract. When enabled, Hermes should report interim status only at explicit round or checkpoint boundaries, include the current and maximum round such as `라운드 7/100 현황` or `Round 7/100 status`, and include stop reason plus side-effect status in the final report.

Approval creates an `orchestrator_candidate` ticket only. Converting accepted options into facts, scenes, actor selections, or canonical world changes remains a later explicit ticket/apply step.

## Template Readiness

Before copying this project into a live runtime instance, verify a clean workspace shape:

```bash
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-template-check template check --write-missing
```

Expected first line:

```text
template_ready: yes
```

## Patch Dashboards

Versioned patches that change architecture, workflows, scripts, Hermes contracts, or runtime behavior should add a human-readable HTML dashboard under `change_log/` and link it from `change_log/index.html` before commit. These dashboards summarize module size, workflow shape, runtime ownership, and user-facing flow so reviewers do not need to reconstruct the product impact from raw diffs alone.

## Pre-Use Diagnostic

After cloning and installing the repository, run a short pre-use diagnostic before connecting any live Hermes runtime:

```bash
python3 -m unittest discover -s tests
PYTHONWARNINGS=error::ResourceWarning python3 -m unittest discover -s tests
python3 -m compileall -q src tests examples/wsa_hermes_cli_reference.py
wsa --workspace /tmp/wsa-template-check template check --write-missing
wsa --workspace /tmp/wsa-template-check doctor
wsa --workspace /tmp/wsa-template-check manager diagnose
wsa --workspace /tmp/wsa-template-check update preflight --format json >/dev/null
python3 -m json.tool examples/hermes_cli.example.json >/dev/null
python3 -m json.tool examples/hermes_command_registry.example.json >/dev/null
python3 -m json.tool examples/hermes_operation_policy.example.json >/dev/null
```

If you have not installed the package and are running directly from the clone, prefix Python and WSA commands with `PYTHONPATH=src`.

Confirm that local admin files, private env files, handoff notes, credentials, tokens, SQLite runtime state, and live workspace artifacts are absent from the clone. The example Hermes files should contain only public-safe schemas, environment variable names, and policy shapes.

`wsa manager diagnose` is read-only by default. Use `--fix` only when you want safe local cleanups and diagnostic log writes.

## Safe Updates

Persistent workspaces can contain live SQLite databases, reports, runtime queues, custom command overlays, and agent artifacts. Before pulling template updates into an instance that has live state, run a read-only update preflight:

```bash
wsa --workspace <live-workspace> update preflight --source-root <wsa-source-root>
wsa --workspace <live-workspace> update preflight --source-root <wsa-source-root> --format json
wsa --workspace <live-workspace> update backup --output-dir <backup-root> --source-root <wsa-source-root>
```

For Hermes chat adapters, `/wsa_update` maps to this preflight. It does not pull, overwrite, migrate, or delete files. The user's Hermes runtime owns the actual source update and approval policy. If Hermes runs from the workspace root, pass the installed WSA source checkout explicitly as `source_root`; otherwise omit it rather than letting the workspace directory masquerade as source code.

Safe update architecture:

- Treat the source/package layer, live workspace, and runtime-local config as separate layers.
- Preserve `workspace/hermes/adapter_config/hermes_commands.local.json`; refresh only generated base files such as `hermes_commands.example.json`.
- Validate local command overlays before and after source updates. If preflight reports high collision risk, Hermes should tell the user which local command should be renamed or documented before live use resumes.
- Pause Hermes task intake, callbacks, and cron jobs before updating. Preflight blocks when pending task queue files, callback files, report outbox files, active task state, or active scheduler jobs are present.
- Back up the live workspace outside the source checkout before updating. SQLite databases, world folders, reports, runtime queues, and local Hermes config should all be restorable.
- During update or backup, mutating WSA CLI paths should respect `workspace/hermes/maintenance/update.lock`; if that lock exists, commands such as world creation, startup answers, task creation, callback collection, meeting decisions, and ticket approval must block.
- Never update a live instance with destructive cleanup commands such as `git clean -fdx`, `rm -rf`, or a fresh copy over the workspace root.
- After updating the source, regenerate base examples if needed, run `wsa update preflight` again, then run `wsa doctor` and `wsa manager diagnose` before resuming Hermes.

WSA refuses to operate on workspace databases with a schema version newer than this build supports. If `wsa doctor` reports an unsupported schema, stop and use a compatible WSA version or an explicit migration path.

## Public Repo Safety

This repository intentionally ignores local workspaces, SQLite databases, runtime queues, callback files, logs, environment files, secrets, session handoff notes, root-local `local_admin/`, and live operation policy JSON files. Public example policy and command-registry files stay tracked.

Keep real runtime credentials outside the repository. Use environment variables or external secret files managed by your deployment/runtime layer. Treat local workspace contents as potentially sensitive: reports, runtime payloads, and SQLite rows may contain user or world-state data even when the template repository itself is public-safe.
