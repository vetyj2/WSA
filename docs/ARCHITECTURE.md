# WSA 아키텍처

World Scene Actors는 공개 가능한 로컬 하네스 템플릿입니다. 저장소에는 재사용 가능한 workflow contract, workspace 구조, diagnostics, reports, tickets, proposal-only orchestration만 둡니다. 실제 agent 실행, provider credential, shell operation 승인, delivery channel, 장기 실행 Hermes process 관리는 저장소 밖의 사용자 Hermes runtime 책임입니다.

## 읽는 순서

처음에는 `README.md`로 설치와 smoke run을 확인하세요. 그 다음 이 문서로 코드 구조를 보고, 실제 Hermes runtime을 붙이기 전에는 `docs/RUNTIME_BOUNDARIES.md`를 읽는 것을 권장합니다.

## Repository Map

```text
World-Scene-Actors/
├── src/wsa/
│   ├── cli.py                     # CLI entrypoint와 command routing
│   ├── workspace.py               # Workspace 생성, schema check, path
│   ├── template.py                # Template readiness와 public-safe default
│   ├── update.py                  # Update preflight, backup, merge safety
│   ├── repositories.py            # SQLite store, temporal graph 포함
│   ├── manager.py                 # World diagnostics와 doctor-style checks
│   ├── autonomous_orchestrator.py # Meetup/scene orchestration scaffold
│   ├── orchestrator_bridge.py     # Hermes callback과 turn bridge
│   ├── orchestrator_*             # Contract, turn, workflow 정의
│   ├── hermes_adapter.py          # Hermes task/callback file contract
│   ├── hermes_commands.py         # Hermes shortcut과 skill registry
│   ├── hermes_doctor.py           # Hermes adapter/runtime diagnostics
│   ├── meeting.py                 # Static proposal-only meetup path
│   ├── startup.py                 # Startup / Easy Startup interview contract
│   ├── actors.py / runtime.py     # Actor와 runtime abstraction
│   ├── reports.py / review_cleanup.py
│   │                              # Review artifact, queue triage, cleanup audit
│   └── tickets.py                 # Approval ticket
├── tests/                         # CLI, storage, Hermes contract tests
├── examples/                      # Public-safe Hermes JSON / CLI examples
├── change_log/                    # Versioned HTML review dashboards
├── docs/                          # 한국어 기본 문서
├── docs/en/                       # English documentation
├── README.md
├── pyproject.toml
└── .gitignore
```

## Main Layers

| Layer | Modules | Notes |
| --- | --- | --- |
| Command surface | `cli.py` | User/Hermes-facing command를 parsing하고 좁은 모듈로 위임합니다. |
| Workspace / template | `workspace.py`, `template.py` | Workspace directory, schema support, template readiness를 확인합니다. |
| Persistence | `repositories.py`, `reports.py`, `review_cleanup.py`, `tickets.py` | SQLite world state, report, review cleanup audit, ticket, fact, scene, diagnostic, graph data를 관리합니다. |
| Diagnostics / update | `manager.py`, `update.py`, `hermes_doctor.py` | Health check와 safe update logic을 generation workflow와 분리합니다. |
| Hermes contract | `hermes_adapter.py`, `hermes_commands.py` | Task packet 생성, callback shape/route validation, public registry example을 담당합니다. |
| Orchestration | `autonomous_orchestrator.py`, `orchestrator_bridge.py`, `orchestrator_*` | Run state, actor_state, floor_state, hook packet, compressed continuity, quality gate, approval package를 기록합니다. |
| Proposal workflows | `meeting.py`, `startup.py` | Canon이 아닌 meeting/interview material을 만들고 report/ticket flow로 넘깁니다. |

`review_cleanup.py`는 live 사용 중 쌓인 pending proposal report, author-review orchestrator run, Hermes callback residue를 안전하게 정리하는 lifecycle을 담당합니다. 승인된 report, canon fact, ticket, startup profile, DB schema는 cleanup 대상에서 제외하고, 변경은 `reports/archived/review-cleanup-*.json` audit artifact로 남깁니다.

## Runtime Shape

Live flow는 의도적으로 분리되어 있습니다.

```text
WSA creates bounded task or hook packet
Hermes runtime executes real agent/subagent work
Hermes writes callback JSON under hermes/callbacks
WSA validates route/shape and updates local reports, tickets, or run state
Author or local policy decides whether anything becomes canon
```

WSA는 subagent call을 직접 실행하지 않습니다. 현재 public template의 mock/static path는 deterministic local simulation입니다. Bridge mode는 사용자 Hermes runtime이 real callback을 제공하기 위한 계약입니다.

## Runtime Bridge State

Bridge mode는 Hermes 전용 프로세스 제어가 아니라 runner-agnostic contract입니다. Hermes가 첫 runtime이지만, 같은 hook/callback shape는 Codex-style local CLI agent나 다른 external actor runtime도 사용할 수 있게 유지합니다.

각 orchestrator run은 다음 상태를 분리해서 기록합니다.

- `floor_state`: 회의장 전체 상태, 최근 turn, verification queue, gap, scheduler state
- `actor_states`: actor별 mandate, scope boundary, prior position, claims, objections, unanswered questions, stance changes, confidence history
- `runtime_hook_packets`: 외부 runtime이 실행할 bounded prompt와 terminal argv shape
- `submitted_callbacks`: 외부 runtime이 제출한 callback provenance와 quality-gate 결과
- `execution_provenance`: local simulation, pending bridge, completed-by-callback 같은 artifact 출처

Round는 사용자/Hermes에게 보고하기 좋은 checkpoint이고, 실제 orchestration cost는 actor turn/callback budget으로 봅니다. Scheduler는 equal airtime을 보장하지 않고 verification need, blocking objection, domain ownership, falsification value, unanswered question을 기준으로 다음 actor hook을 선택합니다.

## Public Files Versus Runtime Files

`examples/` 아래 tracked example은 schema, 환경변수 이름, policy shape만 담습니다. 실제 token, private key path, private remote URL, deployment-specific command mapping은 넣지 않습니다.

Runtime state는 ignored path에 둡니다. 예: `workspace/`, `worlds/`, `reports/`, `manager/runtime_sessions/`, `hermes/callbacks/`, `hermes/task_queue/`, `hermes/adapter_config/hermes_commands.local.json`, live operation policy JSON.
