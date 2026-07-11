# 권장 사용 방향

이 문서는 WSA를 실제 창작 workflow에 사용할 때의 기본 경로와 안전 경계를 설명합니다. 기본값은 한국어 human output, manual review, proposal-only입니다. 자동화는 JSON output과 기존 저수준 명령을 사용할 수 있습니다.

## 1. 동작 모델

```text
사용자 의도와 현재-world 자료 입력
-> WSA가 중립 질문, context, hook 또는 typed change preview 생성
-> 외부 runtime이 필요할 때만 실제 agent/subagent 수행
-> 결과가 report/candidate/concrete ticket으로 review inbox에 도착
-> 사용자가 inspect/revise/hold/reject/review
-> reviewed concrete ticket만 apply
```

WSA core는 API key, OAuth, SSH key, remote URL을 검색하거나 저장하지 않습니다. `orchestrator dispatch`도 사용자가 명시한 argv를 shell 없이 한 번 실행할 뿐 provider 권한을 소유하지 않습니다.

## 2. 첫 Workspace

```bash
wsa --workspace ./workspace init
wsa --workspace ./workspace world create "My World"
wsa --workspace ./workspace world home
```

월드가 하나뿐이면 `world home`, `world continue`, `ticket compose/next/review-next/apply-next`에서 world ID를 생략할 수 있습니다. 여러 월드가 있으면 고유 display name 또는 world ID를 명시해야 하며 WSA가 임의 추정하지 않습니다.

`world home`은 다음을 한 화면에 보여줍니다.

- Startup readiness
- pending report, run, ticket, callback
- blocking diagnostic
- 최근 application receipt
- 하나의 권장 next action

## 3. Startup

### 3.1 중립 최소 프레임

```bash
wsa --workspace ./workspace world startup interview <world_id> --budget 4
wsa --workspace ./workspace world startup answer <world_id> 0001 \
  --text "기존 메모를 정리해 세계관 레퍼런스를 만든다."
wsa --workspace ./workspace world startup summary <world_id>
```

Startup은 제작 목적, 시작 자료, 저자 통제, 출력 목표를 world canon과 분리합니다. 기본 질문은 장르·시대·인물·기관을 선점하지 않습니다.

### 3.2 현재-world 자료 기반 후속 질문

최소 프레임이 준비된 뒤 사용자가 명시한 파일만 일회성 source로 사용할 수 있습니다.

```bash
wsa --workspace ./workspace world startup source-followup <world_id> \
  --source ./notes/opening.txt \
  --source ./notes/places.txt
```

각 질문은 `why_asked`와 `source_refs`를 표시합니다. Source 내용은 이 명령으로 workspace에 저장되지 않습니다. 다른 world, beta memory, manager memory, user profile은 암묵적으로 읽지 않습니다.

## 4. JSON 없는 World 변경

### 4.1 새 변경안

```bash
wsa --workspace ./workspace ticket compose \
  --title "항구 인물과 장소 추가" \
  --add-entity "character|Mina" \
  --add-entity "location|Harbor" \
  --add-fact "Mina|role|navigator" \
  --add-edge "Mina|located_at|Harbor" \
  --add-timeline "Arrival|001"
```

기본 실행은 read-only preview입니다. 내용을 확인한 뒤 같은 명령에 `--write-ticket`을 붙입니다.

```bash
wsa --workspace ./workspace ticket next
wsa --workspace ./workspace ticket review-next
wsa --workspace ./workspace ticket apply-next
```

`ticket next`는 읽기 전용 inspect, `ticket review-next`는 검증 후 approved 전환, `ticket apply-next`는 실제 world mutation입니다. 각 명령은 적격 ticket이 정확히 하나일 때만 선택합니다. 여러 건이면 제목·상태를 표시하고 중단하므로 저수준 `ticket show/review/apply`에서 명시적 ID를 선택할 수 있습니다.

### 4.2 Candidate 일부 수락·수정

Structured candidate의 두 번째 항목을 제외하고 수정본을 더하는 예:

```bash
wsa --workspace ./workspace ticket compose \
  --accept-candidate <candidate_ticket_id> \
  --skip-index 2 \
  --add-fact "Mina|mood|focused"
```

