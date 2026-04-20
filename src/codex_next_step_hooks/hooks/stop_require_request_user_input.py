#!/usr/bin/env python3

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

JUDGE_URL = os.environ.get("CODEX_RUI_JUDGE_URL", "http://127.0.0.1:10531/v1/responses")
JUDGE_MODEL = os.environ.get("CODEX_RUI_JUDGE_MODEL", "gpt-5.4")
JUDGE_REASONING_EFFORT = os.environ.get("CODEX_RUI_JUDGE_REASONING_EFFORT", "medium")
JUDGE_TIMEOUT_SECONDS = float(os.environ.get("CODEX_RUI_JUDGE_TIMEOUT_SECONDS", "30"))
STOP_SELECTION_TERMS = (
    "종료",
    "마무리",
    "finish",
    "stop",
    "enough",
    "그만",
    "충분",
    "괜찮",
)
RECENT_TURNS_LIMIT = 6
RECENT_QUESTIONS_LIMIT = 6
CURRENT_TURN_MESSAGES_LIMIT = 3
CURRENT_TURN_TIMELINE_LIMIT = 12
MAX_CONTEXT_TEXT_CHARS = 240
FOLLOW_UP_CHOICE_PATTERNS = (
    re.compile(r"\boptions like\b", re.IGNORECASE),
    re.compile(r"\bwe can either\b", re.IGNORECASE),
    re.compile(r"\beither\b[\s\S]{0,200}\bor\b", re.IGNORECASE),
    re.compile(r"\bor we can\b", re.IGNORECASE),
    re.compile(r"\b(two|multiple|several)\s+(obvious|natural|materially different)\s+next steps\b", re.IGNORECASE),
    re.compile(r"\bone of (two|several|multiple)\b", re.IGNORECASE),
    re.compile(r"(아니면|또는)"),
)
NEXT_STEP_PATTERNS = (
    re.compile(r"\bthe obvious next step is to (?P<step>[^.?!\n]+)", re.IGNORECASE),
    re.compile(r"\bthe next step is to (?P<step>[^.?!\n]+)", re.IGNORECASE),
    re.compile(r"\bnext we should (?P<step>[^.?!\n]+)", re.IGNORECASE),
    re.compile(r"\bnext we can (?P<step>[^.?!\n]+)", re.IGNORECASE),
    re.compile(r"다음 단계는 (?P<step>[^.\n]+)"),
    re.compile(r"다음으로는 (?P<step>[^.\n]+)"),
)

