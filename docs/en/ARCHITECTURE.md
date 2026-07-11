# WSA Architecture

World Scene Actors is a public-safe local harness template. It keeps reusable workflow contracts, local workspace structure, diagnostics, reports, tickets, and proposal-only orchestration in the repository. Provider credentials, shell-operation approval, delivery channels, and long-running Hermes process management belong outside this repo. WSA may run one user-supplied and confirmed provider-neutral stdio command, but it does not select the provider or credentials.

## Read Order

Start with `README.md` for setup and workflow examples. Then read this file for the code map. Read `RUNTIME_BOUNDARIES.md` before wiring a live Hermes runtime.

## Repository Map

```text
World-Scene-Actors/
├── src/wsa/
│   ├── cli.py                     # Public CLI facade
│   ├── cli_parser.py / cli_parser_* # argparse root and domain parser groups
│   ├── cli_dispatch.py / cli_dispatch_* # Root and domain command routing
│   ├── cli_core.py                # Workspace/startup/manager handlers
│   ├── cli_orchestration.py       # Scene/meeting/orchestrator handlers
│   ├── cli_runtime.py             # Hermes/report/update handlers
│   ├── cli_runtime_loop.py        # Confirmed stdio dispatch/ingest handler
│   ├── workspace.py               # Workspace creation, schema checks, paths
│   ├── application/               # Home/review/draft/deep/revision/runtime-loop services
│   ├── context.py                 # Visibility/time/budget ContextBundle assembly
│   ├── runtime_adapter.py         # Shell-free external stdio protocol
│   ├── run_store.py               # Revisioned SQLite workflow source of truth
│   ├── workflow_engine.py         # Common run states and runner contracts
│   ├── migration.py / migrations/ # Explicit control/world migrations
│   ├── restore.py                 # Backup restore-to-new-path drill
│   ├── diagnostics_policy.py      # World-local edge and interval policy
│   ├── contract_registry.py       # Compact projection refs and expansion
│   ├── command_specs.py           # Shared CLI/Hermes entrypoint metadata
│   ├── template.py                # Template readiness and public-safe defaults
│   ├── update.py                  # Update preflight, backup, merge safety
│   ├── artifact_map.py            # Source/artifact/uninstall boundary map
│   ├── artifacts/                 # Architecture/routing/lifecycle operation facade
│   ├── repositories.py            # Repository public compatibility facade
│   ├── control_repository.py      # Runtime session/message control aggregate
│   ├── world_repository_*         # World core, temporal graph, workflow aggregates
│   ├── repository_*               # Shared codecs and immutable records
│   ├── manager.py                 # World diagnostics and doctor-style checks
│   ├── autonomous_orchestrator.py # Meetup/scene orchestration lifecycle
│   ├── orchestrator_bridge.py     # Hermes callback and turn bridge
│   ├── orchestrator_*             # Contracts, turns, workflow definitions
│   ├── hermes_adapter.py          # Hermes task/callback file contract
│   ├── hermes_commands.py         # Hermes registry public facade/projection
│   ├── hermes_command_*           # Command catalog, builder, local overlay validation
│   ├── hermes_doctor.py           # Hermes adapter/runtime diagnostics
│   ├── meeting.py                 # Static proposal-only meetup path
│   ├── startup.py                 # Startup and Easy Startup interview contracts
│   ├── actors.py / runtime.py     # Actor and runtime abstractions
│   ├── cli_tickets.py             # Guided review, split/merge, and apply CLI
│   ├── ticket_store.py / ticket_* # Validation, apply, and deep persistence
│   └── ticket_revision_store.py   # Atomic amend/split/merge lineage storage
├── tests/                         # Unit tests for CLI, storage, Hermes contracts
├── examples/                      # Public-safe Hermes JSON and CLI examples
├── change_log/                    # Versioned HTML review dashboards
├── README.md
├── pyproject.toml
└── .gitignore
```

## Main Layers