Candidate의 free text는 canon change로 추론하지 않습니다. 명시적 typed change만 가져오며, 애매한 내용은 unresolved로 남깁니다.

### 4.3 기존 Ticket 수정

```bash
wsa --workspace ./workspace ticket amend <source_ticket_id> \
  --skip-index 1 \
  --add-fact "Mina|role|harbor pilot" \
  --write-ticket
```

수정 ticket은 parent lineage와 superseded 관계를 보존합니다. Preview 단계에는 상태 변화가 없습니다.

### 4.4 Ticket 분할·병합

원본의 모든 변경을 누락·중복 없이 두 ticket으로 나눕니다.

```bash
wsa --workspace ./workspace ticket split <source_ticket_id> \
  --part 1,3 --part 2
# preview 확인 후 같은 명령에 --write-ticket 추가
```

둘 이상의 concrete ticket을 입력 순서대로 합칩니다.

```bash
wsa --workspace ./workspace ticket merge <ticket_a> <ticket_b> \
  --title "통합 변경안"
# preview 확인 후 같은 명령에 --write-ticket 추가
```

Split/merge는 원본 ticket과 change를 삭제하지 않습니다. Write는 새 proposed ticket 생성과 원본 supersede를 한 transaction에서 수행하고 lineage를 보존합니다.

## 5. 통합 Review Inbox

```bash
wsa --workspace ./workspace report inbox <world_id>
wsa --workspace ./workspace report show <world_id> <item_id>
wsa --workspace ./workspace report decide <world_id> <item_id> \
  --decision hold --note "근거 보강 필요"
```

Inbox는 report, prep, orchestrator run, candidate, concrete ticket, 현재 world에 route된 callback을 모읍니다. 다른 world callback과 route를 알 수 없는 파일은 섞지 않으며, unrouteable residue는 quarantine-only입니다.

## 6. Actor 깊은 저작

모든 actor write도 preview -> ticket -> review -> apply를 재사용합니다. Actor는 고유 이름 또는 entity ID로 선택할 수 있습니다.

```bash
# Core/goal/secret/speech/style
wsa --workspace ./workspace world actor profile <world_id> Mina \
  --fragment goal --text "신호탑에 도달한다." --write-ticket

# 시간 속성
wsa --workspace ./workspace world actor attribute <world_id> Mina \
  --dimension condition --value-text wounded \
  --valid-from 002 --valid-until 004 --write-ticket

# Fact knowledge 또는 forbidden knowledge
wsa --workspace ./workspace world actor knowledge <world_id> Mina \
  --target-type fact --target-id <fact_id> --state known \
  --acquired-at 002 --write-ticket

# Durable memory
wsa --workspace ./workspace world actor memory <world_id> Mina \
  --time-scope 002 --text "첫 총성을 들었다." --write-ticket

wsa --workspace ./workspace world actor show <world_id> Mina

# 기존 goal의 종료 시각과 새 goal의 시작 시각을 한 ticket으로 연결
wsa --workspace ./workspace world actor profile <world_id> Mina \
  --fragment goal --text "사절을 호위한다." \
  --replace-record <actor_profile_id> --replace-at 005 --write-ticket

# 기존 기록의 status 또는 validity만 수정
wsa --workspace ./workspace world actor revise <world_id> Mina \
  --record-type actor_profile --record-id <actor_profile_id> \
  --status deprecated --write-ticket
```

`revise`는 profile, entity attribute span, knowledge attribution, memory packet을 지원합니다. Status/interval 변경과 새 기록 추가를 한 replacement ticket으로 묶을 수 있고, 기존 `_wsa` provenance와 lifecycle history를 보존합니다. Hidden fact와 secret profile은 명시적 knowledge attribution이 없으면 다른 viewpoint context에 노출되지 않습니다. 유효한 `forbidden` attribution은 같은 시간의 known 상태보다 우선합니다.

## 7. Scene, Meetup, 실행 출처

- `meeting run`과 `scene mock`: `deterministic_mock`
- bridge 준비 후 외부 callback 대기: `external_waiting`
- 검증된 callback ingest 완료: `external_confirmed`

Mock 결과를 실제 agent 실행처럼 해석하면 안 됩니다. CLI와 report의 execution mode/owner/status를 확인합니다.

