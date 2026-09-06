"""Cron health: what counts as evidence that a scheduled job did its work."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "host"))

import cron_health_check  # noqa: E402

HKT = ZoneInfo("Asia/Hong_Kong")


class _Runs:
    def __init__(self, runs):
        self._runs = runs

    def history(self, job, limit=20):
        return self._runs


def _run(status, when):
    return SimpleNamespace(status=status, started_at=when.isoformat())


def test_the_run_provider_is_advisory_and_can_never_fail_the_check():
    """#262 prerequisite. Today the commit IS the receipt, so moving the outputs
    off master makes every job with a commit contract report a false miss.

    The provider answers a DIFFERENT question though — "did the job run", not
    "did the job produce" — so it lands as a second signal to be compared before
    anything depends on it. An advisory signal that can break the health check is
    worse than no advisory signal.
    """
    class Exploding:
        def history(self, job, limit=20):
            raise RuntimeError("provider down")

    assert cron_health_check.runs_finished_today("job", Exploding()) is None
    assert cron_health_check.runs_finished_today(None) is None, (
        "a job with no id has no provider evidence, which is not the same as zero")


def test_only_todays_finished_runs_count_as_evidence():
    today = datetime.now(HKT)
    provider = _Runs([
        _run("ok", today),
        _run("ok", today),
        _run("error", today),                      # ran, did not succeed
        _run("running", today),                    # not finished
        _run("ok", today - timedelta(days=1)),     # yesterday is not today's evidence
    ])

    assert cron_health_check.runs_finished_today("job", provider) == 2


# ── #338: the publisher's only liveness signal ──────────────────────────────
# #325 moved the outputs off master, which removed the `dashboard: scheduled
# publish` commits kcn actually used to see the crontab entry was alive. The
# published generation's own age is the replacement.
def _generation(tmp_path, published_at):
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps({"generated_at": published_at.isoformat()}))
    return path


def test_a_frozen_generation_on_a_trading_day_is_reported():
    # 2026-08-05 is a Wednesday and a session in both markets.
    now = datetime(2026, 8, 5, 16, 0, tzinfo=timezone.utc)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        stale = _generation(Path(d), now - timedelta(hours=4))
        result = cron_health_check.check_scheduled_publisher(now=now, path=stale)
    assert result["state"] == "stale"
    assert result["age_hours"] == 4.0


def test_a_quiet_tick_is_not_a_dead_publisher():
    # The publisher only pushes when the semantic diff changed, so a generation
    # that is merely an hour old is healthy — flagging it would red the workflow
    # on every calm session.
    now = datetime(2026, 8, 5, 16, 0, tzinfo=timezone.utc)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        fresh = _generation(Path(d), now - timedelta(hours=1))
        result = cron_health_check.check_scheduled_publisher(now=now, path=fresh)
    assert result["state"] == "ok"



# ── #696: a Telegram backstop delivery must not read as total non-delivery ──
# report_watchdog.py's Telegram mirror is deliberately commit-free (2026-07-09
# kcn's call: no WeChat resend, so no publish either), so commit-counting alone
# cannot tell "watchdog recovered it" apart from "kcn got nothing" — both showed
# up as the same red. backstop_covered_slots reads the one ledger that can.
def _outcomes(records):
    return {"schema_version": 1, "records": records}


def _outcome_record(job, slot_iso, final_status):
    return {
        "job": job,
        "slot": slot_iso,
        "final_product": {"status": final_status},
    }


def test_backstop_covered_slots_finds_a_recovered_slot():
    from datetime import date
    outcomes = _outcomes([
        _outcome_record("港股午后快报", "2026-08-14T13:11:00+08:00", "recovered"),
    ])
    covered = cron_health_check.backstop_covered_slots(
        "港股午后快报", ["13:11"], "Asia/Hong_Kong", outcomes,
        today=date(2026, 8, 14))
    assert covered == {"13:11"}


def test_backstop_covered_slots_ignores_other_jobs_and_non_recovered_status():
    outcomes = _outcomes([
        _outcome_record("美股收盘报告", "2026-08-14T13:11:00+08:00", "recovered"),  # wrong job
        _outcome_record("港股午后快报", "2026-08-14T13:11:00+08:00", "degraded"),  # not recovered
    ])
    covered = cron_health_check.backstop_covered_slots(
        "港股午后快报", ["13:11"], "Asia/Hong_Kong", outcomes)
    assert covered == set()


def test_backstop_covered_slots_returns_empty_without_a_ledger():
    assert cron_health_check.backstop_covered_slots(
        "港股午后快报", ["13:11"], "Asia/Hong_Kong", None) == set()


def test_backstop_covered_slots_ignores_a_stale_recovered_record_from_another_day():
    """The ledger keeps 96h of history (workflow_outcomes.KEEP_HOURS), so a
    same-clock-time recovery from an earlier day must not paper over a genuine
    miss today — HH:MM alone is not enough, the date has to match too."""
    from datetime import date
    outcomes = _outcomes([
        _outcome_record("港股午后快报", "2026-08-13T13:11:00+08:00", "recovered"),
    ])
    covered = cron_health_check.backstop_covered_slots(
        "港股午后快报", ["13:11"], "Asia/Hong_Kong", outcomes,
        today=date(2026, 8, 14))
    assert covered == set()


# ── #1278 follow-up: a schedule move must not paint every heartbeat slot red ──
# `cron_heartbeat.slot_for()` buckets every event onto the half-hour grid
# (:00/:30), independent of the minute the job actually fired on. #1278 moved
# 盘中盯盘/美股盘中盯盘/美股盘中盯盘-overnight's `expr` to `3,33` specifically to
# dodge MiniMax's on-the-hour congestion, so the slots this check expects are
# now minutes off that grid. An exact HH:MM join (the pre-fix behaviour) would
# never match a single event, painting the whole day red for a job that ran
# fine — the same failure `cron_schedule._records_by_slot` was already fixed
# for on the dashboard timetable panel; these tests hold the health check to
# the same standard.
def _heartbeat_ledger(events):
    return {
        "schema_version": 1,
        "monitoring_started_at": "2026-09-01T00:00:00+08:00",
        "events": events,
    }


def _heartbeat_event(job, slot_iso, state="completed"):
    return {"job": job, "slot": slot_iso, "state": state}


def test_heartbeat_events_snap_to_the_grid_so_a_schedule_move_is_not_all_missed():
    from datetime import date
    ledger = _heartbeat_ledger([
        _heartbeat_event("美股盘中盯盘-overnight", "2026-09-04T00:00:00+08:00"),
        _heartbeat_event("美股盘中盯盘-overnight", "2026-09-04T00:30:00+08:00"),
    ])
    now = datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc)  # 09:00 HKT
    coverage = cron_health_check.heartbeat_coverage(
        "美股盘中盯盘-overnight", ["00:03", "00:33"], "Asia/Hong_Kong", now, ledger,
        day=date(2026, 9, 4))
    assert coverage["missing"] == []
    assert sorted(coverage["healthy"]) == ["00:03", "00:33"]


def test_heartbeat_snapping_never_lets_one_event_answer_for_two_slots():
    from datetime import date
    # A single event exactly between two expected slots must not satisfy both.
    ledger = _heartbeat_ledger([
        _heartbeat_event("盘中盯盘", "2026-09-04T10:15:00+08:00"),
    ])
    now = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)  # 11:00 HKT
    coverage = cron_health_check.heartbeat_coverage(
        "盘中盯盘", ["10:03", "10:33"], "Asia/Hong_Kong", now, ledger,
        day=date(2026, 9, 4))
    assert len(coverage["healthy"]) == 1
    assert len(coverage["missing"]) == 1


def test_a_heartbeat_slot_with_no_event_anywhere_near_it_still_reports_missing():
    from datetime import date
    ledger = _heartbeat_ledger([
        _heartbeat_event("盘中盯盘", "2026-09-04T10:00:00+08:00"),
        # 10:30 never ran — nothing within tolerance of it.
    ])
    now = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)  # 11:00 HKT
    coverage = cron_health_check.heartbeat_coverage(
        "盘中盯盘", ["10:03", "10:33"], "Asia/Hong_Kong", now, ledger,
        day=date(2026, 9, 4))
    assert coverage["healthy"] == ["10:03"]
    assert coverage["missing"] == ["10:33"]


def test_a_closed_weekend_is_silence_by_design():
    # 2026-08-09 12:00 HKT is a Sunday: no session to publish into, so an old
    # generation is correct and must not be reported as a stalled publisher.
    # (UTC, not HKT — 16:00 UTC on a Sunday is already Monday in Hong Kong.)
    now = datetime(2026, 8, 9, 4, 0, tzinfo=timezone.utc)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        stale = _generation(Path(d), now - timedelta(hours=30))
        result = cron_health_check.check_scheduled_publisher(now=now, path=stale)
    assert result["state"] == "ok"
    assert "非交易日" in result["detail"]


def test_commit_evidence_is_fetched_once_not_once_per_job(monkeypatch):
    """Eleven enabled jobs used to mean eleven near-identical `git log`
    subprocesses; the job loop now shares a single fetch."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        stamp = datetime.now(HKT).isoformat()
        return SimpleNamespace(
            returncode=0,
            stdout=f"{stamp}\x00dashboard: 港股收盘报告 (hk 15:06 HKT)\n",
        )

    monkeypatch.setattr(cron_health_check.subprocess, "run", fake_run)
    monkeypatch.setattr(cron_health_check, "_commit_log_cache", None)

    patterns = ["港股收盘报告", "港股收盘报告", "美股.*收盘", "no-such-pattern"]
    counts = [cron_health_check.commit_count_today(p) for p in patterns]

    assert counts == [1, 1, 0, 0]
    assert len(calls) == 1


