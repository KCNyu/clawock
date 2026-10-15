#!/usr/bin/env python3
"""Choose an effective free pool from fresh evidence; the immutable file is a seed order.

No network, inference, seed writes or git operations. Receipts explain every selection.
"""
import argparse
import fcntl
import importlib.util
import json
from pathlib import Path
import sys
import time

SPEC = importlib.util.spec_from_file_location("free_pool_audit", Path(__file__).with_name("audit-free-pool.py"))
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
CHECKER = audit.load_checker()


def policy(path):
    value = json.loads(path.read_text())
    if value.get("mode") not in ("automatic", "seed-only", "paused"):
        raise ValueError("unknown selection mode")
    maximum, position = value.get("max_models"), value.get("exploration_position")
    if type(maximum) is not int or not 1 <= maximum <= 20:
        raise ValueError("max_models must be 1..20")
    if type(position) is not int or not 0 <= position < maximum:
        raise ValueError("invalid exploration_position")
    return value


def eligible(report, seed_path, now):
    if report.get("policy_version") != audit.POLICY_VERSION:
        raise ValueError("audit uses an old admission policy; refresh it")
    if audit.status(report, now) == "stale":
        raise ValueError("free-price evidence missing/stale; no paid or static fallback")
    if not report.get("selection_ready") or report.get("source_errors"):
        raise ValueError("catalog/price sources or pool integrity unavailable")
    hashes = report.get("pool_hashes", [])
    if len(hashes) != 2 or None in hashes or hashes[0] != hashes[1] or audit.identity([seed_path])[0] != hashes[0]:
        raise ValueError("seed changed or differs from repository; refresh audit")
    models = []
    for row in report["models"]:
        name = row["model"]
        if (CHECKER.allowed_name(name) and name not in CHECKER.RETIRED
                and row.get("in_catalog") is True and row.get("in_zen") is True
                and row.get("catalog_cost") == "zero" and row.get("metadata_cost") != "nonzero"):
            models.append(name)
    return CHECKER.validate(models)


def choose(seed, available, settings, cursor=0):
    if settings["mode"] == "paused":
        raise ValueError("automatic free-model selection paused by policy")
    ordered = [m for m in seed if m in available]
    reasons = {m: f"seed priority {seed.index(m) + 1}; fresh catalog zero and Zen membership" for m in ordered}
    newcomers = sorted(set(available) - set(seed)) if settings["mode"] == "automatic" else []
    if newcomers:
        # One fair exploration slot: an unknown model need not wait forever behind all seeds.
        newcomer = newcomers[cursor % len(newcomers)]
        ordered.insert(min(settings["exploration_position"], len(ordered)), newcomer)
        reasons[newcomer] = f"automatic discovery; rotating exploration slot {cursor % len(newcomers) + 1}/{len(newcomers)}"
    ordered = ordered[:settings["max_models"]]
    CHECKER.validate(ordered)
    return ordered, {m: reasons[m] for m in ordered}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=Path(__file__).with_name("opencode-fallback-models"))
    parser.add_argument("--policy", type=Path, default=Path(__file__).with_name("free-pool-policy.json"))
    parser.add_argument("--report", type=Path, default=Path("/root/logs/clawock-patrol/free-pool-audit.json"))
    parser.add_argument("--allow")
    parser.add_argument("--filter", help="comma-separated task pool; output only still-eligible names")
    parser.add_argument("--models", help="explicit manual model list; same price/retirement gates")
    parser.add_argument("--prefer", help="explicit primary model; same price/retirement gates")
    args = parser.parse_args()
    try:
        settings = policy(args.policy)
        if settings["mode"] == "paused":
            raise ValueError("free-model selection paused")
        seed = CHECKER.check(args.pool)
        report = audit.read_report(args.report)
        available = eligible(report, args.pool, time.time())
        if settings["mode"] == "seed-only":
            available = [m for m in available if m in seed]
        if args.allow:
            if args.allow not in available:
                raise ValueError(f"model not currently eligible: {args.allow}")
            return 0
        if args.filter is not None:
            current = [m for m in args.filter.split(",") if m in available]
            CHECKER.validate(current)
            print("\n".join(current))
            return 0
        # Selection state is local runtime data, not a second source of pricing truth.
        state_path = args.report.with_name("free-pool-selection.json")
        with state_path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous = audit.read_report(state_path)
            cursor = previous.get("next_cursor", 0)
            if type(cursor) is not int or cursor < 0:
                cursor = 0
            ordered, reasons = choose(seed, available, settings, cursor)
            if args.models:
                ordered = CHECKER.validate([m for m in args.models.split(",") if m])
                reasons = {m: "explicit model selection; same fresh free-price gates" for m in ordered}
            if args.prefer:
                ordered = [args.prefer] + [m for m in ordered if m != args.prefer]
                ordered = ordered[:settings["max_models"]]
                reasons[args.prefer] = "explicit primary; same fresh free-price gates"
            if len(ordered) > settings["max_models"] or any(m not in available for m in ordered):
                raise ValueError("explicit selection exceeds capacity or includes an ineligible model")
            CHECKER.validate(ordered)
            receipt = {"selected_at": time.time(), "evidence_at": report["checked_at"],
                       "mode": settings["mode"], "models": ordered, "reasons": reasons,
                       "next_cursor": cursor + 1, "seed_sha256": report["pool_hashes"][0]}
            audit.save_report(state_path, receipt)
            print(json.dumps(receipt, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FREE MODEL SELECTION REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
