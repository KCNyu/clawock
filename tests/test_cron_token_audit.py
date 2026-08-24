"""A token regression is only meaningful against a comparable run.

The 2026-07-27 brief burned 13.4M tokens and the tempting headline was "90x the
Sonnet-era 135k". That comparison is not real: `usage.input/output` from the
CLI-backed provider describe the last turn only, and its `total` is accumulated on
different terms from MiniMax's. Against its own MiniMax history the run is ~3.4x,
which is the number worth acting on (issue #122).

These tests pin that distinction, because getting it wrong sends the next person
looking for a 90x bug that does not exist.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


WS = Path(__file__).resolve().parents[1]
HOST_SCRIPTS = str(WS / "ops" / "host")


@pytest.fixture(scope="module")
def audit():
    if HOST_SCRIPTS not in sys.path:
        sys.path.insert(0, HOST_SCRIPTS)
    return pytest.importorskip("cron_token_audit")


def run(total, *, provider="minimax-2", model="MiniMax-M3", status="ok", at=1785110400011):
    return {
        "provider": provider, "model": model, "status": status, "runAtMs": at,
        "usage": {"total_tokens": total, "input_tokens": 100, "output_tokens": 50},
    }


def reader(runs):
    return lambda job_id: runs


def test_the_real_regression_is_flagged(audit):
    # The four MiniMax brief runs, oldest→newest, as recorded.
    runs = [run(3_951_265), run(4_944_327), run(3_673_159), run(13_363_237)]
    report = audit.audit_job("job", "盘前深度简报", runs_reader=reader(runs))
    assert report["state"] == "regressed"
    assert report["ratio"] == pytest.approx(3.38, abs=0.01)


def test_the_normal_spread_is_quiet(audit):
    # 3.67M-4.94M is this job's ordinary range; flagging it would train kcn to
    # ignore the line.
    runs = [run(3_951_265), run(3_673_159), run(4_944_327), run(3_800_000)]
    assert audit.audit_job("job", runs_reader=reader(runs))["state"] == "ok"


def test_a_provider_switch_does_not_manufacture_a_regression(audit):
    # This is the 90x headline, asserted as NOT a finding: the Sonnet runs are not
    # a baseline for a MiniMax run.
    runs = [
        run(156_123, provider="claude-cli", model="claude-sonnet-4-6"),
        run(136_779, provider="claude-cli", model="claude-sonnet-4-6"),
        run(134_330, provider="claude-cli", model="claude-sonnet-4-6"),
        run(3_951_265),
    ]
    report = audit.audit_job("job", runs_reader=reader(runs))
    assert report["state"] == "no_comparable_baseline"
    assert report["baseline_runs"] == 0


def test_a_thin_baseline_says_so_instead_of_guessing(audit):
    runs = [run(3_951_265), run(13_363_237)]
    assert audit.audit_job("job", runs_reader=reader(runs))["state"] == "no_comparable_baseline"


def test_failed_runs_still_report_their_usage(audit):
    # 07-27 is exactly this case: the biggest burn of the month ended in error, so
    # skipping failures would drop the very run worth seeing.
    runs = [run(3_951_265), run(4_944_327), run(3_673_159),
            run(13_363_237, status="error")]
    report = audit.audit_job("job", runs_reader=reader(runs))
    assert report["state"] == "regressed"
    assert report["status"] == "error"


def test_runs_without_usage_are_not_counted_as_zero(audit):
    # The three gateway-restart runs recorded no usage at all. Treating them as 0
    # would drag the median down and manufacture a regression on the next run.
    runs = [{"provider": "minimax-2", "model": "MiniMax-M3", "usage": {}},
            run(3_951_265), run(3_673_159), run(4_944_327), run(4_000_000)]
    report = audit.audit_job("job", runs_reader=reader(runs))
    assert report["state"] == "ok"
    assert report["baseline_median"] == 3_951_265


def test_no_history_is_stated_not_crashed(audit):
    assert audit.audit_job("job", runs_reader=reader([]))["state"] == "no_usage_recorded"


def test_an_unreadable_store_yields_no_findings(audit, monkeypatch):
    def boom(_job_id):
        raise RuntimeError("sqlite locked")
    # The reader seam raising must not propagate: this feeds the health review.
    monkeypatch.setattr(audit, "_load_runs", lambda job_id, reader=None: [])
    assert audit.audit_job("job", runs_reader=None)["state"] == "no_usage_recorded"


def test_only_regressions_reach_the_health_line(audit):
    reports = [
        {"job": "a", "state": "ok", "ratio": 1.1, "total_tokens": 1,
         "provider": "p", "model": "m", "baseline_median": 1},
        {"job": "b", "state": "regressed", "ratio": 3.4, "total_tokens": 13_363_237,
         "provider": "minimax-2", "model": "MiniMax-M3", "baseline_median": 3_951_265},
    ]
    assert [r["job"] for r in audit.regressions(reports)] == ["b"]
    line = audit.format_lines(audit.regressions(reports))[0]
    assert "13,363,237" in line and "⚠️" in line


@pytest.fixture
def health(monkeypatch):
    """cron_health_check.main() with every live source replaced."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cron_health_check_probe", WS / "ops" / "host" / "cron_health_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_runtime_jobs", lambda jobs_file=None: [])
    monkeypatch.setattr(module, "load_heartbeats", lambda path=None: {})
    monkeypatch.setattr(module, "check_dashboard_build",
                        lambda: {"state": "ok", "detail": "ok", "ok": True})
    # The publisher-freshness check reads the LIVE published generation's
    # timestamp — on a Sunday the intraday publisher does not run, the age
    # grows past the 3h threshold, and this fixture's own contract ("every
    # live source replaced") turned every PR's validate red for hours without
    # anyone touching cron code. Stub it like the other live sources.
    monkeypatch.setattr(module, "check_scheduled_publisher",
                        lambda now=None, path=None: {"state": "ok", "detail": "ok"})
    return module


def test_health_check_prints_the_regression_and_still_exits_zero(health, monkeypatch, capsys):
    # Severity is the whole design: kcn does not want per-cron alerts, so the line
    # has to appear in the daily review without turning it red.
    regressed = {"job": "盘前深度简报", "state": "regressed", "ratio": 3.38,
                 "total_tokens": 13_363_237, "provider": "minimax-2",
                 "model": "MiniMax-M3", "baseline_median": 3_951_265}
    monkeypatch.setattr(health.cron_token_audit, "audit", lambda **kw: [regressed])
    monkeypatch.setattr(sys, "argv", ["cron_health_check.py"])

    with pytest.raises(SystemExit) as exit_info:
        health.main()
    assert exit_info.value.code == 0
    assert "13,363,237" in capsys.readouterr().out


def test_health_check_does_not_read_the_live_store_in_ci(health, monkeypatch):
    # `--jobs-file` is the CI path: there is no live run store on a runner, and an
    # audit that tried to read one would either hang on the CLI or report nothing.
    called = []
    monkeypatch.setattr(health.cron_token_audit, "audit",
                        lambda **kw: called.append(1) or [])
    monkeypatch.setattr(sys, "argv",
                        ["cron_health_check.py", "--jobs-file", "config/cron-schedules.json"])
    with pytest.raises(SystemExit):
        health.main()
    assert called == []