def test_commit_evidence_degrades_to_zero_when_git_fails(monkeypatch):
    monkeypatch.setattr(cron_health_check, "_commit_log_cache", None)
    monkeypatch.setattr(
        cron_health_check.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=128, stdout=""))
    assert cron_health_check.commit_count_today("anything") == 0


# ── #955: cross-midnight US jobs are judged on their SESSION day ────────────
# 美股盘中盯盘-overnight (00:00–02:30 HKT dow 2-6) and 美股收盘报告 (04:00 HKT
# dow 2-6) monitor the PREVIOUS day's US session — the dow mask reaches into
# Saturday precisely because the session crosses HKT midnight (#454's rule).
# Judging on the slot's own calendar date got both directions wrong: every
# Saturday read as "US closed" so the Friday-session slots were written into
# the ledgers and verified by no one, while a US holiday's own preflight skip
# surfaced as a missing report on the next trading morning.

_CONTRACT = ROOT / "config" / "cron-schedules.json"


def _run_health_at(monkeypatch, capsys, now_utc, *, heartbeats=None,
                   commit_stamps=()):
    """Drive cron_health_check.main() against the real contract at a frozen instant."""
    ledger = {
        "schema_version": 1,
        "monitoring_started_at": "2026-08-01T00:00:00+08:00",
        "events": [
            {"job": job, "slot": slot, "state": state}
            for job, slot, state in (heartbeats or [])
        ],
    }
    import tempfile
    handle, hb_name = tempfile.mkstemp(suffix=".json")
    hb = Path(hb_name)
    hb.write_text(json.dumps(ledger))
    out_file = hb.with_name("outcomes.json")
    out_file.write_text(json.dumps({"schema_version": 1, "records": []}))

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now_utc if tz is None else now_utc.astimezone(tz)

    monkeypatch.setattr(cron_health_check, "datetime", _Frozen)
    # The holiday gate must judge the frozen instant, not the real wall clock:
    # is_trading_day(market) with no date falls back to sessions' own "today".
    from clawock import sessions as _sessions
    monkeypatch.setattr(
        _sessions, "_today_in_market",
        lambda market: now_utc.astimezone(ZoneInfo(
            "America/New_York" if market == "us" else "Asia/Hong_Kong")).date())
    cache = [(stamp, subject) for stamp, subject in commit_stamps] or None
    monkeypatch.setattr(cron_health_check, "_commit_log_cache",
                        [] if commit_stamps == () else cache)
    monkeypatch.setattr(cron_health_check, "check_dashboard_build",
                        lambda: {"state": "absent", "detail": "t", "age_hours": None})
    monkeypatch.setattr(cron_health_check, "check_scheduled_publisher",
                        lambda now=None, path=None: {"state": "ok", "detail": "t",
                                                     "age_hours": 1.0})
    monkeypatch.setattr(sys, "argv", [
        "cron_health_check.py", "--json",
        "--jobs-file", str(_CONTRACT),
        "--heartbeats-file", str(hb),
        "--outcomes-file", str(out_file),
    ])
    try:
        cron_health_check.main()
    except SystemExit as exc:  # exit codes are asserted nowhere here; the row
        assert exc.code in (0, 1, 2), exc  # statuses above carry the verdicts
    return {r["name"]: r for r in json.loads(capsys.readouterr().out)["jobs"]}


