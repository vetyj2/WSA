# World Scene Actors

World Scene Actors, 줄여서 WSA는 소설/세계관 작업을 위한 로컬 우선 하네스 템플릿입니다. 워크스페이스, 월드 데이터, 리포트, 티켓, Hermes task/callback 계약, proposal-only 오케스트레이션을 다룹니다.

WSA는 공개 저장소로 공유할 수 있는 템플릿을 목표로 합니다. 실사용자의 API 키, OAuth 토큰, SSH 키, Telegram/Docker 상태, 실제 배포 정책, 장기 실행 Hermes 런타임은 이 저장소 밖에 둡니다.

## 핵심 방향

- WSA는 Hermes를 실행하지 않습니다.
- WSA는 provider key, OAuth token, SSH key, remote URL을 저장하지 않습니다.
- WSA는 shell operation 승인이나 외부 delivery channel 관리를 맡지 않습니다.
- WSA는 task packet, callback validation, report, ticket, update preflight, proposal-only workflow를 맡습니다.
- 실제 subagent/session 호출은 사용자 Hermes runtime이 수행하고, WSA는 callback을 받아 검증하고 기록합니다.

## Current MVP

- Workspace 및 per-world SQLite scaffolding
- World, fact, scene, report, ticket, diagnostic 저장소
- Mock scene orchestration 및 mock actor runtime
- Startup / Easy Startup interview 계약
- Static meeting mode와 autonomous orchestrator scaffold
- Hermes task/callback 파일 계약
- Runtime bridge hook, actor_state, floor_state continuity 계약
- Review queue triage와 proposal/callback cleanup audit 계약
- Artifact architecture map과 source/export/uninstall 경계 계약
- Hermes shortcut command registry 예시
- Template readiness, doctor, update preflight

## Architecture Snapshot

| 영역 | 주요 모듈 | 역할 |
| --- | --- | --- |
| CLI / workspace | `cli.py`, `workspace.py`, `template.py` | 명령 라우팅, workspace layout, template readiness |
| Persistence | `repositories.py` | SQLite world data, reports, tickets, temporal graph |
| Diagnostics / update | `manager.py`, `update.py`, `hermes_doctor.py`, `artifact_map.py` | Doctor checks, update preflight, runtime checks, artifact boundary map |
| Hermes contract | `hermes_adapter.py`, `hermes_commands.py` | Task packets, callback collection, command registry |
| Orchestration | `autonomous_orchestrator.py`, `orchestrator_*`, `orchestrator_bridge.py` | Meetup/scene runs, hook packets, callback turns |
| Review workflow | `meeting.py`, `startup.py`, `reports.py`, `review_cleanup.py`, `tickets.py` | Proposal gathering, interviews, reports, review cleanup, approval tickets |

자세한 구조는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)를 보세요. 권장 사용 방향은 [docs/USAGE_GUIDE.md](docs/USAGE_GUIDE.md), WSA/Hermes 권한 경계는 [docs/RUNTIME_BOUNDARIES.md](docs/RUNTIME_BOUNDARIES.md)에 정리되어 있습니다.

## 설치

이 프로젝트는 PyPI에 배포되어 있지 않습니다. 로컬 Git clone에서 설치합니다.

```bash
git clone <repository-url>
cd <repository-directory>
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install .
```

개발 중에는 editable install을 권장합니다.

```bash
python3 -m pip install -e .
```

소스에서 바로 실행할 수도 있습니다.

```bash
PYTHONPATH=src python3 -m wsa --help
```

## 빠른 확인

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

현재 기대 결과:

```text
142 tests OK
```

새 workspace smoke:

```bash
export WSA_WORKSPACE=/tmp/wsa-smoke
PYTHONPATH=src python3 -m wsa init
PYTHONPATH=src python3 -m wsa world create DemoWorld
PYTHONPATH=src python3 -m wsa manager diagnose
```

템플릿 readiness:

```bash
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-template-check template check --write-missing
```

## Hermes 연결

