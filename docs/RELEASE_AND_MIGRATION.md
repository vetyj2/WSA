# 릴리스·마이그레이션 정책

## 버전 경계

WSA 0.3.0은 control DB와 world DB를 schema v2로 올립니다. Startup profile은 `defaults_revision`, workflow run은 별도 run/projection schema를 사용합니다. 코드 버전과 데이터 버전을 같은 숫자로 가정하지 마세요.

## 기존 workspace 업그레이드

1. Hermes task intake, callback 작성, cron/daemon을 중지합니다.
2. `wsa update preflight`와 `wsa migrate --format json`을 실행합니다.
3. plan의 모든 step이 `upgrade_required` 또는 `current`인지 확인합니다.
4. `wsa migrate --apply --format json`을 실행합니다.
5. 출력된 backup path를 보존합니다.
6. `wsa doctor`, `wsa manager diagnose`, 핵심 world 조회를 실행합니다.
7. 검증 후 외부 runtime을 재개합니다.

Migration은 v1 -> v2 순서만 지원하고 downgrade를 자동 수행하지 않습니다. 적용 중 실패하면 WSA를 중지하고 출력된 `.wsa_migration_backups/<timestamp>/`의 SQLite 파일로 복구하세요. 일부 DB만 이미 v2인 중단 상태에서 재실행해도 `current` step은 건너뜁니다.

## 0.3.1 SOL refactor 주요 변경

- JSON 없는 guided ticket 경로 `next -> review-next -> apply-next`
- ticket amend/split/merge의 atomic lineage와 rollback 보장
- actor deep record의 status/interval revision과 replacement ticket
- provider-neutral runtime dispatch, callback receipt, public-safe runtime 경계 보강
- 278개 테스트, strict ResourceWarning, ruff/mypy, build/install smoke 검증

0.3.1은 schema v2를 변경하지 않는 호환 patch release입니다. 기존 0.3.0 migration 정책은 아래와 같이 유지됩니다.

## 0.3.0 주요 변경

- 중립 Startup v2와 legacy answer 보존 migration
- candidate-only ticket apply 차단, candidate materialization, 비변경 review, transactional/idempotent ticket application
- world inspection, proposal preview, portable export/import preview
- viewpoint/time/location/knowledge/memory 기반 ContextBundle과 budget receipt
- SQLite RunStore, revision/CAS, callback replay receipt, interrupt/resume
- explicit control/world migration과 projection repair
- compact run/plan contract references와 concise CLI JSON
- CLI/Hermes registry/repository compatibility facade와 800줄 이하 하위 모듈 분리
- `wsa.artifacts` architecture/routing/lifecycle operation package
- public CI, security/contribution policy, installed golden-path smoke
- pure diagnostics와 `--record-findings`/`--repair-safe-artifacts` 분리, temporal/edge conflict severity

## 호환 정책

- `ticket approve`는 `ticket apply`의 compatibility alias로 유지합니다.
- 기존 proposed concrete ticket의 direct apply는 유지하며, 새 사용자 흐름은 `ticket review -> ticket apply`를 권장합니다.
- 기존 `ContextBuilder.build_actor_context()` API는 v2 assembler facade로 유지합니다.
- static meeting과 mock scene은 deterministic compatibility/demo 경로입니다.
- external runtime은 기존 callback schema와 route 검증을 계속 사용합니다.
- compact projection의 전체 상태는 SQLite 또는 `--expand-contracts`로 조회합니다.

영문 문서는 [docs/en/RELEASE_AND_MIGRATION.md](en/RELEASE_AND_MIGRATION.md)를 참고하세요.
