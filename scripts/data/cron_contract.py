#!/usr/bin/env python3
"""Shared cron contract helpers: seasonal schedules, payloads, and watchdogs."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clawock.workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
DEFAULT_CONTRACT = WS / "config" / "cron-schedules.json"
HKT = ZoneInfo("Asia/Hong_Kong")
ET = ZoneInfo("America/New_York")
TEMPLATE_TOKEN = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")


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
    for profile_name, profile in profiles.items():
        candidates = profile.get("model_candidates")
        if candidates and (
            not isinstance(candidates, list)
            or len(candidates) != len(set(candidates))
            or any(not model for model in candidates)
        ):
            raise ValueError(f"{profile_name}: model_candidates must be unique models")
        fallbacks = profile.get("fallbacks")
        if fallbacks is not None and (
            not isinstance(fallbacks, list)
            or len(fallbacks) != len(set(fallbacks))
            or any(not isinstance(model, str) or not model for model in fallbacks)
        ):
            raise ValueError(f"{profile_name}: fallbacks must be unique models")
        if fallbacks is not None:
            rotation = [profile.get("model"), *fallbacks]
            if any(not model for model in rotation):
                raise ValueError(
                    f"{profile_name}: model is required when fallbacks are declared"
                )
            if len(rotation) != len(set(rotation)):
                raise ValueError(f"{profile_name}: model rotation contains duplicates")
            if candidates and rotation != candidates[:len(rotation)]:
                raise ValueError(
                    f"{profile_name}: configured rotation must be a fixed prefix "
                    f"of model_candidates"
                )
        tools_allow = profile.get("tools_allow")
        if tools_allow is not None and (
            not isinstance(tools_allow, list)
            or not tools_allow
            or len(tools_allow) != len(set(tools_allow))
            or any(not isinstance(tool, str) or not tool for tool in tools_allow)
        ):
            raise ValueError(
                f"{profile_name}: tools_allow must be non-empty unique tool names"
            )
        template = profile.get("message_template")
        if template is not None and (
            not isinstance(template, str)
            or not template.startswith("config/cron-payloads/")
            or not template.endswith(".md")
        ):
            raise ValueError(
                f"{profile_name}: message_template must be a config/cron-payloads/*.md path"
            )
    for job in jobs:
        if bool(job.get("schedule")) == bool(job.get("seasonal_schedules")):
            raise ValueError(f"{job['name']}: define exactly one schedule source")
        seasonal = job.get("seasonal_schedules")
        if seasonal and set(seasonal) != {"daylight", "standard"}:
            raise ValueError(f"{job['name']}: seasonal schedules require daylight+standard")
        if job.get("payload_profile") not in profiles:
            raise ValueError(f"{job['name']}: unknown payload profile")
        render_payload_message(data, job)
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


def render_payload_message(contract: dict, expected_job: dict) -> str | None:
    """Render the exact reviewed message for one tracked agent job."""
    profile_name = expected_job.get("payload_profile")
    profile = (contract.get("payload_profiles") or {}).get(profile_name) or {}
    exact = profile.get("exact_message")
    template_path = profile.get("message_template")
    if exact is not None and template_path is not None:
        raise ValueError(f"{profile_name}: use exact_message or message_template, not both")
    if exact is not None:
        return str(exact).strip()
    if template_path is None:
        return None

    path = (WS / template_path).resolve()
    try:
        path.relative_to(WS.resolve())
    except ValueError as exc:
        raise ValueError(f"{profile_name}: message template escapes workspace") from exc
    try:
        template = path.read_text().rstrip("\n")
    except OSError as exc:
        raise ValueError(f"{profile_name}: cannot read message template: {exc}") from exc

    variables = expected_job.get("payload_vars") or {}
    tokens = set(TEMPLATE_TOKEN.findall(template))
    missing = sorted(tokens - set(variables))
    unused = sorted(set(variables) - tokens)
    if missing:
        raise ValueError(
            f"{expected_job['name']}: missing template variables {missing!r}"
        )
    if unused:
        raise ValueError(
            f"{expected_job['name']}: unused template variables {unused!r}"
        )
    return TEMPLATE_TOKEN.sub(lambda match: str(variables[match.group(1)]), template)


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
    candidates = profile.get("model_candidates")
    if candidates:
        fallbacks = payload.get("fallbacks") or []
        if not isinstance(fallbacks, list):
            errors.append("payload.fallbacks must be a list")
            fallbacks = []
        rotation = [payload.get("model"), *fallbacks]
        if any(not model for model in rotation):
            errors.append("payload model rotation contains an empty model")
        if len(rotation) != len(set(rotation)):
            errors.append("payload model rotation contains duplicates")
        unknown = [model for model in rotation if model not in candidates]
        if unknown:
            errors.append(f"payload model rotation contains unknown models: {unknown}")
        fixed_prefix = candidates[:len(rotation)]
        if rotation != fixed_prefix:
            errors.append(
                f"payload model rotation must be a fixed prefix of {candidates!r}"
            )
    expected_fallbacks = profile.get("fallbacks")
    if expected_fallbacks is not None and payload.get("fallbacks", []) != expected_fallbacks:
        errors.append(
            f"payload.fallbacks expected {expected_fallbacks!r}, "
            f"got {payload.get('fallbacks', [])!r}"
        )
    for field, expected in fields.items():
        if expected is not None and payload.get(field) != expected:
            errors.append(f"payload.{field} expected {expected!r}, got {payload.get(field)!r}")
    # An unbounded agent turn is only stopped by something unrelated restarting the
    # gateway. 盘前深度简报 ran 71, 81 and 86 minutes on 2026-07-15/16/17 that way,
    # each time still holding the agent minutes before the 09:30 report's slot
    # (issue #121). Only profiles that declare a bound are checked; a job with no
    # declared timeout keeps the old behaviour.
    expected_timeout = profile.get("timeout_seconds")
    if expected_timeout is not None and payload.get("timeoutSeconds") != expected_timeout:
        errors.append(
            f"payload.timeoutSeconds expected {expected_timeout!r}, "
            f"got {payload.get('timeoutSeconds')!r}"
        )
    expected_tools = profile.get("tools_allow")
    if "tools_allow" in profile and expected_tools is None:
        if payload.get("toolsAllow") is not None:
            errors.append(
                "payload.toolsAllow expected unrestricted tools, "
                f"got {payload.get('toolsAllow')!r}"
            )
    elif expected_tools is not None:
        live_tools = payload.get("toolsAllow")
        if not isinstance(live_tools, list):
            errors.append(
                f"payload.toolsAllow expected {expected_tools!r}, got {live_tools!r}"
            )
        elif len(live_tools) != len(set(live_tools)):
            errors.append("payload.toolsAllow contains duplicates")
        elif set(live_tools) != set(expected_tools):
            errors.append(
                f"payload.toolsAllow expected {expected_tools!r}, got {live_tools!r}"
            )
    expected_delivery = profile.get("delivery_mode")
    if expected_delivery is not None and delivery.get("mode") != expected_delivery:
        errors.append(
            f"delivery.mode expected {expected_delivery!r}, got {delivery.get('mode')!r}"
        )
    rendered = render_payload_message(contract, expected_job)
    if rendered is not None and message.strip() != rendered:
        errors.append("payload message does not match rendered contract")
    variables = expected_job.get("payload_vars") or {}
    for raw in profile.get("required_substrings", []):
        required = _format_required(raw, variables)
        if required not in message:
            errors.append(f"payload missing {required!r}")
    for forbidden in profile.get("forbidden_substrings", []):
        if forbidden in message:
            errors.append(f"payload contains deprecated {forbidden!r}")
    expected_trigger = profile.get("trigger")
    trigger = live_job.get("trigger")
    if expected_trigger:
        variables = expected_job.get("payload_vars") or {}
        script_path = _format_required(expected_trigger["script_path"], variables)
        expected_script = (WS / script_path).read_text().strip()
        if not isinstance(trigger, dict):
            errors.append("condition trigger missing")
        else:
            if (trigger.get("script") or "").strip() != expected_script:
                errors.append(f"condition trigger does not match {script_path}")
            if bool(trigger.get("once", False)) != bool(expected_trigger.get("once", False)):
                errors.append(
                    f"condition trigger once expected {expected_trigger.get('once', False)!r}"
                )
    elif trigger:
        errors.append("unexpected condition trigger")
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
