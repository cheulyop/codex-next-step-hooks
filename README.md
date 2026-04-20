# codex-next-step-hooks

**English** | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

Translations may lag behind the English version.

Codex hooks that help a turn end the right way: finish normally, continue
automatically, or ask one clear follow-up question.

The canonical package name is `codex-next-step-hooks`, and the canonical Python
module path is `codex_next_step_hooks`. The older
`codex-click-chooser-hooks` / `codex_click_chooser_hooks` name is still kept as
a compatibility alias during the rename window.

## What It Does

This package installs two Codex hooks:

- a `SessionStart` hook that loads the basic "keep going vs ask once" policy
  when a Codex session starts or resumes
- a `Stop` hook that decides whether a closeout should end normally, auto-continue in the same turn, or show a short follow-up chooser

The judge model picks the `end` / `auto_continue` / `ask_user` mode by looking
at the recent conversation context. When `ask_user` is needed, Codex generates
the actual chooser question and options from the live session context.

The hook entries from this package are merged additively into
`~/.codex/hooks.json`, and `uninstall` removes only the entries added by this
package.

## How It Works

1. `SessionStart` loads a short startup policy when a session starts or resumes.
   - if there is one clear next step, prefer same-turn follow-through
   - ask only when the user truly needs to choose
2. `Stop` runs when a turn is about to end.
3. The `Stop` hook bundles recent conversation flow, recent chooser history,
   and the assistant message that is about to end, then sends that summary to
   the judge model.
4. The judge returns one of three structured modes:
   - `end`: let the assistant finish normally
   - `auto_continue`: keep going in the same turn without asking the user
   - `ask_user`: stop and let Codex ask one real follow-up chooser
5. The main Codex session carries out that result:
   - `end`: the turn closes normally
   - `auto_continue`: Codex receives a continue instruction and keeps moving
   - `ask_user`: Codex generates the actual `request_user_input` question and
     options from the live session context
6. The hook appends a `stop_hook_judgment` debug event to the transcript so
   you can inspect what happened later with `observe`.

The judge only returns the mode, a short rationale, and an optional
`continue_instruction`. It does not generate the chooser itself.

For example:

- if the assistant ends with `Confirmed. The path is correct.`, the turn
  usually just ends
- if the assistant ends with `The patch is in, and the next step is to run
  self-test.`, Codex usually keeps going in the same turn
- if the assistant ends with `We can either tighten the prompt or inspect more
  real transcripts.`, Codex usually shows one chooser

## Judge Endpoint

This package does not provide a judge endpoint by itself. You need to connect
an OpenAI-compatible `responses` backend first.

In practice, you usually set:

- `CODEX_RUI_JUDGE_URL`
- `CODEX_RUI_JUDGE_MODEL`
- `CODEX_RUI_JUDGE_REASONING_EFFORT`
- `CODEX_RUI_JUDGE_TIMEOUT_SECONDS`

The judge side requires:

- an OpenAI-compatible `responses` endpoint
- structured JSON output that matches the hook schema
- a response that arrives within the hook timeout window
- support for returning `mode`, `continue_instruction`, and `rationale`

The current code-level fallback values are:

- endpoint: `http://127.0.0.1:10531/v1/responses` when `CODEX_RUI_JUDGE_URL` is
  unset
- model: `gpt-5.4`
- reasoning effort: `medium`
- timeout: `30` seconds

That endpoint is mostly useful as a local-development fallback. New users
should usually point the hook at their own judge backend explicitly.

For the full runtime contract, see [docs/runtime-contract.md](docs/runtime-contract.md).

## What The Judge Looks At

The stop hook does not send the raw transcript wholesale. It sends a compact
summary of the current lane of work.

The judge mainly looks at:

- the last few turns of conversation
- the most recent chooser questions and what the user selected
- how much work the assistant already did in the current turn
- the final assistant message that is about to end

For example, the summary might effectively say:

```text
Recent flow:
- user: Please simplify the README explanation
- assistant: I updated the README and finished verification
- recent chooser: "What should we do next?" -> "Verify, then commit"
- final assistant message: "Verification is done, so the next step is to commit."
```

In a case like that, the judge will often lean toward `auto_continue`. If the
final assistant message instead opens two materially different next directions,
it will often lean toward `ask_user`.

## What The Judge Returns

The judge responds with structured JSON matching this schema:

```json
{
  "mode": "end | auto_continue | ask_user",
  "continue_instruction": "string",
  "rationale": "string"
}
```

Expected behavior by mode:

