# WSA Architecture

World Scene Actors is a public-safe local harness template. It keeps reusable workflow contracts, local workspace structure, diagnostics, reports, tickets, and proposal-only orchestration in the repository. Live agent execution, provider credentials, shell operation approval, delivery channels, and long-running Hermes process management belong outside this repo.

## Read Order

Start with `README.md` for setup and workflow examples. Then read this file for the code map. Read `RUNTIME_BOUNDARIES.md` before wiring a live Hermes runtime.

## Repository Map

```text
World-Scene-Actors/
├── src/wsa/
│   ├── cli.py                     # CLI entrypoint and command routing
│   ├── workspace.py               # Workspace creation, schema checks, paths
│   ├── template.py                # Template readiness and public-safe defaults
│   ├── update.py                  # Update preflight, backup, merge safety
│   ├── repositories.py            # SQLite stores, including temporal graph data
│   ├── manager.py                 # World diagnostics and doctor-style checks
│   ├── autonomous_orchestrator.py # Meetup/scene orchestration scaffold
│   ├── orchestrator_bridge.py     # Hermes callback and turn bridge
│   ├── orchestrator_*             # Contracts, turns, workflow definitions
│   ├── hermes_adapter.py          # Hermes task/callback file contract
│   ├── hermes_commands.py         # Hermes shortcut and skill registry
│   ├── hermes_doctor.py           # Hermes adapter/runtime diagnostics
│   ├── meeting.py                 # Static proposal-only meetup path
│   ├── startup.py                 # Startup and Easy Startup interview contracts
│   ├── actors.py / runtime.py     # Actor and runtime abstractions
│   └── reports.py / tickets.py    # Review artifacts and approval tickets
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
| Command surface | `cli.py` | Parses user and Hermes-facing commands, then delegates to narrow modules. |
| Workspace and template | `workspace.py`, `template.py` | Creates local workspace directories, checks schema support, and verifies template readiness. |
| Persistence | `repositories.py`, `reports.py`, `tickets.py` | Owns SQLite-backed world state, reports, tickets, facts, scenes, diagnostics, and graph data. |
| Diagnostics and updates | `manager.py`, `update.py`, `hermes_doctor.py` | Keeps health checks and safe-update logic separate from generation workflows. |
| Hermes contract | `hermes_adapter.py`, `hermes_commands.py` | Emits task packets, validates callback shape/routes, and publishes public command-registry examples. |
| Orchestration | `autonomous_orchestrator.py`, `orchestrator_bridge.py`, `orchestrator_*` | Records run state, hook packets, compressed continuity, quality gates, and approval packages. |
| Proposal workflows | `meeting.py`, `startup.py` | Creates non-canon meeting/interview material that later flows through reports or tickets. |

## Runtime Shape

The live flow is intentionally split:

```text
WSA creates bounded task or hook packet
Hermes runtime executes real agent/subagent work
Hermes writes callback JSON under hermes/callbacks
WSA validates route/shape and updates local reports, tickets, or run state
Author or local policy decides whether anything becomes canon
```

WSA does not execute the subagent call itself. In the current public template, mock and static paths are deterministic local simulations. Bridge mode is the contract for a user's Hermes runtime to provide real callbacks.

## Public Files Versus Runtime Files

Tracked examples under `examples/` contain schemas, environment variable names, and policy shapes. They must not contain real tokens, private key paths, private remote URLs, or deployment-specific command mappings.

Runtime state belongs in ignored workspace paths such as `workspace/`, `worlds/`, `reports/`, `manager/runtime_sessions/`, `hermes/callbacks/`, `hermes/task_queue/`, `hermes/adapter_config/hermes_commands.local.json`, and local operation policy JSON.
