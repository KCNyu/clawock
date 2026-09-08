#!/usr/bin/env python3
"""Did the off-host brief backstop's weekly rehearsal pass, and how long ago?

`brief-fallback.yml` rehearses its generation chain every Wednesday (`23 4 * * 3`)
precisely because every other run of that workflow is a no-op: the primary brief
lands, the run takes the `already-exists` branch in 20 seconds, and a green tick
says nothing at all about whether the backstop could produce a brief. The
rehearsal is the ONE run per week that carries information.

Nothing read it. On 2026-09-02 the rehearsal failed — MiniMax timed out three
times, opencode returned `HTTP 401 CreditsError: Insufficient balance`, so the
whole off-host chain was dead — and it stayed unnoticed for six days, because:

  - the failure is one red run among ~20 green skips, and `workflow_health.py`'s
    generic heuristic (`streak >= 2` is attention, one failure is a dot) demotes
    it to `· brief-fallback.yml 1 failure(s) in 7d`. For a workflow whose runs are
    almost all no-ops that heuristic is backwards: one failure IS the signal;
  - the rehearsal's verdict is written only to `$GITHUB_STEP_SUMMARY` on that run;
  - nothing else on the daily path looks at brief-fallback at all.

## Identifying the rehearsal run

The GitHub API does not report which cron expression triggered a scheduled run
(`/actions/runs/<id>` has `event`, never the schedule), so the run is identified
by the **shape of its step conclusions**, which is unambiguous and was verified
against real runs:

    branch          preflight/LLM steps    "Commit + push"
    already-exists  skipped                skipped
    too-late        skipped                skipped
    rehearsal       ran                    skipped
    generated       ran                    ran

Note the rehearsal's own check step (`Rehearsal — did the chain…`) is NOT the
discriminator: when the generation chain fails, that step is itself `skipped`,
which is exactly the case this module exists to catch. `tests/` pins the step
names against the workflow file so a rename cannot silently turn every run into
`unknown`.

## Reporting rules

A lookup that failed and a rehearsal that failed must never collapse into the
same answer — that is the same lie `_gh_json` was written to stop telling in
`_watchdog_common`. `status` is one of:

    pass     the last rehearsal generated a brief
    fail     the last rehearsal did not — the backstop would not work today
    overdue  the last rehearsal is older than two of its own weekly periods
    unknown  could not be determined (no gh, bad JSON, no runs, renamed steps)

`--strict` exits non-zero for `fail`/`overdue` only. `unknown` always exits 0:
a gh hiccup must not redden a health check that has its own verdict.

Usage:
    backstop_rehearsal.py              # human-readable verdict, always exit 0
    backstop_rehearsal.py --strict     # exit 1 on a determined failure
    backstop_rehearsal.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

WORKFLOW = "brief-fallback.yml"
# Steps whose conclusion carries the branch signature. Pinned by
# tests/test_backstop_rehearsal.py against the workflow file itself.
GENERATION_STEP = "Call off-host LLM to generate brief"
PUBLISH_STEP = "Commit + push"
# The rehearsal fires weekly; allow two of its own periods before calling it
# overdue, matching workflow_health.MISSED_CADENCE_FACTOR's intent — one delayed
# or skipped week is a slow scheduler, two is a backstop nobody is testing.
OVERDUE_DAYS = 15
RUN_LOOKBACK = 30


def _run(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout


def _json(runner, cmd):
    """Parsed JSON, or None. None means 'could not determine', never 'empty'."""
    try:
        raw = runner(cmd)
    except Exception:
        return None
    try:
        return json.loads(raw or "")
    except (json.JSONDecodeError, TypeError):
        return None


def _steps(runner, run_id, repo):
    payload = _json(runner, ["gh", "api", f"/repos/{repo}/actions/runs/{run_id}/jobs"])
    if not isinstance(payload, dict):
        return None
    steps = {}
    for job in payload.get("jobs") or []:
        for step in job.get("steps") or []:
            name = step.get("name")
            if name:
                steps[name] = step.get("conclusion")
    return steps or None


def classify(steps):
    """Which branch of brief-fallback.yml did this run take?

    Returns 'rehearsal', 'generated', 'skipped', or None when the signature
    cannot be read — a renamed step must produce None, not a wrong branch.
    """
    if not steps or GENERATION_STEP not in steps or PUBLISH_STEP not in steps:
        return None
    if steps[GENERATION_STEP] == "skipped":
        return "skipped"
    return "rehearsal" if steps[PUBLISH_STEP] == "skipped" else "generated"


def _parse(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def assess(runner=None, now=None, repo=None, limit=RUN_LOOKBACK):
    """Verdict on the most recent rehearsal of the off-host brief backstop."""
    runner = runner or _run
    # GITHUB_REPOSITORY first so the check reads the repository it is running
    # in (a fork included) rather than a hard-coded upstream.
    repo = (repo or os.environ.get("GITHUB_REPOSITORY")
            or os.environ.get("CLAWOCK_TRAFFIC_REPO") or "KCNyu/clawock")
    now = now or datetime.now(timezone.utc)

    runs = _json(runner, [
        "gh", "run", "list", "--workflow", WORKFLOW, "--limit", str(limit),
        "--json", "databaseId,createdAt,conclusion,event,url",
    ])
    if not isinstance(runs, list):
        return {"status": "unknown", "reason": "could not list brief-fallback runs"}
    if not runs:
        return {"status": "unknown", "reason": "no brief-fallback runs in history"}

    unreadable = 0
    for entry in sorted(runs, key=lambda r: str(r.get("createdAt")), reverse=True):
        run_id = entry.get("databaseId")
        if run_id is None:
            continue
        branch = classify(_steps(runner, run_id, repo))
        if branch is None:
            unreadable += 1
            continue
        if branch != "rehearsal":
            continue
        at = _parse(entry.get("createdAt"))
        age_days = round((now - at).total_seconds() / 86400, 1) if at else None
        conclusion = entry.get("conclusion")
        result = {
            "run_id": run_id,
            "run_url": entry.get("url"),
            "at": entry.get("createdAt"),
            "age_days": age_days,
            "conclusion": conclusion,
        }
        if conclusion != "success":
            result["status"] = "fail"
            result["reason"] = (
                f"the last rehearsal ({conclusion or 'no conclusion'}) did not produce "
                "a brief — the off-host backstop would not work today")
            return result
        if age_days is not None and age_days > OVERDUE_DAYS:
            result["status"] = "overdue"
            result["reason"] = (
                f"the last passing rehearsal was {age_days}d ago (weekly cadence, "
                f"cutoff {OVERDUE_DAYS}d) — the backstop is untested")
            return result
        result["status"] = "pass"
        result["reason"] = "the off-host generation chain produced a brief"
        return result

    if unreadable:
        return {"status": "unknown",
                "reason": f"{unreadable} run(s) had an unreadable step signature — "
                          "brief-fallback.yml step names may have changed"}
    return {"status": "overdue",
            "reason": f"no rehearsal found in the last {len(runs)} runs — "
                      "the weekly drill is not firing"}


MARKS = {"pass": "✓", "fail": "✗", "overdue": "✗", "unknown": "~"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on a determined failure (never on 'unknown')")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    verdict = assess()
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, sort_keys=True))
    else:
        mark = MARKS.get(verdict["status"], "~")
        print(f"  {mark} off-host brief backstop   {verdict['reason']}")
        if verdict.get("run_url"):
            print(f"      last rehearsal: {verdict['run_url']} "
                  f"({verdict.get('at')})")
    if args.strict and verdict["status"] in ("fail", "overdue"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
