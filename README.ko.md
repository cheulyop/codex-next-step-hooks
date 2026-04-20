# codex-next-step-hooks

[English](README.md) | **한국어** | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

번역 문서는 영어 원본보다 늦게 업데이트될 수 있습니다.

대화를 마무리할 때 적절한 방식으로 끝나도록 돕는 Codex hook 모음입니다.
정상 종료할지, 같은 턴에서 자동으로 이어갈지, 아니면 짧은 후속 질문을
한 번 더 할지를 판단합니다.

## 무엇을 하나요

이 패키지는 Codex hook 두 개를 설치합니다.

- 시작 또는 resume 시, 같은 턴에서 자연스럽게 이어갈지에 대한 기본 원칙을
  불러오는 `SessionStart` hook
- 마무리 응답을 정상 종료할지, 같은 턴에서 자동으로 이어갈지, 짧은 후속 질문을 던질지 결정하는 `Stop` hook

judge 모델은 최근 대화 맥락을 보고 `end` / `auto_continue` / `ask_user`
모드를 고릅니다. `ask_user`가 필요하면 Codex가 실제 후속 질문과 옵션을
현재 세션 맥락에 맞게 생성합니다.

이 패키지가 추가하는 hook 항목들은 `~/.codex/hooks.json`에 additive
방식으로 병합되며, `uninstall`은 이 패키지가 추가한 항목만 제거합니다.

## 동작 방식

1. `SessionStart`는 세션을 시작하거나 resume할 때 짧은 기본 원칙을 불러옵니다.
   - clear next step이 하나이면 같은 턴에서 바로 이어서 진행
   - 실제로 선택이 필요할 때만 한 번 질문
2. 턴이 끝나기 직전에 `Stop` hook이 실행됩니다.
3. `Stop` hook은 최근 대화 흐름, 최근 후속 질문 내역, 막 끝나려는 assistant
   응답을 모아 judge 모델에 보냅니다.
4. judge는 세 가지 structured mode 중 하나를 반환합니다.
   - `end`: assistant 응답을 정상 종료
   - `auto_continue`: 사용자에게 묻지 않고 같은 턴에서 계속 진행
   - `ask_user`: 멈춘 뒤 Codex가 실제 후속 질문을 제시
5. 메인 Codex 세션은 그 결과를 실제로 수행합니다.
   - `end`: 턴이 그대로 종료됩니다
   - `auto_continue`: continue instruction을 받아 같은 턴에서 계속 움직입니다
   - `ask_user`: live session context를 바탕으로 실제 `request_user_input`
     질문과 옵션을 생성합니다
6. 이후 transcript에는 `stop_hook_judgment` debug event가 추가되어,
   나중에 `observe`로 실제 판단을 다시 볼 수 있습니다.

judge는 세 가지 결과 중 하나와 짧은 이유를 돌려줍니다. 실제 후속 질문은
judge가 아니라 메인 Codex 세션이 작성합니다.

예를 들면 이렇게 동작합니다.

- assistant가 `경로 확인됐습니다.`로 끝나면 보통 그냥 종료됩니다
- assistant가 `패치는 반영됐고 다음 단계는 self-test 실행입니다.`로 끝나면
  보통 같은 턴에서 계속 진행합니다
- assistant가 `프롬프트를 다듬을지, observe를 먼저 볼지 정해야 합니다.`처럼
  두 갈래를 열면 보통 후속 질문을 한 번 띄웁니다

## Judge Endpoint

이 패키지는 judge endpoint를 직접 제공하지 않습니다. 먼저 사용 가능한
OpenAI-compatible `responses` backend를 연결해야 합니다.

보통은 다음 환경 변수를 설정합니다.

- `CODEX_RUI_JUDGE_URL`
- `CODEX_RUI_JUDGE_MODEL`
- `CODEX_RUI_JUDGE_REASONING_EFFORT`
- `CODEX_RUI_JUDGE_TIMEOUT_SECONDS`

judge 쪽에는 다음이 필요합니다.

- OpenAI-compatible `responses` endpoint
- hook schema에 맞는 structured JSON output
- hook timeout 안에 응답을 돌려줄 수 있는 latency
- `mode`, `continue_instruction`, `rationale`를 반환할 수 있는 백엔드

현재 코드의 fallback 값은 다음과 같습니다.

- endpoint: `http://127.0.0.1:10531/v1/responses` (`CODEX_RUI_JUDGE_URL` 미설정 시)
- model: `gpt-5.4`
- reasoning effort: `medium`
- timeout: `30`초

