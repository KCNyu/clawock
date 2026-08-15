"""The 09:05 pass gets a second on-host re-run before the off-host fallback (#550).

2026-08-11/12 showed the failure chain: the 08:00 run died, the 08:30 re-run
queued but ITS run also failed, and by 09:05 there was no brief — the only
recovery left was the vendor fallback. A second on-host re-run at 09:05 is
cheaper than the fallback and lands well before the 10:00 HKT cutoff.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from clawock.harness import brief_watchdog as watchdog  # noqa: E402

HKT = timezone(timedelta(hours=8))
TODAY = "2026-08-12"
JOB_ID = "db3df0d0-7622-4b75-81ce-86d510eeef33"


def _job(**state):
    return {"id": JOB_ID, "name": "盘前深度简报", "enabled": True, "state": state}


def _watch(monkeypatch, tmp_path, job=None):
    spy = {}
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    monkeypatch.setattr(watchdog, "log", lambda event: spy.setdefault("logs", []).append(event))
    if job is not None:
        monkeypatch.setattr(watchdog, "brief_cron_job", lambda: job)
        monkeypatch.setattr(
            watchdog, "rerun_cron_job",
            lambda job_id, dry_run=False: (spy.setdefault("reruns", []).append(job_id), (True, "queued"))[1])
    monkeypatch.setattr(watchdog, "dispatch_brief_fallback", lambda dry_run=False: (True, "dispatched"))
    monkeypatch.setattr(watchdog, "send_telegram", lambda *a, **k: (True, "sent"))
    monkeypatch.setattr(watchdog, "write_missing_state", lambda *a, **k: None)
    monkeypatch.setattr(watchdog, "brief_cron_job_state", lambda: {})
    monkeypatch.setattr(watchdog, "await_brief_fallback_outcome", lambda *a, **k: (True, "ok"))
    return spy


def test_miss_detector_fires_second_rerun_before_fallback(monkeypatch, tmp_path):
    """08:30 already re-ran once (flag count=1): 09:05 queues attempt 2."""
    spy = _watch(monkeypatch, tmp_path, job=_job(lastStatus="error", consecutiveErrors=8))
    flag = watchdog.rerun_flag_path(TODAY)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("1")

    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0

    attempts = [e.get("attempt") for e in spy["logs"] if e.get("action") == "rerun-onhost"]
    assert attempts == [2]
    assert len(spy["reruns"]) == 1
    # the dedupe counter advanced
    assert watchdog._rerun_count(TODAY) == 2


def test_miss_detector_stops_after_two_reruns(monkeypatch, tmp_path):
    """Both on-host chances used: no third re-run, fallback still dispatched."""
    spy = _watch(monkeypatch, tmp_path, job=_job(lastStatus="error", consecutiveErrors=8))
    flag = watchdog.rerun_flag_path(TODAY)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("2")

    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0

    assert spy.get("reruns") or [] == []
    assert watchdog._rerun_count(TODAY) == 2


def test_miss_detector_without_schedule_still_alerts(monkeypatch, tmp_path):
    """Unreadable schedule must not block the alert: fallback + notification only."""
    spy = _watch(monkeypatch, tmp_path, job=None)  # brief_cron_job returns None

    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0

    assert spy.get("reruns") or [] == []