- `end`: `continue_instruction` is usually empty
- `auto_continue`: `continue_instruction` must be non-empty
- `ask_user`: `continue_instruction` may be empty because Codex will generate
  the chooser itself

Example outputs:

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

## What The User Experiences

At the UI level, the behavior feels like this:

- if the turn is truly done, Codex just ends normally
- if one next action is obvious, Codex keeps going without making you click
- if a real decision is needed, Codex shows one chooser and continues in the
  same turn after you select it

Typical examples:

- Tiny factual confirmation:
  - user asks: `Does the hook template still point at the packaged script?`
  - assistant ends with: `Confirmed. The hook template still points at the packaged stop-hook script.`
  - expected mode: `end`
- Clear follow-through:
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
- Real branch choice:
  - assistant ends with: `We can either inspect more mode_end cases or tighten the prompt wording.`
  - expected mode: `ask_user`
  - Codex then writes the actual chooser in the same turn

## Stop-Hook Branch Handling

After the judge returns, the stop hook turns that result into one of two block
instructions or lets the turn end:

- `build_auto_continue_block_reason(...)` tells Codex not to ask another
  question and to continue immediately with the supplied instruction
- `build_ask_user_block_reason(...)` tells Codex to call
  `request_user_input` and generate the chooser from session context
- `end` does not produce a follow-up block reason; the turn simply closes

There is also one safety layer after the judge:

- if the raw judge response says `end`, but the assistant message itself
  clearly surfaces multiple follow-up choices, the hook can promote that to
  `ask_user`
- if the raw judge response says `end`, but the assistant message clearly names
  one next step, the hook can promote that to `auto_continue`

That safeguard is meant to catch obviously premature `end` decisions.

Here, "clearly" is not decided by another LLM call. The current implementation
uses lightweight message-pattern checks over the final assistant message.
Examples include phrases like:

- follow-up choice patterns: `we can either`, `options like`, `or we can`,
  `아니면`, `또는`
- next-step patterns: `the next step is to ...`, `the obvious next step is to ...`,
  `다음 단계는 ...`, `다음으로는 ...`

This is intentionally a narrow heuristic backstop. It is useful when the judge
returns an obviously premature `end`, but it is not a full semantic parser.

## Observability And Debugging

Every stop-hook decision appends a transcript debug event with fields such as:

- `status`
- `mode`
- `rationale`
- `continue_instruction`
- `judgment_override`
- `judge_failure_reason`
- `current_turn_context`

That data feeds the `observe` CLI, which is useful for calibration work:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --json
```

If the judge endpoint is unavailable or returns malformed structured output,
the hook records `status="judge_unavailable"` with a best-effort
`judge_failure_reason` and falls back to letting the turn end normally.

Because this hook is ultimately driven by an LLM judge, it will not match
every operator's expectation out of the box. This repo intentionally makes the
behavior easy to inspect and customize:

- `observe` lets you review real transcript-level judgments
- transcript debug events preserve rationale, mode, override, and turn-shape
  data
- the judge prompt is local code in
  `src/codex_next_step_hooks/hooks/stop_require_request_user_input.py`
- the post-judge override heuristics are also local and editable

The intended workflow is: inspect real outcomes, adjust the prompt or
heuristics, then rerun `self-test`, `doctor`, and `observe`.

## What It Includes

- packaged `Stop` and `SessionStart` hook scripts
- additive `install` and `uninstall` commands for `hooks.json`
- `doctor` checks for local package health
- `doctor --live-judge` for a real structured probe against the configured judge endpoint
- a deterministic self-test runner for follow-up decision regressions
- an `observe` CLI for transcript-level judge calibration and mode/rationale inspection
- a `print-layout` CLI for a quick repository layout snapshot
- a runtime contract for endpoint and environment configuration
- transcript debug events that record the judge mode and short rationale
- a thin legacy shim under `src/codex_click_chooser_hooks/` so already-running
  sessions and older import paths do not break immediately after the rename

## Current Capabilities

- context-aware `end` / `auto_continue` / `ask_user` logic for Codex `Stop` hooks
- an `end` override guard when the assistant message itself surfaces a follow-up choice or a clear next step
- startup policy loading through a paired `SessionStart` hook
- template rendering for interpreter and repo-root aware hook commands
- synthetic regression coverage for ask-user, auto-continue, and end behavior
- install-time and runtime verification commands for local environments
- transcript-based observability for mode mix, overrides, and rationale patterns
- an ordered `turn.entries` source-of-truth with derived judge-facing views

## Layout

```text
codex-next-step-hooks/
├─ README.md
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
│  └─ codex_click_chooser_hooks/
│     └─ ... thin compatibility shim during the rename
└─ tests/
   ├─ *.json
   └─ fixtures/
      └─ *.jsonl
