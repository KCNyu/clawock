import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
from clawock_kcnyu.harness import brief_watchdog as watchdog  # noqa: E402


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


def test_dispatch_state_is_persisted_before_notification_and_timeout_is_retried(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    calls = {"dispatch": 0, "send": 0}

    def dispatch(_dry_run):
        calls["dispatch"] += 1
        return True, "workflow queued"

    def send(_target, _message, _dry_run):
        calls["send"] += 1
        state = json.loads(watchdog.missing_state_path(TODAY).read_text())
        assert state["fallback_dispatch_attempted"] is True
        assert state["fallback_dispatch_succeeded"] is True
        if calls["send"] == 1:
            raise subprocess.TimeoutExpired(["openclaw", "message", "send"], 60)
        return True, "telegram delivered"

    monkeypatch.setattr(watchdog, "dispatch_brief_fallback", dispatch)
    monkeypatch.setattr(watchdog, "send_telegram", send)
    monkeypatch.setattr(watchdog, "log", lambda _event: None)

    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0
    state = json.loads(watchdog.missing_state_path(TODAY).read_text())
    assert calls == {"dispatch": 1, "send": 2}
    assert state["notification_attempts"] == 2
    assert state["notification_succeeded"] is True
    assert "telegram delivered" in state["notification_out"]


def test_failed_notification_can_retry_later_without_redispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    calls = {"dispatch": 0, "send": 0}

    def dispatch(_dry_run):
        calls["dispatch"] += 1
        return True, "workflow queued"

    def send_fails(_target, _message, _dry_run):
        calls["send"] += 1
        return False, "telegram unavailable"

    monkeypatch.setattr(watchdog, "dispatch_brief_fallback", dispatch)
    monkeypatch.setattr(watchdog, "send_telegram", send_fails)
    monkeypatch.setattr(watchdog, "log", lambda _event: None)

    assert watchdog.alert_brief_missing(TODAY, False, ["plan_missing"]) == 0
    assert calls == {"dispatch": 1, "send": 2}
    state = json.loads(watchdog.missing_state_path(TODAY).read_text())
    assert state["fallback_dispatch_succeeded"] is True
    assert state["notification_succeeded"] is False

    monkeypatch.setattr(
        watchdog, "send_telegram",
        lambda *_args: calls.__setitem__("send", calls["send"] + 1) or (True, "ok"),
    )
    assert watchdog.alert_brief_missing(TODAY, False, ["plan_missing"]) == 0
    assert calls == {"dispatch": 1, "send": 3}
    state = json.loads(watchdog.missing_state_path(TODAY).read_text())
    assert state["notification_attempts"] == 3
    assert state["notification_succeeded"] is True


def test_dry_run_does_not_poison_recovery_state_or_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    monkeypatch.setattr(
        watchdog, "dispatch_brief_fallback", lambda _dry_run: (True, "dry dispatch")
    )
    monkeypatch.setattr(
        watchdog, "send_telegram", lambda *_args: (True, "dry telegram")
    )
    monkeypatch.setattr(watchdog, "log", lambda _event: None)

    assert watchdog.alert_brief_missing(TODAY, True, ["brief_missing"]) == 0
    assert not watchdog.missing_state_path(TODAY).exists()
    assert not (
        tmp_path / "memory" / ".tmp" / f"watchdog-brief-missing-{TODAY}.done"
    ).exists()


def test_corrupt_state_suppresses_duplicate_dispatch_but_still_notifies(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    path = watchdog.missing_state_path(TODAY)
    path.parent.mkdir(parents=True)
    path.write_text("{bad json")
    calls = {"dispatch": 0, "send": 0}
    monkeypatch.setattr(
        watchdog,
        "dispatch_brief_fallback",
        lambda _dry_run: calls.__setitem__("dispatch", calls["dispatch"] + 1)
        or (True, "should not run"),
    )
    monkeypatch.setattr(
        watchdog,
        "send_telegram",
        lambda *_args: calls.__setitem__("send", calls["send"] + 1) or (True, "ok"),
    )
    monkeypatch.setattr(watchdog, "log", lambda _event: None)

    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0
    assert calls == {"dispatch": 0, "send": 1}
    state = json.loads(path.read_text())
    assert state["fallback_dispatch_attempted"] is True
    assert "state_error" in state
