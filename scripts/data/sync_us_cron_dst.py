#!/usr/bin/env python3
"""Keep US OpenClaw jobs and their system watchdogs aligned with New York DST.

The daemon's America/New_York cron parsing has regressed before, so the runtime
jobs stay in HKT. This tool derives the correct HKT expressions from the tracked
seasonal contract and applies them daily at 06:20 HKT, safely before market jobs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WS / "scripts" / "data"))
sys.path.insert(0, str(WS / "scripts" / "harness"))

from cron_contract import (  # noqa: E402
    effective_schedule,
    find_crontab_row,
    load_contract,
    next_us_dst_transition,
    parse_crontab_lines,
    us_season,
)
from _watchdog_common import load_jobs  # noqa: E402

PROVIDER_HEALTH_COMMAND = (
    "/bin/bash -lc 'cd /root/.openclaw/workspace && "
    "python3 scripts/data/provider_health.py --apply "
    ">> logs/provider-health.log 2>&1'"
)


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
        watchdog = job.get("watchdog") or {}
        if not watchdog.get("seasonal_schedules"):
            continue
        tokens = watchdog.get("command_contains") or []
        row = find_crontab_row(cron_rows, tokens)
        if not row:
            errors.append(f"missing or ambiguous watchdog for {job['name']}: {tokens}")
            continue
        desired_expr = effective_schedule(watchdog, at).get("expr")
        if row["expr"] != desired_expr:
            watchdog_changes.append({
                "name": job["name"], "line_index": row["index"],
                "from": row["expr"], "to": desired_expr,
            })
    # Bootstrap/repair the readiness gate from this already-scheduled 06:20
    # maintenance job. This avoids a circular dependency where provider_health
    # can never run because its own crontab row is missing.
    health = contract.get("provider_health") or {}
    tokens = health.get("command_contains") or []
    row = find_crontab_row(cron_rows, tokens)
    desired_expr = effective_schedule(health, at).get("expr")
    if not row:
        watchdog_changes.append({
            "name": "Provider health",
            "line_index": None,
            "from": None,
            "to": desired_expr,
            "command": PROVIDER_HEALTH_COMMAND,
        })
    elif row["expr"] != desired_expr:
        watchdog_changes.append({
            "name": "Provider health",
            "line_index": row["index"],
            "from": row["expr"],
            "to": desired_expr,
        })
    return openclaw_changes, watchdog_changes, errors


def apply_openclaw(changes: list[dict]) -> list[str]:
    errors = []
    for change in changes:
        if not change.get("id"):
            errors.append(f"{change['name']}: missing runtime id")
            continue
        cmd = [
            "openclaw", "cron", "edit", change["id"],
            "--cron", change["to"]["expr"],
            "--tz", change["to"]["tz"], "--exact",
        ]
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
        if index is None:
            lines.append(f"{change['to']} {change['command']}")
            continue
        parts = lines[index].split(None, 5)
        if len(parts) < 6:
            return [f"cannot parse crontab line {index + 1}"]
        lines[index] = f"{change['to']} {parts[5]}"
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
    live_jobs = load_jobs()
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