```bash
wsa --workspace ./workspace scene start <world_id> \
  --topic "항구 도착" --participant Narrator --format json
wsa --workspace ./workspace report inbox <world_id>
wsa --workspace ./workspace report show <world_id> <prep_item_id>
wsa --workspace ./workspace report decide <world_id> <prep_item_id> \
  --decision approve
```

## 8. Provider-neutral Runtime

### 8.1 Plan

```bash
wsa --workspace ./workspace orchestrator dispatch-plan <run_id> \
  --workdir ./workspace \
  --runtime-command python3 scripts/reference_stdio_adapter.py
```

Plan은 process를 시작하지 않고 redacted argv, workdir, timeout, route digest, capability 요구를 보여줍니다.

### 8.2 한 Turn 실행·Ingest

```bash
wsa --workspace ./workspace orchestrator dispatch <run_id> \
  --workdir ./workspace --timeout 120 --confirm \
  --runtime-command python3 scripts/reference_stdio_adapter.py
```

`--runtime-command`는 마지막 옵션이어야 하며 뒤 토큰을 argv 배열로 취급합니다. WSA는 `shell=False`, 최소 환경 allowlist, bounded stdin/stdout, timeout을 사용합니다. Secret을 argv로 넘기지 말고 외부 runtime 자체의 local credential/config 경계를 사용합니다.

Reject된 callback 본문은 다음 accepted context에 들어가지 않습니다. Retry hook에는 bounded failure reason과 correction scope만 남고, interrupt/resume 뒤에도 같은 pending hook을 이어갑니다.

## 9. 진단과 복구

```bash
wsa --workspace ./workspace manager diagnose --format json
wsa --workspace ./workspace manager diagnose --record-findings
wsa --workspace ./workspace manager diagnose --repair-safe-artifacts
```

World별 `diagnostics/diagnostics_policy.json`에서 관계 cardinality, severity, interval 정책을 명시할 수 있습니다. 기본은 `located_at`만 singleton이며 affiliation 같은 관계는 다중을 허용합니다.

Migration과 restore drill:

```bash
wsa --workspace ./workspace migrate --format json
wsa --workspace ./workspace migrate --apply --format json
wsa --workspace ./workspace migrate restore-plan <backup_root> <new_path>
wsa --workspace ./workspace migrate restore <backup_root> <new_path>
```

Restore는 새 경로만 허용하고 SQLite integrity, row count, path rewrite를 receipt로 남깁니다. Runtime queue, lock, local policy는 backup restore 대상이 아닙니다.

## 10. Context 규모와 Fork Plan

Context assembler는 deterministic token estimate와 budget receipt를 제공하며 time/viewpoint/relevance에 따라 records를 제한합니다.

Portable selective export와 read-only fork plan:

```bash
wsa --workspace ./workspace world export <world_id> \
  --entity <entity_id> --include-timeline --format json
wsa --workspace ./workspace world fork-plan <world_id> \
  --name "Alternative World" --entity <entity_id> --format json
```

선택 entity가 참조하는 외향 dependency는 자동 포함합니다. Runtime message, callback, local overlay, report HTML은 제외합니다. Fork plan은 새 world를 만들지 않으며 portable import ticket 경로만 제시합니다.

## 11. 공개 저장소와 Local Overlay

커밋하지 않는 항목:

- `.env*`, `SESSION_HANDOFF.md`, `local_admin/`
- live workspace, SQLite DB, runtime session
- task/callback queue와 report runtime residue
- `hermes_commands.local.json`, operation policy, private remote/SSH path

공개 예시는 schema, 환경변수 이름, disabled policy shape만 포함합니다. 자세한 경계는 [RUNTIME_BOUNDARIES.md](RUNTIME_BOUNDARIES.md)와 [SECURITY.md](../SECURITY.md)를 확인하세요.

## 12. 검증

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONWARNINGS=error::ResourceWarning PYTHONPATH=src \
  python3 -m unittest discover -s tests
python scripts/check_docs_parity.py
bash scripts/fresh_clone_smoke.sh
```

Release 전에는 blank world, existing-notes world, no-runtime, reference adapter round trip, callback reject/retry/resume, restore-to-new-path, selective export/import 시나리오를 확인합니다.
