# 권장 사용 방향

이 문서는 WSA를 공개 템플릿으로 유지하면서 실제 Hermes runtime과 안전하게 연결하는 권장 사용 방향을 정리합니다.

## 기본 원칙

WSA는 로컬 workspace와 review workflow를 책임지는 하네스입니다. 실제 agent/subagent 실행, provider API 호출, OAuth/API key 관리, Docker/Telegram/cron 운영, shell command 승인 정책은 사용자 Hermes runtime이나 operator layer가 맡습니다.

권장 흐름은 다음과 같습니다.

```text
WSA가 bounded task 또는 hook packet 생성
Hermes runtime이 실제 agent/subagent 작업 수행
Hermes가 workspace/hermes/callbacks/ 아래 callback JSON 작성
WSA가 callback 구조와 route를 검증
WSA가 report, ticket, run state에 결과 기록
사용자 또는 local policy가 canon 적용 여부 결정
```

## 처음 사용하는 흐름

1. 저장소를 clone하고 editable install을 합니다.
2. `template check --write-missing`으로 빈 workspace 구조를 확인합니다.
3. `wsa init`, `wsa world create`로 로컬 workspace와 world를 만듭니다.
4. `startup` 또는 `easystartup`으로 초기 세계관 질문을 시작합니다.
5. `meeting run` 또는 `orchestrator run`으로 proposal-only 검토를 만듭니다.
6. report와 ticket을 확인한 뒤, 필요한 경우에만 ticket apply/approve를 진행합니다.

## Hermes를 붙일 때

먼저 public-safe example만 생성합니다.

```bash
PYTHONPATH=src python3 -m wsa --workspace <workspace> hermes init-example
PYTHONPATH=src python3 -m wsa --workspace <workspace> hermes commands --write-example
```

그 다음 사용자 Hermes runtime이 다음을 책임지게 합니다.

- task packet 읽기
- 실제 subagent/session 호출
- provider credential 관리
- callback JSON 작성
- operation request에 대한 user confirmation
- local command, remote push, deployment policy mapping

WSA 쪽에는 실제 credential이나 private remote 정보를 넣지 않습니다.

## Scene / Meetup 권장 방식

`scene start`와 `orchestrator run --mode hermes-bridge`는 Hermes가 실제 actor/subagent 호출을 수행하도록 hook packet을 제공합니다. WSA는 준비된 context, actor_state, floor_state, prompt packet, queue limit, quality gate, approval package를 기록합니다.

권장 순서:

1. `scene start` 또는 `orchestrator run`으로 prep/report 생성
2. 사용자 또는 Hermes가 prep review 확인
3. `orchestrator prep-approve`로 첫 hook 열기
4. Hermes가 callback 작성
5. `orchestrator submit`으로 callback 제출
6. WSA가 quality gate와 route를 확인하고 다음 hook 또는 review package 생성

Bridge hook에는 actor별 이전 position, objections, unanswered questions, stance, confidence history가 압축되어 들어갑니다. Hermes는 이 정보를 사용해서 같은 actor를 처음부터 다시 시작하지 말고, 필요한 경우 "이전 주장 X에 대한 반박 Y만 답하라" 같은 짧은 follow-up으로 호출해야 합니다.

Round는 중간보고 단위입니다. 실제 비용과 루프 제한은 actor turn/callback budget으로 이해하세요. Hermes는 모든 actor를 매 라운드 호출할 필요가 없습니다. Verification need, blocking objection, domain ownership, candidate falsification value, unanswered question이 있는 actor를 우선 호출하는 것이 권장됩니다.

WSA callback quality gate는 missing fields, unlabeled uncertainty, canon mutation attempt뿐 아니라 empty agreement, repeated prior position 같은 low-value turn warning도 기록합니다. 경고가 있으면 Hermes는 좁은 retry, deepening question, manager/canon verification pause 중 하나를 선택하는 것이 좋습니다.

## Canon 적용 원칙

WSA의 meeting, startup, scene prep, orchestrator output은 기본적으로 proposal입니다. 바로 canon fact나 world state가 되지 않습니다.

Canon 변경은 report, ticket, explicit decision 같은 review boundary를 거쳐야 합니다. 자동 생성이 많아질수록 ticket과 report를 더 보수적으로 사용하세요.

## Update 권장 방식

Live workspace를 업데이트하기 전에는 source/package layer와 runtime workspace를 분리해서 봅니다.

```bash
wsa --workspace <live-workspace> update preflight --source-root <wsa-source-root>
wsa --workspace <live-workspace> update backup --output-dir <backup-root> --source-root <wsa-source-root>
```

Preflight가 확인하는 핵심 항목:

- pending task queue
- pending callbacks
- reports outbox
- active task state
- active scheduler jobs
- local command overlay collision

Hermes 사용자별 shortcut은 `workspace/hermes/adapter_config/hermes_commands.local.json`에 둡니다. 업데이트 전후에는 아래 검진을 함께 실행하고, 충돌이나 mutating command metadata 부족이 나오면 Hermes가 사용자에게 변경 권고를 보고하세요.

```bash
wsa --workspace <live-workspace> hermes commands --validate-local-overlay --format json
wsa --workspace <live-workspace> hermes commands --merged --format json
```
- live adapter config
- update lock

업데이트 중에는 `git clean -fdx`, workspace root 덮어쓰기, live DB 삭제 같은 destructive cleanup을 사용하지 마세요.

## Public Repo 운영 규칙

공개 저장소에는 reusable contract와 example shape만 둡니다. 실사용자의 local runtime 상태는 ignore된 workspace나 외부 secret manager에 둡니다.

커밋 가능한 것:

- `src/wsa/` 코드
- `tests/`
- `examples/*.example.json`
- public-safe docs
- change log dashboard

커밋하지 않는 것:

- `.env*`
- `local_admin/`
- `SESSION_HANDOFF.md`
- live operation policy JSON
- SQLite DB
- real workspace/runtime state
- private remote URL, SSH key path, token value
