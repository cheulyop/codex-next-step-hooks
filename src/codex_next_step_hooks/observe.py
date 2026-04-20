from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Iterable
from typing import Optional

SESSION_ID_PATTERN = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)
VALID_MODES = {"end", "auto_continue", "ask_user"}


def compact_text(text: Any, max_chars: int = 160) -> str:
    if not isinstance(text, str):
        return ""
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def normalize_mode(value: Any) -> str:
    if value in VALID_MODES:
        return value
    return "end"


def default_sessions_root() -> Path:
    return Path.home() / ".codex" / "sessions"


def default_archived_sessions_root() -> Path:
    return Path.home() / ".codex" / "archived_sessions"


def extract_session_id(path: Path) -> str:
    match = SESSION_ID_PATTERN.search(path.name)
    if match is None:
        return path.stem
    return match.group(1)


def normalize_cwd(value: Optional[Path | str]) -> Optional[str]:
    if value is None:
        return None
    path = Path(value).expanduser()
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def iter_rollout_paths(
    sessions_root: Path,
    *,
    archived_sessions_root: Optional[Path] = None,
    include_archived: bool = False,
    session_id: Optional[str] = None,
) -> Iterable[tuple[str, Path]]:
    roots = [("sessions", sessions_root)]
    if include_archived and archived_sessions_root is not None:
        roots.append(("archived_sessions", archived_sessions_root))

    for store_name, root in roots:
        if not root.exists():
            continue
        if session_id:
            needle = f"*{session_id}.jsonl"
            for path in sorted(root.rglob(needle)):
                yield store_name, path
            continue
        for path in sorted(root.rglob("rollout-*.jsonl")):
            yield store_name, path


def parse_date_filter(value: Optional[str]) -> tuple[Optional[date], Optional[str]]:
    if value is None:
        return None, None
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, f"invalid date filter '{value}' (expected YYYY-MM-DD)"


def extract_event_date(timestamp: Any) -> Optional[date]:
    if not isinstance(timestamp, str) or not timestamp.strip():
        return None
    normalized = timestamp.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


def should_include_event_date(
    event_date: Optional[date],
    *,
    date_from: Optional[date],
    date_to: Optional[date],
) -> bool:
    if date_from is None and date_to is None:
        return True
    if event_date is None:
        return False
    if date_from is not None and event_date < date_from:
        return False
    if date_to is not None and event_date > date_to:
        return False
    return True


def extract_session_cwd(path: Path) -> Optional[str]:
    try:
        with path.open() as handle:
            for line_number, line in enumerate(handle, start=1):
                if line_number > 50:
                    break
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("type") != "session_meta":
                    continue
                payload = item.get("payload", {})
                cwd = payload.get("cwd")
                if isinstance(cwd, str) and cwd.strip():
                    return normalize_cwd(cwd)
                break
    except OSError:
        return None
    return None


def should_include_cwd(session_cwd: Optional[str], cwd_filter: Optional[str]) -> bool:
    if cwd_filter is None:
        return True
    if not session_cwd:
        return False
    return session_cwd == cwd_filter


def collect_stop_hook_events(
    path: Path,
    *,
    session_store: str,
    session_cwd: Optional[str],
    mode_filter: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
) -> list[dict[str, Any]]:
    session_id = extract_session_id(path)
    events: list[dict[str, Any]] = []
    try:
        with path.open() as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("type") != "event_msg":
                    continue
                payload = item.get("payload", {})
                if payload.get("type") != "stop_hook_judgment":
                    continue

                event_date = extract_event_date(item.get("timestamp"))
                if not should_include_event_date(
                    event_date,
                    date_from=date_from,
                    date_to=date_to,
                ):
                    continue

                mode = normalize_mode(payload.get("mode"))
                if mode_filter and mode != mode_filter:
                    continue

                current_turn_context = payload.get("current_turn_context", {})
                event = {
                    "session_id": session_id,
                    "session_store": session_store,
                    "transcript_path": str(path),
                    "line_number": line_number,
                    "timestamp": item.get("timestamp"),
                    "event_date": event_date.isoformat() if event_date else None,
                    "cwd": session_cwd,
                    "turn_id": payload.get("turn_id"),
                    "decision": payload.get("decision"),
                    "status": payload.get("status"),
                    "mode": mode,
                    "rationale": compact_text(
                        payload.get("rationale")
                        or payload.get("raw_judgment", {}).get("rationale"),
                        220,
                    ),
                    "continue_instruction": compact_text(
                        payload.get("continue_instruction"), 220
                    ),
                    "override_reason": payload.get("judgment_override", {}).get("reason"),
                    "assistant_messages_since_last_user": current_turn_context.get(
                        "assistant_messages_since_last_user"
                    ),
                    "assistant_message_count": current_turn_context.get(
                        "assistant_message_count"
                    ),
                    "request_count": current_turn_context.get("request_count"),
                }
                events.append(event)
    except OSError:
        return []
    return events


def summarize_turn_shape(events: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        int(value)
        for value in (
            event.get("assistant_messages_since_last_user") for event in events
        )
        if isinstance(value, int)
    ]
    if not values:
        return {}

    histogram = Counter(str(value) for value in values)
    average = round(sum(values) / len(values), 2)
    return {
        "events_with_context": len(values),
        "assistant_messages_since_last_user": {
            "average": average,
            "min": min(values),
            "max": max(values),
            "histogram": dict(sorted(histogram.items(), key=lambda item: int(item[0]))),
        },
    }