def _overnight_slots():
    """The six Saturday-2026-08-22 overnight slots, all completed."""
    return [
        ("美股盘中盯盘-overnight", f"2026-08-22T0{h}:{m:02d}:00+08:00", "completed")
        for h, m in ((0, 3), (0, 33), (1, 3), (1, 33), (2, 3), (2, 33))
    ]


def test_saturday_run_verifies_the_friday_session_slots(monkeypatch, capsys):
    """Sat 2026-08-22 17:17 HKT after a normal Friday session: the six overnight
    slots are heartbeat-verified and the close report's 04:03 commit is counted —
    not waved off as 'holiday' by a calendar that only knows Saturday is closed."""
    rows = _run_health_at(
        monkeypatch, capsys,
        datetime(2026, 8, 22, 9, 17, tzinfo=timezone.utc),
        heartbeats=_overnight_slots(),
        commit_stamps=[("2026-08-22T04:09:00+08:00", "dashboard: 美股收盘报告 (us close)")],
    )
    overnight = rows["美股盘中盯盘-overnight"]
    assert overnight["status"] == "ok-heartbeat", overnight
    assert "6/6" in overnight["detail"]
    close = rows["美股收盘报告"]
    assert close["status"] == "ok", close
    assert "1/1 commits OK" in close["detail"]


