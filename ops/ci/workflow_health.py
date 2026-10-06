#!/usr/bin/env python3
"""Scheduled-workflow health: which ones failed, and which quietly stopped running.

A scheduled GitHub Actions workflow fails invisibly. It is not a required check,
so no pull request goes red; `cron-health.py` watches the openclaw crons in live
SQLite, not Actions; and `system_check.py` only knows the local workspace. In July
2026 `news-digest.yml` failed three days running (07-21 to 07-23) and nothing
surfaced it.

This is a weekly rollup, deliberately not an alert: a single failed run is noise,
a run that fails every day for a week is a fact worth reporting. It also catches
the quieter failure — a workflow that stopped firing at all, where a drifted or
disabled schedule looks exactly like calm.

Cadence comes from the workflow files themselves, so the expectation cannot drift
away from what is actually configured.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
from clawock.workspace import workspace_root  # noqa: E402
from clawock.providers import GitHubRuns, Run  # noqa: E402

WS = workspace_root(_CHECKOUT)
WORKFLOW_DIR = WS / ".github" / "workflows"
LOOKBACK_DAYS = 7
# Maximum scheduled gap plus an independent allowance for runner delay.
DELAY_ALLOWANCE_H = 12.0
CRON_RE = re.compile(r"cron:\s*'([^']+)'")


def schedules(path: Path) -> list[str]:
    return CRON_RE.findall(path.read_text(encoding="utf-8"))


def expected_interval_hours(exprs: list[str]) -> float | None:
    """Maximum gap on the union of weekly schedules, including weekend gaps."""
    from clawock.scheduling import parse_cron_slots
    if not exprs:
        return None
    points = set()
    # A fixed Sunday anchors cron's 0/7 numbering; no mutable wall clock.
    sunday = datetime(2026, 1, 4, tzinfo=timezone.utc)
    for expr in exprs:
        fields = expr.split()
        if len(fields) != 5:
            continue
        if fields[2:4] != ['*', '*']:
            return 24 * 31  # conservative for non-weekly calendar expressions
        for day in range(7):
            for slot in parse_cron_slots(expr, 'UTC', sunday + timedelta(days=day)):
                hour, minute = map(int, slot.split(':'))
                points.add(day * 1440 + hour * 60 + minute)
    if not points:
        return None
    ordered = sorted(points)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    gaps.append(7 * 1440 + ordered[0] - ordered[-1])
    return max(gaps) / 60


def fetch_runs(workflow: str, limit: int = 20, runner=None) -> list[Run]:
    """Production caller for the GitHub run-history provider (#362)."""
    return GitHubRuns(runner=runner).history(workflow, limit=limit, event="schedule")


def _run_field(run, normalized: str, legacy: str):
    """Read the provider shape, while keeping `assess` useful to old callers."""
    if isinstance(run, Run):
        return getattr(run, normalized)
    return run.get(legacy)


def _status(run) -> str:
    if isinstance(run, Run):
        return run.status
    return {
        "success": "ok", "failure": "error", "cancelled": "cancelled",
        "skipped": "skipped", None: "running", "": "running",
    }.get(run.get("conclusion"), "unknown")


def _display_status(run):
    status = _status(run)
    return {
        "ok": "success", "error": "failure", "running": None,
        "cancelled": "cancelled", "skipped": "skipped",
        "unknown": "unknown",
    }[status]


def assess(workflow: str, exprs: list[str], runs: list[Run | dict], now: datetime) -> dict:
    scheduled = [r for r in runs if _run_field(r, "trigger", "event") == "schedule"]
    window_start = now - timedelta(days=LOOKBACK_DAYS)

    def parsed(run):
        try:
            return datetime.fromisoformat(
                str(_run_field(run, "started_at", "createdAt")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    recent = [r for r in scheduled if (parsed(r) or window_start) >= window_start]
    failures = [r for r in recent if _status(r) == "error"]
    # A scheduled run that was cancelled ran no step: nothing it exists to do
    # happened. It used to fall through as neutral, so a leg killed by a
    # concurrency group read `✓` on the only table watching it (#2259).
    cancellations = [r for r in recent if _status(r) == "cancelled"]
    streak = 0
    for run in scheduled:                       # newest first
        if _status(run) == "error":
            streak += 1
        elif _status(run) in ("running", "cancelled", "skipped"):
            continue
        else:
            break
    cancelled_streak = 0
    for run in scheduled:                       # newest first
        if _status(run) == "cancelled":
            cancelled_streak += 1
        elif _status(run) in ("running", "skipped"):
            continue
        else:
            break
    last = parsed(scheduled[0]) if scheduled else None
    interval = expected_interval_hours(exprs)
    overdue_hours = None
    if last and interval:
        age = (now - last).total_seconds() / 3600
        if age > interval + DELAY_ALLOWANCE_H:
            overdue_hours = round(age, 1)
    status = "ok"
    if (not scheduled or streak >= 2 or cancelled_streak >= 2
            or overdue_hours is not None):
        status = "attention"
    elif failures or cancellations:
        status = "noted"
    return {
        "workflow": workflow,
        "schedules": exprs,
        "expected_interval_hours": interval,
        "last_run": last.isoformat() if last else None,
        "last_conclusion": _display_status(scheduled[0]) if scheduled else None,
        "failures_in_window": len(failures),
        "consecutive_failures": streak,
        "cancellations_in_window": len(cancellations),
        "consecutive_cancellations": cancelled_streak,
        "overdue_hours": overdue_hours,
        "status": status,
    }


def report(now: datetime | None = None, runner=None, workflow_dir: Path = WORKFLOW_DIR, source_root: Path = WS) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = []
    for path in sorted(workflow_dir.glob("*.yml")):
        exprs = schedules(path)
        if not exprs:
            continue                            # push/PR workflows report through PRs
        rows.append(assess(path.name, exprs, fetch_runs(path.name, runner=runner), now))
    from clawock.automation.weekly_health import missing_weeks
    gaps = missing_weeks(source_root, now=now)
    for row in rows:
        if row['workflow'] == 'weekly-review.yml':
            row['missing_weeks'] = gaps
            if gaps:
                row['status'] = 'attention'
    attention = [r for r in rows if r["status"] == "attention"]
    return {
        "as_of": now.isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "scheduled_workflows": len(rows),
        "needs_attention": len(attention),
        "workflows": rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = report()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    print(f"scheduled workflows: {result['scheduled_workflows']} · "
          f"needs attention: {result['needs_attention']}")
    for row in result["workflows"]:
        mark = {"ok": "✓", "noted": "·", "attention": "⚠"}[row["status"]]
        detail = _row_detail(row)
        print(f"  {mark} {row['workflow']:26} last={row['last_conclusion'] or '-'}"
              f"@{(row['last_run'] or '-')[:16]}"
              + (f"  {detail}" if detail else ""))
    _surface(result)
    # Report only: a weekly rollup must not fail the job it runs inside.
    return 0


def _row_detail(row):
    detail = []
    if row.get('missing_weeks'):
        detail.append('missing due reviews: ' + ', '.join(row['missing_weeks']))
    if row["consecutive_failures"]:
        detail.append(f"{row['consecutive_failures']} consecutive failures")
    elif row["failures_in_window"]:
        detail.append(f"{row['failures_in_window']} failure(s) in {LOOKBACK_DAYS}d")
    if row.get("consecutive_cancellations"):
        detail.append(f"{row['consecutive_cancellations']} consecutive cancellations "
                      f"(the scheduled run was cancelled before any step ran)")
    elif row.get("cancellations_in_window"):
        detail.append(f"{row['cancellations_in_window']} cancelled run(s) in {LOOKBACK_DAYS}d")
    if row["overdue_hours"]:
        detail.append(f"no run for {row['overdue_hours']}h "
                      f"(maximum scheduled gap {row['expected_interval_hours']}h + {DELAY_ALLOWANCE_H}h delay allowance)")
    return "; ".join(detail)


def _surface(result):
    """Put the rollup where a weekly report can actually be seen.

    The step log scrolls away and continue-on-error keeps the run green, so the
    aggregate view of Actions-side health used to live only in a log line
    nobody opens. $GITHUB_STEP_SUMMARY (set on runners) gets a persistent
    table, and each attention row becomes a ::warning:: annotation on the run
    page itself. Still report-only: no exit-code change, no notifications.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        lines = [
            "## Scheduled workflow health",
            f"needs attention: {result['needs_attention']} of "
            f"{result['scheduled_workflows']} "
            f"(lookback {result['lookback_days']}d)",
            "",
            "| workflow | last run | detail |",
            "|---|---|---|",
        ]
        for row in result["workflows"]:
            detail = _row_detail(row) or "—"
            lines.append(
                f"| {row['workflow']} | {(row['last_conclusion'] or '-')} "
                f"@{(row['last_run'] or '-')[:16]} | {detail} |"
            )
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError as exc:
            print(f"warn: step summary write failed: {exc}", file=sys.stderr)
    for row in result["workflows"]:
        if row["status"] == "attention":
            print(f"::warning::scheduled workflow {row['workflow']}: "
                  f"{_row_detail(row) or 'needs attention'}")


if __name__ == "__main__":
    sys.exit(main())
