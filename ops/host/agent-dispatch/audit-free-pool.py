#!/usr/bin/env python3
"""Read-only catalog/pool audit. Never calls inference, edits the pool or sends messages.

The supervisor calls --due; --status reads the saved report without network access.
Missing price metadata is unknown, never zero. Catalog presence is not tool usability.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ZEN = "https://opencode.ai/zen/v1/models"
PRICES = "https://models.dev/api.json"
INTERVAL = 6 * 3600
RETRY = 3600
STALE = 10 * 3600


def load_checker():
    spec = importlib.util.spec_from_file_location(
        "free_pool_checker", Path(__file__).with_name("check-free-pool.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cost_state(cost):
    """Require explicit numeric input/output prices; check every supplied cost leaf."""
    if not isinstance(cost, dict) or not {"input", "output"} <= cost.keys():
        return "unknown"
    leaves = []

    def visit(value):
        if isinstance(value, dict) and value:
            for item in value.values():
                visit(item)
        else:
            leaves.append(value)

    visit(cost)
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in leaves):
        return "unknown"
    return "nonzero" if any(v > 0 for v in leaves) else "zero"


def parse_catalog(text):
    decoder = json.JSONDecoder()
    rows = {}
    while text.strip():
        name, text = text.lstrip().split("\n", 1)
        value, end = decoder.raw_decode(text)
        if not name.startswith("opencode/") or name in rows or not isinstance(value, dict):
            raise ValueError("invalid/duplicate catalog entry")
        rows[name] = value
        text = text[end:]
    if not rows:
        raise ValueError("empty catalog")
    return rows


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "clawock-free-pool-audit/1.0",
                                                  "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def collect():
    sources, errors = {}, {}
    readers = {
        "catalog": lambda: parse_catalog(subprocess.run(
            ["opencode", "models", "opencode", "--refresh", "--verbose"], check=True,
            capture_output=True, text=True, timeout=20).stdout),
        "zen": lambda: fetch_json(ZEN),
        "prices": lambda: fetch_json(PRICES)["opencode"]["models"],
    }
    for name, read in readers.items():
        try:
            sources[name] = read()
        except Exception as exc:  # A source failure must still leave a fresh failure report.
            errors[name] = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
    return sources, errors


def assess(pool, sources, retired, previous=()):
    catalog = sources.get("catalog")
    prices = sources.get("prices")
    zen = sources.get("zen")
    issues = []
    try:
        rows = zen["data"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("empty/invalid Zen list")
        zen = {row["id"]: row for row in rows}
        if len(zen) != len(rows) or any(not isinstance(k, str) for k in zen):
            raise ValueError("duplicate Zen models")
    except (TypeError, KeyError, ValueError):
        zen = None
        issues.append("zen: missing or invalid catalog")
    if not isinstance(prices, dict) or not prices:
        prices = None
        issues.append("prices: missing or invalid metadata")
    models = []
    for name in sorted(set(catalog or {}) | {"opencode/" + n for n in (zen or {}) if n.endswith("-free")} | set(pool)):
        short = name.removeprefix("opencode/")
        c = (catalog or {}).get(name, {})
        z = (zen or {}).get(short, {})
        p = (prices or {}).get(short, {})
        c = c if isinstance(c, dict) else {}
        z = z if isinstance(z, dict) else {}
        p = p if isinstance(p, dict) else {}
        row = {
            "model": name, "in_pool": name in pool, "retired": name in retired,
            "in_catalog": name in catalog if catalog is not None else None,
            "in_zen": short in zen if zen is not None else None,
            "zen_cost": cost_state(z.get("cost")),
            "catalog_cost": cost_state(c.get("cost")),
            "metadata_cost": cost_state(p.get("cost")),
            "tool_probe": "not_run",
        }
        row["free_verified"] = (row["in_catalog"] is True and row["in_zen"] is True
                                and row["zen_cost"] == "zero"
                                and "nonzero" not in (row["catalog_cost"], row["metadata_cost"]))
        models.append(row)
        if row["in_pool"]:
            if row["in_catalog"] is False or row["in_zen"] is False:
                issues.append(f"{name}: missing from catalog")
            if "nonzero" in (row["zen_cost"], row["catalog_cost"], row["metadata_cost"]):
                issues.append(f"{name}: nonzero cost")
            if not row["free_verified"]:
                issues.append(f"{name}: free status not verified")
    names = sorted(catalog) if catalog is not None else None
    return {
        "models": models, "issues": issues, "catalog_names": names,
        "added": sorted(set(names) - set(previous)) if names is not None else [],
        "removed": sorted(set(previous) - set(names)) if names is not None else [],
    }


def read_report(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def identity(paths):
    values = []
    for path in paths:
        try:
            values.append(hashlib.sha256(path.read_bytes()).hexdigest())
        except OSError:
            values.append(None)
    return values


def save_report(path, report):
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def status(report, now):
    checked = report.get("checked_at")
    if not isinstance(checked, (int, float)) or not 0 <= now - checked <= STALE:
        return "stale"
    return report.get("status", "unknown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=Path(__file__).with_name("opencode-fallback-models"))
    parser.add_argument("--repo-pool", type=Path, default=Path(
        "/root/.openclaw/workspace/ops/host/agent-dispatch/opencode-fallback-models"))
    parser.add_argument("--report", type=Path, default=Path("/root/logs/clawock-patrol/free-pool-audit.json"))
    parser.add_argument("--due", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    now = time.time()
    old = read_report(args.report)
    if args.status:
        print(json.dumps({**old, "status": status(old, now)}, ensure_ascii=False))
        return 0 if status(old, now) == "ok" else 2
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        old = read_report(args.report)
        hashes = identity((args.pool, args.repo_pool))
        interval = RETRY if old.get("source_errors") else INTERVAL
        checked = old.get("checked_at")
        age = now - checked if type(checked) in (int, float) else INTERVAL
        if args.due and 0 <= age < interval and old.get("pool_hashes") == hashes:
            return 0
        checker = load_checker()
        errors = []
        try:
            pool = checker.check(args.pool)
        except (OSError, ValueError) as exc:
            pool = []
            errors.append(f"pool guard: {exc}")
        if None in hashes or hashes[0] != hashes[1]:
            errors.append("installed and repository pool differ or are missing")
        sources, source_errors = collect()
        previous = old.get("last_catalog_names", [])
        report = assess(pool, sources, checker.RETIRED, previous)
        report["issues"] = errors + report["issues"]
        report.update({"checked_at": now, "source_errors": source_errors, "pool_hashes": hashes,
                       "baseline": not bool(previous),
                       "last_catalog_names": report["catalog_names"] if report["catalog_names"] is not None else previous,
                       "sources": {"zen": ZEN, "prices": PRICES, "catalog": "opencode models opencode --refresh --verbose"}})
        report["status"] = "attention" if report["issues"] or source_errors else "ok"
        save_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
