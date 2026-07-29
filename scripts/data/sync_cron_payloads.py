#!/usr/bin/env python3
"""Reconcile tracked OpenClaw jobs with the reviewed cron contract.

The default mode is read-only and exits 1 when drift exists. ``--apply`` edits
only declared fields, one job at a time, and stops at the first failed edit.
Delivery destinations, accounts, failure alerts, and other runtime-only fields
are deliberately preserved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

WS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WS / "scripts" / "data"))

from cron_contract import (  # noqa: E402
    effective_schedule,
    load_contract,
    render_payload_message,
)

Runner = Callable[..., subprocess.CompletedProcess]


def parse_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _json_object(text: str) -> dict:
    """Decode CLI JSON even when a version warning precedes it."""
    start = text.find("{")
    if start < 0:
        raise ValueError("OpenClaw CLI returned no JSON object")
    value = json.loads(text[start:])
    if not isinstance(value, dict):
        raise ValueError("OpenClaw CLI JSON root must be an object")
    return value


def load_live_jobs(runner: Runner = subprocess.run) -> list[dict]:
    result = runner(
        ["openclaw", "cron", "list", "--json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()[-500:]
        raise RuntimeError(f"openclaw cron list failed: {detail}")
    value = _json_object(result.stdout)
    jobs = value.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("OpenClaw CLI JSON has no jobs list")
    return jobs


def _value_summary(value: object) -> object:
    if isinstance(value, str) and ("\n" in value or len(value) > 120):
        digest = hashlib.sha256(value.encode()).hexdigest()[:12]
        return {"sha256": digest, "chars": len(value)}
    return value


def _record(patch: dict, diffs: list[dict], field: str,
            current: object, desired: object) -> None:
    if current == desired:
        return
    patch[field] = desired
    diffs.append({
        "field": field,
        "from": _value_summary(current),
        "to": _value_summary(desired),
    })


def desired_changes(contract: dict, live_jobs: list[dict],
                    at: datetime) -> tuple[list[dict], list[str]]:
    """Return an exact, non-mutating edit plan and precondition errors."""
    expected_names = [job["name"] for job in contract["jobs"]]
    live_names = [job.get("name") for job in live_jobs]
    counts = Counter(live_names)
    errors = [
        f"duplicate live job name {name!r} ({count} matches)"
        for name, count in sorted(counts.items(), key=lambda item: str(item[0]))
        if count > 1
    ]
    for name in sorted(set(expected_names) - set(live_names)):
        errors.append(f"missing live job {name}")
    for name in sorted(set(live_names) - set(expected_names), key=str):
        errors.append(f"unexpected live job {name}")
    if errors:
        return [], errors

    live_by_name = {job["name"]: job for job in live_jobs}
    profiles = contract["payload_profiles"]
    changes = []
    for spec in contract["jobs"]:
        name = spec["name"]
        live = live_by_name[name]
        profile = profiles[spec["payload_profile"]]
        payload = live.get("payload") or {}
        delivery = live.get("delivery") or {}
        patch: dict = {}
        diffs: list[dict] = []

        expected_kind = profile.get("payload_kind")
        if payload.get("kind") != expected_kind:
            errors.append(
                f"{name}: payload kind {payload.get('kind')!r} cannot be "
                f"safely changed to {expected_kind!r}"
            )
            continue

        schedule = effective_schedule(spec, at)
        current_schedule = live.get("schedule") or {}
        if current_schedule.get("kind") != schedule.get("kind"):
            errors.append(
                f"{name}: schedule kind {current_schedule.get('kind')!r} cannot "
                f"be safely changed to {schedule.get('kind')!r}"
            )
            continue
        _record(
            patch, diffs, "schedule",
            {
                "expr": current_schedule.get("expr"),
                "tz": current_schedule.get("tz"),
                "exact": current_schedule.get("staggerMs") in (None, 0),
            },
            {"expr": schedule.get("expr"), "tz": schedule.get("tz"), "exact": True},
        )
        _record(
            patch, diffs, "enabled",
            live.get("enabled", True), spec.get("enabled", True),
        )
        for contract_field, live_field in (
            ("model", "model"),
            ("fallbacks", "fallbacks"),
            ("thinking", "thinking"),
            ("tools_allow", "toolsAllow"),
            ("timeout_seconds", "timeoutSeconds"),
        ):
            if contract_field in profile:
                current = payload.get(live_field, [] if live_field == "fallbacks" else None)
                _record(patch, diffs, live_field, current, profile[contract_field])

        message = render_payload_message(contract, spec)
        if message is not None:
            _record(patch, diffs, "message", payload.get("message", ""), message)

        if "delivery_mode" in profile:
            _record(
                patch, diffs, "deliveryMode",
                delivery.get("mode"), profile["delivery_mode"],
            )

        trigger = profile.get("trigger")
        if trigger:
            variables = spec.get("payload_vars") or {}
            script_path = trigger["script_path"].format(**variables)
            desired_trigger = {
                "scriptPath": script_path,
                "once": bool(trigger.get("once", False)),
            }
            current_trigger = live.get("trigger")
            current_summary = None
            if isinstance(current_trigger, dict):
                current_summary = {
                    "script": _value_summary(
                        (current_trigger.get("script") or "").strip()
                    ),
                    "once": bool(current_trigger.get("once", False)),
                }
            desired_script = (WS / script_path).read_text().strip()
            if current_summary != {
                "script": _value_summary(desired_script),
                "once": desired_trigger["once"],
            }:
                patch["trigger"] = desired_trigger
                diffs.append({
                    "field": "trigger",
                    "from": current_summary,
                    "to": {
                        "scriptPath": script_path,
                        "once": desired_trigger["once"],
                    },
                })
        elif live.get("trigger"):
            patch["clearTrigger"] = True
            diffs.append({
                "field": "trigger",
                "from": "configured",
                "to": None,
            })

        if not diffs:
            continue
        if not live.get("id"):
            errors.append(f"{name}: missing runtime id")
            continue
        state = live.get("state") or {}
        if live.get("status") == "running" or state.get("runningAtMs"):
            errors.append(f"{name}: job is currently running; retry after it finishes")
            continue
        changes.append({
            "id": live["id"],
            "name": name,
            "patch": patch,
            "diffs": diffs,
        })
    return changes, errors


def build_edit_command(change: dict) -> list[str]:
    patch = change["patch"]
    command = ["openclaw", "cron", "edit", change["id"]]
    if "schedule" in patch:
        schedule = patch["schedule"]
        if not schedule.get("tz"):
            raise ValueError(
                f"{change['name']}: clearing a cron timezone is not supported safely"
            )
        command.extend([
            "--cron", schedule["expr"], "--tz", schedule["tz"], "--exact",
        ])
    if "enabled" in patch:
        command.append("--enable" if patch["enabled"] else "--disable")
    if "model" in patch:
        command.extend(["--model", patch["model"]])
    if "fallbacks" in patch:
        if patch["fallbacks"]:
            command.extend(["--fallbacks", ",".join(patch["fallbacks"])])
        else:
            command.append("--clear-fallbacks")
    if "thinking" in patch:
        command.extend(["--thinking", patch["thinking"]])
    if "toolsAllow" in patch:
        tools = patch["toolsAllow"]
        command.extend(["--tools", ",".join(tools)]) if tools else command.append(
            "--clear-tools"
        )
    if "timeoutSeconds" in patch:
        command.extend(["--timeout-seconds", str(patch["timeoutSeconds"])])
    if "message" in patch:
        command.extend(["--message", patch["message"]])
    if "deliveryMode" in patch:
        mode = patch["deliveryMode"]
        if mode == "none":
            command.append("--no-deliver")
        elif mode == "announce":
            command.append("--announce")
        else:
            raise ValueError(
                f"{change['name']}: unsupported delivery mode {mode!r}"
            )
    if patch.get("clearTrigger"):
        command.append("--clear-trigger")
    if "trigger" in patch:
        trigger = patch["trigger"]
        command.extend(["--trigger-script", trigger["scriptPath"]])
        if trigger["once"]:
            command.append("--trigger-once")
    command.extend(["--timeout", "120000"])
    return command


def apply_changes(changes: list[dict], runner: Runner = subprocess.run,
                  live_loader: Callable[[], list[dict]] | None = None) -> list[str]:
    """Apply sequentially and stop immediately after the first failed edit."""
    for change in changes:
        if live_loader is not None:
            try:
                matches = [
                    job for job in live_loader()
                    if job.get("id") == change["id"] and job.get("name") == change["name"]
                ]
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                return [f"{change['name']}: cannot recheck runtime state: {exc}"]
            if len(matches) != 1:
                return [
                    f"{change['name']}: runtime identity changed before apply "
                    f"({len(matches)} matches)"
                ]
            state = matches[0].get("state") or {}
            if matches[0].get("status") == "running" or state.get("runningAtMs"):
                return [
                    f"{change['name']}: job started running before apply; stopped"
                ]
        try:
            command = build_edit_command(change)
        except ValueError as exc:
            return [str(exc)]
        result = runner(
            command,
            cwd=WS,
            capture_output=True,
            text=True,
            timeout=130,
        )
        if result.returncode != 0:
            detail = (result.stdout + result.stderr).strip()[-500:]
            return [f"{change['name']}: cron edit failed: {detail}"]
    return []


def public_changes(changes: list[dict]) -> list[dict]:
    """Return a plan safe for logs: no full prompts or delivery metadata."""
    return [
        {"id": change["id"], "name": change["name"], "diffs": change["diffs"]}
        for change in changes
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply tracked fields; default is a read-only drift check",
    )
    parser.add_argument("--at", help="ISO timestamp override (tests/audits)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    at = parse_at(args.at)
    errors: list[str] = []
    changes: list[dict] = []
    applied = False
    try:
        contract = load_contract()
        changes, errors = desired_changes(contract, load_live_jobs(), at)
        if args.apply and not errors and changes:
            errors = apply_changes(changes, live_loader=load_live_jobs)
            if not errors:
                remaining, verify_errors = desired_changes(
                    contract, load_live_jobs(), at
                )
                errors.extend(verify_errors)
                if remaining:
                    errors.append(
                        f"post-apply verification found {len(remaining)} remaining change(s)"
                    )
                applied = not errors
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        errors.append(str(exc))

    result = {
        "status": "error" if errors else (
            "applied" if applied else ("drift" if changes else "ok")
        ),
        "checked_at": at.isoformat(),
        "apply": args.apply,
        "change_count": len(changes),
        "changes": public_changes(changes),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"Cron payload sync: {result['status']} · "
            f"changes={len(changes)} errors={len(errors)}"
        )
        for change in public_changes(changes):
            fields = ", ".join(diff["field"] for diff in change["diffs"])
            print(f"  {change['name']}: {fields}")
        for error in errors:
            print(f"  ERROR: {error}", file=sys.stderr)
    if errors:
        return 2
    if changes and not args.apply:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
