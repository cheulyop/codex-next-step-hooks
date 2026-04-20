from __future__ import annotations

import json
import shlex
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .runtime_paths import package_root
from .runtime_paths import templates_dir


MANAGED_STATUS_MARKER = "codex-click-chooser-hooks"
MANAGED_SCRIPT_NAMES = (
    "session_start_request_user_input_policy.py",
    "stop_require_request_user_input.py",
)


def read_hooks_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"hooks": {}}
    with path.open() as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object at {path}")
    hooks = payload.get("hooks")
    if hooks is None:
        payload["hooks"] = {}
    elif not isinstance(hooks, dict):
        raise ValueError(f"Expected 'hooks' object at {path}")
    return payload


def write_hooks_config(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp_path.replace(path)


def backup_hooks_config(path: Path, label: str) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.{label}.{timestamp}.bak")
    backup_path.write_text(path.read_text())
    return backup_path


def render_template(template_text: str, python_path: str, repo_root: str) -> str:
    rendered = template_text.replace("{{python}}", shlex.quote(python_path))
    rendered = rendered.replace("{{repo_root}}", shlex.quote(repo_root))
    return rendered


def load_managed_hooks(python_path: str) -> dict[str, Any]:
    template_path = templates_dir() / "hooks.json"
    rendered = render_template(
        template_path.read_text(),
        python_path=python_path,
        repo_root=str(package_root()),
    )
    return json.loads(rendered)


def matcher_key(group: dict[str, Any]) -> str:
    matcher = group.get("matcher")
    return matcher if isinstance(matcher, str) else ""


def is_managed_hook(hook: dict[str, Any]) -> bool:
    if not isinstance(hook, dict):
        return False
    status_message = hook.get("statusMessage")
    if isinstance(status_message, str) and MANAGED_STATUS_MARKER in status_message:
        return True
    command = hook.get("command")
    if not isinstance(command, str):
        return False
    return any(script_name in command for script_name in MANAGED_SCRIPT_NAMES)


def hook_identity(hook: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (
        hook.get("type"),
        hook.get("command"),
        hook.get("statusMessage"),
    )


def merge_hooks_config(
    existing: dict[str, Any], managed: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    merged = deepcopy(existing)
    merged_hooks = merged.setdefault("hooks", {})
    changes = {"updated_events": [], "inserted_hooks": 0}

    for event_name, managed_groups in managed.get("hooks", {}).items():
        existing_groups = merged_hooks.setdefault(event_name, [])
        if not isinstance(existing_groups, list):
            raise ValueError(f"Expected event list for {event_name}")

        for managed_group in managed_groups:
            target_group = None
            for group in existing_groups:
                if isinstance(group, dict) and matcher_key(group) == matcher_key(managed_group):
                    target_group = group
                    break

            if target_group is None:
                existing_groups.append(deepcopy(managed_group))
                changes["updated_events"].append(event_name)
                changes["inserted_hooks"] += len(managed_group.get("hooks", []))
                continue

            group_hooks = target_group.setdefault("hooks", [])
            if not isinstance(group_hooks, list):
                raise ValueError(f"Expected hook list for {event_name}")

            original_identities = {
                hook_identity(hook) for hook in group_hooks if isinstance(hook, dict)
            }
            target_group["hooks"] = [
                hook for hook in group_hooks if not is_managed_hook(hook)
            ]
            existing_identities = {
                hook_identity(hook)
                for hook in target_group["hooks"]
                if isinstance(hook, dict)
            }
            inserted_here = 0
            for hook in managed_group.get("hooks", []):
                identity = hook_identity(hook)
                if identity not in existing_identities:
                    target_group["hooks"].append(deepcopy(hook))
                    existing_identities.add(identity)
                if identity not in original_identities:
                    inserted_here += 1
            if inserted_here:
                changes["updated_events"].append(event_name)
                changes["inserted_hooks"] += inserted_here

    changes["updated_events"] = sorted(set(changes["updated_events"]))
    return merged, changes


def uninstall_managed_hooks(existing: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = deepcopy(existing)
    hooks = updated.get("hooks", {})
    removed_count = 0
    changed_events: list[str] = []

    for event_name in list(hooks.keys()):
        groups = hooks.get(event_name)
        if not isinstance(groups, list):
            continue
        new_groups = []
        event_changed = False
        for group in groups:
            if not isinstance(group, dict):
                new_groups.append(group)
                continue
            group_hooks = group.get("hooks", [])
            if not isinstance(group_hooks, list):
                new_groups.append(group)
                continue
            retained = []
            for hook in group_hooks:
                if isinstance(hook, dict) and is_managed_hook(hook):
                    removed_count += 1
                    event_changed = True
                    continue
                retained.append(hook)
            if retained:
                new_group = deepcopy(group)
                new_group["hooks"] = retained
                new_groups.append(new_group)
            elif group_hooks:
                event_changed = True
        if new_groups:
            hooks[event_name] = new_groups
        else:
            hooks.pop(event_name, None)
        if event_changed:
            changed_events.append(event_name)

    return updated, {
        "removed_hooks": removed_count,
        "updated_events": sorted(set(changed_events)),
    }
