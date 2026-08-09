#!/usr/bin/env python3
"""Reconcile host watchdog commands and US schedules with the cron contract.

The daemon's America/New_York cron parsing has regressed before, so the runtime
jobs stay in HKT. This tool derives the correct HKT expressions from the tracked
seasonal contract and applies them daily at 06:20 HKT, safely before market jobs.
It also owns the exact system-crontab command for every watchdog, including the
installed command used after the source-tree alias cutover.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
sys.path.insert(0, str(_CHECKOUT / "instances" / "kcnyu" / "src"))
from clawock.workspace import workspace_root  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
WS = workspace_root(_CHECKOUT)
from clawock_kcnyu.schedule import (  # noqa: E402
    effective_schedule,
    load_contract,
    next_us_dst_transition,
    parse_crontab_lines,
    us_season,
)
# The cron command line belongs to the adapter (#330 step 2): this script owns
# WHEN the US schedule shifts, not how an edit reaches OpenClaw.
#
# The CHECKOUT root, not WS: `workspace_root` is overridable, so WS can be a
# data directory with no `clawock` package in it.
from clawock.providers.openclaw import (  # noqa: E402
    build_cron_edit_argv,
    read_jobs_strict,
)


def load_live_jobs() -> list[dict]:
    """Read the live scheduler strictly before planning any writes."""
    return read_jobs_strict()


def _find_managed_row(rows: list[dict], spec: dict) -> tuple[dict | None, str]:
    """Find exactly one canonical row."""
    canonical = [row for row in rows if row["command"] == spec.get("command")]
    if len(canonical) == 1:
        return canonical[0], "canonical"
    return None, "missing"


def _crontab_change(name: str, spec: dict, rows: list[dict], at: datetime,
                    *, kind: str) -> tuple[dict | None, str | None]:
    row, matched_by = _find_managed_row(rows, spec)
    if not row:
        return None, f"missing or ambiguous {kind} for {name}"
    desired_expr = effective_schedule(spec, at).get("expr")
    desired_command = spec.get("command")
    if row["expr"] == desired_expr and row["command"] == desired_command:
        return None, None
    return {
        "name": name,
        "kind": kind,
        "line_index": row["index"],
        "matched_by": matched_by,
        "from": {"expr": row["expr"], "command": row["command"]},
        "to": {"expr": desired_expr, "command": desired_command},
    }, None


def parse_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def desired_changes(contract: dict, live_jobs: list[dict], crontab_text: str,
                    at: datetime) -> tuple[list[dict], list[dict], list[str]]:
    live_by_name = {j.get("name"): j for j in live_jobs}
    cron_rows = parse_crontab_lines(crontab_text)
    openclaw_changes = []
    watchdog_changes = []
    errors = []
    for job in contract["jobs"]:
        if job.get("seasonal_schedules"):
            live = live_by_name.get(job["name"])
            if not live:
                errors.append(f"missing live job {job['name']}")
            else:
                desired = effective_schedule(job, at)
                current = live.get("schedule") or {}
                if (current.get("expr"), current.get("tz")) != (
                    desired.get("expr"), desired.get("tz")
                ):
                    openclaw_changes.append({
                        "name": job["name"],
                        "id": live.get("id"),
                        "from": {"expr": current.get("expr"), "tz": current.get("tz")},
                        "to": {"expr": desired.get("expr"), "tz": desired.get("tz")},
                    })
        watchdogs = [("watchdog", job.get("watchdog"))]
        watchdogs.extend(
            (f"extra-watchdog-{index}", watchdog)
            for index, watchdog in enumerate(job.get("extra_watchdogs") or [], start=1)
        )
        for kind, watchdog in watchdogs:
            if not watchdog:
                continue
            change, error = _crontab_change(
                job["name"], watchdog, cron_rows, at, kind=kind)
            if error:
                errors.append(error)
            elif change:
                watchdog_changes.append(change)

    sync = contract["dst_sync"]
    change, error = _crontab_change(
        "US cron DST sync", sync, cron_rows, at, kind="dst-sync")
    if error:
        errors.append(error)
    elif change:
        watchdog_changes.append(change)
    return openclaw_changes, watchdog_changes, errors


def apply_openclaw(changes: list[dict]) -> list[str]:
    errors = []
    for change in changes:
        if not change.get("id"):
            errors.append(f"{change['name']}: missing runtime id")
            continue
        try:
            cmd = build_cron_edit_argv(change["id"], {"schedule": change["to"]})
        except ValueError as exc:
            errors.append(f"{change['name']}: {exc}")
            continue
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if result.returncode != 0:
            errors.append(f"{change['name']}: {(result.stdout + result.stderr)[-300:]}")
    return errors


def apply_crontab(text: str, changes: list[dict]) -> list[str]:
    if not changes:
        return []
    lines = text.splitlines()
    for change in changes:
        index = change["line_index"]
        parts = lines[index].split(None, 5)
        if len(parts) < 6:
            return [f"cannot parse crontab line {index + 1}"]
        lines[index] = f"{change['to']['expr']} {change['to']['command']}"
    payload = "\n".join(lines) + "\n"
    result = subprocess.run(
        ["crontab", "-"], input=payload, capture_output=True, text=True, timeout=15,
    )
    return [] if result.returncode == 0 else [(result.stdout + result.stderr)[-300:]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="apply derived schedules")
    parser.add_argument("--at", help="ISO timestamp override (tests/audits)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    at = parse_at(args.at)
    contract = load_contract()
    live_jobs = load_live_jobs()
    crontab = subprocess.check_output(["crontab", "-l"], text=True)
    oc_changes, wd_changes, errors = desired_changes(contract, live_jobs, crontab, at)
    applied = False
    if args.apply and not errors:
        errors.extend(apply_openclaw(oc_changes))
        if not errors:
            errors.extend(apply_crontab(crontab, wd_changes))
        applied = not errors and bool(oc_changes or wd_changes)

    transition = next_us_dst_transition(at)
    result = {
        "status": "error" if errors else ("applied" if applied else "ok"),
        "season": us_season(at),
        "checked_at": at.isoformat(),
        "next_transition_date": transition.date().isoformat() if transition else None,
        "openclaw_changes": oc_changes,
        "watchdog_changes": wd_changes,
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"US cron DST: {result['status']} · {result['season']} · "
            f"openclaw={len(oc_changes)} watchdog={len(wd_changes)} · "
            f"next={result['next_transition_date']}"
        )
        for error in errors:
            print(f"  ERROR: {error}", file=sys.stderr)
    if errors:
        return 2
    if not args.apply and (oc_changes or wd_changes):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
