#!/usr/bin/env python3
"""Bounded daytime tool evidence. Failures back off; probes never retire/admit a model."""
import argparse
from datetime import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from zoneinfo import ZoneInfo

SPEC = importlib.util.spec_from_file_location("free_selector", Path(__file__).with_name("select-free-models.py"))
selector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selector)
audit = selector.audit


def next_model(available, state, now):
    hour = datetime.fromtimestamp(now, ZoneInfo("Asia/Shanghai")).hour
    if 1 <= hour < 8 or now - state.get("last_run", 0) < 6 * 3600:
        return None
    due = [m for m in available if state.get("models", {}).get(m, {}).get("next_at", 0) <= now]
    return min(due, key=lambda m: (state.get("models", {}).get(m, {}).get("checked_at", 0), m)) if due else None


def verdict(events, rc):
    if rc == 124:
        return "timeout_unknown"
    errors = [r for r in events if r.get("type") == "error"]
    if errors:
        text = json.dumps(errors).lower()
        return "rate_limited" if any(t in text for t in ("429", "rate limit", "freeusagelimit")) else "error"
    tools = [r.get("part", {}) for r in events if r.get("type") == "tool_use"]
    bash = [r for r in tools if r.get("tool") == "bash" and r.get("state", {}).get("status") == "completed"
            and r["state"].get("input", {}).get("command", "").strip() == "echo TOOL-PROBE-OK"
            and r["state"].get("output", "").strip() == "TOOL-PROBE-OK"]
    texts = [r.get("part", {}).get("text", "").strip() for r in events if r.get("type") == "text"]
    return "verified_tool" if rc == 0 and len(bash) == 1 and "PROBE-OK" in texts else "unverified"


def probe(model, out):
    out.mkdir(parents=True, exist_ok=True)
    command = ["bash", str(Path(__file__).with_name("probe-free-models.sh")),
               "--tool", "--timeout", "45", "--batch", "1", model]
    proc = subprocess.Popen(command, cwd=out, env={**os.environ, "OUT": str(out)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        return "timeout_unknown"
    slug = model.replace("/", "_")
    meta = dict(line.split("=", 1) for line in (out / (slug + ".meta")).read_text().splitlines())
    events = [json.loads(line) for line in (out / (slug + ".jsonl")).read_text().splitlines() if line.strip()]
    return verdict(events, int(meta["rc"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--pool", type=Path, default=Path(__file__).with_name("opencode-fallback-models"))
    parser.add_argument("--locks", type=Path, required=True)
    args = parser.parse_args()
    path = args.report.with_name("free-model-probes.json")
    with path.with_suffix(".lock").open("a") as lock, (args.locks / "slot-opencode-1.lock").open("a") as slot:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        now = time.time()
        settings = selector.policy(Path(__file__).with_name("free-pool-policy.json"))
        if settings["mode"] == "paused":
            return 0
        try:
            available = selector.eligible(audit.read_report(args.report), args.pool, now)
            if settings["mode"] == "seed-only":
                available = [m for m in available if m in selector.CHECKER.check(args.pool)]
            state = audit.read_report(path)
            model = next_model(available, state, now)
            if model is None:
                return 0
            out = args.report.parent / "free-model-probes" / f"{int(now)}-{model.split('/')[-1]}"
            try:
                result = probe(model, out)
            except (OSError, ValueError, KeyError):
                result = "probe_error"
            rows = state.setdefault("models", {})
            failures = 0 if result == "verified_tool" else rows.get(model, {}).get("failures", 0) + 1
            delay = 7 * 86400 if not failures else min(7, 2 ** min(failures - 1, 3)) * 86400
            rows[model] = {"checked_at": now, "verdict": result, "failures": failures,
                           "next_at": now + delay, "evidence": str(out)}
            state["last_run"] = now
            audit.save_report(path, state)
            print(json.dumps({"model": model, **rows[model]}, ensure_ascii=False))
            return 0
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"free candidate probe skipped: {exc}")
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
