# 기여 가이드

## 개발 환경

WSA는 Python 3.9 이상과 표준 라이브러리를 기본 runtime으로 사용합니다.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[dev]'
```

## 변경 원칙

- WSA가 credential, OAuth, SSH key 또는 실제 agent process를 소유하게 만들지 않습니다.
- user input, agent proposal, accepted callback, canon mutation을 구분합니다.
- world mutation은 preview -> ticket -> apply 경계를 유지합니다.
- 기존 workspace와 startup profile을 조용히 재작성하지 않습니다.
- public example에는 실제 secret, remote URL, 개인 경로를 넣지 않습니다.
- mock, local simulation, external callback 실행을 출력과 문서에서 구분합니다.

## 검증

```bash
PYTHONPATH=src PYTHONPYCACHEPREFIX=/tmp/wsa-pyc \
  python3 -W error::ResourceWarning -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/wsa-pyc python3 -m compileall -q src/wsa
python3 scripts/check_public_tree.py
python3 scripts/check_docs_parity.py
```

CLI option이나 Hermes route를 변경하면 `command_specs.py`와 drift test를 함께 갱신하세요. 저장소 schema를 변경하면 순차 migration, backup/verify 절차, v1 fixture 보존 테스트가 필요합니다.

## Pull request

PR에는 문제, 사용자-visible 변경, migration/호환 영향, 검증 명령을 짧게 적으세요. 대형 파일 정리와 동작 변경은 가능하면 분리합니다. 보안 취약점은 public PR 전에 [SECURITY.md](SECURITY.md)의 비공개 신고 절차를 사용하세요.

영문 가이드는 [docs/en/CONTRIBUTING.md](docs/en/CONTRIBUTING.md)를 참고하세요.
