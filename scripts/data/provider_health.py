#!/usr/bin/env python3
"""Probe provider readiness and apply an ordered healthy cron rotation."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
CONFIG_PATH = WS / "config" / "provider-health.json"
STATE_PATH = WS / "memory" / ".tmp" / "provider-health.json"
OPENCLAW = "/root/.local/share/pnpm/openclaw"

sys.path.insert(0, str(WS / "scripts" / "data"))
sys.path.insert(0, str(WS / "scripts" / "harness"))

from cron_contract import load_contract  # noqa: E402
from _watchdog_common import KCN_TELEGRAM, load_jobs, send_telegram  # noqa: E402


def load_config(path=CONFIG_PATH):
    data = json.loads(Path(path).read_text())
    if data.get("schema_version") != 1:
        raise ValueError("provider health schema_version must be 1")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("provider health candidates must be non-empty")
    providers = [candidate.get("provider") for candidate in candidates]
    models = [candidate.get("model") for candidate in candidates]
    if any(not value for value in providers + models):
        raise ValueError("provider candidates need provider + model")
    if len(providers) != len(set(providers)) or len(models) != len(set(models)):
        raise ValueError("provider candidates must be unique")
    probe = data.get("probe") or {}
    attempts = probe.get("attempts")
    if not isinstance(attempts, int) or not 1 <= attempts <= 4:
        raise ValueError("probe attempts must be between 1 and 4")
    for spec in data.get("deterministic_product_fallbacks") or []:
        path_text, sep, symbol = spec.partition(":")
        path = WS / path_text
        if not sep or not symbol or not path.is_file() or f"def {symbol}" not in path.read_text():
            raise ValueError(f"deterministic product fallback is unavailable: {spec}")
    return data


def _json_stdout(result):
    start = result.stdout.find("{")
    if start < 0:
        return None
    try:
        return json.loads(result.stdout[start:])
    except json.JSONDecodeError:
        return None


def model_status(*, provider=None, probe=None):
    cmd = [OPENCLAW, "models", "status", "--json"]
    timeout = 45
    if provider:
        probe = probe or {}
        cmd += [
            "--probe",
            "--probe-provider", provider,
            "--probe-max-tokens", str(probe["max_tokens"]),
            "--probe-timeout", str(probe["timeout_ms"]),
            "--probe-concurrency", "1",
        ]
        timeout = max(45, int(probe["timeout_ms"] / 1000) + 30)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return _json_stdout(result)


def configured_providers(status):
    auth = (status or {}).get("auth") or {}
    return {
        row["provider"]
        for row in auth.get("providers") or []
        if row.get("provider") and row.get("effective")
    }


def probe_one(provider, probe, *, sleep=time.sleep):
    attempts = []
    for index in range(probe["attempts"]):
        started = time.monotonic()
        data = model_status(provider=provider, probe=probe)
        results = (((data or {}).get("auth") or {}).get("probes") or {}).get("results") or []
        match = next((row for row in results if row.get("provider") == provider), None)
        ok = bool(match and match.get("status") == "ok")
        attempts.append({
            "status": "ok" if ok else "failed",
            "latency_ms": match.get("latencyMs") if match else round(
                (time.monotonic() - started) * 1000
            ),
        })
        if ok:
            return True, attempts
        if index + 1 < probe["attempts"]:
            sleep(probe["initial_backoff_seconds"] * (2 ** index))
    return False, attempts


def evaluate(config, *, sleep=time.sleep):
    configured = configured_providers(model_status())
    rows = []
    for candidate in config["candidates"]:
        provider = candidate["provider"]
        if provider not in configured:
            rows.append({
                **candidate,
                "configured": False,
                "healthy": False,
                "status": "unconfigured",
                "attempts": [],
            })
            continue
        healthy, attempts = probe_one(provider, config["probe"], sleep=sleep)
        rows.append({
            **candidate,
            "configured": True,
            "healthy": healthy,
            "status": "ok" if healthy else "probe_failed",
            "attempts": attempts,
        })
    return rows


def rotation(results):
    """First item is primary; remaining unique healthy items are fallbacks."""
    return [row["model"] for row in results if row.get("healthy")]


def market_job_names(contract):
    profiles = contract.get("payload_profiles") or {}
    return {
        job["name"]
        for job in contract["jobs"]
        if (profiles.get(job.get("payload_profile")) or {}).get("model_candidates")
    }


def desired_changes(live_jobs, models, names):
    if not models:
        return []
    primary, fallbacks = models[0], models[1:]
    changes = []
    for job in live_jobs:
        if job.get("name") not in names:
            continue
        payload = job.get("payload") or {}
        current_fallbacks = payload.get("fallbacks") or []
        if payload.get("model") == primary and current_fallbacks == fallbacks:
            continue
        changes.append({
            "id": job.get("id"),
            "name": job.get("name"),
            "from": {
                "model": payload.get("model"),
                "fallbacks": current_fallbacks,
            },
            "to": {"model": primary, "fallbacks": fallbacks},
        })
    return changes


def apply_changes(changes):
    errors = []
    for change in changes:
        if not change.get("id"):
            errors.append(f"{change['name']}: missing live job id")
            continue
        cmd = [
            OPENCLAW, "cron", "edit", change["id"],
            "--model", change["to"]["model"],
        ]
        fallbacks = change["to"]["fallbacks"]
        cmd += (
            ["--fallbacks", ",".join(fallbacks)]
            if fallbacks else ["--clear-fallbacks"]
        )
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if result.returncode != 0:
            errors.append(f"{change['name']}: cron edit failed")
    return errors


def _atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def _prior_alert_state():
    try:
        prior = json.loads(STATE_PATH.read_text())
        return prior.get("unhealthy_fingerprint"), prior.get("alert_sent")
    except Exception:
        return None, None


def maybe_alert(state, prior_fingerprint, prior_alert_sent, no_alert):
    fingerprint = state["unhealthy_fingerprint"]
    retry_failed_alert = fingerprint == prior_fingerprint and prior_alert_sent is False
    if (
        no_alert
        or not fingerprint
        or (fingerprint == prior_fingerprint and not retry_failed_alert)
    ):
        return None
    unhealthy = [
        f"{row['provider']}={row['status']}"
        for row in state["providers"] if not row["healthy"]
    ]
    message = (
        "🟠 Provider readiness changed\n"
        + "\n".join(f"• {item}" for item in unhealthy)
        + f"\nActive rotation: {' → '.join(state['rotation']) or 'NONE'}"
    )
    try:
        ok, _ = send_telegram(KCN_TELEGRAM, message, False)
        return bool(ok)
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-alert", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_config()
    results = evaluate(config)
    models = rotation(results)
    prior_fingerprint, prior_alert_sent = _prior_alert_state()
    unhealthy_fingerprint = ",".join(
        f"{row['provider']}:{row['status']}"
        for row in results if not row["healthy"]
    )
    errors = []
    changes = []
    applied = False
    if not models:
        errors.append("no healthy provider; existing cron rotation left unchanged")
    else:
        contract = load_contract()
        changes = desired_changes(
            load_jobs(), models, market_job_names(contract)
        )
        if args.apply:
            errors.extend(apply_changes(changes))
            applied = bool(changes) and not errors
    state = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "error" if errors else (
            "degraded" if unhealthy_fingerprint else "healthy"
        ),
        "providers": results,
        "rotation": models,
        "changes": changes,
        "applied": applied,
        "errors": errors,
        "unhealthy_fingerprint": unhealthy_fingerprint,
    }
    # Persist readiness before notification so alert failure cannot erase the
    # rotation or trigger the same notification on every scheduler retry.
    _atomic_write(STATE_PATH, state)
    state["alert_sent"] = maybe_alert(
        state, prior_fingerprint, prior_alert_sent, args.no_alert
    )
    _atomic_write(STATE_PATH, state)
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        print(
            f"provider health: {state['status']} · "
            f"rotation={' → '.join(models) or 'NONE'} · changes={len(changes)}"
        )
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
