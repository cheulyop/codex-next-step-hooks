from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from codex_next_step_hooks.hooks import stop_require_request_user_input as stop_hook


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class TranscriptLoggingTests(unittest.TestCase):
    def run_main_with_judgment(
        self,
        judgment: dict[str, Any] | None,
        *,
        last_assistant_message: str = (
            "The install is already current and the latest session policy was loaded."
        ),
        stop_hook_active: bool = True,
        transcript_lines: list[str] | None = None,
        response_payload: dict[str, Any] | None = None,
        urlopen_exception: Exception | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_path = Path(temp_dir) / "transcript.jsonl"
            if transcript_lines:
                transcript_path.write_text("\n".join(transcript_lines) + "\n")
            else:
                transcript_path.touch()
            payload = {
                "turn_id": "turn-logging",
                "transcript_path": str(transcript_path),
                "stop_hook_active": stop_hook_active,
                "last_assistant_message": last_assistant_message,
            }

            stdin_backup = sys.stdin
            stdout_buffer = StringIO()
            original_urlopen = urllib.request.urlopen

            def fake_urlopen(request: Any, timeout: float = 0) -> FakeHTTPResponse:
                del request, timeout
                if urlopen_exception is not None:
                    raise urlopen_exception
                payload = response_payload
                if payload is None:
                    payload = {"output_text": json.dumps(judgment)}
                return FakeHTTPResponse(payload)

            urllib.request.urlopen = fake_urlopen
            sys.stdin = StringIO(json.dumps(payload))
            try:
                with redirect_stdout(stdout_buffer):
                    exit_code = stop_hook.main()
            finally:
                sys.stdin = stdin_backup
                urllib.request.urlopen = original_urlopen

            self.assertEqual(exit_code, 0)

            hook_output = json.loads(stdout_buffer.getvalue())
            lines = transcript_path.read_text().splitlines()
            self.assertTrue(lines)
            event = json.loads(lines[-1])
            return hook_output, event

    def test_main_logs_end_judgment_to_transcript(self) -> None:
        hook_output, event = self.run_main_with_judgment(
            {
                "mode": "end",
                "continue_instruction": "",
                "rationale": "The reply is a narrow factual confirmation with no further action.",
            }
        )

        self.assertEqual(hook_output, {"continue": True})
        self.assertEqual(event["type"], "event_msg")
        self.assertEqual(event["payload"]["type"], "stop_hook_judgment")
        self.assertEqual(event["payload"]["decision"], "continue")
        self.assertEqual(event["payload"]["status"], "mode_end")
        self.assertEqual(event["payload"]["mode"], "end")
        self.assertEqual(event["payload"]["judge_model"], "gpt-5.4")
        self.assertEqual(event["payload"]["judge_reasoning_effort"], "medium")
        self.assertEqual(
            event["payload"]["rationale"],
            "The reply is a narrow factual confirmation with no further action.",
        )

    def test_main_logs_ask_user_judgment_to_transcript(self) -> None:
        judgment = {
            "mode": "ask_user",
            "continue_instruction": "",
            "rationale": "The user needs to choose between materially different next steps.",
        }
        hook_output, event = self.run_main_with_judgment(judgment)

        self.assertEqual(hook_output["decision"], "block")
        self.assertIn("Generate the header, exactly one next-step question", hook_output["reason"])
        self.assertEqual(event["payload"]["decision"], "block")
        self.assertEqual(event["payload"]["status"], "mode_ask_user")
        self.assertEqual(event["payload"]["mode"], "ask_user")
        self.assertEqual(
            event["payload"]["rationale"],
            "The user needs to choose between materially different next steps.",
        )
        self.assertNotIn("question", event["payload"])
        self.assertNotIn("options", event["payload"])
        self.assertEqual(event["payload"]["ask_user_prompt_source"], "codex_session")

    def test_main_logs_end_override_to_auto_continue(self) -> None:
        hook_output, event = self.run_main_with_judgment(
            {
                "mode": "end",
                "continue_instruction": "",
                "rationale": "The work is already complete.",
            },
            last_assistant_message=(
                "The rationale patch is done and verified.\n\n"
                "The next step is to inspect a few mode_end rationales before weakening the end wording."
            ),
        )

        self.assertEqual(hook_output["decision"], "block")
        self.assertIn(
            "Continue with the next step the assistant just surfaced:",
            hook_output["reason"],
        )
        self.assertEqual(event["payload"]["decision"], "block")
        self.assertEqual(event["payload"]["status"], "mode_auto_continue_end_override")
        self.assertEqual(event["payload"]["mode"], "auto_continue")
        self.assertEqual(event["payload"]["raw_judgment"]["mode"], "end")
        self.assertEqual(
            event["payload"]["judgment_override"]["reason"],
            "assistant_message_surfaces_clear_next_step",
        )
        self.assertIn(
            "inspect a few mode_end rationales before weakening the end wording",
            event["payload"]["continue_instruction"],
        )

    def test_main_logs_current_turn_context_summary(self) -> None:
        transcript_lines = [
            json.dumps({"type": "turn_context", "payload": {"turn_id": "turn-logging"}}),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Go ahead and keep moving."}
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "I checked the launcher path first."}
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "The config flag is still missing in the current runtime path.",
                            }
                        ],
                    },
                }
            ),
        ]
        hook_output, event = self.run_main_with_judgment(
            {
                "mode": "end",
                "continue_instruction": "",
                "rationale": "The explanation already covered the current question.",
            },
            last_assistant_message=(
                "The config flag is still missing in the current runtime path."
            ),
            transcript_lines=transcript_lines,
        )

        context = event["payload"]["current_turn_context"]
        self.assertEqual(context["user_message_count"], 1)
        self.assertEqual(context["assistant_message_count"], 2)
        self.assertEqual(context["assistant_messages_since_last_user"], 2)
        self.assertEqual(context["request_count"], 0)
        self.assertEqual(
            context["prior_assistant_messages_before_final"],
            ["I checked the launcher path first."],
        )
        self.assertEqual(context["last_substantive_user_message"], "Go ahead and keep moving.")
        self.assertEqual(context["timeline_since_last_user"][0]["role"], "user")
        self.assertEqual(
            context["timeline_since_last_user"][0]["message_kind"],
            "intent",
        )
        self.assertEqual(
            context["timeline_since_last_user"][0]["text"],
            "Go ahead and keep moving.",
        )
        self.assertEqual(context["timeline_since_last_user"][1]["role"], "assistant")
        self.assertEqual(
            context["timeline_since_last_user"][1]["text"],
            "I checked the launcher path first.",
        )
        self.assertEqual(context["timeline_since_last_user"][2]["role"], "assistant")
        self.assertEqual(
            context["timeline_since_last_user"][2]["text"],
            "The config flag is still missing in the current runtime path.",
        )
        self.assertEqual(hook_output, {"continue": True})

    def test_main_turns_end_into_one_safe_summary_continuation(self) -> None:
        transcript_lines = [
            json.dumps({"type": "turn_context", "payload": {"turn_id": "turn-logging"}}),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Go ahead and keep moving."}
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "I checked the launcher path first."}
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "The config flag is still missing in the current runtime path.",
                            }
                        ],
                    },
                }
            ),
        ]

        hook_output, event = self.run_main_with_judgment(
            {
                "mode": "end",
                "continue_instruction": "",
                "rationale": "The explanation already covered the current question.",
            },
            last_assistant_message=(
                "The config flag is still missing in the current runtime path."
            ),
            stop_hook_active=False,
            transcript_lines=transcript_lines,
        )

        self.assertEqual(hook_output["decision"], "block")
        self.assertIn("Before ending, write a closing summary", hook_output["reason"])
        self.assertIn("Latest substantive user message:", hook_output["reason"])
        self.assertIn("Go ahead and keep moving.", hook_output["reason"])
        self.assertIn("Assistant work since that message:", hook_output["reason"])
        self.assertIn("I checked the launcher path first.", hook_output["reason"])
        self.assertIn(
            "The config flag is still missing in the current runtime path.",
            hook_output["reason"],
        )
        self.assertEqual(event["payload"]["decision"], "block")
        self.assertEqual(event["payload"]["status"], "mode_end_summary_continuation")
        self.assertEqual(event["payload"]["mode"], "end")

    def test_read_recent_session_context_uses_entries_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_path = Path(temp_dir) / "transcript.jsonl"
            transcript_lines = [
                json.dumps({"type": "turn_context", "payload": {"turn_id": "turn-entries"}}),
                json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "Please expand the README explanation.",
                    },
                }
            ),
            json.dumps(
                {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Sounds good. I will inspect the README structure first.",
                            }
                        ],
                    },
                }
            ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "request_user_input",
                            "call_id": "call-1",
                            "arguments": json.dumps(
                                {
                                    "questions": [
                                        {
                                            "header": "Next Step",
                                            "question": "How should we proceed?",
                                            "options": [
                                                {
                                                    "label": "README only",
                                                    "description": "Update the documentation only.",
                                                },
                                                {
                                                    "label": "README plus tests",
                                                    "description": "Update the documentation and review the tests.",
                                                },
                                            ],
                                        }
                                    ]
                                }
                            ),
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call-1",
                            "output": json.dumps(
                                {"answers": {"next_step": {"answers": ["README only"]}}}
                            ),
                        },
                    }
                ),
            ]
            transcript_path.write_text("\n".join(transcript_lines) + "\n")

            context = stop_hook.read_recent_session_context(
                str(transcript_path), "turn-entries"
            )

        recent_turn = context["recent_turns"][0]
        self.assertEqual(recent_turn["turn_id"], "turn-entries")
        self.assertIn("entries", recent_turn)
        self.assertNotIn("user_messages", recent_turn)
        self.assertNotIn("assistant_messages", recent_turn)
        self.assertNotIn("requests", recent_turn)
        self.assertNotIn("timeline", recent_turn)
        self.assertEqual(
            recent_turn["entries"],
            [
                {
                    "kind": "message",
                    "role": "user",
                    "text": "Please expand the README explanation.",
                    "seq": 1,
                    "message_kind": "intent",
                },
                {
                    "kind": "message",
                    "role": "assistant",
                    "text": "Sounds good. I will inspect the README structure first.",
                    "seq": 2,
                },
                {
                    "kind": "request_user_input",
                    "call_id": "call-1",
                    "turn_id": "turn-entries",
                    "header": "Next Step",
                    "question": "How should we proceed?",
                    "options": [
                        {"label": "README only", "description": "Update the documentation only."},
                        {
                            "label": "README plus tests",
                            "description": "Update the documentation and review the tests.",
                        },
                    ],
                    "anchor_turn_id": "turn-entries",
                    "anchor_text": "Please expand the README explanation.",
                    "anchor_seq": 1,
                },
                {
                    "kind": "request_user_input_output",
                    "call_id": "call-1",
                    "turn_id": "turn-entries",
                    "answers": ["README only"],
                },
            ],
        )
        self.assertEqual(len(context["recent_questions"]), 1)
        self.assertEqual(context["recent_questions"][0]["answers"], ["README only"])
        self.assertEqual(
            context["recent_questions"][0]["anchor_text"],
            "Please expand the README explanation.",
        )
        self.assertEqual(context["current_turn_requests"][0]["question"], "How should we proceed?")

    def test_main_logs_judge_unavailable_failure_reason(self) -> None:
        hook_output, event = self.run_main_with_judgment(
            None,
            urlopen_exception=urllib.error.URLError(TimeoutError("timed out")),
        )

        self.assertEqual(hook_output, {"continue": True})
        self.assertEqual(event["payload"]["decision"], "continue")
        self.assertEqual(event["payload"]["status"], "judge_unavailable")
        self.assertEqual(event["payload"]["judge_timeout_seconds"], 30.0)
        self.assertEqual(
            event["payload"]["judge_failure_reason"],
            "URLError: TimeoutError: timed out",
        )

    def test_judge_request_includes_raw_current_turn_timeline(self) -> None:
        original_urlopen = urllib.request.urlopen
        captured_prompt: dict[str, str] = {}

        def fake_urlopen(request: Any, timeout: float = 0) -> FakeHTTPResponse:
            del timeout
            body = json.loads(request.data.decode("utf-8"))
            captured_prompt["text"] = body["input"][1]["content"][0]["text"]
            return FakeHTTPResponse(
                {
                    "output_text": json.dumps(
                        {
                            "mode": "end",
                            "continue_instruction": "",
                            "rationale": "The reply is complete.",
                        }
                    )
                }
            )

        current_turn_context = {
            "user_message_count": 1,
            "assistant_message_count": 2,
            "request_count": 0,
            "assistant_messages_since_last_user": 2,
            "recent_user_messages": ["Go ahead and keep moving."],
            "recent_timeline": [
                {"role": "user", "text": "Go ahead and keep moving."},
                {"role": "assistant", "text": "I checked the launcher path first."},
                {
                    "role": "assistant",
                    "text": "The config flag is still missing in the current runtime path.",
                },
            ],
            "timeline_since_last_user": [
                {"role": "user", "text": "Go ahead and keep moving."},
                {"role": "assistant", "text": "I checked the launcher path first."},
                {
                    "role": "assistant",
                    "text": "The config flag is still missing in the current runtime path.",
                },
            ],
        }

        urllib.request.urlopen = fake_urlopen
        try:
            judgment, failure_reason = stop_hook.judge_should_request(
                "The config flag is still missing in the current runtime path.",
                [],
                [],
                current_turn_context,
            )
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertIsNone(failure_reason)
        self.assertEqual(judgment["mode"], "end")
        prompt_text = captured_prompt["text"]
        self.assertNotIn("<last_user_message>", prompt_text)
        self.assertNotIn("<request_user_input_history>", prompt_text)
        self.assertIn("<current_turn_timeline_since_last_user>", prompt_text)
        self.assertNotIn("<current_turn_user_messages>", prompt_text)
        self.assertNotIn("<current_turn_assistant_history_before_final>", prompt_text)
        self.assertNotIn("<current_turn_recent_timeline>", prompt_text)
        self.assertIn("Go ahead and keep moving.", prompt_text)
        self.assertIn("I checked the launcher path first.", prompt_text)
        self.assertIn("[01] [user:intent] Go ahead and keep moving.", prompt_text)
        self.assertIn(
            "The config flag is still missing in the current runtime path.",
            prompt_text,
        )

    def test_judge_request_prefers_substantive_user_anchor_and_filters_stale_questions(
        self,
    ) -> None:
        original_urlopen = urllib.request.urlopen
        captured_prompt: dict[str, str] = {}

        def fake_urlopen(request: Any, timeout: float = 0) -> FakeHTTPResponse:
            del timeout
            body = json.loads(request.data.decode("utf-8"))
            captured_prompt["text"] = body["input"][1]["content"][0]["text"]
            return FakeHTTPResponse(
                {
                    "output_text": json.dumps(
                        {
                            "mode": "end",
                            "continue_instruction": "",
                            "rationale": "The reply is complete.",
                        }
                    )
                }
            )

        transcript_lines = [
            json.dumps(
                {"type": "turn_context", "payload": {"turn_id": "turn-prev"}}
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "How should we continue organizing the draft notes?",
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "request_user_input",
                        "call_id": "call-prev",
                        "arguments": json.dumps(
                            {
                                "questions": [
                                    {
                                        "header": "Note Format",
                                        "question": "How should we continue organizing the draft notes?",
                                        "options": [
                                            {
                                                "label": "Two-line summary",
                                                "description": "Keep the result short and compact.",
                                            },
                                            {
                                                "label": "One-paragraph summary",
                                                "description": "Write a slightly fuller summary.",
                                            },
                                        ],
                                    }
                                ]
                            }
                        ),
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-prev",
                        "output": json.dumps(
                            {"answers": {"memo": {"answers": ["Two-line summary"]}}}
                        ),
                    },
                }
            ),
            json.dumps(
                {"type": "turn_context", "payload": {"turn_id": "turn-current"}}
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "Review the conversation summary and change proposal, then tell me which evaluation preset to use.",
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<skill>\n<name>context-fetch</name>\n...</skill>",
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "I will compare the relevant materials and summarize the conclusion.",
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "In the current setup, the standard-lenient preset is closest to the baseline.",
                            }
                        ],
                    },
                }
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_path = Path(temp_dir) / "transcript.jsonl"
            transcript_path.write_text("\n".join(transcript_lines) + "\n")
            context = stop_hook.read_recent_session_context(
                str(transcript_path), "turn-current"
            )
            filtered_questions = stop_hook.filter_recent_questions_to_current_lane(
                context["recent_turns"],
                context["recent_questions"],
                context["current_turn_context"],
            )

            urllib.request.urlopen = fake_urlopen
            try:
                judgment, failure_reason = stop_hook.judge_should_request(
                    "In the current setup, the standard-lenient preset is closest to the baseline.",
                    context["recent_turns"],
                    filtered_questions,
                    context["current_turn_context"],
                )
            finally:
                urllib.request.urlopen = original_urlopen

        self.assertIsNone(failure_reason)
        self.assertEqual(judgment["mode"], "end")
        self.assertEqual(filtered_questions, [])
        prompt_text = captured_prompt["text"]
        self.assertIn("<last_substantive_user_message>", prompt_text)
        self.assertIn(
            "Review the conversation summary and change proposal, then tell me which evaluation preset to use.",
            prompt_text,
        )
        self.assertIn("[01] [user:intent]", prompt_text)
        self.assertIn("[02] [user:context]", prompt_text)
        self.assertNotIn("Two-line summary", prompt_text)
        self.assertNotIn("<recent_question_summary>", prompt_text)

    def test_filter_recent_questions_prefers_recorded_anchor_text(self) -> None:
        recent_turns = [
            {
                "turn_id": "turn-prev",
                "entries": [
                    {
                        "kind": "message",
                        "role": "user",
                        "text": "How should we organize the draft notes?",
                        "seq": 1,
                        "message_kind": "intent",
                    }
                ],
            }
        ]
        recent_questions = [
            {
                "call_id": "call-prev",
                "turn_id": "turn-prev",
                "question": "Which evaluation preset should we use?",
                "options": [],
                "answers": ["Two-line summary"],
                "anchor_turn_id": "turn-prev",
                "anchor_text": "How should we organize the draft notes?",
                "anchor_seq": 1,
            }
        ]
        current_turn_context = {
            "turn_id": "turn-current",
            "last_substantive_user_message": "Tell me which evaluation preset we should use.",
        }

        filtered = stop_hook.filter_recent_questions_to_current_lane(
            recent_turns,
            recent_questions,
            current_turn_context,
        )

        self.assertEqual(filtered, [])


if __name__ == "__main__":
    unittest.main()
