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
- Hermes shortcut command registry 예시
- Template readiness, doctor, update preflight

## Architecture Snapshot

| 영역 | 주요 모듈 | 역할 |
| --- | --- | --- |
| CLI / workspace | `cli.py`, `workspace.py`, `template.py` | 명령 라우팅, workspace layout, template readiness |
| Persistence | `repositories.py` | SQLite world data, reports, tickets, temporal graph |
| Diagnostics / update | `manager.py`, `update.py`, `hermes_doctor.py` | Doctor checks, update preflight, runtime checks |
| Hermes contract | `hermes_adapter.py`, `hermes_commands.py` | Task packets, callback collection, command registry |
| Orchestration | `autonomous_orchestrator.py`, `orchestrator_*`, `orchestrator_bridge.py` | Meetup/scene runs, hook packets, callback turns |
| Review workflow | `meeting.py`, `startup.py`, `reports.py`, `tickets.py` | Proposal gathering, interviews, reports, approval tickets |

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
119 tests OK
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
```

Callback은 기본적으로 `workspace/hermes/callbacks/` 아래 파일만 받습니다. 이 검증은 구조/route 기반이며 cryptographic authentication이나 OAuth authorization이 아닙니다. 해당 디렉터리는 신뢰된 로컬 Hermes runtime 또는 operator automation만 쓸 수 있게 유지하세요.

`orchestrator run --mode hermes-bridge`와 `scene start`는 실제 actor를 직접 호출하지 않습니다. 대신 WSA가 `actor_state`, `floor_state`, scheduler rationale, bounded prompt, expected callback route를 담은 hook packet을 만들고, Hermes 또는 다른 외부 agent runtime이 그 hook을 실행한 뒤 callback을 돌려줍니다. 이 bridge contract는 runner-agnostic하게 설계되어 있어 향후 Codex-style local CLI agent나 custom actor runtime도 같은 callback 규격을 사용할 수 있습니다.

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
