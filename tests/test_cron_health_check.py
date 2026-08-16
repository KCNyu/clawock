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
    outcomes = _outcomes([
        _outcome_record("港股午后快报", "2026-08-14T13:11:00+08:00", "recovered"),
    ])
    covered = cron_health_check.backstop_covered_slots(
        "港股午后快报", ["13:11"], "Asia/Hong_Kong", outcomes)
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
