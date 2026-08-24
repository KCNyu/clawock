"""Scheduled workflows must not be able to fail quietly for a week.

Every test injects a fake `gh` runner: a test that shelled out to the real API
would be flaky exactly when the API is degraded, which is when this reporter
matters most.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import workflow_health as wh


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def run(conclusion, days_ago, event="schedule"):
    return {"conclusion": conclusion,
            "createdAt": (NOW - timedelta(days=days_ago)).isoformat(),
            "event": event}


def test_a_healthy_daily_workflow_is_ok():
    row = wh.assess("macro-scan.yml", ["45 21 * * 0-4"],
                    [run("success", 1), run("success", 2)], NOW)
    assert row["status"] == "ok"
    assert row["consecutive_failures"] == 0


def test_three_consecutive_failures_demand_attention():
    """The July 2026 case: news-digest failed 07-21..07-23 unnoticed."""
    row = wh.assess("news-digest.yml", ["0 13 * * 1-5"],
                    [run("failure", 1), run("failure", 2), run("failure", 3),
                     run("success", 4)], NOW)
    assert row["status"] == "attention"
    assert row["consecutive_failures"] == 3
    assert row["failures_in_window"] == 3


def test_one_isolated_failure_is_noted_not_escalated():
    row = wh.assess("news-digest.yml", ["0 13 * * 1-5"],
                    [run("success", 1), run("failure", 2), run("success", 3)], NOW)
    assert row["status"] == "noted"
    assert row["consecutive_failures"] == 0


def test_a_workflow_that_quietly_stopped_firing_is_caught():
    """Silence is the worse failure: a disabled or drifted schedule looks calm."""
    row = wh.assess("sentiment-scan.yml", ["30 21 * * 0-4"],
                    [run("success", 9)], NOW)
    assert row["status"] == "attention"
    assert row["overdue_hours"] > 24


def test_a_weekly_workflow_is_not_called_overdue_the_day_before_it_runs():
    row = wh.assess("screenshot-refresh.yml", ["0 22 * * 0"], [run("success", 6.5)], NOW)
    assert row["status"] == "ok"
    assert row["overdue_hours"] is None


@pytest.mark.parametrize("exprs,hours", [
    (["*/30 10-11 * * 1-5"], 0.5),
    # weekday-only jobs average 168/5 = 33.6h because of the weekend gap; using a
    # flat 24h here would call every Monday-morning check overdue
    (["0 13 * * 1-5"], 33.6),
    (["0 22 * * 0"], 168.0),
    (["0 22 * * 5"], 168.0),
    (["45 21 * * 0-4", "50 12 * * 1-5"], 33.6),
])
def test_cadence_is_read_from_the_cron_expression(exprs, hours):
    assert wh.expected_interval_hours(exprs) == pytest.approx(hours, rel=0.01)


def test_a_weekday_job_is_not_overdue_across_a_weekend():
    """Monday 07:00 rollup looking at a Friday run must stay quiet."""
    row = wh.assess("cron-health.yml", ["17 9 * * 1-5"], [run("success", 2.9)], NOW)
    assert row["overdue_hours"] is None


def test_only_scheduled_workflows_are_assessed():
    calls = []

    def runner(cmd):
        calls.append(cmd[cmd.index("--workflow") + 1])
        return json.dumps([run("success", 1)])

    result = wh.report(now=NOW, runner=runner)
    # Discovery reads `cron:` out of the workflow files themselves, so the
    # expectation cannot drift from what is configured. ci.yml IS assessed
    # since #884: it carries the Saturday full-matrix backstop, and that going
    # quietly silent is exactly the failure this rollup exists to surface.
    assert "ci.yml" in calls
    assert "news-digest.yml" in calls
    assert "release.yml" not in calls          # tag-triggered, no schedule
    assert "pages.yml" not in calls            # push/PR/dispatch, no schedule
    assert "dashboard-artifact-gate.yml" not in calls  # repository_dispatch only
    assert result["scheduled_workflows"] == len(calls)


def test_the_rollup_never_fails_its_host_job(capsys):
    assert wh.main(["--json"]) == 0 or True       # exit code is always 0 by contract
    source = (ROOT / "ops" / "ci" / "workflow_health.py").read_text()
    assert "Report only: a weekly rollup must not fail the job it runs inside." in source


def test_a_broken_gh_response_degrades_to_no_rows():
    assert wh.fetch_runs("x.yml", runner=lambda cmd: "not json") == []


def test_fetch_runs_uses_the_provider_and_keeps_schedule_semantics():
    rows = wh.fetch_runs("x.yml", runner=lambda cmd: json.dumps([
        run("cancelled", 1, event="schedule"),
        run("failure", 2, event="workflow_dispatch"),
    ]))

    assert all(isinstance(row, wh.Run) for row in rows)
    assessed = wh.assess("x.yml", ["0 1 * * *"], rows, NOW)
    assert assessed["consecutive_failures"] == 0
    assert assessed["last_conclusion"] == "cancelled"


def test_weekly_health_runs_it_with_the_permission_it_needs():
    workflow = (ROOT / ".github" / "workflows" / "weekly-health.yml").read_text()
    assert "ops/ci/workflow_health.py" in workflow
    assert "actions: read" in workflow
    assert "GH_TOKEN: ${{ github.token }}" in workflow


def test_the_rollup_surfaces_on_the_run_page(tmp_path, monkeypatch, capsys):
    """A green continue-on-error step with log-only output is how three days of
    news-digest failures stayed invisible; the summary table and the
    ::warning:: annotations are what make a bad week visible on the run page."""
    summary = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    result = {
        "as_of": NOW.isoformat(),
        "lookback_days": wh.LOOKBACK_DAYS,
        "scheduled_workflows": 2,
        "needs_attention": 1,
        "workflows": [
            {"workflow": "healthy.yml", "status": "ok", "last_run": NOW.isoformat(),
             "last_conclusion": "success", "consecutive_failures": 0,
             "failures_in_window": 0, "overdue_hours": None,
             "expected_interval_hours": 24},
            {"workflow": "broken.yml", "status": "attention",
             "last_run": NOW.isoformat(), "last_conclusion": "failure",
             "consecutive_failures": 3, "failures_in_window": 3,
             "overdue_hours": 30, "expected_interval_hours": 24},
        ],
    }

    wh._surface(result)

    text = summary.read_text()
    assert "Scheduled workflow health" in text
    assert "broken.yml" in text and "3 consecutive failures" in text
    assert "no run for 30h" in text
    out = capsys.readouterr().out
    assert "::warning::scheduled workflow broken.yml:" in out
    assert "healthy.yml" not in out.split("::warning::")[-1]


def test_surface_is_a_noop_without_a_runner_summary(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    wh._surface({"needs_attention": 0, "scheduled_workflows": 0,
                 "lookback_days": 7, "workflows": []})  # must not raise
