"""The host crontab owns *when* for a host-triggered job; OpenClaw still runs it.

kcn 2026-09-12:「openclaw 的 cron 可以触发多轮 ai 吧，那个可以用到 harness，你改成系统
cron 怎么做」— the multi-turn agent run stays OpenClaw's (`openclaw cron run <id>` runs
the job's own payload, isolated session and delivery settings; verified on the host
that a job disabled in OpenClaw still runs in full this way). Only the scheduler
moves, because OpenClaw's swallows cron-expression ticks from 2026.9.1 (#139215).
"""
import importlib.util
import sys
from pathlib import Path

from clawock import scheduling
from clawock.automation import cron_trigger

ROOT = Path(__file__).resolve().parents[1]
CMD = '/root/.local/bin/clawock cron-trigger --job-name "港股午后快报" >> /x.log 2>&1'


def _job(host=True, enabled=True):
    job = {"name": "港股午后快报", "enabled": enabled,
           "schedule": {"kind": "cron", "expr": "33 13 * * 1-5", "tz": "Asia/Shanghai"}}
    if host:
        job["trigger"] = {"by": "host", "command": CMD}
    return job


def test_a_host_triggered_job_must_be_disabled_in_openclaw():
    assert scheduling.runtime_enabled(_job(host=False)) is True
    assert scheduling.runtime_enabled(_job(host=True)) is False
    assert scheduling.runtime_enabled(_job(host=True, enabled=False)) is False
    live = {"name": "港股午后快报", "enabled": True,
            "schedule": {"expr": "33 13 * * 1-5", "tz": "Asia/Shanghai"}}
    contract = {"jobs": [_job()], "payload_profiles": {}}
    schedule_errors = [e for e in scheduling.validate_live_jobs(contract, [live])
                       if "schedule" in e]
    assert schedule_errors, "OpenClaw still firing a host-triggered job must be flagged"
    live["enabled"] = False
    assert not [e for e in scheduling.validate_live_jobs(contract, [live]) if "schedule" in e]


def test_the_host_crontab_must_carry_the_trigger_line_at_the_contract_time():
    contract = {"jobs": [_job()]}
    assert any("host trigger command missing" in e
               for e in scheduling.validate_watchdogs(contract, ""))
    assert any("expected '33 13 * * 1-5'" in e
               for e in scheduling.validate_watchdogs(contract, f"34 13 * * 1-5 {CMD}\n"))
    assert not [e for e in scheduling.validate_watchdogs(contract, f"33 13 * * 1-5 {CMD}\n")
                if "host trigger" in e]
    us = _job()
    us["schedule"]["tz"] = "America/New_York"
    assert any("host-timezone" in e for e in scheduling.validate_watchdogs({"jobs": [us]}, ""))


def test_the_trigger_refuses_anything_that_would_run_twice(tmp_path):
    ran = []
    run = lambda job_id: (ran.append(job_id) or (True, "queued"))  # noqa: E731
    contract = {"jobs": [_job(host=False)]}
    assert cron_trigger.trigger("港股午后快报", contract=contract, live_jobs=[],
                                run=run, workspace=tmp_path) == cron_trigger.EXIT_REFUSED
    live = [{"name": "港股午后快报", "id": "job-1", "enabled": True}]
    assert cron_trigger.trigger("港股午后快报", contract={"jobs": [_job()]}, live_jobs=live,
                                run=run, workspace=tmp_path) == cron_trigger.EXIT_REFUSED
    assert ran == []


def test_the_trigger_queues_the_disabled_job_and_logs_it(tmp_path):
    ran = []
    live = [{"name": "港股午后快报", "id": "job-1", "enabled": False}]
    code = cron_trigger.trigger("港股午后快报", contract={"jobs": [_job()]}, live_jobs=live,
                                run=lambda job_id: (ran.append(job_id) or (True, "queued")),
                                workspace=tmp_path)
    assert code == 0 and ran == ["job-1"]
    assert '"ok": true' in (tmp_path / "logs" / "cron-trigger.jsonl").read_text()


def test_check_mode_fires_nothing(tmp_path):
    ran = []
    live = [{"name": "港股午后快报", "id": "job-1", "enabled": False}]
    assert cron_trigger.trigger("港股午后快报", contract={"jobs": [_job()]}, live_jobs=live,
                                run=lambda job_id: ran.append(job_id), workspace=tmp_path,
                                check=True) == 0
    assert ran == []


def test_the_health_check_still_owes_a_host_triggered_job_its_slots(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "cron_health_check", ROOT / "ops" / "host" / "cron_health_check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("cron_health_check_under_test", module)
    spec.loader.exec_module(module)

    class Listing:
        entries = [{"name": "港股午后快报", "id": "job-1", "enabled": False,
                    "schedule": {"expr": "33 13 * * 1-5", "tz": "Asia/Shanghai"}}]

    monkeypatch.setattr(module.openclaw, "read_jobs", lambda: Listing())
    monkeypatch.setattr(scheduling, "load_contract", lambda *a, **k: {"jobs": [_job()]})
    jobs = module.load_runtime_jobs()
    assert jobs[0]["enabled"] is True and jobs[0]["schedule"]["expr"] == "33 13 * * 1-5"


def test_the_live_contract_trial_is_one_hk_job():
    """The first host-triggered job is a low-stakes HK slot (no DST, a 13:45
    report watchdog behind it). Widening this is a decision, not a drift."""
    contract = scheduling.load_contract()
    hosted = [job["name"] for job in contract["jobs"] if scheduling.host_trigger(job)]
    assert hosted == ["港股午后快报"]
