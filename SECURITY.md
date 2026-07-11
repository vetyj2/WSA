# 보안 정책

## 지원 범위

보안 수정은 현재 `main`과 최신 릴리스 계열에 우선 적용합니다. 오래된 workspace는 먼저 `wsa migrate` 계획을 확인하고 백업 후 업그레이드하세요.

## 취약점 신고

API key, token, 개인 경로, callback 원문 같은 민감정보를 public issue에 올리지 마세요. 가능하면 GitHub의 [비공개 보안 권고](https://github.com/vetyj2/WSA/security/advisories/new)를 사용하고, 사용할 수 없다면 민감한 재현자료를 제거한 최소 설명으로 maintainer에게 비공개 연락 경로를 요청하세요.

다음 내용을 포함하면 진단에 도움이 됩니다.

- 영향을 받는 WSA 버전과 Python 버전
- 공격자가 통제해야 하는 입력 또는 파일 경로
- 재현 단계와 예상/실제 결과
- secret을 제거한 로그 또는 최소 fixture
- 데이터 노출, 임의 파일 쓰기, canon mutation 등 실제 영향

## 신뢰 경계

WSA는 provider credential, OAuth token, SSH key, 장기 실행 Hermes process를 소유하지 않습니다. 외부 runtime이 agent/subagent와 provider 권한을 소유하고 WSA는 bounded hook, callback validation, report, ticket, local state를 관리합니다. 사용자가 argv/workdir을 명시하고 확인하면 WSA의 stdio adapter가 외부 command 한 개를 실행할 수 있지만 provider나 credential을 자동 탐색하지 않습니다.

Callback 검증은 schema와 route 기반입니다. 암호학적 인증이 아니므로 `workspace/hermes/callbacks/`를 공개 upload endpoint로 노출하면 안 됩니다. 신뢰되지 않은 사용자가 workspace 파일이나 SQLite DB를 쓸 수 있다면 WSA의 로컬 경계만으로 방어할 수 없습니다.

보안상 중요한 기본값:

- callback은 기본적으로 workspace 내부 경로만 허용
- stdio dispatch는 `--confirm`, `shell=False`, 최소 환경 allowlist, bounded I/O와 timeout 사용
- runtime command/credential은 public registry가 아니라 사용자 local 경계에서 선택
- concrete ticket change가 없으면 world apply 차단
- canon mutation은 ticket apply 경로로 제한
- run update와 callback replay는 SQLite revision/receipt로 중복 차단
- runtime JSON과 SQLite DB, `.env*`, local policy는 Git에서 제외
- migration은 read-only plan 후 backup/apply/verify 순서로만 실행

영문 정책은 [docs/en/SECURITY.md](docs/en/SECURITY.md)를 참고하세요.