```

## Quick Start

```bash
cd /path/to/codex-next-step-hooks
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --dry-run --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --live-judge --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli self-test --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --json
PYTHONPATH=src python3 -m codex_next_step_hooks.cli print-layout --json
```

## Install

Preview the changes first:

```bash
cd /path/to/codex-next-step-hooks
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --dry-run --json
```

Apply the install:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --json
```

If you renamed from an older checkout or still see an error that mentions
`src/codex_click_chooser_hooks/...`, rerun `install` once. New installs rewrite
`~/.codex/hooks.json` to point at `src/codex_next_step_hooks/...`.

Override the Python interpreter or Codex home if needed:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli install --python /path/to/python --codex-home /path/to/.codex --json
```

What `install` does:

- renders the hook template with the current Python interpreter path
- injects the current repo root into the hook commands added by this package
- merges the hook entries from this package into `~/.codex/hooks.json`
- creates a backup before writing if the file changes
- rewrites older managed entries from the pre-rename package to the new script
  paths

## Verify

Run the static checks:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --json
```

Run the live judge probe:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli doctor --live-judge --json
```

Run the deterministic regression suite:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli self-test --json
```

Inspect recent stop-hook judgments for this repo:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --json
```

By default, `observe` scopes to the current working directory. Use
`--all-cwds` to scan every cwd instead.

Focus on one historical session:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --session-id 019da87f-2a7f-7870-a5aa-84a28745e9db --json
```

Scan all current and archived Codex sessions:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --all-cwds --include-archived --json
```

Filter calibration output to a date window:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --all-cwds --date-from 2026-04-20 --date-to 2026-04-20 --json
```

Filter to one mode or change the example count:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli observe --mode ask_user --limit 3 --json
```

## Rename Compatibility

- new installs and docs use `codex-next-step-hooks` and
  `codex_next_step_hooks`
- the legacy console-script name `codex-click-chooser-hooks` still points at
  the same CLI entrypoint
- the repo also ships thin files under `src/codex_click_chooser_hooks/hooks/`
  so older live sessions that still invoke the old hook paths do not fail with
  `No such file or directory`
- `uninstall` recognizes both the old and new managed hook markers

## Uninstall

Preview the removal:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli uninstall --dry-run --json
```

Remove the hook entries added by this package:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli uninstall --json
```

Target a different Codex home if needed:

```bash
PYTHONPATH=src python3 -m codex_next_step_hooks.cli uninstall --codex-home /path/to/.codex --json
```

`uninstall` removes only the hook entries added by this package and
leaves unrelated hook configuration intact, including during the rename window
from the older package name.

## CLI Commands

- `install`: render the hook template and merge the hook entries from this package into `hooks.json`
- `uninstall`: remove only the hook entries from this package while leaving unrelated hook config intact
- `doctor`: run static package and file checks
- `doctor --live-judge`: probe the configured judge endpoint with a structured request
- `self-test`: run the deterministic synthetic regression suite
  - supports `--case /path/to/test.json` for a single case
- `observe`: summarize recorded `stop_hook_judgment` events for calibration work
  - supports repo-scoped or all-cwd scans, archived session inclusion, and date filtering
  - supports `--session-id`, `--mode`, and `--limit` for narrower inspection
- `print-layout`: print the repo's key paths as JSON or a plain dict

The canonical CLI examples in this README use `codex_next_step_hooks`, but the
legacy console-script name `codex-click-chooser-hooks` is still available for
compatibility.

## Runtime Configuration

- judge backend and env vars: `docs/runtime-contract.md`

## Installed Hook Entries

The package template adds one handler under each of these events:

- `SessionStart` with matcher `startup|resume`
- `Stop`

The commands point at:

- `src/codex_next_step_hooks/hooks/session_start_request_user_input_policy.py`
- `src/codex_next_step_hooks/hooks/stop_require_request_user_input.py`

For compatibility, thin wrapper files also exist under
`src/codex_click_chooser_hooks/hooks/`, but new installs should point at the
`codex_next_step_hooks` paths above.

## Future Improvements

- harden uninstall coverage for repo moves and renamed interpreters
- expand installer safety checks around existing user config edge cases
- deepen `doctor --live-judge` with richer failure hints if needed
- add more release-ready examples and regression cases
