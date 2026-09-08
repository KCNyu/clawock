#!/usr/bin/env python3
"""Do the workflows that bet on GitHub being punctual still win that bet?

`assets/data/schedule-drift.json` has been measuring GitHub's delivery lateness
twice a week since #781. Nothing read it. Five workflow headers meanwhile carry
a punctuality budget in prose — "~2.25h before the 08:00 HKT brief", "buffer for
GH Actions' 1-2h scheduled-cron delay" — and those sentences were the only thing
holding the design together.

On 2026-08-27 the drift regime changed. Measured on `news-digest.yml`, the
cleanest probe in the repo (one daily cron, `0 13 * * 1-5`):

    07-28..08-26   n=22   median  72.5 min   max 157.2
    08-27..09-07   n=8    median 271.4 min   min 219.1

The step is clean (the post-08-27 minimum exceeds the pre-08-27 maximum) and it
is not ours: it lands on four different UTC hours at once, runs/day went *down*
over the same period (206 -> 145), and `created_at == run_started_at` on all 203
scheduled runs sampled, so the delay is in GitHub creating the run, not in
waiting for a runner. Nothing on our side can shorten it.

What can be fixed is that no gate noticed. `workflow_health.py` asks "did it
fail" and "did it run at all"; a workflow delivered four hours late still ran, so
lateness is invisible to it. `brief-fallback.yml`'s three-attempt mitigation —
correct when it was calibrated against 89-159 minutes — has not landed inside its
own usefulness window on any of the last 10 scheduled days, and said nothing.

## The contract

`config/schedule-punctuality.json` classifies every scheduled workflow: a
`deadline_hkt` (the instant past which the run has lost its purpose) or `null`
with the reason it has none. `tests/` enumerates the workflow directory against
it, so a new workflow cannot acquire a deadline silently.

A deadline is `enforced` (a sustained breach reddens the daily run) or
`accepted` (real, currently unmet, and the reason says why that is tolerated).
`accepted` exists so the answer to an unfixable breach is a written decision
rather than either a lie or a permanently red check nobody can act on.

## Why "sustained"

One late arrival is GitHub having a bad hour; that is a warning, and the count is
reported. A red means the bet is structurally lost — the last
`SUSTAINED_BREACH_RUNS` measured arrivals ALL missed the deadline. That is the
difference between brief-fallback (0 in window in 10 days) and macro-scan (late
6 times in 20, median arrival still 25 minutes early).

Usage:
    schedule_punctuality.py            # table, always exit 0
    schedule_punctuality.py --strict   # exit 1 on a sustained enforced breach
    schedule_punctuality.py --json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "config" / "schedule-punctuality.json"
DRIFT = ROOT / "assets" / "data" / "schedule-drift.json"
WORKFLOW_DIR = ROOT / ".github" / "workflows"
HKT = dt.timezone(dt.timedelta(hours=8))
# How many consecutive missed deadlines turn a warning into a verdict. Five is
# a working week for a daily workflow: long enough that a bad GitHub day cannot
# reach it, short enough that a design which has actually stopped working is
# caught inside a week.
SUSTAINED_BREACH_RUNS = 5


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _parse(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def deadline_instant(scheduled, deadline_hkt):
    """The instant this run had to arrive by, given when it was scheduled.

    The deadline is a time of day. It belongs to the scheduled run's own HKT day
    when it falls later that day, and to the next one otherwise — which is what
    makes an evening scan (20:50 HKT) measure against the brief it actually
    feeds, tomorrow's 08:00, rather than against one that was already over.
    """
    hour, minute = (int(part) for part in deadline_hkt.split(":"))
    local = scheduled.astimezone(HKT)
    due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= local:
        due += dt.timedelta(days=1)
    return due


def assess_workflow(rule, runs):
    """Verdict for one workflow's measured arrivals against its deadline."""
    deadline = rule.get("deadline_hkt")
    if not deadline:
        return {"status": "no-deadline"}

    samples = []
    for run in runs:
        scheduled, started = _parse(run.get("scheduled_at")), _parse(run.get("started_at"))
        if not scheduled or not started:
            continue
        due = deadline_instant(scheduled, deadline)
        samples.append({
            "started_at": run.get("started_at"),
            "arrived_hkt": started.astimezone(HKT).strftime("%m-%d %H:%M"),
            "due_hkt": due.strftime("%m-%d %H:%M"),
            "late": started > due,
            "minutes_late": round((started - due).total_seconds() / 60, 1),
        })
    if not samples:
        return {"status": "unmeasured", "deadline_hkt": deadline,
                "reason": "no usable drift samples for this workflow"}

    samples.sort(key=lambda s: str(s["started_at"]), reverse=True)
    recent = samples[:SUSTAINED_BREACH_RUNS]
    late = [s for s in samples if s["late"]]
    sustained = len(recent) == SUSTAINED_BREACH_RUNS and all(s["late"] for s in recent)

    enforcement = rule.get("enforcement", "enforced")
    if sustained:
        status = "breached" if enforcement == "enforced" else "accepted-breach"
    elif late:
        status = "late-sometimes"
    else:
        status = "ok"
    return {
        "status": status,
        "deadline_hkt": deadline,
        "enforcement": enforcement,
        "samples": len(samples),
        "late": len(late),
        "worst_minutes_late": max((s["minutes_late"] for s in late), default=0.0),
        "latest_arrivals": [f"{s['arrived_hkt']} (due {s['due_hkt']})" for s in recent[:3]],
    }


