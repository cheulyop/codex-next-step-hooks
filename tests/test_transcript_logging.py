from __future__ import annotations

import json
import sys
import tempfile
import unittest
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
    def run_main_with_judgment(self, judgment: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_path = Path(temp_dir) / "transcript.jsonl"
            transcript_path.touch()
            payload = {
                "turn_id": "turn-logging",
                "transcript_path": str(transcript_path),
                "stop_hook_active": True,
                "last_assistant_message": "The install is already current and the latest session policy was loaded.",
            }

            stdin_backup = sys.stdin
            stdout_buffer = StringIO()
            original_urlopen = urllib.request.urlopen

            def fake_urlopen(request: Any, timeout: float = 0) -> FakeHTTPResponse:
                del request, timeout
                return FakeHTTPResponse({"output_text": json.dumps(judgment)})

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

    def test_main_logs_ask_user_judgment_to_transcript(self) -> None:
        judgment = {
            "mode": "ask_user",
            "continue_instruction": "",
        }
        hook_output, event = self.run_main_with_judgment(judgment)

        self.assertEqual(hook_output["decision"], "block")
        self.assertIn("Generate the chooser header, exactly one chooser question", hook_output["reason"])
        self.assertEqual(event["payload"]["decision"], "block")
        self.assertEqual(event["payload"]["status"], "mode_ask_user")
        self.assertEqual(event["payload"]["mode"], "ask_user")
        self.assertNotIn("question", event["payload"])
        self.assertNotIn("options", event["payload"])
        self.assertEqual(event["payload"]["ask_user_prompt_source"], "codex_session")


if __name__ == "__main__":
    unittest.main()
