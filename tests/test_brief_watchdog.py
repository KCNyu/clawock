import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
from clawock.harness import brief_watchdog as watchdog  # noqa: E402


TODAY = "2026-07-17"


@pytest.fixture(autouse=True)
def _no_live_scheduler(monkeypatch):
    """The 09:05 alert asks the scheduler for the job's retry budget (#506).

    Unstubbed that is a real `openclaw cron list --json` round trip — 3s per
    test against whatever the live gateway happens to hold, or a timeout on a
    host where the binary exists and the gateway does not. The budget line has
    its own suite; here the scheduler is simply absent, which is the case that
    must leave every assertion below unchanged.
    """
    monkeypatch.setattr(watchdog, "brief_cron_job", lambda: None)


def _stub_outcome(monkeypatch, outcome="success", detail="https://example/run/1"):
    """Neutralise the post-dispatch poll. Tests that care assert on it explicitly.

    Without this the alert path would shell out to `gh` from the test suite."""
    monkeypatch.setattr(
        watchdog, "await_brief_fallback_outcome",
        lambda _since, _dry_run, **_kw: (outcome, detail),
    )


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
    _stub_outcome(monkeypatch)

    issues = ["plan_missing"]
    assert watchdog.alert_brief_missing(TODAY, False, issues) == 0
    assert watchdog.alert_brief_missing(TODAY, False, issues) == 0
    # 2 sends on the first pass: the 09:05 miss alert, then the outcome follow-up.
    assert calls == {"dispatch": 1, "send": 2}


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
    _stub_outcome(monkeypatch)

    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0
    state = json.loads(watchdog.missing_state_path(TODAY).read_text())
    assert calls == {"dispatch": 1, "send": 3}
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
    _stub_outcome(monkeypatch)

    assert watchdog.alert_brief_missing(TODAY, False, ["plan_missing"]) == 0
    assert calls == {"dispatch": 1, "send": 3}
    state = json.loads(watchdog.missing_state_path(TODAY).read_text())
    assert state["fallback_dispatch_succeeded"] is True
    assert state["notification_succeeded"] is False

    monkeypatch.setattr(
        watchdog, "send_telegram",
        lambda *_args: calls.__setitem__("send", calls["send"] + 1) or (True, "ok"),
    )
    assert watchdog.alert_brief_missing(TODAY, False, ["plan_missing"]) == 0
    assert calls == {"dispatch": 1, "send": 5}
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
    _stub_outcome(monkeypatch, "pending", "(dry-run) outcome polling skipped")

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
    _stub_outcome(monkeypatch)

    # dispatched is False here, so there is no run to poll and no follow-up.
    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0
    assert calls == {"dispatch": 0, "send": 1}
    state = json.loads(path.read_text())
    assert state["fallback_dispatch_attempted"] is True
    assert "state_error" in state


def _run_alert_capturing_messages(monkeypatch, tmp_path, outcome, detail):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    messages = []
    monkeypatch.setattr(
        watchdog, "dispatch_brief_fallback", lambda _dry_run: (True, "queued")
    )
    monkeypatch.setattr(
        watchdog, "send_telegram",
        lambda _target, message, _dry_run: (messages.append(message), (True, "ok"))[1],
    )
    monkeypatch.setattr(watchdog, "log", lambda _event: None)
    _stub_outcome(monkeypatch, outcome, detail)
    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0
    return messages


def test_the_dispatched_run_url_is_handed_to_the_outcome_poll(tmp_path, monkeypatch):
    """#512's fix is only real if the wiring carries it.

    `await_brief_fallback_outcome` can read the outcome straight from the run the
    dispatch named, but only if this caller passes that URL down. The stub in
    `_stub_outcome` accepts any kwargs, so nothing else in this file would notice
    the argument being dropped — and a dropped argument silently returns the whole
    path to the timestamp heuristic that #512 is about.
    """
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    run_url = "https://github.com/KCNyu/clawock/actions/runs/31656565034\n"
    seen = {}
    monkeypatch.setattr(
        watchdog, "dispatch_brief_fallback", lambda _dry_run: (True, run_url)
    )
    monkeypatch.setattr(watchdog, "send_telegram", lambda *_args: (True, "ok"))
    monkeypatch.setattr(watchdog, "log", lambda _event: None)
    monkeypatch.setattr(
        watchdog, "await_brief_fallback_outcome",
        lambda _since, _dry_run, **kw: (seen.update(kw), ("success", run_url))[1],
    )

    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0

    assert seen.get("dispatch_out") == run_url


def test_a_failed_fallback_run_is_reported_as_failed_not_as_dispatched_ok(
    tmp_path, monkeypatch
):
    """2026-08-11 regression: dispatch succeeded, the run failed 8 min later, and the
    only thing kcn was told was a green check. The follow-up must name the failure."""
    messages = _run_alert_capturing_messages(
        monkeypatch, tmp_path, "failure",
        "failure https://gh/run/1 plan.json v2 validation failed",
    )

    assert len(messages) == 2
    first, follow_up = messages
    # The 09:05 alert may say a dispatch happened, but must not claim it will land.
    assert "落盘并 push" not in first
    assert "🔴 off-host 兜底失败" in follow_up
    assert "plan.json v2 validation failed" in follow_up
    assert "✅" not in follow_up


def test_unfinished_fallback_run_is_reported_as_unverified_never_as_success(
    tmp_path, monkeypatch
):
    messages = _run_alert_capturing_messages(
        monkeypatch, tmp_path, "pending", "still in_progress after 15min: https://gh/2"
    )

    follow_up = messages[-1]
    assert "未确认" in follow_up
    assert "这不代表成功" in follow_up
    assert "✅" not in follow_up


def test_successful_fallback_run_is_the_only_case_that_claims_the_brief_exists(
    tmp_path, monkeypatch
):
    messages = _run_alert_capturing_messages(
        monkeypatch, tmp_path, "success", "https://gh/run/3"
    )

    follow_up = messages[-1]
    assert follow_up.startswith("✅ off-host 兜底已完成")
    assert "https://gh/run/3" in follow_up


def test_outcome_is_persisted_so_a_later_pass_can_see_what_happened(
    tmp_path, monkeypatch
):
    _run_alert_capturing_messages(
        monkeypatch, tmp_path, "failure", "failure https://gh/run/4"
    )

    state = json.loads(watchdog.missing_state_path(TODAY).read_text())
    assert state["fallback_outcome"] == "failure"
    assert "https://gh/run/4" in state["fallback_outcome_detail"]
