import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from codex_next_step_hooks.hooks.session_start_request_user_input_policy import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
