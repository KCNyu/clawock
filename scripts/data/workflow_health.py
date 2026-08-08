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
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clawock.workspace import workspace_root  # noqa: E402
from clawock.providers import GitHubRuns, Run  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
WORKFLOW_DIR = WS / ".github" / "workflows"
LOOKBACK_DAYS = 7
# A schedule that fires at most weekly still has to fire inside two of its own
# periods before we call it missing; anything tighter turns a delayed runner into
# a false alarm.
MISSED_CADENCE_FACTOR = 2.2
CRON_RE = re.compile(r"cron:\s*'([^']+)'")


def schedules(path: Path) -> list[str]:
    return CRON_RE.findall(path.read_text(encoding="utf-8"))


def expected_interval_hours(exprs: list[str]) -> float | None:
    """Roughly how often this workflow should fire, from its cron expressions.

    Deliberately coarse: the question is "should something have happened by now",
    not the exact next fire time.
    """
    if not exprs:
        return None
    best = None
    for expr in exprs:
        fields = expr.split()
        if len(fields) != 5:
            continue
        minute, hour, dom, month, dow = fields
        if minute.startswith("*/"):
            hours = int(minute[2:]) / 60
        elif hour.startswith("*/"):
            hours = int(hour[2:])
        elif hour == "*":
            hours = 1
        elif dow != "*" and dom == "*":
            days = len([d for d in _expand_dow(dow)]) or 1
            hours = 24 * 7 / days
        elif dom != "*":
            hours = 24 * 31
        else:
            hours = 24
        best = hours if best is None else min(best, hours)
    return best


def _expand_dow(dow: str) -> list[int]:
    out: list[int] = []
    for part in dow.split(","):
        if "-" in part:
            start, end = part.split("-")[:2]
            try:
                out.extend(range(int(start), int(end) + 1))
            except ValueError:
                continue
        else:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return out


def fetch_runs(workflow: str, limit: int = 20, runner=None) -> list[Run]:
    """Production caller for the GitHub run-history provider (#362)."""
    return GitHubRuns(runner=runner).history(workflow, limit=limit)


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
    scheduled = [r for r in runs if _run_field(r, "trigger", "event") == "schedule"] or runs
    window_start = now - timedelta(days=LOOKBACK_DAYS)

    def parsed(run):
        try:
            return datetime.fromisoformat(
                str(_run_field(run, "started_at", "createdAt")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    recent = [r for r in scheduled if (parsed(r) or window_start) >= window_start]
    failures = [r for r in recent if _status(r) == "error"]
    streak = 0
    for run in scheduled:                       # newest first
        if _status(run) == "error":
            streak += 1
        elif _status(run) in ("running", "cancelled", "skipped"):
            continue
        else:
            break
    last = parsed(scheduled[0]) if scheduled else None
    interval = expected_interval_hours(exprs)
    overdue_hours = None
    if last and interval:
        age = (now - last).total_seconds() / 3600
        if age > interval * MISSED_CADENCE_FACTOR:
            overdue_hours = round(age, 1)
    status = "ok"
    if streak >= 2 or overdue_hours is not None:
        status = "attention"
    elif failures:
        status = "noted"
    return {
        "workflow": workflow,
        "schedules": exprs,
        "expected_interval_hours": interval,
        "last_run": last.isoformat() if last else None,
        "last_conclusion": _display_status(scheduled[0]) if scheduled else None,
        "failures_in_window": len(failures),
        "consecutive_failures": streak,
        "overdue_hours": overdue_hours,
        "status": status,
    }


def report(now: datetime | None = None, runner=None, workflow_dir: Path = WORKFLOW_DIR) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = []
    for path in sorted(workflow_dir.glob("*.yml")):
        exprs = schedules(path)
        if not exprs:
            continue                            # push/PR workflows report through PRs
        rows.append(assess(path.name, exprs, fetch_runs(path.name, runner=runner), now))
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
        detail = []
        if row["consecutive_failures"]:
            detail.append(f"{row['consecutive_failures']} consecutive failures")
        elif row["failures_in_window"]:
            detail.append(f"{row['failures_in_window']} failure(s) in {LOOKBACK_DAYS}d")
        if row["overdue_hours"]:
            detail.append(f"no run for {row['overdue_hours']}h "
                          f"(expected every ~{row['expected_interval_hours']}h)")
        print(f"  {mark} {row['workflow']:26} last={row['last_conclusion'] or '-'}"
              f"@{(row['last_run'] or '-')[:16]}"
              + (f"  {'; '.join(detail)}" if detail else ""))
    # Report only: a weekly rollup must not fail the job it runs inside.
    return 0


if __name__ == "__main__":
    sys.exit(main())
