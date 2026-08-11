"""await_brief_fallback_outcome must never report an unverified run as success.

The 2026-08-11 outage was not a missing check — it was a check that reported the
dispatch call's exit status and called that recovery. Every test here pins the
direction of the failure: when in doubt, not success.
"""
from datetime import datetime, timedelta, timezone

from clawock_kcnyu.harness import _watchdog_common as common


SINCE = "2026-08-11T01:05:00Z"
HKT = timezone(timedelta(hours=8))


class FakeClock:
    """Virtual time, so a 15-minute poll budget costs no wall clock in CI."""

    def __init__(self):
        self._t = datetime(2026, 8, 11, 9, 5, tzinfo=HKT)
        self.slept = []

    def now(self):
        return self._t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self._t += timedelta(seconds=seconds)


def _fake_gh(monkeypatch, pages):
    """Serve one `gh run list` JSON payload per poll, in order."""
    calls = {"n": 0}

    def gh_json(args, timeout=60):
        assert args[:2] == ["run", "list"]
        page = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return page

    monkeypatch.setattr(common, "_gh_json", gh_json)
    return calls


def test_completed_success_is_reported_as_success(monkeypatch):
    _fake_gh(monkeypatch, [[{
        "databaseId": 1, "status": "completed", "conclusion": "success",
        "url": "https://gh/run/1", "createdAt": "2026-08-11T01:05:04Z",
    }]])

    clock = FakeClock()
    assert common.await_brief_fallback_outcome(
        SINCE, budget_s=60, interval_s=30, sleep=clock.sleep, now=clock.now
    ) == ("success", "https://gh/run/1")


def test_completed_failure_is_reported_as_failure_with_the_reason(monkeypatch):
    _fake_gh(monkeypatch, [[{
        "databaseId": 2, "status": "completed", "conclusion": "failure",
        "url": "https://gh/run/2", "createdAt": "2026-08-11T01:05:04Z",
    }]])
    monkeypatch.setattr(common, "_gh_run_failure_detail",
                        lambda _run, **_kw: "plan.json v2 validation failed")

    clock = FakeClock()
    state, detail = common.await_brief_fallback_outcome(
        SINCE, budget_s=60, interval_s=30, sleep=clock.sleep, now=clock.now)
    assert state == "failure"
    assert "plan.json v2 validation failed" in detail


def test_a_run_that_never_completes_is_pending_not_success(monkeypatch):
    _fake_gh(monkeypatch, [[{
        "databaseId": 3, "status": "in_progress", "conclusion": None,
        "url": "https://gh/run/3", "createdAt": "2026-08-11T01:05:04Z",
    }]])
    clock = FakeClock()

    state, detail = common.await_brief_fallback_outcome(
        SINCE, budget_s=900, interval_s=30, sleep=clock.sleep, now=clock.now)

    assert state == "pending"
    assert "https://gh/run/3" in detail
    assert clock.slept, "should have polled rather than returning immediately"
    assert sum(clock.slept) <= 900, "must not poll past its own budget"


def test_a_run_created_before_our_dispatch_is_never_adopted(monkeypatch):
    """A stale green run from a previous day must not stand in for today's."""
    _fake_gh(monkeypatch, [[{
        "databaseId": 4, "status": "completed", "conclusion": "success",
        "url": "https://gh/run/old", "createdAt": "2026-08-10T02:38:41Z",
    }]])

    clock = FakeClock()
    state, detail = common.await_brief_fallback_outcome(
        SINCE, budget_s=60, interval_s=30, sleep=clock.sleep, now=clock.now)

    assert state == "unknown"
    assert "https://gh/run/old" not in detail


def test_gh_lookup_failure_is_unknown_not_success(monkeypatch):
    _fake_gh(monkeypatch, [None])
    clock = FakeClock()

    state, _detail = common.await_brief_fallback_outcome(
        SINCE, budget_s=60, interval_s=30, sleep=clock.sleep, now=clock.now)

    assert state == "unknown"


def test_a_queued_run_that_later_completes_is_picked_up(monkeypatch):
    _fake_gh(monkeypatch, [
        [{"databaseId": 5, "status": "queued", "conclusion": None,
          "url": "https://gh/run/5", "createdAt": "2026-08-11T01:05:04Z"}],
        [{"databaseId": 5, "status": "completed", "conclusion": "success",
          "url": "https://gh/run/5", "createdAt": "2026-08-11T01:05:04Z"}],
    ])

    clock = FakeClock()
    state, _detail = common.await_brief_fallback_outcome(
        SINCE, budget_s=600, interval_s=30, sleep=clock.sleep, now=clock.now)

    assert state == "success"
    assert clock.slept == [30], "should poll once, then see the completed run"


def test_dry_run_does_not_poll_and_does_not_claim_success(monkeypatch):
    def explode(*_a, **_kw):
        raise AssertionError("dry-run must not shell out to gh")

    monkeypatch.setattr(common, "_gh_json", explode)

    state, _detail = common.await_brief_fallback_outcome(SINCE, dry_run=True)
    assert state == "pending"


# The dispatch timestamp is written in HKT; GitHub reports createdAt in UTC. These
# describe the same instant 4 seconds apart, and a naive string compare ranks the
# UTC one first — which would discard the run we just fired, every single day.
HKT_DISPATCH = "2026-08-11T09:05:00.367448+08:00"
UTC_CREATED = "2026-08-11T01:05:04Z"


def test_the_run_we_just_dispatched_is_matched_across_timezone_forms(monkeypatch):
    _fake_gh(monkeypatch, [[{
        "databaseId": 9, "status": "completed", "conclusion": "failure",
        "url": "https://gh/run/9", "createdAt": UTC_CREATED,
    }]])
    monkeypatch.setattr(common, "_gh_run_failure_detail", lambda _run, **_kw: "boom")
    clock = FakeClock()

    # Bounded clock on purpose: if the match regresses, this must fail in a
    # millisecond rather than spin out the real 15-minute poll budget.
    state, _detail = common.await_brief_fallback_outcome(
        HKT_DISPATCH, budget_s=60, interval_s=30, sleep=clock.sleep, now=clock.now)

    assert state == "failure", (
        "a UTC createdAt must not sort before an HKT dispatch of the same instant"
    )


def test_a_genuinely_earlier_run_is_still_rejected_across_timezone_forms(monkeypatch):
    """The timezone fix must not weaken the stale-run guard it sits inside."""
    _fake_gh(monkeypatch, [[{
        "databaseId": 10, "status": "completed", "conclusion": "success",
        "url": "https://gh/run/old", "createdAt": "2026-08-10T02:38:41Z",
    }]])
    clock = FakeClock()

    state, _detail = common.await_brief_fallback_outcome(
        HKT_DISPATCH, budget_s=60, interval_s=30, sleep=clock.sleep, now=clock.now)

    assert state == "unknown"


def test_an_undated_run_is_never_adopted(monkeypatch):
    _fake_gh(monkeypatch, [[{
        "databaseId": 11, "status": "completed", "conclusion": "success",
        "url": "https://gh/run/undated", "createdAt": None,
    }]])
    clock = FakeClock()

    state, _detail = common.await_brief_fallback_outcome(
        HKT_DISPATCH, budget_s=60, interval_s=30, sleep=clock.sleep, now=clock.now)

    assert state == "unknown"
