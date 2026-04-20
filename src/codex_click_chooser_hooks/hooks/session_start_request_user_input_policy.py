#!/usr/bin/env python3

import json


def main() -> int:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "If a turn is ending, prefer automatic same-turn follow-through when "
                "there is one clear next step. Use the `request_user_input` tool only "
                "when the user needs to make a real choice that materially changes "
                "the outcome, risk, or scope. When you do ask, ask one question "
                "using natural single-select options that fit the context. A combined "
                "option such as doing all relevant actions is allowed when it fits "
                "the context."
            ),
        }
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
