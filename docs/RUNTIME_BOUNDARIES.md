# Runtime 권한 경계

이 문서는 공개 WSA 템플릿과 사용자 private Hermes runtime 사이의 신뢰 경계를 정리합니다.

## WSA가 맡는 것

- Workspace layout과 schema checks
- SQLite-backed world data, reports, tickets, diagnostics, runtime messages
- Hermes task packet과 callback file contract
- Callback shape, route, operation-request, quality-gate checks
- Proposal-only meetup, scene-prep, startup, review workflows
- Update preflight와 backup safety checks
- Runtime bridge hook 생성, actor_state/floor_state 유지, callback quality gate 기록

## Hermes 또는 operator가 맡는 것

- Provider credentials와 model configuration
- OAuth token, API key, SSH key, remote URL, delivery channel
- Docker, Telegram, cron, daemon 등 long-running process management
- 실제 subagent/session invocation
- Actor/session process lifecycle, interrupt, cleanup 실행
- Operation request에 대한 shell command mapping
- User confirmation과 deployment-specific approval policy

## Callback Trust Model

WSA는 기본적으로 configured local workspace path 아래의 callback JSON만 받습니다.

```text
workspace/hermes/callbacks/
```

이 validation은 structural and route-based입니다. Schema, task ID, workspace ID, world route, status, operation request mode, payload shape를 확인합니다. 이것은 cryptographic authentication, OAuth authorization, 특정 process에서 왔다는 증명이 아닙니다.

`hermes/callbacks/`는 신뢰된 local Hermes runtime 또는 operator automation만 쓸 수 있게 유지하세요. 이 디렉터리를 untrusted upload target으로 노출하지 마세요. `--allow-external-callback`은 trusted local import에만 사용하세요.

## Runtime Bridge Boundary

`hermes-bridge`는 이름에 Hermes가 들어가지만 실행 정책은 runner-agnostic합니다. WSA가 하는 일은 다음 hook과 callback 계약을 만드는 것입니다. 실제 actor/subagent 호출, model/provider 선택, Docker/Telegram/Codex/local runner process 관리, interrupt, cleanup 실행은 외부 runtime이 맡습니다.

WSA는 callback이 들어오면 route, turn ID, expected fields, canon mutation attempt, low-value/repetition warning을 검증하고 `actor_state`와 `floor_state`를 갱신합니다. 하지만 이 callback이 어떤 process에서 생성되었는지 cryptographic하게 증명하지는 않습니다. 따라서 cleanup status나 real actor session metadata는 external runtime이 보고한 provenance로만 취급합니다.

## Operation Requests

WSA는 `version_control.snapshot` 같은 operation request를 선언할 수 있습니다. Public template은 그것이 no action, local commit, remote push, custom command 중 무엇인지 결정하지 않습니다.

Hermes runtime 또는 local operator policy가 concrete action으로 mapping하고 필요한 user approval을 받아야 합니다. 실제 operation policy JSON, private remote, SSH key path, token, custom command mapping은 repository 밖에 둡니다.

## Public Repo Rules

커밋하지 마세요.

- `.env*`
- `SESSION_HANDOFF.md`
- `local_admin/`
- 실제 operation policy JSON
- SQLite databases
- Live workspace data
- Hermes task queues, callbacks, reports outbox, runtime sessions, adapter-local config

Public-safe example은 환경변수 이름과 disabled policy shape를 포함할 수 있지만, secret value는 포함하지 않습니다.