def test_a_us_holiday_session_suppresses_its_saturday_slots_without_a_red(monkeypatch, capsys):
    """Sat 2026-07-04 17:17 HKT: Friday Jul 3 was Independence Day (observed), so
    the session genuinely did not happen — 'holiday' is correct and must not be
    reported as a miss even though no Saturday evidence exists."""
    rows = _run_health_at(
        monkeypatch, capsys, datetime(2026, 7, 4, 9, 17, tzinfo=timezone.utc))
    assert rows["美股盘中盯盘-overnight"]["status"] == "holiday"
    assert rows["美股收盘报告"]["status"] == "holiday"


def test_a_monday_holiday_does_not_red_the_tuesday_close_report(monkeypatch, capsys):
    """Tue 2026-05-26 17:17 HKT: Monday May 25 was Memorial Day, so preflight had
    skipped the Tue 04:00 close slot by design. The old gate judged Tuesday's own
    calendar (a trading day) and read that skip as a missing commit."""
    rows = _run_health_at(
        monkeypatch, capsys, datetime(2026, 5, 26, 9, 17, tzinfo=timezone.utc))
    assert rows["美股收盘报告"]["status"] == "holiday"
    assert rows["美股盘中盯盘-overnight"]["status"] == "holiday"


# ── #996: the US EVENING jobs are verified by the NEXT day's run ────────────
# 美股开盘报告 (21:33/22:33 HKT) and the 美股盘中盯盘 evening half-hour slots fire
# after every cron-health window of their own calendar day (17:17 HKT, worst
# observed drift ≈20:35), and both evidence sources read only TODAY — so their
# products landed in the ledgers and were verified by no one, the weekday-wide
# version of #955's Saturday hole.