WSA의 Hermes adapter는 CLI/file-contract 템플릿입니다. Task JSON을 만들고 callback JSON을 수집합니다. Docker를 시작하거나, Telegram bot을 실행하거나, API key를 저장하거나, provider API를 직접 호출하지 않습니다.

```bash
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-smoke hermes init-example
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-smoke hermes commands
PYTHONPATH=src python3 -m wsa --workspace /tmp/wsa-smoke hermes commands --validate-local-overlay
```

Callback은 기본적으로 `workspace/hermes/callbacks/` 아래 파일만 받습니다. 이 검증은 구조/route 기반이며 cryptographic authentication이나 OAuth authorization이 아닙니다. 해당 디렉터리는 신뢰된 로컬 Hermes runtime 또는 operator automation만 쓸 수 있게 유지하세요.

`orchestrator run --mode hermes-bridge`와 `scene start`는 실제 actor를 직접 호출하지 않습니다. 대신 WSA가 `actor_state`, `floor_state`, scheduler rationale, bounded prompt, expected callback route를 담은 hook packet을 만들고, Hermes 또는 다른 외부 agent runtime이 그 hook을 실행한 뒤 callback을 돌려줍니다. 이 bridge contract는 runner-agnostic하게 설계되어 있어 향후 Codex-style local CLI agent나 custom actor runtime도 같은 callback 규격을 사용할 수 있습니다.

사용자별 Hermes shortcut은 공식 명령어로 계속 흡수하지 않고 `workspace/hermes/adapter_config/hermes_commands.local.json` overlay로 둡니다. WSA는 `hermes commands --write-local-template`, `--validate-local-overlay`, `--merged`로 충돌 진단과 병합 미리보기를 제공하며, update preflight는 `/wsa_`/`/filltherest` 충돌이나 mutating command metadata 부족을 Hermes가 사용자에게 보고하도록 노출합니다.

밋업/씬 보고는 `wsa.reporting.artifact_contract.v1` 권장 규격을 따릅니다. 기본 원칙은 날짜별 session log를 source of truth로 두고, 필요할 때 `human_session_minutes`(회의록), `draft_output`(원고초안/결론), `round_orchestration_report`(라운드별 오케스트레이션 보고서)를 TXT/HTML로 export하는 것입니다. 자동 생성/전송 여부는 사용자 Hermes profile 또는 local overlay가 결정합니다.

`wsa report export <world_id> --run-id <run_id> --artifact-type human_session_minutes --format txt`로 preview할 수 있고, `--write`를 붙이면 world artifact zone 아래에 export와 `artifact_source_map.json` manifest를 씁니다.

`wsa artifact diagnose`는 workspace 안의 `artifact_source_map.json` manifest와 source-map 없이 남은 export 파일을 read-only로 점검합니다.

`wsa artifact uninstall-discover --scan-root <path>`는 명시한 외부 scan root 아래에서 WSA 인접 후보를 read-only로 찾고 source checkout, workspace, external artifact, backup preserve, runtime-owned overlay 등으로 분류합니다. `--exclude-root`는 외부백업처럼 보존할 경로를 traversal과 삭제 후보에서 제외합니다. `--write`는 discovery manifest만 저장하며 삭제하지 않습니다.

`wsa artifact uninstall-plan`은 uninstall 전에 보존 대상, archive 후보, source-map 검토가 필요한 항목을 dry-run으로 보여줍니다. `--write`는 계획 JSON만 저장하며 파일 삭제는 수행하지 않습니다.

향후 실제 uninstall apply 이후에는 Hermes doctor 또는 동등한 runtime diagnostics를 실행해 삭제된 WSA 경로를 가리키는 shortcut, local overlay, callback route, runtime-owned WSA memory가 남아 있는지 확인해야 합니다.

`wsa artifact maintenance-scan`은 report/log/callback/archive 볼륨을 read-only로 요약하고 cleanup 전 권장 조치를 제안합니다. `--write`는 scan JSON만 저장합니다.

