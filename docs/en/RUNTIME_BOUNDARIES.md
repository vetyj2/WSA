# Runtime Boundaries

This document defines the trust boundary between the public WSA template and a user's private Hermes runtime.

## What WSA Owns

- Workspace layout and schema checks
- SQLite-backed world data, reports, tickets, diagnostics, and runtime messages
- Hermes task packet and callback file contracts
- Callback shape, route, operation-request, and quality-gate checks
- Proposal-only meetup, scene-prep, startup, and review workflows
- Update preflight and backup safety checks
- Runtime bridge hook creation, actor_state/floor_state continuity, and callback quality-gate records
- Bounded execution of one user-supplied and confirmed provider-neutral stdio command

## What Hermes Or The Operator Owns

- Provider credentials and model configuration
- OAuth tokens, API keys, SSH keys, remote URLs, and delivery channels
- Docker, Telegram, cron, daemon, or other long-running process management
- Actual subagent/session invocation
- Provider/session lifecycle, long-running processes, interrupt execution, and cleanup
- Shell command mappings for operation requests
- User confirmation and deployment-specific approval policy

## Callback Trust Model

WSA accepts callback JSON only from the configured local workspace path by default:

```text
workspace/hermes/callbacks/
```

The validation is structural and route-based. It checks schema, task ID, workspace ID, world route, status, operation request mode, and payload shape. It is not cryptographic authentication, OAuth authorization, or proof that the callback came from a specific process.

Keep `hermes/callbacks/` writable only by the trusted local Hermes runtime or operator automation. Do not expose that directory as an untrusted upload target. Use `--allow-external-callback` only for trusted local imports.

## Runtime Bridge Boundary

`hermes-bridge` includes Hermes in the mode name, but the execution policy is runner-agnostic. WSA creates the next hook and callback contract. The external runtime owns actor/subagent invocation, model/provider selection, Docker/Telegram/Codex/local-runner process management, interrupts, and cleanup execution.

When a callback arrives, WSA validates route, turn ID, expected fields, canon mutation attempts, and low-value or repetition warnings. It then updates `actor_state` and `floor_state`. WSA does not cryptographically prove which process produced the callback. Cleanup status and real actor-session metadata are therefore treated as external-runtime provenance.

## Stdio Adapter Boundary

`orchestrator dispatch-plan` starts no process. It shows redacted argv, workdir, timeout, route digest, and required capabilities. `orchestrator dispatch --confirm` runs the user-supplied argv once with `shell=False`, sends the hook on stdin, and submits the stdout callback to the bridge.

The adapter does not discover providers or request/store API keys and OAuth tokens. It inherits only a minimal environment allowlist and does not record raw stdout/stderr in its receipt. Provider credentials should remain in the external command's ignored local config or keychain boundary; do not put secrets in argv.

The dispatch receipt and route digest bind a callback to the current run, turn, and task, but they do not prove cryptographic process identity. Local callback-directory write permissions remain an operator responsibility.

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