def _evening_slots():
    """Monday 2026-08-24's four US evening intraday slots, all completed."""
    return [
        ("美股盘中盯盘", f"2026-08-24T2{h}:{m:02d}:00+08:00", "completed")
        for h, m in ((2, 3), (2, 33), (3, 3), (3, 33))
    ]


def test_the_next_days_run_verifies_the_previous_evening_products(monkeypatch, capsys):
    """Tue 17:17 HKT after a normal Monday: Monday evening's open-report commit
    and intraday heartbeats must be counted — not waved through as 'idle'."""
    rows = _run_health_at(
        monkeypatch, capsys,
        datetime(2026, 8, 25, 9, 17, tzinfo=timezone.utc),
        heartbeats=_evening_slots(),
        commit_stamps=[("2026-08-24T21:36:00+08:00",
                        "dashboard: 美股开盘报告 (us open 21:33 HKT)")],
    )
    open_row = rows["美股开盘报告"]
    assert open_row["status"] == "ok", open_row
    assert "1/1 commits OK" in open_row["detail"]
    intraday = rows["美股盘中盯盘"]
    assert intraday["status"] == "ok-heartbeat", intraday
    assert "4/4" in intraday["detail"]


def test_a_missing_previous_evening_commit_is_a_miss_not_idle(monkeypatch, capsys):
    """Anti-idle: with no matching commit from Monday evening, the open report
    reads as MISSING on Tuesday — the verdict that never fired before."""
    rows = _run_health_at(
        monkeypatch, capsys,
        datetime(2026, 8, 25, 9, 17, tzinfo=timezone.utc),
        heartbeats=_evening_slots(),
        commit_stamps=[("2026-08-24T21:36:00+08:00", "dashboard: 港股收盘报告")],
    )
    assert rows["美股开盘报告"]["status"] == "missing", rows["美股开盘报告"]


def test_a_us_holiday_suppresses_the_previous_evening_slots_without_a_red(monkeypatch, capsys):
    """Tue 2026-05-26 17:17 HKT: Monday May 25 (Memorial Day) had no US session,
    so Monday evening's open report was skipped by design — the verify-day gate
    asks MONDAY's calendar and stays quiet despite zero evidence."""
    rows = _run_health_at(
        monkeypatch, capsys, datetime(2026, 5, 26, 9, 17, tzinfo=timezone.utc))
    assert rows["美股开盘报告"]["status"] == "holiday"
    assert rows["美股盘中盯盘"]["status"] == "holiday"


# --- publish backlog (#1241) ------------------------------------------------
#
# This gate runs on GitHub Actions, against artifacts that were *published*. A
# checkout that commits and never pushes looks from here exactly like one that
# had nothing to say — which is how six commits sat unpushed for eight hours on
# 2026-08-31 while `data-plane` published on schedule and every visible surface
# stayed green. Only the host can measure it; it carries the number in the
# heartbeat and these read it.

#: The heartbeats below are written between 10:00 and 19:00 HKT on 2026-08-31;
#: judge them from that evening, i.e. while they still describe the machine.
_JUDGED_AT = datetime(2026, 8, 31, 20, 0, tzinfo=ZoneInfo("Asia/Hong_Kong"))


def _ledger(*counts):
    return {"events": [{"slot": f"2026-08-31T1{i}:00:00+08:00",
                        "updated_at": f"2026-08-31T1{i}:05:00+08:00",
                        **({} if count is None else {"unpushed_commits": count})}
                       for i, count in enumerate(counts)]}


