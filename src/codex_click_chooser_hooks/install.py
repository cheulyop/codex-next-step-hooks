from __future__ import annotations

import sys
from pathlib import Path

from .merge import backup_hooks_config
from .merge import load_managed_hooks
from .merge import merge_hooks_config
from .merge import read_hooks_config
from .merge import write_hooks_config
from .runtime_paths import default_codex_home
from .runtime_paths import package_root


def run_install(
    codex_home: Path | None = None,
    python_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    resolved_codex_home = codex_home or default_codex_home()
    resolved_python = python_path or sys.executable
    hooks_path = resolved_codex_home / "hooks.json"

    existing = read_hooks_config(hooks_path)
    managed = load_managed_hooks(resolved_python)
    merged, changes = merge_hooks_config(existing, managed)
    changed = merged != existing
    backup_path = None

    if not dry_run and changed:
        backup_path = backup_hooks_config(hooks_path, "install")
        write_hooks_config(hooks_path, merged)

    return {
        "ok": True,
        "action": "install",
        "dry_run": dry_run,
        "changed": changed,
        "repo_root": str(package_root()),
        "codex_home": str(resolved_codex_home),
        "hooks_path": str(hooks_path),
        "python": resolved_python,
        "changes": changes,
        "backup_path": str(backup_path) if backup_path else None,
    }
