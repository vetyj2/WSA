# World Scene Actors

World Scene Actors(WSA)는 소설과 세계관 작업을 위한 로컬 우선 하네스입니다. 월드별 SQLite, 중립 Startup, viewpoint/time context, report·ticket review, proposal-only scene/meetup orchestration, Hermes-compatible callback 계약을 제공합니다.

기본 human output은 한국어이고 JSON field와 schema는 영어로 고정됩니다. 영문 문서는 [docs/en/README.md](docs/en/README.md)에 있습니다.

## 책임 경계

WSA core는 provider를 선택하거나 API key, OAuth token, SSH key, remote URL을 읽고 저장하지 않습니다. 실제 agent/subagent 권한과 credential은 사용자가 선택한 외부 runtime이 소유합니다.

WSA가 맡는 범위:

- workspace와 per-world SQLite
- Startup intent와 world assertion 분리
- task/hook packet, callback route와 dispatch receipt 검증
- report inbox, concrete ticket, review 후 apply
- deterministic mock과 provider-neutral stdio adapter
- migration backup/restore, diagnostics, portable export/fork plan

외부 runtime이 맡는 범위:

- provider account, API/OAuth 권한과 과금
- 실제 agent/subagent/session 실행
- shell·remote·delivery operation 승인
- private command, deployment, Docker/Telegram/cron 정책

`orchestrator dispatch`는 사용자가 argv와 workdir을 명시하고 `--confirm`한 경우에만 shell 없이 프로세스 하나를 시작합니다. WSA는 credential을 검색하거나 command를 자동 선택하지 않습니다.

## 현재 기능

| 영역 | 상태 |
| --- | --- |
| Workspace / world isolation | 구현됨 |
| Neutral Startup / source-grounded follow-up | 구현됨 |
| World Home / unified review inbox | 구현됨 |
| JSON 없는 ticket 작성·수정·분할·병합 | 구현됨 |
| Actor profile, 시간 속성, 지식, memory 수명주기 | 구현됨 |
| Mock / external waiting / external confirmed provenance | 구현됨 |
| Provider-neutral stdio dispatch + callback ingest | 구현됨 |
| Migration backup / restore-to-new-path | 구현됨 |
| Diagnostics policy / token-aware context / selective fork plan | 구현됨 |

## 설치

Python 3.9 이상을 지원합니다. PyPI 패키지가 아니므로 clone에서 설치합니다.

```bash
git clone <repository-url>
cd <repository-directory>
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

소스에서 바로 실행할 수도 있습니다.

```bash
PYTHONPATH=src python3 -m wsa --help
```

## 첫 변경

```bash
wsa --workspace ./workspace init
wsa --workspace ./workspace world create "My World"
wsa --workspace ./workspace world home

wsa --workspace ./workspace ticket compose \
  --title "Add Mina" \
  --add-entity "character|Mina" \
  --add-fact "Mina|role|navigator"

# preview를 확인한 뒤 같은 compose 명령에 --write-ticket 추가
wsa --workspace ./workspace ticket next
wsa --workspace ./workspace ticket review-next
wsa --workspace ./workspace ticket apply-next
```

Preview와 review는 world canon을 바꾸지 않습니다. `ticket apply-next`만 검토된 concrete change를 적용합니다. 단일 적격 ticket일 때만 자동 선택하며 여러 건이면 선택하지 않고 중단합니다. Candidate 수정과 ticket amend/split/merge는 [권장 사용 방향](docs/USAGE_GUIDE.md)에 정리되어 있습니다.

Actor의 profile, 시간 속성, knowledge boundary, memory도 같은 review/apply 경로를 사용합니다.

```bash
wsa --workspace ./workspace world actor profile <world_id> Mina \
  --fragment goal --text "Reach the signal tower." --write-ticket
wsa --workspace ./workspace world actor show <world_id> Mina
```

## 외부 Runtime

먼저 read-only plan을 확인합니다.

```bash
wsa --workspace ./workspace orchestrator dispatch-plan <run_id> \
  --runtime-command python3 scripts/reference_stdio_adapter.py
```

같은 command와 workdir을 확인한 뒤 한 turn만 실행·ingest합니다.

```bash
wsa --workspace ./workspace orchestrator dispatch <run_id> --confirm \
  --runtime-command python3 scripts/reference_stdio_adapter.py
```

Reference adapter와 실제 외부 runtime은 같은 stdin hook → stdout callback protocol을 사용합니다. Callback은 자동 canon mutation을 수행하지 않습니다.

## 진단과 복구

```bash
wsa --workspace ./workspace manager diagnose
wsa --workspace ./workspace manager diagnose --record-findings
wsa --workspace ./workspace manager diagnose --repair-safe-artifacts
wsa --workspace ./workspace migrate --apply --format json
wsa --workspace ./workspace migrate restore-plan <backup> <new-path>
```

`manager diagnose` 기본값은 read-only입니다. `migrate --apply`는 backup과 integrity verification을 수행하며 restore는 기존 경로를 덮어쓰지 않습니다.

## 검증

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
python scripts/check_docs_parity.py
bash scripts/fresh_clone_smoke.sh
```

## 공개 저장소 안전

`.env*`, `local_admin/`, `SESSION_HANDOFF.md`, live workspace/SQLite, callback/task queue, runtime session, local command overlay와 operation policy는 ignore 대상입니다. Public example에는 schema와 비활성 예시만 두고 실제 secret이나 private remote 정보를 넣지 마세요.

취약점 제보와 공개 범위는 [SECURITY.md](SECURITY.md), 사용 조건은 [MIT License](LICENSE)를 확인하세요.

## 문서

- [권장 사용 방향](docs/USAGE_GUIDE.md)
- [아키텍처](docs/ARCHITECTURE.md)
- [Runtime 권한 경계](docs/RUNTIME_BOUNDARIES.md)
- [릴리스·마이그레이션](docs/RELEASE_AND_MIGRATION.md)
- [기여 가이드](CONTRIBUTING.md)
- [English documentation](docs/en/README.md)