SYSTEM_PROMPT = """You are a Codex stop-hook judge.

Decide among exactly three modes:

- `mode="end"`: let the assistant end normally.
- `mode="auto_continue"`: stop the closeout and tell Codex to continue in the
  same turn without asking the user.
- `mode="ask_user"`: stop the closeout because user input is genuinely needed.
  Codex will generate the actual `request_user_input` question and options in
  the same turn.

Your main goal is useful progress with minimal friction. Do NOT ask the user
just because an extra follow-up question would be convenient.

Prefer `mode="auto_continue"` when there is one clearly dominant next action
that is already implied by the user's direction and does not depend on an
unresolved preference choice. This often applies when the next step is simply
to make the answer concrete, implement the obvious follow-through, inspect one
clearly indicated file, run the natural next check, or continue down the lane
the user already chose.

Prefer `mode="ask_user"` only when the user needs to make a real decision:
multiple plausible branches would materially change the outcome, there is a
tradeoff between next steps, or approval or permission is still genuinely
unresolved.

Prefer `mode="end"` only when the assistant message is already a sufficient
ending and does not itself surface a meaningful next-step lane. A narrow
factual confirmation or tiny verification may end normally only when it does
not offer, imply, or tee up a natural follow-up action or user choice.
`mode="end"` is the strictest option. Do not choose it just because the answer
is complete, explanatory, well-supported, or persuasive.

If the assistant just resolved a blocker, explained a root cause, proposed a
patch, summarized the current state, or finished a verification pass, assume
there is often still a live follow-through lane. In those cases, prefer:
- `mode="auto_continue"` when one concrete next action is the natural
  continuation of the same lane.
- `mode="ask_user"` when there are two or more concrete next lanes and the user
  should pick among them.

Choose `mode="end"` only when the work is actually done for now, or when any
reasonable follow-up would be speculative, redundant, or clearly outside the
current lane.

If the assistant message explicitly surfaces next steps, follow-up options, or
a "we can continue with..." style invitation, do not choose `mode="end"` for
that reason alone.
- Prefer `mode="auto_continue"` if one next step is clearly dominant.
- Prefer `mode="ask_user"` if two or more materially different next steps are
  surfaced.

Do not treat explanatory completeness by itself as a reason to ask the user. A
well-explained answer may still call for `auto_continue` if the next step is
obvious, or `end` if the task is simply done.

When deciding between `mode="end"` and a continuation mode, ask yourself:
"Would a useful collaborator naturally keep moving here?" If yes, do not pick
`mode="end"`.

Use the recent session context, not just the last assistant message. Pay
special attention to recent `request_user_input` questions, the options that
were already shown, and the user's selections or free-form answers.

Use the shape of the current turn. The prompt may include multiple user and
assistant messages from the same turn, including assistant sub-answers that
already happened after the latest user message.

If the latest user instruction is broad, such as "go ahead", "continue", or a
general implementation request, and the assistant has already produced one or
more substantive sub-answers after that message, do not let that older broad
instruction alone force another `mode="auto_continue"`. In that situation,
prefer `mode="auto_continue"` only when the latest assistant message still
leaves one clearly dominant follow-through inside the same lane. If the old
intent has already been substantially consumed and the next move is now a real
choice, prefer `mode="ask_user"`. If the lane is genuinely complete, prefer
`mode="end"`.

If the same or substantially similar follow-up question was already shown recently and the
conversation did not materially advance to a new state, prefer
`mode="end"` or `mode="auto_continue"` instead of repeating that question. Avoid
re-asking it within the same continued turn after the user already answered it.

If the user answered a follow-up question with a free-form instruction, complaint, or
course correction, treat that as real intent to act on rather than as a reason
to ask the same question again.

If the user already selected a high-level lane recently, do not offer that same
lane again. Move one level deeper and propose the next concrete actions within
that lane if `mode="ask_user"` is still necessary. Otherwise prefer
`mode="auto_continue"` and keep moving.

When using `mode="ask_user"`, you are only deciding that user input is needed.
Do not try to author the follow-up question itself. Codex will generate the
actual question and options from the recent session context.

When using `mode="auto_continue"`, provide a concise `continue_instruction`
that tells Codex what to do next in the same turn. Do not ask the user in that
mode.

Always provide a concise `rationale` that explains why the selected mode fits
the current turn. Keep it short, concrete, and grounded in the recent session
context.

Return JSON only. For `mode="auto_continue"`, provide a non-empty
`continue_instruction`. For `mode="end"` and `mode="ask_user"`,
`continue_instruction` may be empty. `rationale` must always be non-empty.

Write the header, question, labels, and descriptions in the same language as
the assistant final message unless there is a very strong reason not to.
"""

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {
            "type": "string",
            "enum": ["end", "auto_continue", "ask_user"],
        },
        "continue_instruction": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["mode", "continue_instruction", "rationale"],
}


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value


def extract_input_text(content: Any) -> Optional[str]:
    if not isinstance(content, list):
        return None
    texts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    if not texts:
        return None
    return "\n".join(texts)


def normalize_compare_text(text: Optional[str]) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def compact_render_text(text: Optional[str], max_chars: int = MAX_CONTEXT_TEXT_CHARS) -> str:
    if not isinstance(text, str):
        return ""
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def summarize_error_text(text: Optional[str], max_chars: int = 160) -> str:
    if not isinstance(text, str):
        return ""
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def describe_judge_failure(exc: Exception) -> str:
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, BaseException):
            detail = f"{type(reason).__name__}: {reason}"
        elif reason:
            detail = str(reason)
        else:
            detail = str(exc)
        return f"{type(exc).__name__}: {detail}"
    detail = str(exc).strip()
    if detail:
        return f"{type(exc).__name__}: {detail}"
    return type(exc).__name__


def is_runtime_control_message(text: Optional[str]) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.lstrip()
    return stripped.startswith("<turn_aborted>") or stripped.startswith("<hook_prompt")


def append_turn_message(turn: Dict[str, Any], role: str, text: str) -> None:
    stripped = text.strip()
    if not stripped:
        return

    entries = turn.setdefault("entries", [])
    if entries:
        previous = entries[-1]
        if (
            previous.get("kind") == "message"
            and previous.get("role") == role
            and normalize_compare_text(previous.get("text")) == normalize_compare_text(stripped)
        ):
            return

    entries.append({"kind": "message", "role": role, "text": stripped})


def request_entries_from_turn(turn: Dict[str, Any]) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    by_call_id: Dict[str, Dict[str, Any]] = {}
    for entry in turn.get("entries", []):
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind == "request_user_input":
            question_request = {
                "call_id": entry.get("call_id"),
                "turn_id": entry.get("turn_id"),
                "header": entry.get("header"),
                "question": entry.get("question"),
                "options": normalize_options(entry.get("options")),
                "answers": [],
            }
            collected.append(question_request)
            call_id = question_request.get("call_id")
            if isinstance(call_id, str):
                by_call_id[call_id] = question_request
            continue
        if kind != "request_user_input_output":
            continue
        call_id = entry.get("call_id")
        if not isinstance(call_id, str):
            continue
        previous = by_call_id.get(call_id)
        if previous is None:
            continue
        answers = normalize_answer_list(entry.get("answers"))
        if answers:
            previous["answers"].extend(answers)
    return collected


