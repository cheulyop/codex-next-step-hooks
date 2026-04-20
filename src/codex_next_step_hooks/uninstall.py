from __future__ import annotations

from pathlib import Path

from .merge import backup_hooks_config
from .merge import read_hooks_config
from .merge import uninstall_managed_hooks
from .merge import write_hooks_config
from .runtime_paths import default_codex_home
from .runtime_paths import package_root


def run_uninstall(codex_home: Path | None = None, dry_run: bool = False) -> dict:
    resolved_codex_home = codex_home or default_codex_home()
    hooks_path = resolved_codex_home / "hooks.json"
    existing = read_hooks_config(hooks_path)
    updated, changes = uninstall_managed_hooks(existing)
    changed = changes["removed_hooks"] > 0
    backup_path = None

    if not dry_run and changed:
        backup_path = backup_hooks_config(hooks_path, "uninstall")
        write_hooks_config(hooks_path, updated)

    return {
        "ok": True,
        "action": "uninstall",
        "dry_run": dry_run,
        "changed": changed,
        "repo_root": str(package_root()),
        "codex_home": str(resolved_codex_home),
        "hooks_path": str(hooks_path),
        "changes": changes,
        "backup_path": str(backup_path) if backup_path else None,
    }
