from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from codex_next_step_hooks.hooks import session_start_request_user_input_policy
from codex_next_step_hooks.hooks.stop_require_request_user_input import (
    JUDGE_MODEL,
    JUDGE_REASONING_EFFORT,
    SYSTEM_PROMPT,
    build_ask_user_block_reason,
)


class PolicyTextTests(unittest.TestCase):
    def test_judge_defaults_use_gpt_5_4_with_medium_reasoning(self) -> None:
        self.assertEqual(JUDGE_MODEL, "gpt-5.4")
        self.assertEqual(JUDGE_REASONING_EFFORT, "medium")

    def test_session_start_policy_uses_clear_next_step_wording(self) -> None:
        buffer = StringIO()

        with redirect_stdout(buffer):
            exit_code = session_start_request_user_input_policy.main()

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        context = payload["hookSpecificOutput"]["additionalContext"]

        self.assertIn("one clear next step", context)
        self.assertNotIn("low-risk", context)
        self.assertIn("When you do ask, ask one question", context)
        self.assertNotIn("2-3", context)
        self.assertIn("doing all relevant actions", context)

    def test_stop_hook_prompt_drops_short_question_wording(self) -> None:
        self.assertNotIn("low-risk", SYSTEM_PROMPT)
        self.assertNotIn("2-3", SYSTEM_PROMPT)
        self.assertNotIn("one short single-select", SYSTEM_PROMPT)
        self.assertIn("Codex will generate the actual", SYSTEM_PROMPT)
        self.assertNotIn("provide a short `header`", SYSTEM_PROMPT)
        self.assertIn("Always provide a concise `rationale`", SYSTEM_PROMPT)
        self.assertIn("surface a meaningful next-step lane", SYSTEM_PROMPT)
        self.assertIn("do not choose `mode=\"end\"`", SYSTEM_PROMPT)
        self.assertIn("`mode=\"end\"` is the strictest option", SYSTEM_PROMPT)
        self.assertIn("Do not choose it just because the answer", SYSTEM_PROMPT)
        self.assertIn("Would a useful collaborator naturally keep moving here?", SYSTEM_PROMPT)
        self.assertIn("Use the shape of the current turn.", SYSTEM_PROMPT)
        self.assertIn("older broad\ninstruction alone force another `mode=\"auto_continue\"`", SYSTEM_PROMPT)

        fallback = build_ask_user_block_reason({}, [])
        self.assertIn("Generate the chooser header, exactly one chooser question", fallback)
        self.assertIn("the natural single-select options yourself", fallback)
        self.assertNotIn("one short question", fallback)
        self.assertNotIn("2-3", fallback)


if __name__ == "__main__":
    unittest.main()
