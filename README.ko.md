# codex-click-chooser-hooks

[English](README.md) | **한국어** | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

번역 문서는 영어 원본보다 늦게 업데이트될 수 있습니다.

대화를 마무리할 때 적절한 방식으로 끝나도록 돕는 Codex hook 모음입니다.
정상 종료할지, 같은 턴에서 자동으로 이어갈지, 아니면 짧은 후속 질문을
한 번 더 할지를 판단합니다.

## 무엇을 하나요

이 패키지는 관리되는 Codex hook 두 개를 설치합니다.

- 시작 또는 resume 시 chooser 정책을 불러오는 `SessionStart` hook
- 마무리 응답을 정상 종료할지, 같은 턴에서 자동으로 이어갈지, 짧은 후속 chooser를 보여줄지 결정하는 `Stop` hook

judge 모델은 최근 대화 맥락을 보고 `end` / `auto_continue` / `ask_user`
모드를 고릅니다. `ask_user`가 필요하면 Codex가 실제 chooser 질문과 옵션을
현재 세션 맥락에 맞게 생성합니다.

이 hook들은 `~/.codex/hooks.json`에 additive 방식으로 병합되며,
`uninstall`은 이 패키지가 관리하는 항목만 제거합니다.

## 포함 내용

- 패키지에 포함된 `Stop` / `SessionStart` hook 스크립트
- `hooks.json`용 additive `install` / `uninstall` 명령
- 로컬 패키지 상태를 점검하는 `doctor`
- 현재 judge endpoint에 실제 structured probe를 보내는 `doctor --live-judge`
- follow-up decision 회귀를 위한 deterministic self-test
- 런타임 및 endpoint 구성을 설명하는 contract 문서
- judge mode와 짧은 rationale을 기록하는 transcript debug event

## 현재 기능

- Codex `Stop` hook을 위한 context-aware `end` / `auto_continue` / `ask_user` 로직
- assistant 응답이 후속 선택지나 명확한 다음 단계를 직접 드러낼 때 `end`를 막는 override guard
- `SessionStart` hook을 통한 시작 시 정책 로딩
- Python 인터프리터 및 repo root를 반영하는 template rendering
- ask-user, auto-continue, end 동작에 대한 synthetic regression coverage
- 로컬 환경용 install 및 runtime verification 명령

## 구조

```text
codex-click-chooser-hooks/
├─ README.md
├─ README.ko.md
├─ README.ja.md
├─ README.zh-CN.md
├─ LICENSE
├─ pyproject.toml
├─ docs/
│  └─ runtime-contract.md
├─ src/
│  └─ codex_click_chooser_hooks/
│     ├─ __init__.py
│     ├─ cli.py
│     ├─ doctor.py
│     ├─ install.py
│     ├─ uninstall.py
│     ├─ merge.py
│     ├─ runtime_paths.py
│     ├─ selftest.py
│     ├─ hooks/
│     │  ├─ session_start_request_user_input_policy.py
│     │  └─ stop_require_request_user_input.py
│     └─ templates/
│        └─ hooks.json
└─ tests/
   ├─ *.json
   └─ fixtures/
      └─ *.jsonl
```

## 빠른 시작

```bash
cd /path/to/codex-click-chooser-hooks
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --dry-run --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --live-judge --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli self-test --json
```

## 설치

먼저 변경 사항을 미리 봅니다.

```bash
cd /path/to/codex-click-chooser-hooks
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --dry-run --json
```

실제로 설치합니다.

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --json
```

`install`이 하는 일:

- 현재 Python 인터프리터 경로로 hook template를 렌더링합니다
- 현재 repo root를 관리 대상 hook command에 반영합니다
- 관리 대상 handler를 `~/.codex/hooks.json`에 병합합니다
- 파일이 바뀌면 쓰기 전에 backup을 만듭니다

## 검증

정적 점검:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --json
```

live judge probe:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --live-judge --json
```

deterministic regression suite:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli self-test --json
```

## 제거

먼저 제거 결과를 미리 봅니다.

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli uninstall --dry-run --json
```

관리 대상 handler를 제거합니다.

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli uninstall --json
```

`uninstall`은 이 패키지가 관리하는 항목만 제거하고, 관련 없는 hook 설정은
그대로 둡니다.

## CLI 명령

- `install`: hook template를 렌더링하고 관리 대상 handler를 `hooks.json`에 병합
- `uninstall`: 관련 없는 hook 설정은 유지한 채 관리 대상 항목만 제거
- `doctor`: 정적 파일 및 패키지 상태 점검
- `doctor --live-judge`: judge endpoint에 structured request를 보내 실제 응답 점검
- `self-test`: deterministic synthetic regression suite 실행

## 런타임 구성

- judge backend와 환경 변수: `docs/runtime-contract.md`

## 관리되는 hook 항목

관리되는 template는 아래 이벤트마다 handler 하나씩 추가합니다.

- `SessionStart` with matcher `startup|resume`
- `Stop`

각 command는 아래 스크립트를 가리킵니다.

- `src/codex_click_chooser_hooks/hooks/session_start_request_user_input_policy.py`
- `src/codex_click_chooser_hooks/hooks/stop_require_request_user_input.py`

## 앞으로 개선할 점

- repo 이동이나 인터프리터 이름 변경 상황에서 uninstall 보강
- 기존 사용자 설정의 edge case에 대한 installer safety check 확대
- 필요 시 `doctor --live-judge` 실패 힌트 강화
- 공개용 예시와 regression case 추가
