# WSA 아키텍처

World Scene Actors는 공개 가능한 로컬 하네스 템플릿입니다. 저장소에는 재사용 가능한 workflow contract, workspace 구조, diagnostics, reports, tickets, proposal-only orchestration을 둡니다. Provider credential, shell operation 승인, delivery channel, 장기 실행 Hermes process 관리는 저장소 밖의 사용자 runtime 책임입니다. WSA는 사용자가 명시·확인한 provider-neutral stdio command 한 개를 실행할 수 있지만 provider나 credential을 선택하지 않습니다.

## 읽는 순서

처음에는 `README.md`로 설치와 smoke run을 확인하세요. 그 다음 이 문서로 코드 구조를 보고, 실제 Hermes runtime을 붙이기 전에는 `docs/RUNTIME_BOUNDARIES.md`를 읽는 것을 권장합니다.

## Repository Map

```text
World-Scene-Actors/
├── src/wsa/
│   ├── cli.py                     # Public CLI facade
│   ├── cli_parser.py / cli_parser_* # argparse root와 domain parser groups
│   ├── cli_dispatch.py / cli_dispatch_* # Root와 domain command routing
│   ├── cli_core.py                # Workspace/startup/manager handlers
│   ├── cli_orchestration.py       # Scene/meeting/orchestrator handlers
│   ├── cli_runtime.py             # Hermes/report/update handlers
│   ├── cli_runtime_loop.py        # Confirmed stdio dispatch/ingest handler
│   ├── workspace.py               # Workspace 생성, schema check, path
│   ├── application/               # Home/review/draft/deep/revision/runtime-loop service
│   ├── context.py                 # Visibility/time/budget 기반 ContextBundle
│   ├── runtime_adapter.py         # Shell-free external stdio protocol
│   ├── run_store.py               # Revisioned SQLite workflow source of truth
│   ├── workflow_engine.py         # 공통 run state와 mock/callback runner 계약
│   ├── migration.py / migrations/ # Explicit control/world migration
│   ├── restore.py                 # Backup restore-to-new-path drill
│   ├── diagnostics_policy.py      # World-local edge/interval policy
│   ├── contract_registry.py       # Compact projection contract ref/expansion
│   ├── command_specs.py           # CLI/Hermes visible entrypoint metadata
│   ├── template.py                # Template readiness와 public-safe default
│   ├── update.py                  # Update preflight, backup, merge safety
│   ├── artifact_map.py            # Source/artifact/uninstall boundary map
│   ├── artifacts/                 # Architecture/routing/lifecycle operation facade
│   ├── repositories.py            # Repository public compatibility facade
│   ├── control_repository.py      # Runtime session/message control aggregate
│   ├── world_repository_*         # World core, temporal graph, workflow aggregates
│   ├── repository_*               # Shared codec와 immutable records
│   ├── manager.py                 # World diagnostics와 doctor-style checks
│   ├── autonomous_orchestrator.py # Meetup/scene orchestration lifecycle
│   ├── orchestrator_bridge.py     # Hermes callback과 turn bridge
│   ├── orchestrator_*             # Contract, turn, workflow 정의
│   ├── hermes_adapter.py          # Hermes task/callback file contract
│   ├── hermes_commands.py         # Hermes registry public facade/projection
│   ├── hermes_command_*           # Command catalog, builder, local overlay validation
│   ├── hermes_doctor.py           # Hermes adapter/runtime diagnostics
│   ├── meeting.py                 # Static proposal-only meetup path
│   ├── startup.py                 # Startup / Easy Startup interview contract
│   ├── actors.py / runtime.py     # Actor와 runtime abstraction
│   ├── reports.py / review_cleanup.py
│   │                              # Review artifact, queue triage, cleanup audit
│   ├── cli_tickets.py             # Guided review, split/merge, apply CLI
│   ├── ticket_store.py / ticket_* # Ticket validation, apply, deep persistence
│   └── ticket_revision_store.py   # Atomic amend/split/merge lineage storage
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
| Command surface | `cli.py`, `cli_parser.py`, `cli_dispatch.py`, `cli_*` | Public facade, parser contract, dispatch, domain handler를 분리합니다. |
| Workspace / template | `workspace.py`, `template.py` | Workspace directory, schema support, template readiness를 확인합니다. |
| Application / context | `application/`, `context.py` | Read/preview service와 actor viewpoint별 context 조립을 담당합니다. |
| Persistence | `repositories.py`, `control_repository.py`, `world_repository_*`, `run_store.py`, `migration.py` | Compatibility facade 뒤에서 control/world/graph/workflow aggregate와 run state를 분리합니다. |
| Diagnostics / update | `manager.py`, `update.py`, `hermes_doctor.py`, `artifacts/` | Health check, safe update, artifact architecture/routing/lifecycle을 generation workflow와 분리합니다. |
| Hermes contract | `hermes_adapter.py`, `hermes_commands.py`, `hermes_command_*` | Task/callback 계약과 registry projection, catalog, local overlay validation을 분리합니다. |
| Orchestration | `autonomous_orchestrator.py`, `orchestrator_bridge.py`, `orchestrator_*` | Run state, actor_state, floor_state, hook packet, compressed continuity, quality gate, approval package를 기록합니다. |
| Proposal workflows | `meeting.py`, `startup.py` | Canon이 아닌 meeting/interview material을 만들고 report/ticket flow로 넘깁니다. |

Concrete ticket은 preview가 기본입니다. `ticket_selection_service.py`는 단일 적격 ticket만 guided next/review/apply 대상으로 선택하고, `ticket_revision_service.py`와 `ticket_revision_store.py`는 amend/split/merge 원본과 lineage를 보존합니다. Deep actor lifecycle update는 optimistic revision snapshot을 검증한 뒤 같은 ticket application transaction에서 적용됩니다.

`review_cleanup.py`는 live 사용 중 쌓인 pending proposal report, author-review orchestrator run, Hermes callback residue를 안전하게 정리하는 lifecycle을 담당합니다. 승인된 report, canon fact, ticket, startup profile, DB schema는 cleanup 대상에서 제외하고, 변경은 `reports/archived/review-cleanup-*.json` audit artifact로 남깁니다.

`artifact_map.py`는 `manager/artifact_map/artifact_architecture_map.json`에 저장되는 작은 directory-base map을 정의합니다. 이 맵은 source-of-truth zone과 managed artifact zone을 분리하고, 외부 artifact는 `artifact_source_map.json` 없이는 자동 삭제하지 않는 경계 정책을 담습니다. `artifact_routing.py`는 Hermes/runtime이 파일을 만들기 전에 artifact type, world/session/run, filename을 기준으로 권장 내부 경로와 관리주체를 read-only로 계산합니다. 이후 export, uninstall, maintenance 기능은 이 맵을 기준으로 dry-run plan을 만들 수 있어야 합니다.

## Runtime Shape

Live flow는 의도적으로 분리되어 있습니다.

```text
WSA creates bounded task or hook packet
user confirms an external stdio command, or another runtime consumes the hook
external runtime returns callback JSON
WSA validates route/shape and updates local reports, tickets, or run state
Author or local policy decides whether anything becomes canon
```

WSA는 provider SDK나 subagent API를 직접 호출하지 않습니다. Public template의 mock/static path는 deterministic local simulation입니다. Bridge mode는 사용자 Hermes runtime 또는 명시적 stdio adapter가 real callback을 제공하기 위한 계약입니다. `dispatch-plan`은 읽기 전용이고 `dispatch --confirm`만 `shell=False`, 최소 환경 allowlist와 bounded I/O로 프로세스 한 개를 시작합니다.

## Runtime Bridge State

Bridge mode는 Hermes 전용 프로세스 제어가 아니라 runner-agnostic contract입니다. Hermes가 첫 runtime이지만, 같은 hook/callback shape는 Codex-style local CLI agent나 다른 external actor runtime도 사용할 수 있게 유지합니다.

각 orchestrator run의 durable source는 control DB의 `workflow_runs`입니다. `run.json`은 반복 계약을 digest reference로 줄인 projection이며 DB revision과 compare-and-swap으로 stale update를 차단합니다. 각 run은 다음 상태를 분리해서 기록합니다.

- `floor_state`: 회의장 전체 상태, 최근 turn, verification queue, gap, scheduler state
- `actor_states`: actor별 mandate, scope boundary, prior position, claims, objections, unanswered questions, stance changes, confidence history
- `runtime_hook_packets`: 외부 runtime이 실행할 bounded prompt와 terminal argv shape
- `submitted_callbacks`: 외부 runtime이 제출한 callback provenance와 quality-gate 결과
- `execution_provenance`: local simulation, pending bridge, completed-by-callback 같은 artifact 출처

Round는 사용자/Hermes에게 보고하기 좋은 checkpoint이고, 실제 orchestration cost는 actor turn/callback budget으로 봅니다. Scheduler는 equal airtime을 보장하지 않고 verification need, blocking objection, domain ownership, falsification value, unanswered question을 기준으로 다음 actor hook을 선택합니다.

## Public Files Versus Runtime Files

`examples/` 아래 tracked example은 schema, 환경변수 이름, policy shape만 담습니다. 실제 token, private key path, private remote URL, deployment-specific command mapping은 넣지 않습니다.

Runtime state는 ignored path에 둡니다. 예: `workspace/`, `worlds/`, `reports/`, `manager/runtime_sessions/`, `hermes/callbacks/`, `hermes/task_queue/`, `hermes/adapter_config/hermes_commands.local.json`, live operation policy JSON.

## Known Structural Debt

0.3.1은 CLI routing, ticket persistence, Hermes command registry와 repository를 작은 facade와 하위 모듈로 분리했습니다. 다만 `autonomous_orchestrator.py`, `startup.py`, `orchestrator_bridge.py`, `workspace.py`, `hermes_adapter.py`는 아직 권장 800줄 상한을 넘거나 여러 책임을 함께 가집니다. 후속 분리는 public JSON/schema와 저장 호환성을 먼저 고정한 뒤 workflow lifecycle, Startup state/compiler, schema bootstrap, callback validation을 각각 떼어내야 합니다. 이는 유지보수 부채이며 해당 runtime 기능이 없다는 뜻은 아닙니다.
