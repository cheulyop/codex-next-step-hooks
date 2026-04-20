from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from codex_next_step_hooks.install import run_install
from codex_next_step_hooks.merge import load_managed_hooks
from codex_next_step_hooks.merge import merge_hooks_config
from codex_next_step_hooks.merge import uninstall_managed_hooks


class InstallTests(unittest.TestCase):
    def test_uninstall_removes_managed_hook(self) -> None:
        existing = {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/usr/bin/python3 /tmp/src/codex_next_step_hooks/hooks/stop_require_request_user_input.py",
                                "statusMessage": "Checking next-step decision (codex-next-step-hooks)",
                            }
                        ]
                    }
                ]
            }
        }

        updated, changes = uninstall_managed_hooks(existing)

        self.assertEqual(changes["removed_hooks"], 1)
        self.assertEqual(changes["updated_events"], ["Stop"])
        self.assertEqual(updated["hooks"], {})

    def test_merge_does_not_report_inserts_for_identical_managed_hooks(self) -> None:
        managed = load_managed_hooks(sys.executable)

        merged, changes = merge_hooks_config(managed, managed)

        self.assertEqual(merged, managed)
        self.assertEqual(changes["inserted_hooks"], 0)
        self.assertEqual(changes["updated_events"], [])

    def test_install_dry_run_reports_no_change_when_hooks_are_already_installed(self) -> None:
        managed = load_managed_hooks(sys.executable)

        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir)
            hooks_path = codex_home / "hooks.json"
            hooks_path.write_text(json.dumps(managed, ensure_ascii=False, indent=2) + "\n")

            report = run_install(
                codex_home=codex_home,
                python_path=sys.executable,
                dry_run=True,
            )

        self.assertFalse(report["changed"])
        self.assertEqual(report["changes"]["inserted_hooks"], 0)
        self.assertEqual(report["changes"]["updated_events"], [])

    def test_install_reports_change_when_hooks_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir)

            report = run_install(
                codex_home=codex_home,
                python_path=sys.executable,
                dry_run=True,
            )

        self.assertTrue(report["changed"])
        self.assertEqual(report["changes"]["inserted_hooks"], 2)
        self.assertEqual(report["changes"]["updated_events"], ["SessionStart", "Stop"])


if __name__ == "__main__":
    unittest.main()
