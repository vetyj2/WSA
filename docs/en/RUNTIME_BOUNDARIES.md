# Runtime Boundaries

This document defines the trust boundary between the public WSA template and a user's private Hermes runtime.

## What WSA Owns

- Workspace layout and schema checks
- SQLite-backed world data, reports, tickets, diagnostics, and runtime messages
- Hermes task packet and callback file contracts
- Callback shape, route, operation-request, and quality-gate checks
- Proposal-only meetup, scene-prep, startup, and review workflows
- Update preflight and backup safety checks

## What Hermes Or The Operator Owns

- Provider credentials and model configuration
- OAuth tokens, API keys, SSH keys, remote URLs, and delivery channels
- Docker, Telegram, cron, daemon, or other long-running process management
- Actual subagent/session invocation
- Shell command mappings for operation requests
- User confirmation and deployment-specific approval policy

## Callback Trust Model

WSA accepts callback JSON only from the configured local workspace path by default:

```text
workspace/hermes/callbacks/
```

The validation is structural and route-based. It checks schema, task ID, workspace ID, world route, status, operation request mode, and payload shape. It is not cryptographic authentication, OAuth authorization, or proof that the callback came from a specific process.

Keep `hermes/callbacks/` writable only by the trusted local Hermes runtime or operator automation. Do not expose that directory as an untrusted upload target. Use `--allow-external-callback` only for trusted local imports.

## Operation Requests

WSA can declare an operation request such as `version_control.snapshot`. The public template does not decide whether that means no action, local commit, remote push, or a custom command.

The Hermes runtime or local operator policy must map the request to a concrete action and obtain any required user approval. Real operation policy JSON, private remotes, SSH key paths, tokens, and custom command mappings should stay outside the repository.

## Public Repo Rules

Do not commit:

- `.env*`
- `SESSION_HANDOFF.md`
- `local_admin/`
- Real operation policy JSON
- SQLite databases
- Live workspace data
- Hermes task queues, callbacks, reports outbox, runtime sessions, or adapter-local config

Public-safe examples may include environment variable names and disabled policy shapes, but not the corresponding secret values.
