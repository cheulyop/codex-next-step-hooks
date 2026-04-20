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

from codex_click_chooser_hooks.hooks import stop_require_request_user_input as stop_hook


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
                "stop_hook_active": True,
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
        self.assertIn("Generate the chooser header, exactly one chooser question", hook_output["reason"])
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
        _, event = self.run_main_with_judgment(
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
        self.assertEqual(
            context["timeline_since_last_user"],
            [
                {"role": "user", "text": "Go ahead and keep moving."},
                {"role": "assistant", "text": "I checked the launcher path first."},
                {
                    "role": "assistant",
                    "text": "The config flag is still missing in the current runtime path.",
                },
            ],
        )

    def test_main_logs_judge_unavailable_failure_reason(self) -> None:
        hook_output, event = self.run_main_with_judgment(
            None,
            urlopen_exception=urllib.error.URLError(TimeoutError("timed out")),
        )

        self.assertEqual(hook_output, {"continue": True})
        self.assertEqual(event["payload"]["decision"], "continue")
        self.assertEqual(event["payload"]["status"], "judge_unavailable")
        self.assertEqual(event["payload"]["judge_timeout_seconds"], 15.0)
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
        self.assertIn(
            "The config flag is still missing in the current runtime path.",
            prompt_text,
        )


if __name__ == "__main__":
    unittest.main()
