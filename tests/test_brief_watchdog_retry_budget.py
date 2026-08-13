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


def test_a_config_that_parses_without_the_field_uses_the_runtime_default(tmp_path):
    """This is the one case the runtime itself documents a default for."""
    default = provider.RUNTIME_DEFAULT_MAX_TRANSIENT_RETRIES

    assert provider.cron_max_attempts(paths=_paths(tmp_path, {})) == default
    assert provider.cron_max_attempts(paths=_paths(tmp_path, {"cron": {"retry": {}}})) == default
    assert provider.cron_max_attempts(
        paths=_paths(tmp_path, {"cron": {"retry": {"maxAttempts": 7}}})) == 7


def test_an_unreadable_cap_is_unknown_and_never_a_default(tmp_path):
    """Inventing a cap invents accusations: real cap 10, counter 6, verdict wrong.

    A file that cannot be read tells us nothing about what the live scheduler
    loaded, so it must not be answered with a number that happens to be
    plausible. Only a config that parses and omits the field has a documented
    default.
    """
    # No config file at all — an installation this process cannot read.
    assert provider.cron_max_attempts(paths=_paths(tmp_path / "absent")) is None
    for value in ("5", True, -1, None, 11, 20):
        assert provider.cron_max_attempts(
            paths=_paths(tmp_path, {"cron": {"retry": {"maxAttempts": value}}})) is None, value
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "openclaw.json").write_text("{not json")
    assert provider.cron_max_attempts(
        paths=provider.OpenClawPaths(binary="openclaw", home=corrupt, install_dir=None)) is None


def test_an_unknown_cap_makes_the_verdict_unknown_not_exhausted(tmp_path):
    budget = provider.cron_retry_budget(_job(consecutiveErrors=6),
                                        paths=_paths(tmp_path / "absent"))

    assert budget.exhausted is None
    assert budget.consecutive_errors == 6 and budget.max_attempts is None


def test_a_counter_past_the_schema_ceiling_cannot_be_fixed_by_raising_the_cap(tmp_path):
    """The runtime rejects maxAttempts > 10, so 12 bad days needs a reset.

    10 itself is still raisable: the rule is `errors > cap`, so a cap of exactly
    10 leaves a counter of 10 one retry.
    """
    paths = _paths(tmp_path, {"cron": {"retry": {"maxAttempts": 5}}})

    assert provider.cron_retry_budget(_job(consecutiveErrors=8), paths=paths).raisable is True
    assert provider.cron_retry_budget(_job(consecutiveErrors=10), paths=paths).raisable is True
    assert provider.cron_retry_budget(_job(consecutiveErrors=11), paths=paths).raisable is False
    assert provider.cron_retry_budget(_job(consecutiveErrors=12), paths=paths).raisable is False


# ── the alert ────────────────────────────────────────────────────────────────

_RUNS = [0]


def _alert_text(monkeypatch, tmp_path, job, budget=None):
    """Run the 09:05 alert with a stubbed job and return what Telegram got.

    Each call gets its own workspace: the alert writes a dedupe flag and
    recovery state, and a second call sharing them would return early without
    sending anything at all.
    """
    sent = []
    _RUNS[0] += 1
    ws = tmp_path / f"ws{_RUNS[0]}"
    ws.mkdir()
    monkeypatch.setattr(watchdog, "WS", ws)
    monkeypatch.setattr(watchdog, "brief_cron_job_state", lambda: job)
    if budget is not None:
        monkeypatch.setattr(watchdog, "cron_retry_budget", lambda _job: budget)
    monkeypatch.setattr(watchdog, "dispatch_brief_fallback", lambda _dry: (True, "ok"))
    monkeypatch.setattr(watchdog, "send_telegram",
                        lambda _to, message, _dry: (sent.append(message), (True, "ok"))[1])
    monkeypatch.setattr(watchdog, "await_brief_fallback_outcome",
                        lambda _since, _dry, **_kw: ("success", "https://example/run/1"))
    monkeypatch.setattr(watchdog, "log", lambda _event: None)
    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing", "plan_missing"]) == 0
    return sent[0]


def _baseline(monkeypatch, tmp_path):
    """The alert as it reads when the budget contributes nothing."""
    return _alert_text(monkeypatch, tmp_path, None)