위 endpoint는 로컬 개발 환경에서만 바로 맞을 가능성이 높습니다. 새 사용자는
대개 자신의 judge backend URL을 명시적으로 설정하는 편이 안전합니다.

전체 런타임 contract는 [docs/runtime-contract.md](docs/runtime-contract.md)를
보세요.

## Judge는 무엇을 참고하나요

Stop hook은 raw transcript 전체를 그대로 보내지 않고, 현재 작업 흐름을
짧게 압축해서 judge에 보냅니다.

judge가 주로 참고하는 것은 다음 네 가지입니다.

- 최근 몇 턴의 대화 흐름
- 최근 후속 질문과 사용자의 선택
- 현재 턴에서 assistant가 이미 얼마나 진행했는지
- 지금 막 끝나려는 마지막 assistant 응답

예를 들어 judge에는 대략 이런 정보가 들어갑니다.

```text
최근 흐름:
- user: README 설명을 더 간단하게 정리해 주세요
- assistant: README 수정과 검증을 마쳤습니다
- 최근 후속 질문: "다음엔 무엇을 할까요?" -> "검증 후 커밋"
- final assistant message: "검증은 끝났습니다. 이제 커밋할 수 있습니다."
```

이런 경우 judge는 보통 `auto_continue` 쪽으로 기울 수 있습니다. 반대로
마지막 assistant 응답이 두 개 이상의 실질적인 다음 방향을 열어두면
`ask_user` 쪽으로 기울 수 있습니다.

## Judge가 반환하는 값

judge는 다음 schema에 맞는 structured JSON을 반환합니다.

```json
{
  "mode": "end | auto_continue | ask_user",
  "continue_instruction": "string",
  "rationale": "string"
}
```

mode별 기대 동작:

- `end`: `continue_instruction`은 보통 비어 있습니다
- `auto_continue`: `continue_instruction`이 반드시 비어 있지 않아야 합니다
- `ask_user`: 실제 후속 질문은 Codex가 생성하므로 `continue_instruction`은 비어 있을 수 있습니다

예시:

```json
{
  "mode": "end",
  "continue_instruction": "",
  "rationale": "The reply already closes the current lane and does not tee up a meaningful next step."
}
```

```json
{
  "mode": "auto_continue",
  "continue_instruction": "Update the stop-hook schema to use mode=end|auto_continue|ask_user, then split the branch handling for ask_user and auto_continue.",
  "rationale": "The user already chose the implementation lane and one next action is clearly dominant."
}
```

```json
{
  "mode": "ask_user",
  "continue_instruction": "",
  "rationale": "Two materially different next paths are open and the user should pick between them."
}
```

## 사용자에게는 어떻게 보이나요

UI 수준에서는 대체로 이렇게 느껴집니다.

- 턴이 진짜 끝난 경우에는 그냥 정상 종료됩니다
- 다음 행동이 하나로 명확하면 클릭을 요구하지 않고 그대로 계속 진행합니다
- 실제로 선택이 필요할 때만 후속 질문을 띄우고, 선택 후에도 같은 턴에서 이어서 진행합니다

좀 더 구체적인 예시:

- 작은 사실 확인:
  - user asks: `Does the hook template still point at the packaged script?`
  - assistant ends with: `Confirmed. The hook template still points at the packaged stop-hook script.`
  - expected mode: `end`
- 명확한 후속 진행:
  - assistant ends with: `The patch is in. The next step is to run the verification command.`
  - expected mode: `auto_continue`
  - expected output shape:

    ```json
    {
      "mode": "auto_continue",
      "continue_instruction": "Run the verification command next.",
      "rationale": "One dominant follow-through step is already clear."
    }
    ```
- 실제 분기 선택:
  - assistant ends with: `We can either inspect more mode_end cases or tighten the prompt wording.`
  - expected mode: `ask_user`
  - 이후 Codex가 같은 턴에서 실제 후속 질문을 생성합니다

## Stop hook 분기 처리

judge가 응답을 반환한 뒤 stop hook은 그것을 두 종류의 block instruction
중 하나로 바꾸거나, 그대로 종료시킵니다.

- `build_auto_continue_block_reason(...)`는 사용자에게 다시 묻지 말고,
  바로 continue instruction을 수행하라고 Codex에 지시합니다
- `build_ask_user_block_reason(...)`는 `request_user_input`를 호출하고,
  session context를 바탕으로 후속 질문을 생성하라고 지시합니다
