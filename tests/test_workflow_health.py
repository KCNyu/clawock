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


def test_a_cancelled_scheduled_run_is_not_a_healthy_one():
    # #2259: cancelled before any step ran, and the table printed `✓`.
    once = wh.assess("x.yml", ["0 1 * * *"],
                     [run("success", 1), run("cancelled", 2), run("success", 3)], NOW)
    assert once["status"] == "noted" and once["cancellations_in_window"] == 1

    twice = wh.assess("x.yml", ["0 1 * * *"],
                      [run("cancelled", 1), run("cancelled", 2), run("success", 3)], NOW)
    assert twice["status"] == "attention"
    assert "2 consecutive cancellations" in wh._row_detail(twice)


def test_a_workflow_that_quietly_stopped_firing_is_caught():
    """Silence is the worse failure: a disabled or drifted schedule looks calm."""
    row = wh.assess("sentiment-scan.yml", ["30 21 * * 0-4"],
                    [run("success", 9)], NOW)
    assert row["status"] == "attention"
    assert row["overdue_hours"] > 24


def test_push_runs_and_empty_history_are_not_schedule_evidence():
    for runs in ([run("success", 0.1, event="push")], []):
        row = wh.assess("ci.yml", ["41 3 * * 6"], runs, NOW)
        assert row["status"] == "attention"
        assert row["last_run"] is None


def test_fetch_runs_requests_only_schedule_events():
    commands = []

    def runner(command):
        commands.append(command)
        return "[]"

    assert wh.fetch_runs("ci.yml", runner=runner) == []
    assert commands[0][commands[0].index("--event") + 1] == "schedule"


def test_a_weekly_workflow_is_not_called_overdue_the_day_before_it_runs():
    row = wh.assess("screenshot-refresh.yml", ["0 22 * * 0"], [run("success", 6.5)], NOW)
    assert row["status"] == "ok"
    assert row["overdue_hours"] is None


@pytest.mark.parametrize("exprs,hours", [
    (["*/30 10-11 * * 1-5"], 70.5),
    # Weekday-only schedules carry a 72h weekend gap.
    (["0 13 * * 1-5"], 72),
    (["0 22 * * 0"], 168.0),
    (["0 22 * * 5"], 168.0),
    (["45 21 * * 0-4", "50 12 * * 1-5"], 56.916667),
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
    # Each workflow is listed twice: filtered to its scheduled runs, and
    # unfiltered for the ones the filter has not caught up with.
    assert result["scheduled_workflows"] == len(set(calls))


def test_the_rollup_never_fails_its_host_job(capsys, monkeypatch):
    """Exit 0 whatever the rollup found — and without asking GitHub.

    This used to call `wh.main(["--json"])` bare, so every run of the unit suite
    shelled out to `gh` once per tracked workflow and waited on the network:
    18.1s on 2026-09-06, and an answer that depended on this host's `gh` auth and
    on GitHub being up. The assertion never looked at the result (`== 0 or True`
    cannot fail), so all of that bought nothing.

    `report()` already takes a `runner`, which is the seam the rest of this
    module tests through; `main` reaches it via the same provider. Feeding it a
    canned failure is a stronger version of the same claim: the rollup returns 0
    even when what it found is bad.
    """
    monkeypatch.setattr(wh, "fetch_runs",
                        lambda workflow, limit=20, runner=None: [
                            run("failure", 1), run("failure", 2)])
    assert wh.main(["--json"]) == 0
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


def test_multiple_weekly_expressions_merge_into_one_gap():
    assert wh.expected_interval_hours(['0 0 * * 3', '0 0 * * 6']) == 96


def test_weekend_gap_has_separate_runner_delay_allowance():
    gap = wh.expected_interval_hours(['0 13 * * 1-5'])
    row = wh.assess('weekday.yml', ['0 13 * * 1-5'], [run('success', 83 / 24)], NOW)
    assert gap == 72 and row['overdue_hours'] is None
    row = wh.assess('weekday.yml', ['0 13 * * 1-5'], [run('success', 85 / 24)], NOW)
    assert row['overdue_hours'] == 85


def test_weekly_build_checks_all_outputs_with_canonical_clock_normalization():
    text = (ROOT / '.github/workflows/weekly-health.yml').read_text()
    step = text.split('- name: Dashboard build idempotency')[1]
    assert 'config/dashboard-outputs.json' in step
    assert 'ops/ci/strip_dashboard_clocks.py' in step
    assert 'for name in $names' in step
