#!/usr/bin/env python3
"""Token usage per cron run, compared only against comparable runs.

Written for issue #122: 盘前深度简报 burned 13,363,237 tokens on 2026-07-27, on a
run that failed. The obvious framing — "90x the Sonnet-era 135k" — is wrong, and
this module exists partly to stop that framing from being repeated. The run log's
`usage` is reported differently per provider:

    claude-cli/claude-sonnet-4-6   input=1     output=2      total=136,966
    minimax-2/MiniMax-M3           input=88k   output=30k    total=3,951,265

`input`/`output` from the CLI-backed provider describe the last turn only, so a
cross-provider total ratio measures the accounting, not the work. What is real is
the within-provider comparison: against its own last three MiniMax runs (3.67M /
3.95M / 4.94M) the 07-27 run is 2.7-3.6x high, and that is the signal worth
alerting on.

So: group by (provider, model), compare each run to the trailing median of its own
group, and report the composition alongside the total so the next person can see
which number moved. No circuit-breaker here — deciding what to cut requires
knowing where the tokens go, and this is the instrument that answers that.

Read-only. Never raises on a missing or unreadable run store: this feeds the daily
health review, and an audit that could red the review would be worse than no
audit (kcn does not want per-cron alerts — see feedback_no_individual_cron_alerts).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.providers import openclaw  # noqa: E402

HKT = timezone(timedelta(hours=8))
# Enough history to have a stable median per provider without reaching back to a
# different prompt generation.
BASELINE_RUNS = 8
MIN_BASELINE = 3
# 07-27 sat at 3.4x its own group median. 2.5x flags that class while leaving the
# observed 3.67M-4.94M spread (max 1.35x off median) quiet.
REGRESSION_RATIO = 2.5


# Read the live SQLite directly rather than through `auto`. `auto` shells out to
# `openclaw cron runs --id` once per job; across 11 jobs that took minutes, and the
# CLI's own slowness is a known source of silent fallback to a stale fossil store
# (2026-07-18). This is a read-only report — the fastest honest source wins.
RUN_SOURCE = "sqlite"


def _load_runs(job_id, reader=None):
    if reader is not None:
        return reader(job_id) or []
    try:
        return openclaw.read_runs(job_id, RUN_SOURCE).entries
    except Exception:  # noqa: BLE001 — a health report must not die on the store
        return []


def _load_jobs(reader=None):
    if reader is not None:
        return reader()
    try:
        return openclaw.read_jobs(RUN_SOURCE).entries
    except Exception:  # noqa: BLE001
        return []


def _usage(run):
    usage = run.get("usage") or {}
    total = usage.get("total_tokens")
    if not isinstance(total, (int, float)) or total <= 0:
        return None
    return {
        "total": int(total),
        "input": usage.get("input_tokens"),
        "output": usage.get("output_tokens"),
        "provider": run.get("provider"),
        "model": run.get("model"),
        "status": run.get("status"),
        "run_at": run.get("runAtMs"),
    }


def audit_job(job_id, name=None, *, runs_reader=None,
              baseline=BASELINE_RUNS, ratio=REGRESSION_RATIO):
    """Latest run's token usage vs the trailing median of its own provider group."""
    runs = [u for u in (_usage(run) for run in _load_runs(job_id, runs_reader)) if u]
    if not runs:
        return {"job": name or job_id, "state": "no_usage_recorded"}

    latest = runs[-1]
    group = [
        u for u in runs[:-1]
        if (u["provider"], u["model"]) == (latest["provider"], latest["model"])
    ][-baseline:]

    report = {
        "job": name or job_id,
        "state": "ok",
        "provider": latest["provider"],
        "model": latest["model"],
        "status": latest["status"],
        "total_tokens": latest["total"],
        "input_tokens": latest["input"],
        "output_tokens": latest["output"],
        "baseline_runs": len(group),
        "run_at": (datetime.fromtimestamp(latest["run_at"] / 1000, HKT).isoformat()
                   if latest.get("run_at") else None),
    }
    if len(group) < MIN_BASELINE:
        # A provider swap resets the baseline. Saying "no comparable history" is
        # the honest answer; comparing across providers is what produced the
        # bogus 90x in the first place.
        report["state"] = "no_comparable_baseline"
        return report

    median = statistics.median(u["total"] for u in group)
    report["baseline_median"] = int(median)
    report["ratio"] = round(latest["total"] / median, 2) if median else None
    if median and latest["total"] > median * ratio:
        report["state"] = "regressed"
    return report


def audit(*, runs_reader=None, jobs_reader=None, ratio=REGRESSION_RATIO):
    reports = []
    for job in _load_jobs(jobs_reader):
        job_id = job.get("id") or job.get("job_id")
        if not job_id:
            continue
        reports.append(audit_job(job_id, job.get("name"),
                                 runs_reader=runs_reader, ratio=ratio))
    return reports


def regressions(reports):
    return [r for r in reports if r.get("state") == "regressed"]


def format_lines(reports):
    lines = []
    for report in sorted(reports, key=lambda r: -(r.get("ratio") or 0)):
        if report["state"] == "no_usage_recorded":
            continue
        mark = "⚠️" if report["state"] == "regressed" else "·"
        total = f'{report.get("total_tokens", 0):,}'
        if report["state"] == "no_comparable_baseline":
            detail = f'{report.get("baseline_runs", 0)} comparable runs — no baseline yet'
        else:
            detail = (f'median {report.get("baseline_median", 0):,} '
                      f'× {report.get("ratio")}')
        lines.append(
            f'{mark} {report["job"]}: {total} tokens '
            f'({report.get("provider")}/{report.get("model")}, {detail})'
        )
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--ratio", type=float, default=REGRESSION_RATIO)
    args = parser.parse_args()

    reports = audit(ratio=args.ratio)
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for line in format_lines(reports):
            print(line)
    # Advisory only: a token regression is a thing to look at in the daily review,
    # never a reason to fail whatever called this.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