- `end`는 별도 block reason 없이 턴을 그대로 닫습니다

judge 뒤에는 safety layer도 하나 있습니다.

- raw judge response가 `end`였더라도 assistant message 자체가 follow-up choice를
  여러 개 명확히 드러내면 `ask_user`로 승격할 수 있습니다
- raw judge response가 `end`였더라도 assistant message 자체가 하나의 next step을
  명확히 이름 붙이면 `auto_continue`로 승격할 수 있습니다

이 safety layer는 너무 이른 `end`를 잡아내기 위한 장치입니다.

여기서 "clearly"는 다른 LLM 호출로 판단하는 게 아닙니다. 현재 구현은 final
assistant message에 대해 lightweight message-pattern check를 수행합니다.
예를 들어:

- follow-up choice patterns: `we can either`, `options like`, `or we can`,
  `아니면`, `또는`
- next-step patterns: `the next step is to ...`, `the obvious next step is to ...`,
  `다음 단계는 ...`, `다음으로는 ...`

즉 이건 좁은 heuristic backstop입니다. judge가 명백히 너무 이른 `end`를
반환했을 때는 유용하지만, 완전한 semantic parser는 아닙니다.

## 관측성과 디버깅

각 stop-hook 판단은 transcript에 다음 같은 필드를 가진 debug event를 남깁니다.

- `status`
- `mode`
- `rationale`
- `continue_instruction`
- `judgment_override`
- `judge_failure_reason`
- `current_turn_context`

이 데이터는 calibration 작업에 유용한 `observe` CLI로 이어집니다.

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --json
```

judge endpoint가 unavailable이거나 malformed structured output을 반환하면,
hook은 `status="judge_unavailable"`과 best-effort `judge_failure_reason`을
남기고, 기본적으로 turn을 정상 종료시키는 쪽으로 fallback합니다.

이 hook은 결국 LLM judge 기반이기 때문에, 처음부터 모든 사용자의 기대에
완벽히 맞지는 않을 수 있습니다. 그래서 이 repo는 동작을 직접 관찰하고
customize하기 쉽게 만드는 쪽을 의도합니다.

- `observe`로 실제 transcript-level 판단을 다시 볼 수 있습니다
- transcript debug event가 rationale, mode, override, turn-shape 데이터를 남깁니다
- judge prompt는 로컬 코드
  `src/codex_next_step_hooks/hooks/stop_require_request_user_input.py`
  에 있습니다
- post-judge override heuristic도 로컬에서 직접 수정할 수 있습니다

권장 workflow는 이렇습니다: 실제 결과를 보고, prompt나 heuristic을 수정한 뒤,
`self-test`, `doctor`, `observe`를 다시 돌립니다.

## 포함 내용

- 패키지에 포함된 `Stop` / `SessionStart` hook 스크립트
- `hooks.json`용 additive `install` / `uninstall` 명령
- 로컬 패키지 상태를 점검하는 `doctor`
- 현재 judge endpoint에 실제 structured probe를 보내는 `doctor --live-judge`
- follow-up decision 회귀를 위한 deterministic self-test
- transcript 단위 judge calibration과 mode/rationale 점검용 `observe` CLI
- repo 핵심 경로를 빠르게 확인하는 `print-layout` CLI
- 런타임 및 endpoint 구성을 설명하는 contract 문서
- judge mode와 짧은 rationale을 기록하는 transcript debug event

## 현재 기능

- Codex `Stop` hook을 위한 context-aware `end` / `auto_continue` / `ask_user` 로직
- assistant 응답이 후속 선택지나 명확한 다음 단계를 직접 드러낼 때 `end`를 막는 override guard
- `SessionStart` hook을 통한 시작 시 정책 로딩
- Python 인터프리터 및 repo root를 반영하는 template rendering
- ask-user, auto-continue, end 동작에 대한 synthetic regression coverage
- 로컬 환경용 install 및 runtime verification 명령
- mode 비율, override, rationale 패턴을 보는 transcript 기반 observability
- ordered `turn.entries` source-of-truth와 거기서 파생한 judge용 view

## 구조

```text
codex-next-step-hooks/
├─ README.md
├─ README.ko.md
├─ README.ja.md
├─ README.zh-CN.md
├─ LICENSE
├─ pyproject.toml
├─ docs/
│  └─ runtime-contract.md
├─ src/
│  ├─ codex_next_step_hooks/
│  │  ├─ __init__.py
│  │  ├─ cli.py
│  │  ├─ doctor.py
│  │  ├─ install.py
│  │  ├─ observe.py
│  │  ├─ uninstall.py
│  │  ├─ merge.py
│  │  ├─ runtime_paths.py
│  │  ├─ selftest.py
│  │  ├─ hooks/
│  │  │  ├─ session_start_request_user_input_policy.py
│  │  │  └─ stop_require_request_user_input.py
│  │  └─ templates/
│  │     └─ hooks.json
└─ tests/
   ├─ *.json
   └─ fixtures/
      └─ *.jsonl