def test_a_backlog_the_size_of_the_incident_is_degraded():
    result = cron_health_check.publish_backlog(_ledger(0, 6), now=_JUDGED_AT)

    assert result["state"] == "degraded"
    assert result["count"] == 6
    assert "never published" in result["detail"]


def test_a_normal_publish_cycle_is_not_a_backlog():
    assert cron_health_check.publish_backlog(
        _ledger(0, 1), now=_JUDGED_AT)["state"] == "ok"


def test_only_the_newest_heartbeat_that_carries_the_field_decides():
    """An old degraded reading must not outlive the recovery that followed it."""
    result = cron_health_check.publish_backlog(_ledger(9, 9, 0), now=_JUDGED_AT)

    assert (result["state"], result["count"]) == ("ok", 0)


def test_a_reading_older_than_the_heartbeats_that_refresh_it_is_not_now():
    """Measured 2026-09-06: the line read "6 commit(s) committed here and never
    published — check what pre-push is refusing" all weekend, off a Friday 02:43
    heartbeat, while `origin/master..HEAD` had been 0 for over a day. Only the
    intraday postflight writes this number, and those crons do not run on a
    closed market, so the reading ages every weekend by design.

    An instruction to go look at something that is not wrong is how a health
    line stops being read.
    """
    stale = _JUDGED_AT + timedelta(hours=40)
    result = cron_health_check.publish_backlog(_ledger(0, 6), now=stale)

    assert result["state"] == "stale-measurement"
    assert result["count"] == 6, "the last reading is still worth carrying"
    assert result["age_hours"] > cron_health_check.BACKLOG_MEASUREMENT_MAX_AGE_H
    assert "history not now" in result["detail"]
    assert "pre-push" not in result["detail"], (
        "a stale reading must not tell anyone to go check a refusal that has "
        "had a day and a half to clear")


def test_a_stale_reading_is_printed_as_nothing_to_do():
    """`⚠` is a claim that something is wrong, and "I last looked on Friday" is
    not one. The host measures this live every twenty minutes in
    `system_check.check_publish_backlog`, so the mirror escalating its own
    unknown would fire every weekend and mean nothing both times."""
    assert cron_health_check.DASHBOARD_STATE_ICONS["stale-measurement"] == "·"
    assert cron_health_check.publish_backlog(
        _ledger(0, 6), now=_JUDGED_AT + timedelta(hours=40)
    )["state"] != "degraded", "only a fresh reading may escalate"


def test_a_measurement_with_no_timestamp_is_still_judged():
    """`updated_at` is the write time and `slot` the boundary it belongs to;
    an event carrying neither cannot be aged, and a backlog that cannot be aged
    is still a backlog."""
    ledger = {"events": [{"unpushed_commits": 6}]}

    assert cron_health_check.publish_backlog(ledger, now=_JUDGED_AT)["state"] == (
        "degraded")


def test_a_host_that_cannot_measure_it_is_absent_not_zero():
    """The failure being guarded is a lane that looked fine because nobody looked.

    Reporting `absent` as `0 unpushed` would rebuild exactly that.
    """
    assert cron_health_check.publish_backlog(_ledger(None, None))["state"] == "absent"
    assert cron_health_check.publish_backlog({"events": []})["state"] == "absent"
    assert cron_health_check.publish_backlog({})["count"] is None


def test_the_host_measurement_says_none_rather_than_zero_when_it_cannot_tell(tmp_path):
    from clawock.automation import cron_heartbeat

    assert cron_heartbeat.unpushed_commits(tmp_path) is None, (
        "a directory that is not a git checkout has no backlog to report, and "
        "0 would be a claim it cannot make"
    )
    assert cron_heartbeat.unpushed_commits(ROOT) is not None, (
        "this checkout can be asked, so the answer must be a number"
    )
