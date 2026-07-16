#!/usr/bin/env python3
"""Shared cron contract helpers: seasonal schedules, payloads, and watchdogs."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WS = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = WS / "config" / "cron-schedules.json"
HKT = ZoneInfo("Asia/Hong_Kong")
ET = ZoneInfo("America/New_York")


def load_contract(path: str | Path | None = None) -> dict:
    data = json.loads(Path(path or DEFAULT_CONTRACT).read_text())
    if data.get("schema_version") != 2:
        raise ValueError("cron contract schema_version must be 2")
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("cron contract jobs must be a non-empty list")
    names = [j.get("name") for j in jobs]
    if len(names) != len(set(names)) or any(not n for n in names):
        raise ValueError("cron contract job names must be non-empty and unique")
    profiles = data.get("payload_profiles") or {}
    for job in jobs:
        if bool(job.get("schedule")) == bool(job.get("seasonal_schedules")):
            raise ValueError(f"{job['name']}: define exactly one schedule source")
        seasonal = job.get("seasonal_schedules")
        if seasonal and set(seasonal) != {"daylight", "standard"}:
            raise ValueError(f"{job['name']}: seasonal schedules require daylight+standard")
        if job.get("payload_profile") not in profiles:
            raise ValueError(f"{job['name']}: unknown payload profile")
        watchdog = job.get("watchdog")
        if watchdog:
            if bool(watchdog.get("schedule")) == bool(watchdog.get("seasonal_schedules")):
                raise ValueError(f"{job['name']}: watchdog needs exactly one schedule source")
            if not watchdog.get("command_contains"):
                raise ValueError(f"{job['name']}: watchdog command matcher missing")
    sync = data.get("dst_sync") or {}
    if not sync.get("schedule") or not sync.get("command_contains"):
        raise ValueError("dst_sync schedule and command matcher are required")
    return data


def us_season(at: datetime | None = None) -> str:
    """Return daylight/standard using the actual New York UTC offset."""
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    local = at.astimezone(ET)
    return "daylight" if local.dst() and local.dst() != timedelta(0) else "standard"


def next_us_dst_transition(at: datetime | None = None) -> datetime | None:
    """Find the next ET offset transition, to hour precision, within 370 days."""
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    base = at.astimezone(ET).utcoffset()
    for hours in range(1, 370 * 24 + 1):
        probe = at + timedelta(hours=hours)
        if probe.astimezone(ET).utcoffset() != base:
            return probe
    return None


def effective_schedule(item: dict, at: datetime | None = None) -> dict:
    seasonal = item.get("seasonal_schedules")
    if seasonal:
        season = us_season(at)
        if season not in seasonal:
            raise ValueError(f"missing {season} seasonal schedule")
        return seasonal[season]
    schedule = item.get("schedule")
    if not schedule:
        raise ValueError("missing schedule")
    return schedule


def schedule_tuple(item: dict, at: datetime | None = None) -> tuple:
    schedule = effective_schedule(item, at)
    return schedule.get("expr"), schedule.get("tz"), item.get("enabled", True)


def _format_required(text: str, variables: dict) -> str:
    try:
        return text.format(**variables)
    except KeyError as exc:
        raise ValueError(f"missing payload variable {exc.args[0]!r}") from exc


def payload_errors(contract: dict, expected_job: dict, live_job: dict) -> list[str]:
    profile_name = expected_job.get("payload_profile")
    profiles = contract.get("payload_profiles") or {}
    profile = profiles.get(profile_name)
    if not profile:
        return [f"unknown payload profile {profile_name!r}"]
    payload = live_job.get("payload") or {}
    delivery = live_job.get("delivery") or {}
    message = payload.get("message") or ""
    errors = []
    fields = {
        "kind": profile.get("payload_kind"),
        "model": profile.get("model"),
        "thinking": profile.get("thinking"),
    }
    for field, expected in fields.items():
        if expected is not None and payload.get(field) != expected:
            errors.append(f"payload.{field} expected {expected!r}, got {payload.get(field)!r}")
    expected_delivery = profile.get("delivery_mode")
    if expected_delivery is not None and delivery.get("mode") != expected_delivery:
        errors.append(
            f"delivery.mode expected {expected_delivery!r}, got {delivery.get('mode')!r}"
        )
    exact = profile.get("exact_message")
    if exact is not None and message.strip() != exact:
        errors.append("payload message does not match exact contract")
    variables = expected_job.get("payload_vars") or {}
    for raw in profile.get("required_substrings", []):
        required = _format_required(raw, variables)
        if required not in message:
            errors.append(f"payload missing {required!r}")
    for forbidden in profile.get("forbidden_substrings", []):
        if forbidden in message:
            errors.append(f"payload contains deprecated {forbidden!r}")
    return errors


def validate_live_jobs(contract: dict, live_jobs: list[dict],
                       at: datetime | None = None) -> list[str]:
    expected = {j["name"]: j for j in contract["jobs"]}
    actual = {j.get("name"): j for j in live_jobs}
    errors = []
    for name in sorted(set(expected) - set(actual)):
        errors.append(f"missing live job {name}")
    for name in sorted(set(actual) - set(expected)):
        errors.append(f"unexpected live job {name}")
    for name in sorted(set(expected) & set(actual)):
        exp = expected[name]
        got = actual[name]
        exp_schedule = schedule_tuple(exp, at)
        sched = got.get("schedule") or {}
        got_schedule = (sched.get("expr"), sched.get("tz"), got.get("enabled", True))
        if exp_schedule != got_schedule:
            errors.append(
                f"{name} schedule expected {exp_schedule}, got {got_schedule}"
            )
        for issue in payload_errors(contract, exp, got):
            errors.append(f"{name}: {issue}")
    return errors


def parse_crontab_lines(text: str) -> list[dict]:
    rows = []
    for index, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        rows.append({"index": index, "expr": " ".join(parts[:5]), "command": parts[5]})
    return rows


def find_crontab_row(rows: list[dict], command_contains: list[str]) -> dict | None:
    matches = [r for r in rows if all(token in r["command"] for token in command_contains)]
    return matches[0] if len(matches) == 1 else None


def validate_watchdogs(contract: dict, crontab_text: str,
                       at: datetime | None = None) -> list[str]:
    rows = parse_crontab_lines(crontab_text)
    errors = []
    for job in contract["jobs"]:
        # `watchdog` is the job's primary backstop; `extra_watchdogs` (optional list)
        # declares additional passes over the same job. 盘前深度简报 needs two: the
        # 08:30 delivery backstop, and a 09:05 miss detector — 08:30 falls inside the
        # brief's own 08:13-08:49 landing window, so it cannot tell a slow brief from
        # a dead one and a second pass after the window is the only place to judge.
        # Each entry must still match EXACTLY ONE crontab row, so their
        # command_contains have to be mutually exclusive, not just present.
        for watchdog in [job.get("watchdog")] + list(job.get("extra_watchdogs") or []):
            if not watchdog:
                continue
            tokens = watchdog.get("command_contains") or []
            row = find_crontab_row(rows, tokens)
            if not row:
                errors.append(f"{job['name']} watchdog missing or ambiguous: {tokens}")
                continue
            expected = effective_schedule(watchdog, at).get("expr")
            if row["expr"] != expected:
                errors.append(
                    f"{job['name']} watchdog expected {expected!r}, got {row['expr']!r}"
                )
    sync = contract.get("dst_sync") or {}
    if sync:
        tokens = sync.get("command_contains") or []
        row = find_crontab_row(rows, tokens)
        if not row:
            errors.append(f"DST sync cron missing or ambiguous: {tokens}")
        else:
            expected = effective_schedule(sync, at).get("expr")
            if row["expr"] != expected:
                errors.append(f"DST sync cron expected {expected!r}, got {row['expr']!r}")
    return errors
