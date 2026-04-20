from __future__ import annotations

import argparse
import json
from pathlib import Path

from .doctor import run_doctor
from .install import run_install
from .observe import run_observe
from .selftest import run_selftest
from .uninstall import run_uninstall


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-next-step-hooks")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--live-judge", action="store_true")

    install = sub.add_parser("install")
    install.add_argument("--json", action="store_true")
    install.add_argument("--codex-home", type=Path)
    install.add_argument("--python", dest="python_path")
    install.add_argument("--dry-run", action="store_true")

    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("--json", action="store_true")
    uninstall.add_argument("--codex-home", type=Path)
    uninstall.add_argument("--dry-run", action="store_true")

    selftest = sub.add_parser("self-test")
    selftest.add_argument("--json", action="store_true")
    selftest.add_argument("--case", type=Path)

    observe = sub.add_parser("observe")
    observe.add_argument("--json", action="store_true")
    observe.add_argument("--sessions-root", type=Path)
    observe.add_argument("--archived-sessions-root", type=Path)
    observe.add_argument("--include-archived", action="store_true")
    observe.add_argument("--cwd", type=Path)
    observe.add_argument("--all-cwds", action="store_true")
    observe.add_argument("--session-id")
    observe.add_argument("--mode", choices=["end", "auto_continue", "ask_user"])
    observe.add_argument("--date-from")
    observe.add_argument("--date-to")
    observe.add_argument("--limit", type=int, default=8)

    layout = sub.add_parser("print-layout")
    layout.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "doctor":
        report = run_doctor(live_judge=args.live_judge)
    elif args.command == "install":
        report = run_install(
            codex_home=args.codex_home,
            python_path=args.python_path,
            dry_run=args.dry_run,
        )
    elif args.command == "uninstall":
        report = run_uninstall(
            codex_home=args.codex_home,
            dry_run=args.dry_run,
        )
    elif args.command == "self-test":
        report = run_selftest(args.case)
    elif args.command == "observe":
        report = run_observe(
            sessions_root=args.sessions_root,
            archived_sessions_root=args.archived_sessions_root,
            include_archived=args.include_archived,
            cwd=args.cwd,
            all_cwds=args.all_cwds,
            session_id=args.session_id,
            mode=args.mode,
            date_from=args.date_from,
            date_to=args.date_to,
            limit=args.limit,
        )
    else:
        report = {
            "repo": "codex-next-step-hooks",
            "paths": [
                "src/codex_next_step_hooks/install.py",
                "src/codex_next_step_hooks/uninstall.py",
                "src/codex_next_step_hooks/merge.py",
                "src/codex_next_step_hooks/runtime_paths.py",
                "src/codex_next_step_hooks/observe.py",
                "src/codex_next_step_hooks/hooks",
                "src/codex_next_step_hooks/templates",
                "tests/fixtures",
                "docs",
            ],
        }

    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report)
    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
