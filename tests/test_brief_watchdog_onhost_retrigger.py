"""The 08:30 pass may re-run the brief, but only on evidence the run is over.

On 2026-08-11 there was no brief at all. The 08:00 run died on a MiniMax
response-header timeout — the same first-call timeout that hit nine other jobs
that morning, all of which the runtime retried minutes later and all of which
then succeeded. The brief did not get that retry: the runtime stops retrying at
`consecutiveErrors > cron.retry.maxAttempts` — 5 in this host's config, 3 by
runtime default — and that counter only resets on a success, which a job with
one attempt a day never reaches while it is failing. It stood at 8 (#493).

Meanwhile the 08:30 watchdog logged `skip`, reasoning from the absence of a file
that the brief might still be landing — 29 minutes after the run it was waiting
for had ended in error.

So the pass now asks the scheduler. What it must not do is guess: a running job,
a job that has not run today, and an unreadable schedule are all silence, for
the reason #490 spelled out — a report that is missing is not a report that
failed.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from clawock.harness import brief_watchdog as watchdog  # noqa: E402
from clawock.harness import _watchdog_common as common  # noqa: E402

HKT = timezone(timedelta(hours=8))
TODAY = "2026-08-11"
JOB_ID = "db3df0d0-7622-4b75-81ce-86d510eeef33"


def _at(clock):
    """Epoch ms for an HKT wall clock on TODAY."""
    return int(datetime.strptime(f"{TODAY} {clock}", "%Y-%m-%d %H:%M")
               .replace(tzinfo=HKT).timestamp() * 1000)


def _job(**state):
    return {"id": JOB_ID, "name": "盘前深度简报", "enabled": True, "state": state}


def _watch(monkeypatch, tmp_path, job, spy):
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    monkeypatch.setattr(watchdog, "log", lambda event: spy.setdefault("logs", []).append(event))
    monkeypatch.setattr(watchdog, "brief_cron_job", lambda: job)
    monkeypatch.setattr(
        watchdog, "rerun_cron_job",
        lambda job_id, dry_run=False: (spy.setdefault("reruns", []).append(job_id), (True, "queued"))[1])


def _actions(spy):
    return [event.get("action") for event in spy.get("logs", [])]


def test_a_run_that_already_failed_today_is_re_run_once(tmp_path, monkeypatch):
    spy = {}
    _watch(monkeypatch, tmp_path, _job(lastStatus="error", lastRunAtMs=_at("08:01"),
                                       consecutiveErrors=8), spy)

    assert watchdog.retrigger_or_wait(TODAY, dry_run=False) == 0
    assert spy["reruns"] == [JOB_ID]
    assert _actions(spy) == ["rerun-onhost"]

    # Second pass, same day: the flag it wrote is the whole point.
    assert watchdog.retrigger_or_wait(TODAY, dry_run=False) == 0
    assert spy["reruns"] == [JOB_ID]
    assert _actions(spy)[-1] == "skip"


def test_a_run_still_in_flight_is_left_alone(tmp_path, monkeypatch):
    """The landing window the old skip was right about."""
    spy = {}
    _watch(monkeypatch, tmp_path, _job(runningAtMs=_at("08:00"), lastStatus="error",
                                       lastRunAtMs=_at("08:01")), spy)

    assert watchdog.retrigger_or_wait(TODAY, dry_run=False) == 0
    assert spy.get("reruns") is None
    assert _actions(spy) == ["skip"]


def test_a_schedule_that_cannot_be_read_is_not_evidence_of_failure(tmp_path, monkeypatch):
    spy = {}
    _watch(monkeypatch, tmp_path, None, spy)

    assert watchdog.retrigger_or_wait(TODAY, dry_run=False) == 0
    assert spy.get("reruns") is None
    assert _actions(spy) == ["skip"]


def test_yesterdays_failure_does_not_re_run_todays_job(tmp_path, monkeypatch):
    """Otherwise every morning would open with a re-run of a job that has not
    had its scheduled attempt yet."""
    spy = {}
    yesterday = _at("08:01") - 24 * 3600 * 1000
    _watch(monkeypatch, tmp_path, _job(lastStatus="error", lastRunAtMs=yesterday), spy)

    assert watchdog.retrigger_or_wait(TODAY, dry_run=False) == 0
    assert spy.get("reruns") is None


def test_dry_run_queues_nothing_and_writes_no_flag(tmp_path, monkeypatch):
    spy = {}
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    monkeypatch.setattr(watchdog, "log", lambda event: spy.setdefault("logs", []).append(event))
    monkeypatch.setattr(watchdog, "brief_cron_job",
                        lambda: _job(lastStatus="error", lastRunAtMs=_at("08:01")))

    assert watchdog.retrigger_or_wait(TODAY, dry_run=True) == 0
    assert not watchdog.rerun_flag_path(TODAY).exists()
    assert _actions(spy) == ["rerun-onhost"]


def test_the_evidence_reader_answers_three_ways():
    """`None` is not `False`: one means no evidence, the other means the run is
    fine. Collapsing them is how a provider outage got read as context loss."""
    assert common.cron_run_ended_in_failure(
        _job(lastStatus="error", lastRunAtMs=_at("08:01")), TODAY) is True
    assert common.cron_run_ended_in_failure(
        _job(lastStatus="ok", lastRunAtMs=_at("08:01")), TODAY) is False
    assert common.cron_run_ended_in_failure(
        _job(lastRunAtMs=_at("08:01")), TODAY) is None
    assert common.cron_run_ended_in_failure(_job(), TODAY) is None
    assert common.cron_run_ended_in_failure(None, TODAY) is None


def test_the_brief_job_is_found_through_the_contract_not_a_typed_name(monkeypatch):
    """A name typed in the watchdog would keep matching nothing after a rename."""
    contract = json.loads((ROOT / "config" / "cron-schedules.json").read_text())
    brief = [job for job in contract["jobs"]
             if job.get("mode") == common.BRIEF_CONTRACT_MODE]
    assert len(brief) == 1, "the contract no longer names exactly one brief job"

    monkeypatch.setattr(common, "_cron_cli_json", lambda _argv: {
        "jobs": [{"id": "other", "name": "港股收盘报告"},
                 {"id": JOB_ID, "name": brief[0]["name"]}]})

    assert common.brief_cron_job()["id"] == JOB_ID


def test_no_live_job_matches_the_contract_name(monkeypatch):
    monkeypatch.setattr(common, "_cron_cli_json", lambda _argv: {"jobs": [
        {"id": "other", "name": "港股收盘报告"}]})

    assert common.brief_cron_job() is None
