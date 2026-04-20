# Runtime Contract

`codex-next-step-hooks` is a public package for Codex hook workflows.

This document captures the minimal contract for the judge backend and the
install-time template rendering flow.

## Judge Backend

The `Stop` hook sends the current turn closeout to a small judge model and
decides whether to:

- end normally
- auto-continue in the same turn without asking the user
- ask one `request_user_input` follow-up question

The judge decides the tri-state outcome. When it returns `mode="ask_user"`,
Codex generates the actual follow-up question and options from the live session
context in the same turn.

Defaults:

- endpoint: `http://127.0.0.1:10531/v1/responses`
- model: `gpt-5.4`
- reasoning effort: `medium`
- timeout: `30` seconds

Implementation:

- `src/codex_next_step_hooks/hooks/stop_require_request_user_input.py`

The judge backend must:

- provide an OpenAI-compatible `responses` endpoint
- support JSON structured output
- respond within the hook timeout window
- return `mode`, `continue_instruction`, and a short `rationale`

## Environment Variables

### `CODEX_RUI_JUDGE_URL`

- meaning: endpoint called by the stop hook
- default: `http://127.0.0.1:10531/v1/responses`
- use when: your local proxy port or gateway address differs

```bash
export CODEX_RUI_JUDGE_URL=http://127.0.0.1:10531/v1/responses
```

### `CODEX_RUI_JUDGE_MODEL`

- meaning: model slug used for follow-up judgment
- default: `gpt-5.4`
- use when: you want to tune cost, latency, or decision behavior

```bash
export CODEX_RUI_JUDGE_MODEL=gpt-5.4
```

### `CODEX_RUI_JUDGE_REASONING_EFFORT`

- meaning: reasoning effort passed to the judge model
- default: `medium`
- use when: you want the judge to trade off speed and depth differently

```bash
export CODEX_RUI_JUDGE_REASONING_EFFORT=medium
```

### `CODEX_RUI_JUDGE_TIMEOUT_SECONDS`

- meaning: time to wait for the judge response
- default: `30`
- use when: the endpoint is slower or the timeout is too aggressive

```bash
export CODEX_RUI_JUDGE_TIMEOUT_SECONDS=30
```

## Install-Time Rendering

The template file `src/codex_next_step_hooks/templates/hooks.json`
contains `{{python}}` and `{{repo_root}}` placeholders.

The installer renders the template and then merges the resulting commands into
the user's `hooks.json`.

- `{{python}}`: Python interpreter path used at `install` time
- `{{repo_root}}`: repo root path where the package is installed

The template stays generic; only rendered commands are written into user
config.

## Current Non-Goals

This package does not currently cover:

- background service installation
- platform-specific deployment guides
- hosted judge infrastructure provisioning

## Recommended Verification

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --live-judge --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli self-test --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --dry-run --json
```

`doctor --live-judge` performs a structured probe using the same endpoint and
model configuration as the real hook.

The live probe and transcript debug event both surface the judge's short
`rationale` when the endpoint provides it.

When the judge endpoint is unavailable or returns malformed structured output,
the transcript debug event records `status="judge_unavailable"` together with a
best-effort `judge_failure_reason`, and `doctor --live-judge` reports the same
reason string in its `error` field.

At runtime, the hook may override a raw `mode="end"` if the assistant message
itself clearly surfaces either:

- multiple materially different follow-up options, which promotes the turn to
  `ask_user`
- one clear next step, which promotes the turn to `auto_continue`

When this happens, the transcript debug event keeps the original `raw_judgment`
and records `judgment_override` metadata for comparison.

- endpoint unreachable or structured output failure: `fail`
- endpoint reachable but no follow-up action recommendation for the sample closeout: `warn`
- endpoint reachable and a structured follow-up action recommendation returned as expected: `pass`
