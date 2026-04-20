from __future__ import annotations

from pathlib import Path


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def package_src_root() -> Path:
    return package_root() / "src" / "codex_next_step_hooks"


def templates_dir() -> Path:
    return package_src_root() / "templates"


def hooks_dir() -> Path:
    return package_src_root() / "hooks"


def default_codex_home() -> Path:
    return Path.home() / ".codex"