def most_common_strings(values: Iterable[str], limit: int) -> list[dict[str, Any]]:
    counts = Counter(value for value in values if isinstance(value, str) and value)
    return [
        {"value": value, "count": count}
        for value, count in counts.most_common(limit)
    ]


def run_observe(
    *,
    sessions_root: Optional[Path] = None,
    archived_sessions_root: Optional[Path] = None,
    include_archived: bool = False,
    cwd: Optional[Path | str] = None,
    all_cwds: bool = False,
    session_id: Optional[str] = None,
    mode: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 8,
) -> dict[str, Any]:
    root = (sessions_root or default_sessions_root()).expanduser()
    archived_root = (
        (archived_sessions_root or default_archived_sessions_root()).expanduser()
        if include_archived
        else None
    )
    mode_filter = mode if mode in VALID_MODES else None
    cwd_filter = None if all_cwds else normalize_cwd(cwd or Path.cwd())
    parsed_date_from, date_from_error = parse_date_filter(date_from)
    parsed_date_to, date_to_error = parse_date_filter(date_to)

    if date_from_error or date_to_error:
        errors = [error for error in [date_from_error, date_to_error] if error]
        return {
            "ok": False,
            "error": "; ".join(errors),
            "filters": {
                "sessions_root": str(root),
                "archived_sessions_root": str(archived_root) if archived_root else None,
                "include_archived": include_archived,
                "cwd": cwd_filter,
                "all_cwds": all_cwds,
                "session_id": session_id,
                "mode": mode_filter,
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
            },
        }
    if (
        parsed_date_from is not None
        and parsed_date_to is not None
        and parsed_date_from > parsed_date_to
    ):
        return {
            "ok": False,
            "error": "date_from must be on or before date_to",
            "filters": {
                "sessions_root": str(root),
                "archived_sessions_root": str(archived_root) if archived_root else None,
                "include_archived": include_archived,
                "cwd": cwd_filter,
                "all_cwds": all_cwds,
                "session_id": session_id,
                "mode": mode_filter,
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
            },
        }

    if not root.exists():
        return {
            "ok": False,
            "error": f"sessions root does not exist: {root}",
            "filters": {
                "sessions_root": str(root),
                "archived_sessions_root": str(archived_root) if archived_root else None,
                "include_archived": include_archived,
                "cwd": cwd_filter,
                "all_cwds": all_cwds,
                "session_id": session_id,
                "mode": mode_filter,
                "date_from": date_from,
                "date_to": date_to,
                "limit": limit,
            },
        }

    rollout_paths = list(
        iter_rollout_paths(
            root,
            archived_sessions_root=archived_root,
            include_archived=include_archived,
            session_id=session_id,
        )
    )
    matched_session_ids: set[str] = set()
    events: list[dict[str, Any]] = []
    files_considered = 0
    files_matched = 0
    store_counts = Counter()

    for session_store, path in rollout_paths:
        files_considered += 1
        session_cwd = extract_session_cwd(path)
        if not should_include_cwd(session_cwd, cwd_filter):
            continue
        files_matched += 1
        store_counts[session_store] += 1
        file_events = collect_stop_hook_events(
            path,
            session_store=session_store,
            session_cwd=session_cwd,
            mode_filter=mode_filter,
            date_from=parsed_date_from,
            date_to=parsed_date_to,
        )
        if file_events:
            matched_session_ids.add(file_events[0]["session_id"])
            events.extend(file_events)

    mode_counts = Counter(event["mode"] for event in events)
    status_counts = Counter(event["status"] for event in events if event.get("status"))
    override_counts = Counter(
        event["override_reason"] for event in events if event.get("override_reason")
    )
    session_counts = Counter(event["session_id"] for event in events)
    event_store_counts = Counter(
        event["session_store"] for event in events if event.get("session_store")
    )
    recent_examples = list(reversed(events[-limit:]))

    return {
        "ok": True,
        "filters": {
            "sessions_root": str(root),
            "archived_sessions_root": str(archived_root) if archived_root else None,
            "cwd": cwd_filter,
            "all_cwds": all_cwds,
            "include_archived": include_archived,
            "session_id": session_id,
            "mode": mode_filter,
            "date_from": parsed_date_from.isoformat() if parsed_date_from else None,
            "date_to": parsed_date_to.isoformat() if parsed_date_to else None,
            "limit": limit,
        },
        "files_considered": files_considered,
        "files_matched": files_matched,
        "file_store_counts": dict(store_counts),
        "matched_session_count": len(matched_session_ids),
        "judgment_count": len(events),
        "mode_counts": dict(mode_counts),
        "status_counts": dict(status_counts),
        "override_counts": dict(override_counts),
        "event_store_counts": dict(event_store_counts),
        "top_sessions": [
            {"session_id": session_key, "judgment_count": count}
            for session_key, count in session_counts.most_common(limit)
        ],
        "top_rationales": most_common_strings(
            (event["rationale"] for event in events), limit
        ),
        "turn_shape": summarize_turn_shape(events),
        "examples": recent_examples,
    }