# `None` is a real answer here — it is what `load` returns for a file that is
# missing or corrupt, and telling that apart from a met deadline is the whole
# job. So "argument not supplied" needs its own value, or a test cannot inject
# the unreadable case and the seam quietly tests nothing.
_UNSET = object()


def report(contract=_UNSET, drift=_UNSET):
    contract = load(CONTRACT) if contract is _UNSET else contract
    drift = load(DRIFT) if drift is _UNSET else drift
    if not contract:
        return {"status": "unknown", "reason": f"cannot read {CONTRACT.name}",
                "workflows": {}}
    if not drift:
        return {"status": "unknown", "reason": f"cannot read {DRIFT.name}",
                "workflows": {}}

    measured = {entry.get("workflow"): entry.get("runs") or []
                for entry in drift.get("workflows") or []}
    rows = {}
    for name, rule in (contract.get("workflows") or {}).items():
        rows[name] = assess_workflow(rule, measured.get(name, []))
        rows[name]["why"] = rule.get("why", "")
    breached = [n for n, r in rows.items() if r["status"] == "breached"]
    return {
        "status": "breached" if breached else "ok",
        "measured_at": drift.get("generated_at"),
        "breached": breached,
        "workflows": rows,
    }


MARKS = {"ok": "✓", "late-sometimes": "·", "breached": "✗",
         "accepted-breach": "~", "no-deadline": " ", "unmeasured": "~"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when an enforced deadline is sustainedly breached")
    ap.add_argument("--all", action="store_true",
                    help="also list the workflows that have no deadline")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    result = report()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1 if (args.strict and result["status"] == "breached") else 0

    if result["status"] == "unknown":
        print(f"  ~ schedule punctuality      {result['reason']}")
        return 0
    print(f"schedule punctuality · drift measured {(result['measured_at'] or '?')[:16]}")
    for name, row in sorted(result["workflows"].items()):
        if row["status"] == "no-deadline" and not args.all:
            continue
        mark = MARKS.get(row["status"], "?")
        detail = ""
        if row["status"] in ("ok", "late-sometimes", "breached", "accepted-breach"):
            detail = (f"deadline {row['deadline_hkt']} HKT · "
                      f"{row['late']}/{row['samples']} late")
            if row["late"]:
                detail += f" · worst +{row['worst_minutes_late']:.0f}min"
        elif row["status"] == "unmeasured":
            detail = row["reason"]
        print(f"  {mark} {name:26} {detail}")
        if row["status"] in ("breached", "accepted-breach"):
            for arrival in row["latest_arrivals"]:
                print(f"      arrived {arrival}")
    if result["breached"]:
        print(f"\n🔴 punctuality — {', '.join(result['breached'])} "
              f"missed its deadline on the last {SUSTAINED_BREACH_RUNS} measured runs")
    if args.strict and result["status"] == "breached":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
