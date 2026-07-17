import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "harness"))

import brief_watchdog as watchdog  # noqa: E402


TODAY = "2026-07-17"


def _write_brief(ws):
    path = ws / "memory" / f"{TODAY}-pre-open.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# brief")


def _write_plan(ws, decisions):
    path = ws / "memory" / f"{TODAY}-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 2, "decisions": decisions}))


def test_0905_detects_brief_present_plan_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    _write_brief(tmp_path)

    assert watchdog.inspect_brief_artifacts(TODAY) == ["plan_missing"]


def test_0905_detects_empty_plan_as_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    _write_brief(tmp_path)
    _write_plan(tmp_path, [])

    assert watchdog.inspect_brief_artifacts(TODAY) == ["plan_invalid"]


def test_0905_accepts_brief_and_nonempty_v2_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    _write_brief(tmp_path)
    _write_plan(tmp_path, [{"action": "hold_and_watch"}])

    assert watchdog.inspect_brief_artifacts(TODAY) == []


def test_missing_alert_dispatches_only_once_after_success(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    calls = {"dispatch": 0, "send": 0}

    def dispatch(_dry_run):
        calls["dispatch"] += 1
        return True, "ok"

    def send(_target, _message, _dry_run):
        calls["send"] += 1
        return True, "ok"

    monkeypatch.setattr(watchdog, "dispatch_brief_fallback", dispatch)
    monkeypatch.setattr(watchdog, "send_telegram", send)
    monkeypatch.setattr(watchdog, "log", lambda _event: None)

    issues = ["plan_missing"]
    assert watchdog.alert_brief_missing(TODAY, False, issues) == 0
    assert watchdog.alert_brief_missing(TODAY, False, issues) == 0
    assert calls == {"dispatch": 1, "send": 1}
