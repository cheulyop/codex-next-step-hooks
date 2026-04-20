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
JUDGE_TIMEOUT_SECONDS = float(os.environ.get("CODEX_RUI_JUDGE_TIMEOUT_SECONDS", "8"))
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
RECENT_CHOOSERS_LIMIT = 6
MAX_CONTEXT_TEXT_CHARS = 240

SYSTEM_PROMPT = """You are a Codex stop-hook judge.

Decide among exactly three modes:

- `mode="end"`: let the assistant end normally.
- `mode="auto_continue"`: stop the closeout and tell Codex to continue in the
  same turn without asking the user.
- `mode="ask_user"`: stop the closeout because user input is genuinely needed.
  Codex will generate the actual `request_user_input` question and options in
  the same turn.

Your main goal is useful progress with minimal friction. Do NOT ask the user
just because a clickable chooser would be convenient.

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

Prefer `mode="end"` when the assistant message is already a sufficient ending:
the reply is a narrow factual confirmation, a tiny verification answer, a
completed result with no meaningful next step, or the task should stop here.

Do not treat explanatory completeness by itself as a reason to ask the user. A
well-explained answer may still call for `auto_continue` if the next step is
obvious, or `end` if the task is simply done.

Use the recent session context, not just the last assistant message. Pay
special attention to recent `request_user_input` questions, the options that
were already shown, and the user's selections or free-form answers.

If the same or substantially similar chooser was already shown recently and the
conversation did not materially advance to a new state, prefer
`mode="end"` or `mode="auto_continue"` instead of repeating the chooser. Avoid
re-asking it within the same continued turn after the user already answered it.

If the user answered a chooser with a free-form instruction, complaint, or
course correction, treat that as real intent to act on rather than as a reason
to ask the same chooser again.

If the user already selected a high-level lane recently, do not offer that same
lane again. Move one level deeper and propose the next concrete actions within
that lane if `mode="ask_user"` is still necessary. Otherwise prefer
`mode="auto_continue"` and keep moving.

When using `mode="ask_user"`, you are only deciding that user input is needed.
Do not try to author the chooser itself. Codex will generate the actual
question and options from the recent session context.

When using `mode="auto_continue"`, provide a concise `continue_instruction`
that tells Codex what to do next in the same turn. Do not ask the user in that
mode.

Return JSON only. For `mode="auto_continue"`, provide a non-empty
`continue_instruction`. For `mode="end"` and `mode="ask_user"`,
`continue_instruction` may be empty.

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
    },
    "required": ["mode", "continue_instruction"],
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


def compact_text(text: Optional[str], max_chars: int = MAX_CONTEXT_TEXT_CHARS) -> str:
    normalized = normalize_compare_text(text)
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def is_runtime_control_message(text: Optional[str]) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.lstrip()
    return stripped.startswith("<turn_aborted>") or stripped.startswith("<hook_prompt")


def read_recent_session_context(
    transcript_path: str, turn_id: str
) -> Dict[str, Any]:
    path = Path(transcript_path)
    if not path.exists():
        return {
            "last_user_message": None,
            "recent_turns": [],
            "recent_choosers": [],
            "current_turn_requests": [],
        }

    turns: List[Dict[str, Any]] = []
    turn_by_id: Dict[str, Dict[str, Any]] = {}
    pending_by_call_id: Dict[str, Dict[str, Any]] = {}
    current_turn: Optional[Dict[str, Any]] = None

    def ensure_turn(current_turn_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not isinstance(current_turn_id, str) or not current_turn_id:
            return None
        existing = turn_by_id.get(current_turn_id)
        if existing is not None:
            return existing
        created = {
            "turn_id": current_turn_id,
            "user_messages": [],
            "assistant_messages": [],
            "requests": [],
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
                    current_turn["user_messages"].append(message.strip())
                continue

            if item_type != "response_item":
                continue

            if payload.get("type") == "message":
                role = payload.get("role")
                text = extract_input_text(payload.get("content"))
                if text:
                    if role == "user":
                        if not is_runtime_control_message(text):
                            current_turn["user_messages"].append(text)
                    elif role == "assistant":
                        current_turn["assistant_messages"].append(text)
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
                parsed["call_id"] = call_id
                parsed["turn_id"] = current_turn["turn_id"]
                current_turn["requests"].append(parsed)
                pending_by_call_id[call_id] = parsed
                continue

            if payload.get("type") == "function_call_output":
                call_id = payload.get("call_id")
                if not isinstance(call_id, str):
                    continue
                previous = pending_by_call_id.get(call_id)
                if previous is None:
                    continue
                previous["answers"] = extract_request_user_input_answers(
                    payload.get("output", "")
                )

    target_index = -1
    for index, turn in enumerate(turns):
        if turn.get("turn_id") == turn_id:
            target_index = index
            break
    if target_index == -1:
        return {
            "last_user_message": None,
            "recent_turns": [],
            "recent_choosers": [],
            "current_turn_requests": [],
        }

    recent_turns = turns[max(0, target_index - RECENT_TURNS_LIMIT + 1) : target_index + 1]
    recent_choosers: List[Dict[str, Any]] = []
    for turn in recent_turns:
        for request in turn.get("requests", []):
            recent_choosers.append(request)
    recent_choosers = recent_choosers[-RECENT_CHOOSERS_LIMIT:]

    last_user_message: Optional[str] = None
    current_turn_requests: List[Dict[str, Any]] = []
    if recent_turns:
        current_turn_summary = recent_turns[-1]
        user_messages = current_turn_summary.get("user_messages", [])
        if user_messages:
            last_user_message = user_messages[-1]
        current_turn_requests = list(current_turn_summary.get("requests", []))

    return {
        "last_user_message": last_user_message,
        "recent_turns": recent_turns,
        "recent_choosers": recent_choosers,
        "current_turn_requests": current_turn_requests,
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
        "answers": [],
    }


def extract_request_user_input_answers(output: str) -> List[str]:
    payload = parse_json_object(output)
    if not isinstance(payload, dict):
        return []
    answers_block = payload.get("answers")
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


def chooser_option_labels(chooser: Dict[str, Any]) -> List[str]:
    return [
        compact_text(option.get("label"), 80)
        for option in normalize_options(chooser.get("options"))
        if compact_text(option.get("label"), 80)
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
    last_user_message: Optional[str],
    recent_turns: List[Dict[str, Any]],
    recent_choosers: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    context_parts = ["Recent session context follows."]
    if recent_turns:
        context_parts.extend(["", "<recent_session_context>"])
        for turn in recent_turns:
            context_parts.append(f'<turn id="{turn.get("turn_id", "")}">')
            user_messages = turn.get("user_messages", [])
            if user_messages:
                context_parts.extend(
                    [
                        "<last_user_message>",
                        compact_text(user_messages[-1]),
                        "</last_user_message>",
                    ]
                )
            requests = turn.get("requests", [])
            if requests:
                context_parts.append("<request_user_input_history>")
                for request in requests[-2:]:
                    question = compact_text(request.get("question"))
                    if question:
                        context_parts.append(f"- question: {question}")
                    option_labels = chooser_option_labels(request)
                    if option_labels:
                        context_parts.append(f"  options: {', '.join(option_labels)}")
                    answers = [
                        compact_text(answer, 120)
                        for answer in request.get("answers", [])
                        if compact_text(answer, 120)
                    ]
                    if answers:
                        context_parts.append(f"  user_answer: {' | '.join(answers)}")
                context_parts.append("</request_user_input_history>")
            context_parts.append("</turn>")
        context_parts.append("</recent_session_context>")
    if isinstance(last_user_message, str) and last_user_message.strip():
        context_parts.extend(
            [
                "",
                "<last_user_message>",
                last_user_message.strip(),
                "</last_user_message>",
            ]
        )
    if recent_choosers:
        context_parts.extend(["", "<recent_chooser_summary>"])
        for chooser in recent_choosers[-3:]:
            question = compact_text(chooser.get("question"))
            if question:
                context_parts.append(f"- question: {question}")
            option_labels = chooser_option_labels(chooser)
            if option_labels:
                context_parts.append(f"  options: {', '.join(option_labels)}")
            answers = [
                compact_text(answer, 120)
                for answer in chooser.get("answers", [])
                if compact_text(answer, 120)
            ]
            if answers:
                context_parts.append(f"  user_answer: {' | '.join(answers)}")
        context_parts.append("</recent_chooser_summary>")
    context_parts.extend(
        [
            "",
            "<assistant_final_message>",
            last_assistant_message,
            "</assistant_final_message>",
            "",
            "Decide whether the assistant should end, auto-continue in the same "
            "turn without asking the user, or ask the user a short "
            "`request_user_input` chooser.",
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
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
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
        return None
    return parse_json_object(output_text)


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


def ask_user_prompt_source() -> str:
    return "codex_session"


def build_stop_hook_debug_payload(
    payload: Dict[str, Any],
    *,
    decision: str,
    status: str,
    judgment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    debug_payload: Dict[str, Any] = {
        "type": "stop_hook_judgment",
        "hook_event": "Stop",
        "turn_id": payload.get("turn_id"),
        "decision": decision,
        "status": status,
        "judge_model": JUDGE_MODEL,
        "judge_reasoning_effort": JUDGE_REASONING_EFFORT,
    }
    if not isinstance(judgment, dict):
        return debug_payload

    mode = normalize_mode(judgment.get("mode"))
    debug_payload["mode"] = mode
    debug_payload["raw_judgment"] = judgment

    continue_instruction = normalize_continue_instruction(judgment)
    if continue_instruction:
        debug_payload["continue_instruction"] = continue_instruction

    if mode == "ask_user":
        debug_payload["ask_user_prompt_source"] = ask_user_prompt_source()

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


def render_recent_chooser_history(recent_choosers: List[Dict[str, Any]]) -> str:
    if not recent_choosers:
        return ""
    lines = ["Recent chooser history:"]
    for chooser in recent_choosers[-3:]:
        question = compact_text(chooser.get("question"))
        if question:
            lines.append(f"- Question: {question}")
        option_labels = chooser_option_labels(chooser)
        if option_labels:
            lines.append(f"  Options: {', '.join(option_labels)}")
        answers = [
            compact_text(answer, 120)
            for answer in chooser.get("answers", [])
            if compact_text(answer, 120)
        ]
        if answers:
            lines.append(f"  User answer: {' | '.join(answers)}")
    return "\n".join(lines)


def build_ask_user_block_reason(
    judgment: Dict[str, Any], recent_choosers: List[Dict[str, Any]]
) -> str:
    del judgment
    recent_history_block = render_recent_chooser_history(recent_choosers)
    anti_repeat_instruction = (
        "Do not ask the same or substantially similar chooser again if the recent "
        "history already offered it. Treat free-form answers as new user intent to "
        "act on, not as a cue to re-ask the same chooser."
    )
    parts = [
        "Use the `request_user_input` tool now. Do not send another prose or bullet-list "
        "answer.",
        "Generate the chooser header, exactly one chooser question, and the natural "
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
            "The chooser should feel like a natural continuation of the just-finished "
            "answer, not a reset-style menu. Use options that materially move the work "
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
    judgment: Dict[str, Any], recent_choosers: List[Dict[str, Any]]
) -> str:
    instruction = normalize_continue_instruction(judgment)
    recent_history_block = render_recent_chooser_history(recent_choosers)
    parts = [
        "Do not ask the user another question or show a chooser here.",
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
            "Treat the user's recent direction and chooser answers as already "
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
    judgment: Dict[str, Any], recent_choosers: List[Dict[str, Any]]
) -> str:
    mode = normalize_mode(judgment.get("mode"))
    if mode == "auto_continue":
        return build_auto_continue_block_reason(judgment, recent_choosers)
    return build_ask_user_block_reason(judgment, recent_choosers)


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
    last_user_message = None
    recent_turns: List[Dict[str, Any]] = []
    recent_choosers: List[Dict[str, Any]] = []
    current_turn_requests: List[Dict[str, Any]] = []
    if isinstance(transcript_path, str) and isinstance(turn_id, str):
        context = read_recent_session_context(transcript_path, turn_id)
        last_user_message = context.get("last_user_message")
        recent_turns = context.get("recent_turns", [])
        recent_choosers = context.get("recent_choosers", [])
        current_turn_requests = context.get("current_turn_requests", [])
    if latest_answer_is_explicit_stop(current_turn_requests):
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="explicit_stop_already_selected",
        )
        return True
    judgment = judge_should_request(
        message,
        last_user_message,
        recent_turns,
        recent_choosers,
    )
    if judgment is None:
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="judge_unavailable",
        )
        return True
    mode = normalize_mode(judgment.get("mode"))
    if mode == "end":
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="mode_end",
            judgment=judgment,
        )
        return True
    if mode == "auto_continue" and not normalize_continue_instruction(judgment):
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="invalid_auto_continue_missing_instruction",
            judgment=judgment,
        )
        return True
    if mode != "ask_user" and mode != "auto_continue":
        payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
            payload,
            decision="continue",
            status="invalid_mode",
            judgment=judgment,
        )
        return True
    payload["_judgment"] = judgment
    payload["_recent_choosers"] = recent_choosers
    payload["_stop_hook_debug"] = build_stop_hook_debug_payload(
        payload,
        decision="block",
        status="mode_ask_user" if mode == "ask_user" else "mode_auto_continue",
        judgment=judgment,
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
                    payload["_judgment"], payload.get("_recent_choosers", [])
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
