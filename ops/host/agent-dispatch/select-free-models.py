#!/usr/bin/env python3
"""Choose an effective free pool from fresh evidence; the immutable file is a seed order.

No network, inference, seed writes or git operations. Receipts explain every selection.
"""
import argparse
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

SPEC = importlib.util.spec_from_file_location("free_pool_audit", Path(__file__).with_name("audit-free-pool.py"))
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
CHECKER = audit.load_checker()

# Recent outcomes come from the runner's own run.log lines, which are already bounded per task.
# Seven days covers a weekly quota cycle; three attempts is the minimum sample before a model
# can move ahead of the reviewed seed order. The immutable seed stays the tie-breaker.
HISTORY_WINDOW = 7 * 86400
HISTORY_MIN_ATTEMPTS = 3
_ATTEMPT_START = re.compile(
    r"^---- (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) attempt (\d+)(?:/\d+)? \([^)]*\) .*? model=(\S+)")
_ATTEMPT_END = re.compile(
    r"^---- (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) attempt (\d+) \([^)]*\) rc=-?\d+ kind=(\w+)")


def recent_history(root, now, window=HISTORY_WINDOW):
    """{model: {"ok": n, "rate_limited": n}} from runs that ended inside the window.

    Only successful calls and free-window refusals count. A timeout after real generation is
    not a quota refusal; folding it in would rank a slow model below one that never answered.
    Unreadable or missing logs mean no evidence, never a failed selection.
    """
    stats = {}
    base = Path(root)
    cutoff = now - window
    if not base.is_dir():
        return stats
    for log in base.glob("*/run.log"):
        try:
            if log.stat().st_mtime < cutoff:
                continue
            lines = log.open(errors="replace")
        except OSError:
            continue
        current = None
        with lines:
            for line in lines:
                if not line.startswith("---- "):
                    continue
                started = _ATTEMPT_START.match(line)
                if started:
                    try:
                        at = time.mktime(time.strptime(started.group(1), "%Y-%m-%d %H:%M:%S"))
                    except ValueError:
                        current = None
                        continue
                    current = (int(started.group(2)), at, started.group(3))
                    continue
                ended = _ATTEMPT_END.match(line)
                if ended and current and int(ended.group(2)) == current[0]:
                    at, model, kind = current[1], current[2], ended.group(3)
                    if cutoff <= at <= now and kind in ("ok", "rate_limited"):
                        row = stats.setdefault(model, {"ok": 0, "rate_limited": 0})
                        row[kind] += 1
                    current = None
    return stats


def rank_seeds(seed, history=None):
    """Move recently answering seeds up and recently refused ones down, keeping seed order ties.

    Positive evidence first, no/neutral evidence next, negative evidence last. A model needs
    HISTORY_MIN_ATTEMPTS decisive outcomes before it can move, so one lucky call does not
    overturn the reviewed order and one bad call does not bury a working model.
    """
    if not history:
        return list(seed)

    def key(item):
        index, model = item
        row = history.get(model) or {}
        ok, limited = row.get("ok", 0), row.get("rate_limited", 0)
        n = ok + limited
        if n < HISTORY_MIN_ATTEMPTS:
            return (1, 0.0, index)
        score = (ok - limited) / n
        if score > 0:
            return (0, -score, index)
        if score == 0:
            return (1, 0.0, index)
        return (2, -score, index)

    return [model for _, model in sorted(enumerate(seed), key=key)]


def selection_reason(model, seed, history):
    index = seed.index(model) + 1
    row = (history or {}).get(model) or {}
    ok, limited = row.get("ok", 0), row.get("rate_limited", 0)
    if ok + limited < HISTORY_MIN_ATTEMPTS:
        return f"seed priority {index}; no recent pool evidence"
    return (f"seed priority {index}; recent {HISTORY_WINDOW // 86400}d: "
            f"{ok} ok, {limited} rate-limited")


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


def choose(seed, available, settings, cursor=0, history=None):
    if settings["mode"] == "paused":
        raise ValueError("automatic free-model selection paused by policy")
    ordered = rank_seeds([m for m in seed if m in available], history)
    reasons = {m: selection_reason(m, seed, history) for m in ordered}
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
    parser.add_argument("--history", type=Path, default=Path("/root/logs/agent-dispatch"),
                        help="task log root for recent free-model outcomes")
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
            history = recent_history(args.history, time.time())
            ordered, reasons = choose(seed, available, settings, cursor, history)
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
                       "history": {"window_days": HISTORY_WINDOW // 86400,
                                   "models": len(history),
                                   "attempts": sum(r["ok"] + r["rate_limited"] for r in history.values())},
                       "next_cursor": cursor + 1, "seed_sha256": report["pool_hashes"][0]}
            audit.save_report(state_path, receipt)
            print(json.dumps(receipt, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FREE MODEL SELECTION REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
