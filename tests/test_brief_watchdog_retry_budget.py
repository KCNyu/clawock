"""An exhausted retry budget has to be named, because only kcn can clear it.

2026-08-13: no brief. The 08:00 run died on a MiniMax first-call timeout, the
08:30 re-run died on the same one, and the 09:05 alert told kcn to go look at
`sar -q` and the provider — both of which were healthy. Every other job that
morning hit the identical timeout and lived, because the runtime retried them
minutes later. The brief could not be retried: `consecutiveErrors` stood at 12
against `cron.retry.maxAttempts`, it only clears on a success, and a job with
one attempt a day cannot reach one while it is failing (#506, the recurrence of
#493).

That state is invisible from everything the watchdog reported, and it is not
self-healing, so the alert now carries the numbers and the way out. It stays
silent when the budget is healthy or unreadable: a missing brief has other
causes, and pointing at this one when it is not the cause is how the last
three diagnoses went wrong.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from clawock.providers import openclaw as provider  # noqa: E402
from clawock_kcnyu.harness import brief_watchdog as watchdog  # noqa: E402

TODAY = "2026-08-13"


def _job(**state):
    return {"id": "db3df0d0", "name": "盘前深度简报", "state": state}


def _paths(tmp_path, config=None):
    if config is not None:
        (tmp_path / "openclaw.json").write_text(json.dumps(config))
    return provider.OpenClawPaths(binary="openclaw", home=tmp_path, install_dir=None)


# ── the reader ───────────────────────────────────────────────────────────────

def test_budget_is_exhausted_only_past_the_configured_cap(tmp_path):
    paths = _paths(tmp_path, {"cron": {"retry": {"maxAttempts": 5}}})

    assert provider.cron_retry_budget(_job(consecutiveErrors=6), paths=paths).exhausted is True
    # The runtime's own rule is `>`, not `>=`: at exactly the cap one retry is left.
    assert provider.cron_retry_budget(_job(consecutiveErrors=5), paths=paths).exhausted is False
    assert provider.cron_retry_budget(_job(consecutiveErrors=0), paths=paths).exhausted is False


def test_an_unreadable_counter_is_unknown_not_healthy(tmp_path):
    paths = _paths(tmp_path, {"cron": {"retry": {"maxAttempts": 5}}})

    for job in (_job(), _job(consecutiveErrors=None), _job(consecutiveErrors="12"),
                _job(consecutiveErrors=-1), {"id": "x"}, None):
        budget = provider.cron_retry_budget(job, paths=paths)
        assert budget.exhausted is None, job
        assert budget.consecutive_errors is None, job


def test_a_missing_or_invalid_cap_falls_back_to_the_runtime_default(tmp_path):
    default = provider.RUNTIME_DEFAULT_MAX_TRANSIENT_RETRIES

    assert provider.cron_max_attempts(paths=_paths(tmp_path, {})) == default
    assert provider.cron_max_attempts(paths=_paths(tmp_path, {"cron": {"retry": {}}})) == default
    assert provider.cron_max_attempts(
        paths=_paths(tmp_path, {"cron": {"retry": {"maxAttempts": "5"}}})) == default
    # No config file at all — an installation this process cannot read.
    assert provider.cron_max_attempts(paths=_paths(tmp_path / "absent")) == default
    assert provider.cron_max_attempts(
        paths=_paths(tmp_path, {"cron": {"retry": {"maxAttempts": 7}}})) == 7


def test_a_counter_past_the_schema_ceiling_cannot_be_fixed_by_raising_the_cap(tmp_path):
    """The runtime rejects maxAttempts > 10, so 12 bad days needs a reset."""
    paths = _paths(tmp_path, {"cron": {"retry": {"maxAttempts": 5}}})

    assert provider.cron_retry_budget(_job(consecutiveErrors=8), paths=paths).raisable is True
    assert provider.cron_retry_budget(_job(consecutiveErrors=12), paths=paths).raisable is False


# ── the alert ────────────────────────────────────────────────────────────────

def _alert_text(monkeypatch, tmp_path, job):
    """Run the 09:05 alert with a stubbed job and return what Telegram got."""
    sent = []
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    monkeypatch.setattr(watchdog, "brief_cron_job", lambda: job)
    monkeypatch.setattr(watchdog, "dispatch_brief_fallback", lambda _dry: (True, "ok"))
    monkeypatch.setattr(watchdog, "send_telegram",
                        lambda _to, message, _dry: (sent.append(message), (True, "ok"))[1])
    monkeypatch.setattr(watchdog, "await_brief_fallback_outcome",
                        lambda _since, _dry, **_kw: ("success", "https://example/run/1"))
    monkeypatch.setattr(watchdog, "log", lambda _event: None)
    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing", "plan_missing"]) == 0
    return sent[0]


def test_the_alert_names_the_exhausted_budget_and_the_only_way_out(
        monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog, "cron_retry_budget",
                        lambda _job: provider.CronRetryBudget(12, 5, True))

    text = _alert_text(monkeypatch, tmp_path, _job(consecutiveErrors=12))

    assert "12" in text and "5" in text
    # 12 is past the schema ceiling, so the alert must not send kcn to raise the
    # cap — that config edit is rejected by the runtime.
    assert "maxAttempts 已经救不回来" in text
    assert "consecutive_errors" in text


def test_a_budget_below_the_ceiling_is_told_it_can_be_raised(monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog, "cron_retry_budget",
                        lambda _job: provider.CronRetryBudget(6, 5, True))

    text = _alert_text(monkeypatch, tmp_path, _job(consecutiveErrors=6))

    assert "cron.retry.maxAttempts" in text and "6" in text
    assert "已经救不回来" not in text


def test_a_healthy_budget_leaves_the_alert_exactly_as_it_was(monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog, "cron_retry_budget",
                        lambda _job: provider.CronRetryBudget(1, 5, False))

    text = _alert_text(monkeypatch, tmp_path, _job(consecutiveErrors=1))

    assert "重试预算" not in text
    assert "盘前深度简报产物不完整" in text


def test_an_unreadable_job_says_nothing_about_the_budget(monkeypatch, tmp_path):
    text = _alert_text(monkeypatch, tmp_path, None)

    assert "重试预算" not in text


def test_an_unknown_budget_says_nothing_about_the_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(watchdog, "cron_retry_budget",
                        lambda _job: provider.CronRetryBudget(None, 5, None))

    text = _alert_text(monkeypatch, tmp_path, _job())

    assert "重试预算" not in text


# ── the 08:30 re-run ─────────────────────────────────────────────────────────

def test_the_0830_rerun_records_the_budget_it_is_running_against(
        monkeypatch, tmp_path):
    """The re-run is one more single attempt; the log has to show that."""
    logged = []
    job = _job(lastStatus="error", lastRunAtMs=None, consecutiveErrors=12)
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    monkeypatch.setattr(watchdog, "brief_cron_job", lambda: job)
    monkeypatch.setattr(watchdog, "cron_run_ended_in_failure", lambda _job, _today: True)
    monkeypatch.setattr(watchdog, "cron_retry_budget",
                        lambda _job: provider.CronRetryBudget(12, 5, True))
    monkeypatch.setattr(watchdog, "rerun_cron_job", lambda _id, _dry: (True, "queued"))
    monkeypatch.setattr(watchdog, "log", logged.append)

    assert watchdog.retrigger_or_wait(TODAY, False) == 0

    rerun = [event for event in logged if event.get("action") == "rerun-onhost"]
    assert len(rerun) == 1
    assert rerun[0]["retry_budget_exhausted"] is True
    assert "12" in rerun[0]["retry_budget"] and "5" in rerun[0]["retry_budget"]