def test_the_alert_names_the_exhausted_budget_and_the_only_way_out(
        monkeypatch, tmp_path):
    text = _alert_text(monkeypatch, tmp_path, _job(consecutiveErrors=12),
                       provider.CronRetryBudget(12, 5, True))

    # Both numbers, in the one form that cannot be satisfied by the "09:05" and
    # the date already in the message.
    assert "consecutiveErrors=12 > maxAttempts=5" in text
    # 12 is past the schema ceiling, so the alert must not send kcn to raise the
    # cap — that config edit is rejected by the runtime.
    assert "maxAttempts 已经救不回来" in text
    assert "consecutive_errors" in text
    assert "cron.retry.maxAttempts 设为" not in text


def test_a_budget_below_the_ceiling_is_told_which_value_to_set(monkeypatch, tmp_path):
    """`errors > cap` ⇒ the cap has to reach the counter, not pass it.

    Told to "raise past 6" an operator sets 7, which is fine; told to raise past
    10 they would set 11, which the runtime's schema rejects outright. Naming
    the value removes the trap.
    """
    text = _alert_text(monkeypatch, tmp_path, _job(consecutiveErrors=10),
                       provider.CronRetryBudget(10, 5, True))

    assert "cron.retry.maxAttempts 设为 ≥ 10" in text
    assert "已经救不回来" not in text


def test_the_alert_claims_only_what_the_counter_proves(monkeypatch, tmp_path):
    """No causal story: this reading does not know why today's run failed.

    The first draft said "one chance a day" (the day had two on-host runs) and
    "the other jobs survived the same wall" (nothing here observed the other
    jobs). Both were true on 08-13 and neither was evidence from this reading.
    """
    text = _alert_text(monkeypatch, tmp_path, _job(consecutiveErrors=12),
                       provider.CronRetryBudget(12, 5, True))

    assert "每天只有一次机会" not in text
    assert "别的 job" not in text
    assert "调度器不会再自动重试" in text


def test_a_healthy_budget_leaves_the_alert_byte_identical(monkeypatch, tmp_path):
    baseline = _baseline(monkeypatch, tmp_path)

    text = _alert_text(monkeypatch, tmp_path, _job(consecutiveErrors=1),
                       provider.CronRetryBudget(1, 5, False))

    assert text == baseline


def test_an_unknown_verdict_leaves_the_alert_byte_identical(monkeypatch, tmp_path):
    """Counter or cap unreadable — the two ways to know nothing."""
    baseline = _baseline(monkeypatch, tmp_path)

    for budget in (provider.CronRetryBudget(None, 5, None),
                   provider.CronRetryBudget(6, None, None)):
        assert _alert_text(monkeypatch, tmp_path, _job(), budget) == baseline


def test_an_unreadable_job_says_nothing_about_the_budget(monkeypatch, tmp_path):
    text = _alert_text(monkeypatch, tmp_path, None)

    assert "重试预算" not in text
    assert "盘前深度简报产物不完整" in text


def test_a_broken_budget_lookup_never_costs_the_alert(monkeypatch, tmp_path):
    """Reading the budget goes through the gateway — the thing that may be down.

    This alert is the last notification that reaches a human on a morning with
    no brief. Losing it to an exception raised while collecting an extra line
    about *why* would be strictly worse than sending the line-less alert.
    """
    def explode():
        raise RuntimeError("gateway unreachable")

    monkeypatch.setattr(watchdog, "brief_cron_job_state", explode)
    sent = []
    monkeypatch.setattr(watchdog, "WS", tmp_path)
    monkeypatch.setattr(watchdog, "dispatch_brief_fallback", lambda _dry: (True, "ok"))
    monkeypatch.setattr(watchdog, "send_telegram",
                        lambda _to, message, _dry: (sent.append(message), (True, "ok"))[1])
    monkeypatch.setattr(watchdog, "await_brief_fallback_outcome",
                        lambda _since, _dry, **_kw: ("success", "https://example/run/1"))
    monkeypatch.setattr(watchdog, "log", lambda _event: None)

    assert watchdog.alert_brief_missing(TODAY, False, ["brief_missing"]) == 0

    assert sent and "盘前深度简报产物不完整" in sent[0]
    assert "重试预算" not in sent[0]


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