```

## 빠른 시작

```bash
cd /path/to/codex-next-step-hooks
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --dry-run --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --live-judge --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli self-test --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli print-layout --json
```

## 설치

먼저 변경 사항을 미리 봅니다.

```bash
cd /path/to/codex-next-step-hooks
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --dry-run --json
```

실제로 설치합니다.

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --json
```

필요하면 Python 인터프리터나 Codex home을 직접 지정할 수 있습니다.

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --python /path/to/python --codex-home /path/to/.codex --json
```

`install`이 하는 일:

- 현재 Python 인터프리터 경로로 hook template를 렌더링합니다
- 현재 repo root를 이 패키지가 추가하는 hook command에 반영합니다
- 이 패키지가 추가하는 hook 항목을 `~/.codex/hooks.json`에 병합합니다
- 파일이 바뀌면 쓰기 전에 backup을 만듭니다

## 검증

정적 점검:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --json
```

live judge probe:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --live-judge --json
```

deterministic regression suite:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli self-test --json
```

이 repo 기준 최근 stop-hook 판단을 점검:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --json
```

기본적으로 `observe`는 현재 working directory 기준으로만 집계합니다.
모든 cwd를 같이 보려면 `--all-cwds`를 쓰면 됩니다.

특정 과거 세션만 보기:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --session-id 019da87f-2a7f-7870-a5aa-84a28745e9db --json
```

현재 세션과 archived 세션 전체를 함께 보기:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --all-cwds --include-archived --json
```

특정 날짜 범위만 필터링:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --all-cwds --date-from 2026-04-20 --date-to 2026-04-20 --json
```

특정 mode만 보거나 example 개수를 줄일 수도 있습니다.

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --mode ask_user --limit 3 --json
```

## 제거

먼저 제거 결과를 미리 봅니다.

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli uninstall --dry-run --json
```

이 패키지가 추가한 hook 항목을 제거합니다.

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli uninstall --json
```

다른 Codex home을 대상으로 제거할 수도 있습니다.

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli uninstall --codex-home /path/to/.codex --json
```

`uninstall`은 이 패키지가 추가한 항목만 제거하고, 관련 없는 hook 설정은
그대로 둡니다.

## CLI 명령

- `install`: hook template를 렌더링하고 이 패키지의 hook 항목을 `hooks.json`에 병합
- `uninstall`: 관련 없는 hook 설정은 유지한 채 이 패키지의 hook 항목만 제거
- `doctor`: 정적 파일 및 패키지 상태 점검
- `doctor --live-judge`: judge endpoint에 structured request를 보내 실제 응답 점검
- `self-test`: deterministic synthetic regression suite 실행
  - `--case /path/to/test.json`으로 단일 케이스만 돌릴 수 있습니다
- `observe`: calibration용 `stop_hook_judgment` 이벤트 요약
  - repo 범위/전체 범위, archived 세션 포함, 날짜 필터를 지원
  - `--session-id`, `--mode`, `--limit`으로 더 좁게 볼 수 있습니다
- `print-layout`: repo의 주요 경로를 JSON 또는 plain dict로 출력

## 런타임 구성

- judge backend와 환경 변수: `docs/runtime-contract.md`

## 설치되는 hook 항목

이 패키지의 template는 아래 이벤트마다 handler 하나씩 추가합니다.

- `SessionStart` with matcher `startup|resume`
- `Stop`

각 command는 아래 스크립트를 가리킵니다.

- `src/codex_next_step_hooks/hooks/session_start_request_user_input_policy.py`
- `src/codex_next_step_hooks/hooks/stop_require_request_user_input.py`

## 앞으로 개선할 점

- repo 이동이나 인터프리터 이름 변경 상황에서 uninstall 보강
- 기존 사용자 설정의 edge case에 대한 installer safety check 확대
- 필요 시 `doctor --live-judge` 실패 힌트 강화
- 공개용 예시와 regression case 추가
