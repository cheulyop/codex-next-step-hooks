from __future__ import annotations

import json
import urllib.request
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def hook_path() -> Path:
    return package_root() / "src/codex_click_chooser_hooks/hooks/stop_require_request_user_input.py"


def default_case_path() -> Path:
    return package_root() / "tests/explanatory_closure_should_request.json"


def default_case_paths() -> list[Path]:
    return sorted((package_root() / "tests").glob("*.json"))


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def load_case(case_path: Path | None = None) -> dict[str, Any]:
    path = case_path or default_case_path()
    with path.open() as handle:
        case = json.load(handle)
    transcript_path = Path(case["transcript_path"])
    if not transcript_path.is_absolute():
        case["transcript_path"] = str(package_root() / transcript_path)
    return case


def run_selftest_case(case_path: Path | None = None) -> dict[str, Any]:
    case = load_case(case_path)
    hook = SourceFileLoader("packaged_stop_hook", str(hook_path())).load_module()

    payload = dict(case["payload"])
    payload["transcript_path"] = case["transcript_path"]
    captured_request: dict[str, Any] = {}

    original_urlopen = urllib.request.urlopen

    def fake_urlopen(request: Any, timeout: float = 0) -> FakeHTTPResponse:
        del timeout
        body = json.loads(request.data.decode("utf-8"))
        captured_request["body"] = body
        return FakeHTTPResponse({"output_text": json.dumps(case["judge_result"])})

    urllib.request.urlopen = fake_urlopen
    try:
        should_continue = hook.should_continue(payload)
    finally:
        urllib.request.urlopen = original_urlopen

    expected = case["expected"]
    actual_decision = "continue" if should_continue else "block"
    failures: list[str] = []

    if actual_decision != expected["decision"]:
        failures.append(
            f"decision mismatch: expected {expected['decision']}, got {actual_decision}"
        )

    context_text = captured_request["body"]["input"][1]["content"][0]["text"]
    for needle in expected.get("context_contains", []):
        if needle not in context_text:
            failures.append(f"context missing: {needle}")

    reason_text = ""
    if actual_decision == "block":
        reason_text = hook.build_block_reason(
            payload["_judgment"], payload.get("_recent_choosers", [])
        )
        for needle in expected.get("reason_contains", []):
            if needle not in reason_text:
                failures.append(f"reason missing: {needle}")

    result = {
        "ok": not failures,
        "case": case["name"],
        "decision": actual_decision,
        "failures": failures,
        "captured_context_preview": context_text[:1000],
    }
    if reason_text:
        result["block_reason_preview"] = reason_text[:1000]
    return result


def run_selftest(case_path: Path | None = None) -> dict[str, Any]:
    if case_path is not None:
        return run_selftest_case(case_path)

    case_paths = default_case_paths()
    if not case_paths:
        return {
            "ok": False,
            "case_count": 0,
            "cases": [],
            "error": "no self-test case files were found under tests/",
        }

    results = [run_selftest_case(path) for path in case_paths]
    return {
        "ok": all(item.get("ok") for item in results),
        "case_count": len(results),
        "cases": results,
    }