| Layer | Modules | Notes |
| --- | --- | --- |
| Command surface | `cli.py`, `cli_parser.py`, `cli_dispatch.py`, `cli_*` | Separates the public facade, parser contract, dispatch, and domain handlers. |
| Workspace and template | `workspace.py`, `template.py` | Creates local workspace directories, checks schema support, and verifies template readiness. |
| Application and context | `application/`, `context.py` | Owns read/preview services and actor-viewpoint context assembly. |
| Persistence | `repositories.py`, `control_repository.py`, `world_repository_*`, `run_store.py`, `migration.py` | Separates control/world/graph/workflow aggregates and run state behind a compatibility facade. |
| Diagnostics and updates | `manager.py`, `update.py`, `hermes_doctor.py`, `artifacts/` | Keeps health checks, safe updates, and artifact architecture/routing/lifecycle operations separate from generation workflows. |
| Hermes contract | `hermes_adapter.py`, `hermes_commands.py`, `hermes_command_*` | Separates task/callback contracts from registry projection, catalogs, and local overlay validation. |
| Orchestration | `autonomous_orchestrator.py`, `orchestrator_bridge.py`, `orchestrator_*` | Records run state, actor_state, floor_state, hook packets, compressed continuity, quality gates, and approval packages. |
| Proposal workflows | `meeting.py`, `startup.py` | Creates non-canon meeting/interview material that later flows through reports or tickets. |

Concrete tickets are preview-first. `ticket_selection_service.py` chooses only one eligible ticket for guided next/review/apply, while `ticket_revision_service.py` and `ticket_revision_store.py` retain amend/split/merge sources and lineage. Deep actor lifecycle updates verify an optimistic revision snapshot before applying inside the same ticket transaction.

## Runtime Shape

The live flow is intentionally split:

```text
WSA creates bounded task or hook packet
the user confirms an external stdio command, or another runtime consumes the hook
the external runtime returns callback JSON
WSA validates route/shape and updates local reports, tickets, or run state
Author or local policy decides whether anything becomes canon
```

WSA does not call a provider SDK or subagent API itself. Mock and static paths are deterministic local simulations. Bridge mode lets a user's Hermes runtime or explicit stdio adapter provide real callbacks. `dispatch-plan` is read-only; only `dispatch --confirm` starts one process with `shell=False`, a minimal environment allowlist, and bounded I/O.

## Runtime Bridge State

Bridge mode is a runner-agnostic contract, not Hermes process control. Hermes is the first intended runtime, but the same hook/callback shape can later be consumed by Codex-style local CLI agents or other external actor runtimes.

Durable orchestrator state lives in control DB `workflow_runs`. `run.json` is a compact projection with digest references, while DB revisions and compare-and-swap reject stale updates. Each run separates:

- `floor_state`: shared meeting or scene-prep state, recent turns, verification queue, gaps, scheduler state
- `actor_states`: per-actor mandate, scope boundaries, prior position, claims, objections, unanswered questions, stance changes, confidence history
- `runtime_hook_packets`: bounded prompts and terminal argv shapes for the external runtime
- `submitted_callbacks`: callback provenance and quality-gate results
- `execution_provenance`: whether the artifact is local-simulated, pending bridge work, or completed from external callbacks

Rounds are reporting checkpoints. Runtime cost should be understood as actor turns or callback budget. The scheduler does not promise equal airtime; it prioritizes verification need, blocking objections, domain ownership, candidate falsification value, and unanswered questions.

## Public Files Versus Runtime Files

Tracked examples under `examples/` contain schemas, environment variable names, and policy shapes. They must not contain real tokens, private key paths, private remote URLs, or deployment-specific command mappings.

Runtime state belongs in ignored workspace paths such as `workspace/`, `worlds/`, `reports/`, `manager/runtime_sessions/`, `hermes/callbacks/`, `hermes/task_queue/`, `hermes/adapter_config/hermes_commands.local.json`, and local operation policy JSON.

`manager/artifact_map/artifact_architecture_map.json` is the compact directory-base map for this boundary. It separates source-of-truth zones from managed artifacts and says that external artifacts require `artifact_source_map.json` provenance before any uninstall or maintenance plan treats them as cleanup candidates. `artifact_routing.py` provides the read-only pre-write recommendation used by Hermes/runtime to classify WSA-related outputs and keep custom artifacts inside managed world/session paths whenever possible.

## Known Structural Debt

Version 0.3.1 splits CLI routing, ticket persistence, the Hermes command registry, and repositories into smaller facades and subordinate modules. `autonomous_orchestrator.py`, `startup.py`, `orchestrator_bridge.py`, `workspace.py`, and `hermes_adapter.py` still exceed the advised 800-line ceiling or combine multiple responsibilities. Later decomposition must first freeze public JSON/schema and persistence compatibility, then separate workflow lifecycle, Startup state/compiler, schema bootstrap, and callback validation. This is maintainability debt, not a claim that the runtime behavior is absent.