하네스 사용 중 파생되는 산출물은 가능하면 workspace의 정해진 artifact/report/runtime 디렉터리 안에 둡니다. 런타임 정책상 외부 경로에 만들어야 하는 파일은 `artifact_source_map.json`으로 생성 원천, run/session, 경로, cleanup hint를 남겨 설치/마이그레이션/언인스톨 때 추적 가능하게 해야 합니다.

Workspace의 원본/파생/외부 artifact 경계는 `manager/artifact_map/artifact_architecture_map.json`에 저장할 수 있습니다. 이 맵은 `control.sqlite`, `worlds/{world_id}/world.sqlite`, startup profile, orchestrator run log, session log를 source-of-truth로 분리하고, report mailbox, world artifacts, scene/meeting folders, Hermes archive/outbox를 managed artifact zone으로 한정합니다. 기본 정책은 dry-run, archive-before-delete, unknown external artifact는 보고만 하는 것입니다.

```bash
PYTHONPATH=src python3 -m wsa artifact map
PYTHONPATH=src python3 -m wsa artifact map --write --format json
```

씬 생성 모드는 강제하지 않고 기록합니다. `--generation-mode auto`는 Hermes/profile/자연어 해석에 맡기고, 명시값은 `fact-audit-synthesis`, `writing-room-line-build`입니다. Run artifact에는 요청 모드, 해석된 모드, 해석 출처, confidence, 액터가 실제 수행한 일, 수행되지 않은 일을 남기며, callback/reject/rollback/fact-audit/co-writer 여부도 `actor_contribution_summary`로 기록합니다.

`fact-audit-synthesis`는 `source_refs`, `fact_lookup_queries`, `checked_tables`, `checked_reports`, `conflicts_found`, `deferred_claims` 같은 evidence가 있을 때만 깊은 fact-audit으로 해석합니다. `writing-room-line-build`는 `line_build_ledger`에 후보 문장/beat, PASS/FAIL/HOLD/RETRY, rollback reason, adopted marker가 남아야 공동 작성으로 보고합니다.

Hook packet은 workflow와 scene mode에 맞는 `mode_aware_turn_contract`를 포함합니다. Meetup은 얕은 동의 대신 제약/반박/의존성을 요구하고, fact-audit scene turn은 근거와 보류 claim을 요구하며, line-build scene turn은 1-3개 후보 문장/beat와 검증 결정을 요구합니다.

승인대기 proposal과 callback residue는 `report` 하위 lifecycle로 정리합니다. `report triage`는 읽기 전용으로 pending report, reviewable orchestrator run, callback residue를 요약합니다. `report reject-pending`은 명시적 author intent가 있을 때 `inbox`/`pending_review` report와 `awaiting_author_review` run만 rejected로 전환하고 감사 JSON을 `reports/archived/`에 남깁니다. `--archive-callbacks`를 붙이면 callback JSON은 삭제하지 않고 `hermes/callback_archive/`로 이동합니다. 승인된 report, canon fact, ticket, DB schema는 건드리지 않습니다.

```bash
PYTHONPATH=src python3 -m wsa report triage <world_id>
PYTHONPATH=src python3 -m wsa report reject-pending <world_id> --reason "author rejected pending proposals" --archive-callbacks
PYTHONPATH=src python3 -m wsa report archive-callbacks <world_id> --reason "completed callback residue"
```

## 공개 저장소 안전 원칙

이 저장소는 local workspace, SQLite DB, runtime queue, callback file, log, environment file, secret, session handoff note, root-local `local_admin/`, live operation policy JSON을 ignore합니다.

커밋하면 안 되는 항목:

- `.env*`
- `SESSION_HANDOFF.md`
- `local_admin/`
- 실제 operation policy JSON
- SQLite DB와 live workspace data
- Hermes callback/task queue/runtime session/local adapter config

Public example 파일에는 schema, 환경변수 이름, disabled policy shape만 담고 실제 secret value는 담지 않습니다.

## 문서

- [권장 사용 방향](docs/USAGE_GUIDE.md)
- [아키텍처 맵](docs/ARCHITECTURE.md)
- [Runtime 권한 경계](docs/RUNTIME_BOUNDARIES.md)
- [English documentation](docs/en/README.md)