def timeline_entries_from_turn(turn: Dict[str, Any]) -> List[Dict[str, str]]:
    timeline: List[Dict[str, str]] = []
    for entry in turn.get("entries", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") != "message":
            continue
        role = entry.get("role")
        text = entry.get("text")
        if role in {"user", "assistant"} and isinstance(text, str) and text.strip():
            timeline.append({"role": role, "text": text.strip()})
    return timeline


def recent_messages_by_role(
    timeline: List[Dict[str, str]], role: str, limit: int
) -> List[str]:
    collected = [
        item["text"]
        for item in timeline
        if item.get("role") == role and isinstance(item.get("text"), str) and item["text"].strip()
    ]
    return collected[-limit:]


def last_user_message_for_turn(turn: Dict[str, Any]) -> str:
    timeline = timeline_entries_from_turn(turn)
    for item in range(len(timeline) - 1, -1, -1):
        candidate = timeline[item]
        if candidate.get("role") == "user":
            return candidate.get("text", "")
    return ""


def summarize_current_turn(turn: Dict[str, Any]) -> Dict[str, Any]:
    timeline = timeline_entries_from_turn(turn)
    user_messages = recent_messages_by_role(
        timeline, "user", CURRENT_TURN_MESSAGES_LIMIT
    )
    assistant_messages = recent_messages_by_role(
        timeline, "assistant", CURRENT_TURN_MESSAGES_LIMIT
    )
    assistant_messages_since_last_user: List[str] = []
    recent_timeline: List[Dict[str, str]] = []

    last_user_index: Optional[int] = None
    for index in range(len(timeline) - 1, -1, -1):
        item = timeline[index]
        if item.get("role") == "user":
            last_user_index = index
            break

    for item in timeline[-CURRENT_TURN_TIMELINE_LIMIT:]:
        role = item.get("role")
        text = item.get("text")
        if role in {"user", "assistant"} and isinstance(text, str) and text.strip():
            recent_timeline.append({"role": role, "text": text.strip()})

    timeline_since_last_user: List[Dict[str, str]] = []
    start_index = (
        last_user_index
        if last_user_index is not None
        else max(0, len(timeline) - CURRENT_TURN_TIMELINE_LIMIT)
    )
    for item in timeline[start_index:]:
        role = item.get("role")
        text = item.get("text")
        if role in {"user", "assistant"} and isinstance(text, str) and text.strip():
            timeline_since_last_user.append({"role": role, "text": text.strip()})

    if last_user_index is not None:
        for item in timeline[last_user_index + 1 :]:
            if item.get("role") == "assistant":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    assistant_messages_since_last_user.append(text.strip())

    return {
        "turn_id": turn.get("turn_id"),
        "user_message_count": len([item for item in timeline if item.get("role") == "user"]),
        "assistant_message_count": len(
            [item for item in timeline if item.get("role") == "assistant"]
        ),
        "request_count": len(request_entries_from_turn(turn)),
        "recent_user_messages": user_messages,
        "recent_assistant_messages": assistant_messages,
        "assistant_messages_since_last_user": len(assistant_messages_since_last_user),
        "assistant_messages_since_last_user_texts": assistant_messages_since_last_user[
            -CURRENT_TURN_MESSAGES_LIMIT:
        ],
        "recent_timeline": recent_timeline,
        "timeline_since_last_user": timeline_since_last_user,
    }


def prior_assistant_messages_before_final(
    current_turn_context: Dict[str, Any], last_assistant_message: str
) -> List[str]:
    messages = []
    for item in current_turn_context.get("assistant_messages_since_last_user_texts", []):
        if isinstance(item, str) and item.strip():
            messages.append(item.strip())

    if not messages:
        for item in current_turn_context.get("recent_assistant_messages", []):
            if isinstance(item, str) and item.strip():
                messages.append(item.strip())

    normalized_final = normalize_compare_text(last_assistant_message)
    if messages and normalized_final:
        for index in range(len(messages) - 1, -1, -1):
            if normalize_compare_text(messages[index]) == normalized_final:
                del messages[index]
                break

    return messages[-CURRENT_TURN_MESSAGES_LIMIT:]


def summarize_timeline_entries(
    entries: Any, max_chars: int = MAX_CONTEXT_TEXT_CHARS
) -> List[Dict[str, str]]:
    summarized: List[Dict[str, str]] = []
    if not isinstance(entries, list):
        return summarized
    for item in entries:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        text = compact_render_text(item.get("text"), max_chars)
        if role in {"user", "assistant"} and text:
            summarized.append({"role": role, "text": text})
    return summarized


def read_recent_session_context(
    transcript_path: str, turn_id: str
) -> Dict[str, Any]:
    path = Path(transcript_path)
    if not path.exists():
        return {
            "recent_turns": [],
            "recent_questions": [],
            "current_turn_requests": [],
            "current_turn_context": {},
        }

    turns: List[Dict[str, Any]] = []
    turn_by_id: Dict[str, Dict[str, Any]] = {}
    pending_request_call_ids: set[str] = set()
    current_turn: Optional[Dict[str, Any]] = None

    def ensure_turn(current_turn_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not isinstance(current_turn_id, str) or not current_turn_id:
            return None
        existing = turn_by_id.get(current_turn_id)
        if existing is not None:
            return existing
        created = {
            "turn_id": current_turn_id,
            "entries": [],
        }
        turns.append(created)
        turn_by_id[current_turn_id] = created
        return created

    with path.open() as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            if item.get("type") == "turn_context":
                current_turn = ensure_turn(item.get("payload", {}).get("turn_id"))
                continue

            if current_turn is None:
                continue

            item_type = item.get("type")
            payload = item.get("payload", {})

            if item_type == "event_msg" and payload.get("type") == "user_message":
                message = payload.get("message")
                if (
                    isinstance(message, str)
                    and message.strip()
                    and not is_runtime_control_message(message)
                ):
                    append_turn_message(current_turn, "user", message)
                continue

            if item_type != "response_item":
                continue

            if payload.get("type") == "message":
                role = payload.get("role")
                text = extract_input_text(payload.get("content"))
                if text:
                    if role == "user":
                        if not is_runtime_control_message(text):
                            append_turn_message(current_turn, "user", text)
                    elif role == "assistant":
                        append_turn_message(current_turn, "assistant", text)
                continue

            if (
                payload.get("type") == "function_call"
                and payload.get("name") == "request_user_input"
            ):
                call_id = payload.get("call_id")
                if not isinstance(call_id, str):
                    continue
                parsed = parse_request_user_input_question(payload.get("arguments", ""))
                if parsed is None:
                    continue
                request_entry = {
                    "kind": "request_user_input",
                    "call_id": call_id,
                    "turn_id": current_turn["turn_id"],
                    "header": parsed.get("header"),
                    "question": parsed.get("question"),
                    "options": parsed.get("options"),
                }
                current_turn.setdefault("entries", []).append(request_entry)
                pending_request_call_ids.add(call_id)
                continue

            if payload.get("type") == "function_call_output":
                call_id = payload.get("call_id")
                if not isinstance(call_id, str):
                    continue
                if call_id not in pending_request_call_ids:
                    continue
                current_turn.setdefault("entries", []).append(
                    {
                        "kind": "request_user_input_output",
                        "call_id": call_id,
                        "turn_id": current_turn["turn_id"],
                        "answers": extract_request_user_input_answers(payload.get("output", "")),
                    }
                )

    target_index = -1
    for index, turn in enumerate(turns):
        if turn.get("turn_id") == turn_id:
            target_index = index
            break
    if target_index == -1:
        return {
            "recent_turns": [],
            "recent_questions": [],
            "current_turn_requests": [],
            "current_turn_context": {},
        }

    recent_turns = turns[max(0, target_index - RECENT_TURNS_LIMIT + 1) : target_index + 1]
    recent_questions: List[Dict[str, Any]] = []
    for turn in recent_turns:
        for request in request_entries_from_turn(turn):
            recent_questions.append(request)
    recent_questions = recent_questions[-RECENT_QUESTIONS_LIMIT:]

    current_turn_requests: List[Dict[str, Any]] = []
    current_turn_context: Dict[str, Any] = {}
    if recent_turns:
        current_turn_summary = recent_turns[-1]
        current_turn_requests = list(request_entries_from_turn(current_turn_summary))
        current_turn_context = summarize_current_turn(current_turn_summary)

    return {
        "recent_turns": recent_turns,
        "recent_questions": recent_questions,
        "current_turn_requests": current_turn_requests,
        "current_turn_context": current_turn_context,
    }


def parse_request_user_input_question(arguments: str) -> Optional[Dict[str, Any]]:
    payload = parse_json_object(arguments)
    if not isinstance(payload, dict):
        return None
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return None
    question = questions[0]
    if not isinstance(question, dict):
        return None
    return {
        "header": question.get("header"),
        "question": question.get("question"),
        "options": normalize_options(question.get("options")),
    }


def extract_request_user_input_answers_from_value(answers_block: Any) -> List[str]:
    if not isinstance(answers_block, dict):
        return []
    collected: List[str] = []
    for value in answers_block.values():
        if not isinstance(value, dict):
            continue
        answers = value.get("answers")
        if not isinstance(answers, list):
            continue
        for answer in answers:
            if isinstance(answer, str) and answer.strip():
                collected.append(answer.strip())
    return collected


def normalize_answer_list(raw_answers: Any) -> List[str]:
    if not isinstance(raw_answers, list):
        return []
    collected: List[str] = []
    for answer in raw_answers:
        if isinstance(answer, str) and answer.strip():
            collected.append(answer.strip())
    return collected


def extract_request_user_input_answers(output: str) -> List[str]:
    payload = parse_json_object(output)
    if not isinstance(payload, dict):
        return []
    return extract_request_user_input_answers_from_value(payload.get("answers"))


def question_option_labels(question_request: Dict[str, Any]) -> List[str]:
    return [
        compact_render_text(option.get("label"), 80)
        for option in normalize_options(question_request.get("options"))
        if compact_render_text(option.get("label"), 80)
    ]


def latest_answer_is_explicit_stop(history: List[Dict[str, Any]]) -> bool:
    if not history:
        return False
    latest_answers = history[-1].get("answers")
    if not isinstance(latest_answers, list):
        return False
    for answer in latest_answers:
        normalized = normalize_compare_text(answer)
        if any(term in normalized for term in STOP_SELECTION_TERMS):
            return True
    return False


def judge_should_request(
    last_assistant_message: str,
    recent_turns: List[Dict[str, Any]],
    recent_questions: List[Dict[str, Any]],
    current_turn_context: Dict[str, Any],
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    context_parts = ["Recent session context follows."]
    if recent_turns:
        context_parts.extend(["", "<recent_session_context>"])
        for turn in recent_turns:
            context_parts.append(f'<turn id="{turn.get("turn_id", "")}">')
            last_user_message = last_user_message_for_turn(turn)
            if last_user_message:
                rendered_last_user_message = compact_render_text(last_user_message, 240)
                context_parts.extend(
                    [
                        "<last_user_message>",
                        rendered_last_user_message,
                        "</last_user_message>",
                    ]
                )
            context_parts.append("</turn>")
        context_parts.append("</recent_session_context>")
    if current_turn_context:
        context_parts.extend(["", "<current_turn_state>"])
        context_parts.append(
            "- user_message_count: "
            f"{current_turn_context.get('user_message_count', 0)}"
        )
        context_parts.append(
            "- assistant_message_count: "
            f"{current_turn_context.get('assistant_message_count', 0)}"
        )
        context_parts.append(
            "- request_user_input_count: "
            f"{current_turn_context.get('request_count', 0)}"
        )
        context_parts.append(
            "- assistant_messages_since_last_user: "
            f"{current_turn_context.get('assistant_messages_since_last_user', 0)}"
        )
        context_parts.append("</current_turn_state>")

        timeline_since_last_user = summarize_timeline_entries(
            current_turn_context.get("timeline_since_last_user"),
            320,
        )
        if timeline_since_last_user:
            context_parts.extend(["", "<current_turn_timeline_since_last_user>"])
            for item in timeline_since_last_user:
                context_parts.append(f"- {item['role']}: {item['text']}")
            context_parts.append("</current_turn_timeline_since_last_user>")
    if recent_questions:
        context_parts.extend(["", "<recent_question_summary>"])
        for question_request in recent_questions[-3:]:
            question = compact_render_text(question_request.get("question"), 200)
            if question:
                context_parts.append(f"- question: {question}")
            option_labels = question_option_labels(question_request)
            if option_labels:
                context_parts.append(f"  options: {', '.join(option_labels)}")
            answers = [
                compact_render_text(answer, 120)
                for answer in question_request.get("answers", [])
                if compact_render_text(answer, 120)
            ]
            if answers:
                context_parts.append(f"  user_answer: {' | '.join(answers)}")
        context_parts.append("</recent_question_summary>")
    context_parts.extend(
        [
            "",
            "<assistant_final_message>",
            last_assistant_message,
            "</assistant_final_message>",
            "",
            "Decide whether the assistant should end, auto-continue in the same "
            "turn without asking the user, or ask the user one "
            "`request_user_input` follow-up question.",
        ]
    )

    body = {
        "model": JUDGE_MODEL,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "\n".join(context_parts),
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "request_user_input_decision",
                "schema": JUDGE_SCHEMA,
            }
        },
        "reasoning": {"effort": JUDGE_REASONING_EFFORT},
    }
    request = urllib.request.Request(
        JUDGE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=JUDGE_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return None, describe_judge_failure(exc)
    output_text = payload.get("output_text")
    if not isinstance(output_text, str):
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text")
                    if isinstance(text, str):
                        output_text = text
                        break
                if isinstance(output_text, str):
                    break
    if not isinstance(output_text, str):
        return None, "judge response missing output_text"
    judgment = parse_json_object(output_text)
    if not isinstance(judgment, dict):
        snippet = summarize_error_text(output_text)
        if snippet:
            return None, f"judge returned non-JSON-object output: {snippet}"
        return None, "judge returned non-JSON-object output"
    return judgment, None


def normalize_options(raw_options: Any) -> List[Dict[str, str]]:
    normalized = []
    if not isinstance(raw_options, list):
        return normalized
    for item in raw_options[:3]:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        description = item.get("description")
        if isinstance(label, str) and isinstance(description, str) and label.strip():
            normalized.append(
                {"label": label.strip(), "description": description.strip()}
            )
    return normalized


def normalize_mode(value: Any) -> str:
    if value in {"end", "auto_continue", "ask_user"}:
        return value
    return "end"


def normalize_continue_instruction(judgment: Dict[str, Any]) -> str:
    instruction = judgment.get("continue_instruction")
    if not isinstance(instruction, str):
        return ""
    return instruction.strip()


def normalize_rationale(judgment: Dict[str, Any]) -> str:
    rationale = judgment.get("rationale")
    if not isinstance(rationale, str):
        return ""
    return rationale.strip()


def ask_user_prompt_source() -> str:
    return "codex_session"


def ends_with_terminal_punctuation(text: str) -> bool:
    return text.endswith((".", "!", "?", "…"))


def assistant_message_surfaces_follow_up_choice(message: str) -> bool:
    return any(pattern.search(message) for pattern in FOLLOW_UP_CHOICE_PATTERNS)


def extract_surfaced_next_step(message: str) -> Optional[str]:
    for pattern in NEXT_STEP_PATTERNS:
        match = pattern.search(message)
        if match is None:
            continue
        step = match.group("step").strip()
        if step:
            return step
    return None


def apply_end_mode_overrides(
    message: str, judgment: Dict[str, Any]
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    if normalize_mode(judgment.get("mode")) != "end":
        return judgment, None

    if assistant_message_surfaces_follow_up_choice(message):
        overridden = dict(judgment)
        overridden["mode"] = "ask_user"
        overridden["continue_instruction"] = ""
        overridden["rationale"] = (
            "The assistant message itself surfaces multiple follow-up options, "
            "so ending here would prematurely close a natural next user choice."
        )
        return overridden, {
            "from_mode": "end",
            "to_mode": "ask_user",
            "reason": "assistant_message_surfaces_follow_up_choice",
        }

    surfaced_next_step = extract_surfaced_next_step(message)
    if surfaced_next_step:
        continue_instruction = (
            "Continue with the next step the assistant just surfaced: "
            f"{surfaced_next_step}"
        )
        if not ends_with_terminal_punctuation(continue_instruction):
            continue_instruction += "."
        overridden = dict(judgment)
        overridden["mode"] = "auto_continue"
        overridden["continue_instruction"] = continue_instruction
        overridden["rationale"] = (
            "The assistant message already names a clear next step, so ending "
            "here would interrupt an obvious same-turn follow-through."
        )
        return overridden, {
            "from_mode": "end",
            "to_mode": "auto_continue",
            "reason": "assistant_message_surfaces_clear_next_step",
            "surfaced_next_step": surfaced_next_step,
        }

    return judgment, None


def build_debug_current_turn_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    context = payload.get("_current_turn_context")
    if not isinstance(context, dict) or not context:
        return {}

    summary: Dict[str, Any] = {
        "user_message_count": context.get("user_message_count", 0),
        "assistant_message_count": context.get("assistant_message_count", 0),
        "request_count": context.get("request_count", 0),
        "assistant_messages_since_last_user": context.get(
            "assistant_messages_since_last_user", 0
        ),
    }

    recent_user_messages = [
        compact_render_text(message, 160)
        for message in context.get("recent_user_messages", [])
        if compact_render_text(message, 160)
    ]
    if recent_user_messages:
        summary["recent_user_messages"] = recent_user_messages

    last_assistant_message = payload.get("last_assistant_message")
    if isinstance(last_assistant_message, str) and last_assistant_message.strip():
        prior_assistant_messages = [
            compact_render_text(message, 160)
            for message in prior_assistant_messages_before_final(
                context, last_assistant_message
            )
            if compact_render_text(message, 160)
        ]
        if prior_assistant_messages:
            summary["prior_assistant_messages_before_final"] = (
                prior_assistant_messages
            )

    recent_timeline = summarize_timeline_entries(context.get("recent_timeline"), 160)
    if recent_timeline:
        summary["recent_timeline"] = recent_timeline

    timeline_since_last_user = summarize_timeline_entries(
        context.get("timeline_since_last_user"),
        160,
    )
    if timeline_since_last_user:
        summary["timeline_since_last_user"] = timeline_since_last_user

    return summary


def build_stop_hook_debug_payload(
    payload: Dict[str, Any],
    *,
    decision: str,
    status: str,
    judgment: Optional[Dict[str, Any]] = None,
    raw_judgment: Optional[Dict[str, Any]] = None,
    judgment_override: Optional[Dict[str, Any]] = None,
    judge_failure_reason: Optional[str] = None,
) -> Dict[str, Any]:
    debug_payload: Dict[str, Any] = {
        "type": "stop_hook_judgment",
        "hook_event": "Stop",
        "turn_id": payload.get("turn_id"),
        "decision": decision,
        "status": status,
        "judge_model": JUDGE_MODEL,
        "judge_reasoning_effort": JUDGE_REASONING_EFFORT,
        "judge_timeout_seconds": JUDGE_TIMEOUT_SECONDS,
    }
    if isinstance(judge_failure_reason, str) and judge_failure_reason.strip():
        debug_payload["judge_failure_reason"] = judge_failure_reason.strip()

    current_turn_context = build_debug_current_turn_context(payload)
    if current_turn_context:
        debug_payload["current_turn_context"] = current_turn_context

    if not isinstance(judgment, dict):
        return debug_payload

    mode = normalize_mode(judgment.get("mode"))
    debug_payload["mode"] = mode
    if isinstance(raw_judgment, dict):
        debug_payload["raw_judgment"] = raw_judgment
    else:
        debug_payload["raw_judgment"] = judgment

    continue_instruction = normalize_continue_instruction(judgment)
    if continue_instruction:
        debug_payload["continue_instruction"] = continue_instruction

    rationale = normalize_rationale(judgment)
    if rationale:
        debug_payload["rationale"] = rationale

    if mode == "ask_user":
        debug_payload["ask_user_prompt_source"] = ask_user_prompt_source()

    if isinstance(judgment_override, dict):
        debug_payload["judgment_override"] = judgment_override

    return debug_payload


def append_stop_hook_debug_event(payload: Dict[str, Any]) -> None:
    debug_payload = payload.get("_stop_hook_debug")
    transcript_path = payload.get("transcript_path")
    if not isinstance(debug_payload, dict):
        return
    if not isinstance(transcript_path, str) or not transcript_path:
        return

    path = Path(transcript_path)
    if not path.exists():
        return

    event = {
        "timestamp": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "type": "event_msg",
        "payload": debug_payload,
    }
    try:
        with path.open("a") as handle:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")
    except OSError:
        return


def render_recent_question_history(recent_questions: List[Dict[str, Any]]) -> str:
    if not recent_questions:
        return ""
    lines = ["Recent follow-up question history:"]
    for question_request in recent_questions[-3:]:
        question = compact_render_text(question_request.get("question"), 200)
        if question:
            lines.append(f"- Question: {question}")
        option_labels = question_option_labels(question_request)
        if option_labels:
            lines.append(f"  Options: {', '.join(option_labels)}")
        answers = [
            compact_render_text(answer, 120)
            for answer in question_request.get("answers", [])
            if compact_render_text(answer, 120)
        ]
        if answers:
            lines.append(f"  User answer: {' | '.join(answers)}")
    return "\n".join(lines)


def build_ask_user_block_reason(
    judgment: Dict[str, Any], recent_questions: List[Dict[str, Any]]
) -> str:
    del judgment
    recent_history_block = render_recent_question_history(recent_questions)
    anti_repeat_instruction = (
        "Do not ask the same or substantially similar follow-up question again if the recent "
        "history already offered it. Treat free-form answers as new user intent to "
        "act on, not as a cue to re-ask the same question."
    )
    parts = [
        "Use the `request_user_input` tool now. Do not send another prose or bullet-list "
        "answer.",
        "Generate the header, exactly one follow-up question, and the natural "
        "single-select options yourself from the recent session context and the "
        "assistant message that just ended, then wait for the user's selection.",
    ]
    if recent_history_block:
        parts.extend(["", recent_history_block])
    parts.extend(
        [
            "",
            anti_repeat_instruction,
            "",
            "The follow-up question should feel like a natural continuation of the "
            "just-finished answer, not a reset-style menu. Use options that materially move the work "
            "forward, and combine actions when that is the most natural single choice.",
            "",
            "After the user selects an option, immediately continue in the same turn by "
            "carrying out the selected next action. Treat the selected option as the "
            "user's new instruction. Do not stop right after the `request_user_input` tool "
            "output, and do not end with an empty or placeholder final "
            "answer. If the selected option asks for more detail, provide that detail "
            "immediately. If the selected option is to stop or finish here, end normally.",
        ]
    )
    return "\n".join(parts)


def build_auto_continue_block_reason(
    judgment: Dict[str, Any], recent_questions: List[Dict[str, Any]]
) -> str:
    instruction = normalize_continue_instruction(judgment)
    recent_history_block = render_recent_question_history(recent_questions)
    parts = [
        "Do not ask the user another follow-up question here.",
        "The next step is clear enough to continue in the same turn without "
        "waiting for user input.",
        "",
        "Continue immediately with this instruction:",
        instruction,
    ]
    if recent_history_block:
        parts.extend(["", recent_history_block])
    parts.extend(
        [
            "",
            "Treat the user's recent direction and recent answers as already "
            "settled intent. Do not re-ask the same branching question unless "
            "a genuinely new hidden risk or materially different outcome appears.",
            "",
            "Carry out the instruction now. Do not stop with a plan-only, "
            "placeholder, or empty answer. If completing the instruction fully "
            "finishes the task, reply with the concrete result. If a new "
            "decision point appears that materially changes the outcome, then "
            "ask the user at that point.",
        ]
    )
    return "\n".join(parts)


def build_block_reason(
    judgment: Dict[str, Any], recent_questions: List[Dict[str, Any]]
) -> str:
    mode = normalize_mode(judgment.get("mode"))
    if mode == "auto_continue":
        return build_auto_continue_block_reason(judgment, recent_questions)
    return build_ask_user_block_reason(judgment, recent_questions)


def should_continue(payload: Dict[str, Any]) -> bool:
    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="empty_last_assistant_message",
        )
        return True
    transcript_path = payload.get("transcript_path")
    turn_id = payload.get("turn_id")
    recent_turns: List[Dict[str, Any]] = []
    recent_questions: List[Dict[str, Any]] = []
    current_turn_requests: List[Dict[str, Any]] = []
    current_turn_context: Dict[str, Any] = {}
    if isinstance(transcript_path, str) and isinstance(turn_id, str):
        context = read_recent_session_context(transcript_path, turn_id)
        recent_turns = context.get("recent_turns", [])
        recent_questions = context.get("recent_questions", [])
        current_turn_requests = context.get("current_turn_requests", [])
        current_turn_context = context.get("current_turn_context", {})
    if current_turn_context:
        payload["_current_turn_context"] = current_turn_context
    if latest_answer_is_explicit_stop(current_turn_requests):
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="explicit_stop_already_selected",
        )
        return True
    raw_judgment, judge_failure_reason = judge_should_request(
        message,
        recent_turns,
        recent_questions,
        current_turn_context,
    )
    if raw_judgment is None:
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="judge_unavailable",
            judge_failure_reason=judge_failure_reason,
        )
        return True
    judgment, judgment_override = apply_end_mode_overrides(message, raw_judgment)
    mode = normalize_mode(judgment.get("mode"))
    if mode == "end":
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="mode_end",
            judgment=judgment,
            raw_judgment=raw_judgment,
            judgment_override=judgment_override,
        )
        return True
    if mode == "auto_continue" and not normalize_continue_instruction(judgment):
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="invalid_auto_continue_missing_instruction",
            judgment=judgment,
            raw_judgment=raw_judgment,
            judgment_override=judgment_override,
        )
        return True
    if mode != "ask_user" and mode != "auto_continue":
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="invalid_mode",
            judgment=judgment,
            raw_judgment=raw_judgment,
            judgment_override=judgment_override,
        )
        return True
    payload["_judgment"] = judgment
    payload["_recent_questions"] = recent_questions
    payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
        payload,
        decision="block",
        status=(
            "mode_ask_user_end_override"
            if mode == "ask_user" and judgment_override
            else "mode_auto_continue_end_override"
            if mode == "auto_continue" and judgment_override
            else "mode_ask_user"
            if mode == "ask_user"
            else "mode_auto_continue"
        ),
        judgment=judgment,
        raw_judgment=raw_judgment,
        judgment_override=judgment_override,
    )
    return False


def main() -> int:
    payload = json.load(sys.stdin)
    if should_continue(payload):
        append_stop_hook_debug_event(payload)
        print(json.dumps({"continue": True}))
        return 0

    append_stop_hook_debug_event(payload)
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": build_block_reason(
                    payload["_judgment"], payload.get("_recent_questions", [])
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
