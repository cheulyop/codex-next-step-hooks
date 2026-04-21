from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_next_step_hooks.observe import run_observe


def write_rollout(
    path: Path,
    *,
    cwd: str,
    events: list[dict],
) -> None:
    lines = [
        {"type": "session_meta", "payload": {"id": path.stem, "cwd": cwd}},
    ]
    lines.extend(events)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in lines) + "\n")


class ObserveTests(unittest.TestCase):
    def test_run_observe_summarizes_repo_scoped_judgments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sessions_root = Path(temp_dir) / "sessions"
            repo_cwd = "/workspace/codex-next-step-hooks"
            other_cwd = "/workspace/other-repo"

            write_rollout(
                sessions_root
                / "2026"
                / "04"
                / "20"
                / "rollout-2026-04-20T10-00-00-019da111-1111-7111-8111-111111111111.jsonl",
                cwd=repo_cwd,
                events=[
                    {
                        "timestamp": "2026-04-20T01:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "stop_hook_judgment",
                            "turn_id": "turn-1",
                            "decision": "continue",
                            "status": "mode_end",
                            "mode": "end",
                            "rationale": "The answer already covered the narrow check.",
                            "current_turn_context": {
                                "assistant_messages_since_last_user": 0,
                                "assistant_message_count": 1,
                                "request_count": 0,
                            },
                        },
                    },
                    {
                        "timestamp": "2026-04-20T01:05:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "stop_hook_judgment",
                            "turn_id": "turn-2",
                            "decision": "block",
                            "status": "mode_auto_continue",
                            "mode": "auto_continue",
                            "continue_instruction": "Inspect the runtime config next.",
                            "rationale": "There is one dominant next check inside the same lane.",
                            "current_turn_context": {
                                "assistant_messages_since_last_user": 2,
                                "assistant_message_count": 3,
                                "request_count": 0,
                            },
                        },
                    },
                ],
            )

            write_rollout(
                sessions_root
                / "2026"
                / "04"
                / "20"
                / "rollout-2026-04-20T11-00-00-019da222-2222-7222-8222-222222222222.jsonl",
                cwd=other_cwd,
                events=[
                    {
                        "timestamp": "2026-04-20T02:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "stop_hook_judgment",
                            "turn_id": "turn-3",
                            "decision": "block",
                            "status": "mode_ask_user",
                            "mode": "ask_user",
                            "rationale": "The user must choose between deployment branches.",
                        },
                    }
                ],
            )

            report = run_observe(
                sessions_root=sessions_root,
                cwd=repo_cwd,
                limit=3,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["files_considered"], 2)
        self.assertEqual(report["files_matched"], 1)
        self.assertEqual(report["matched_session_count"], 1)
        self.assertEqual(report["judgment_count"], 2)
        self.assertEqual(report["mode_counts"], {"end": 1, "auto_continue": 1})
        self.assertEqual(report["status_counts"]["mode_end"], 1)
        self.assertEqual(report["status_counts"]["mode_auto_continue"], 1)
        self.assertEqual(
            report["turn_shape"]["assistant_messages_since_last_user"]["average"], 1.0
        )
        self.assertEqual(report["examples"][0]["mode"], "auto_continue")
        self.assertEqual(report["examples"][1]["mode"], "end")

    def test_run_observe_filters_by_session_id_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sessions_root = Path(temp_dir) / "sessions"
            repo_cwd = "/workspace/codex-next-step-hooks"
            target_session_id = "019da333-3333-7333-8333-333333333333"

            write_rollout(
                sessions_root
                / "2026"
                / "04"
                / "20"
                / f"rollout-2026-04-20T12-00-00-{target_session_id}.jsonl",
                cwd=repo_cwd,
                events=[
                    {
                        "timestamp": "2026-04-20T03:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "stop_hook_judgment",
                            "turn_id": "turn-4",
                            "decision": "block",
                            "status": "mode_ask_user",
                            "mode": "ask_user",
                            "rationale": "Two materially different next steps remain.",
                        },
                    },
                    {
                        "timestamp": "2026-04-20T03:10:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "stop_hook_judgment",
                            "turn_id": "turn-5",
                            "decision": "continue",
                            "status": "mode_end",
                            "mode": "end",
                            "rationale": "The quick factual confirmation is complete.",
                        },
                    },
                ],
            )

            report = run_observe(
                sessions_root=sessions_root,
                cwd=repo_cwd,
                session_id=target_session_id,
                mode="ask_user",
                limit=2,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["files_considered"], 1)
        self.assertEqual(report["files_matched"], 1)
        self.assertEqual(report["judgment_count"], 1)
        self.assertEqual(report["mode_counts"], {"ask_user": 1})
        self.assertEqual(report["examples"][0]["session_id"], target_session_id)
        self.assertEqual(report["examples"][0]["mode"], "ask_user")

    def test_run_observe_can_include_archived_sessions_and_date_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sessions_root = Path(temp_dir) / "sessions"
            archived_root = Path(temp_dir) / "archived_sessions"
            repo_cwd = "/workspace/codex-next-step-hooks"

            write_rollout(
                sessions_root
                / "2026"
                / "04"
                / "19"
                / "rollout-2026-04-19T10-00-00-019da444-4444-7444-8444-444444444444.jsonl",
                cwd=repo_cwd,
                events=[
                    {
                        "timestamp": "2026-04-19T01:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "stop_hook_judgment",
                            "turn_id": "turn-6",
                            "decision": "continue",
                            "status": "mode_end",
                            "mode": "end",
                            "rationale": "The task was already done for that turn.",
                        },
                    }
                ],
            )
            write_rollout(
                archived_root
                / "rollout-2026-04-18T08-00-00-019da555-5555-7555-8555-555555555555.jsonl",
                cwd=repo_cwd,
                events=[
                    {
                        "timestamp": "2026-04-18T02:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "stop_hook_judgment",
                            "turn_id": "turn-7",
                            "decision": "block",
                            "status": "mode_ask_user",
                            "mode": "ask_user",
                            "rationale": "The user still needed to choose a branch.",
                        },
                    }
                ],
            )

            report = run_observe(
                sessions_root=sessions_root,
                archived_sessions_root=archived_root,
                include_archived=True,
                cwd=repo_cwd,
                date_from="2026-04-18",
                date_to="2026-04-18",
                limit=4,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["files_considered"], 2)
        self.assertEqual(
            report["file_store_counts"],
            {"sessions": 1, "archived_sessions": 1},
        )
        self.assertEqual(report["judgment_count"], 1)
        self.assertEqual(report["mode_counts"], {"ask_user": 1})
        self.assertEqual(report["event_store_counts"], {"archived_sessions": 1})
        self.assertEqual(report["examples"][0]["event_date"], "2026-04-18")
        self.assertEqual(report["examples"][0]["session_store"], "archived_sessions")

    def test_run_observe_rejects_invalid_date_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sessions_root = Path(temp_dir) / "sessions"

            report = run_observe(
                sessions_root=sessions_root,
                date_from="2026-04-20",
                date_to="2026-04-19",
            )

        self.assertFalse(report["ok"])
        self.assertIn("date_from must be on or before date_to", report["error"])


if __name__ == "__main__":
    unittest.main()
