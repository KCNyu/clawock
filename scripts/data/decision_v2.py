#!/usr/bin/env python3
"""clawock decision ledger v2.

The legacy scorecard treated every plan row as an independent prediction and
added percentage points across positions.  V2 keeps the raw decision events but
evaluates one representative per strategy episode, only after its condition
actually fired.  Multiple decisions for one ticker/day remain valid when they
belong to different strategies (core position, intraday T, risk rebalance, …).

Authoritative persisted store: ``memory/decisions.jsonl``.
Plan contract: ``schema_version=2`` + top-level ``decisions``.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
LEDGER = WS / "memory" / "decisions.jsonl"
SNAP_DIR = WS / "memory" / "snapshots"

SCHEMA_VERSION = 2
ACTIONS = {
    "cut", "trim_on_rebound", "hold_and_watch", "t_only",
    "add_only_on_trigger", "add_on_breakout", "watch",
}
CONDITION_TYPES = {
    "open", "price_above", "price_below", "index_breakdown",
    "event", "manual", "always",
}
DRIVERS = {"technical", "catalyst", "sentiment", "influencer", "macro", "peer", "risk_rule"}
STRATEGIES = {
    "core_position", "risk_rebalance", "intraday_t", "event_trade",
    "tactical_entry", "legacy_unknown",
}
ACTIVE_ACTIONS = {"cut", "trim_on_rebound", "t_only", "add_only_on_trigger", "add_on_breakout"}
SELL_ACTIONS = {"cut", "trim_on_rebound", "t_only"}


def _slug(value: object, fallback: str = "unknown") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return s or fallback


def _stable_id(prefix: str, *parts: object, size: int = 12) -> str:
    raw = "\x1f".join(str(p or "") for p in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode()).hexdigest()[:size]}"


def _float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value):
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def infer_strategy(action: dict) -> str:
    """Best-effort legacy classifier. New plans must state strategy_id."""
    bucket = action.get("action") or action.get("bucket") or ""
    text = " ".join(str(action.get(k) or "") for k in ("rationale", "size_note", "trigger_condition")).lower()
    if bucket == "t_only" or "日内" in text or "做t" in text:
        return "intraday_t"
    risk_words = ("硬止损", "止损", "breach", "cap", "上限", "降杠杆", "换仓", "再平衡", "single_name", "regime")
    if any(w in text for w in risk_words):
        return "risk_rebalance"
    if action.get("driven_by") == "catalyst" or action.get("trigger_type") == "event":
        return "event_trade"
    if bucket in ("add_only_on_trigger", "add_on_breakout"):
        return "tactical_entry"
    return "core_position"


def legacy_action_to_decision(action: dict, plan_date: str, ordinal: int = 0) -> dict:
    ticker = str(action.get("ticker") or "").strip()
    act = action.get("action") or action.get("bucket") or "watch"
    act = {"sell": "cut", "buy": "add_only_on_trigger", "hold": "hold_and_watch"}.get(act, act)
    strategy = action.get("strategy_id") or infer_strategy(action)
    authored_condition = action.get("condition") if isinstance(action.get("condition"), dict) else {}
    authored_size = action.get("size") if isinstance(action.get("size"), dict) else {}
    condition_type = authored_condition.get("type") or action.get("trigger_type") or "manual"
    condition_price = _float(authored_condition.get("price"))
    if condition_price is None:
        condition_price = _float(action.get("trigger_price"))
    if condition_type not in CONDITION_TYPES:
        condition_type = "manual"
    if condition_type in ("price_above", "price_below") and condition_price is None:
        condition_type = "manual"  # legacy row had an unscorable price condition
    decision_id = action.get("decision_id") or _stable_id(
        "dec", plan_date, ticker, strategy, act, condition_type, condition_price, ordinal
    )
    thesis_id = action.get("thesis_id") or f"{_slug(ticker)}-{strategy}"
    created_at = action.get("created_at") or f"{plan_date}T08:00:00+08:00"
    return {
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id,
        "episode_id": action.get("episode_id"),
        "decision_group_id": action.get("decision_group_id") or f"{plan_date}:{ticker}",
        "plan_date": plan_date,
        "created_at": created_at,
        "ticker": ticker,
        "name": action.get("name") or "",
        "leg": action.get("leg") or ("HK" if ticker.isdigit() else "US"),
        "strategy_id": strategy,
        "thesis_id": thesis_id,
        "action": act,
        "condition": {
            "type": condition_type,
            "price": condition_price,
            "description": authored_condition.get("description") or action.get("trigger_condition") or "",
        },
        "size": {
            "shares": _int(authored_size.get("shares")) if authored_size else _int(action.get("size_shares")),
            "pct": _float(authored_size.get("pct")) if authored_size else _float(action.get("size_pct")),
            "note": authored_size.get("note") or action.get("size_note") or "",
        },
        "confidence": _float(action.get("confidence")),
        "driven_by": action.get("driven_by") or "technical",
        "rationale": action.get("rationale") or "",
        "simulated_entry_price": _float(action.get("simulated_entry_price")),
        "horizon_sessions": int(action.get("horizon_sessions") or 1),
        "override": action.get("override") or {
            "status": "none", "reason": "", "expires_on": None, "revisit_condition": ""
        },
        "evaluation": action.get("evaluation") or {
            "status": "pending", "triggered": None, "trigger_session": None,
            "execution_price": None, "underlying_return_t1_pct": None,
            "benefit_t1_pct": None, "benefit_t5_pct": None, "outcome": "pending",
            "capital": None,
        },
        "execution": action.get("execution") or {
            "status": "unknown", "detected_at": None, "source": None,
        },
        "migration": action.get("migration") or {"source": "plan_v1"},
    }


def assign_episode_ids(decisions: list[dict]) -> list[dict]:
    """Assign episodes across consecutive reaffirmations of the same strategy/action.

    A strategy action change starts a new episode. A gap over four calendar days
    also starts a new episode. Different strategy_id values never collide, so a
    core HOLD and a risk-rebalance TRIM can coexist on the same ticker/day.
    """
    ordered = sorted(enumerate(decisions), key=lambda x: (x[1].get("plan_date", ""), x[0]))
    state: dict[tuple[str, str], dict] = {}
    for _, d in ordered:
        key = (d.get("ticker", ""), d.get("strategy_id", "legacy_unknown"))
        cur_date = datetime.strptime(d["plan_date"], "%Y-%m-%d").date()
        if d.get("episode_id"):
            state[key] = {"action": d.get("action"), "date": cur_date,
                          "episode_id": d.get("episode_id")}
            continue
        prev = state.get(key)
        continue_episode = False
        if prev and prev["action"] == d.get("action"):
            gap = (cur_date - prev["date"]).days
            continue_episode = 0 <= gap <= 4
        if continue_episode:
            episode_id = prev["episode_id"]
        else:
            episode_id = _stable_id(
                "ep", d.get("ticker"), d.get("strategy_id"), d.get("action"), d.get("plan_date"), d.get("decision_id")
            )
        d["episode_id"] = episode_id
        state[key] = {"action": d.get("action"), "date": cur_date, "episode_id": episode_id}
    return decisions


def validate_decision(d: dict) -> list[str]:
    errors = []
    for key in ("decision_id", "episode_id", "plan_date", "created_at", "ticker", "strategy_id", "action", "condition"):
        if d.get(key) in (None, ""):
            errors.append(f"missing {key}")
    if d.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 2")
    if d.get("action") not in ACTIONS:
        errors.append(f"bad action {d.get('action')!r}")
    if d.get("strategy_id") not in STRATEGIES:
        errors.append(f"bad strategy_id {d.get('strategy_id')!r}")
    condition = d.get("condition") or {}
    if condition.get("type") not in CONDITION_TYPES:
        errors.append(f"bad condition.type {condition.get('type')!r}")
    if condition.get("type") in ("price_above", "price_below") and _float(condition.get("price")) is None:
        errors.append("price condition requires condition.price")
    conf = _float(d.get("confidence"))
    if conf is None or not 0 <= conf <= 1:
        errors.append("confidence must be in [0,1]")
    if d.get("driven_by") not in DRIVERS:
        errors.append(f"bad driven_by {d.get('driven_by')!r}")
    override = d.get("override") or {}
    if override.get("status", "none") not in ("none", "active", "expired", "revoked"):
        errors.append(f"bad override.status {override.get('status')!r}")
    return errors


def missing_size_warnings(decisions: list[dict]) -> list[str]:
    """Active calls with no share count. A warning, never an error.

    Without shares there is no capital, so the call can be scored for direction
    but never priced — it silently vanishes from the only chart that answers
    "what did listening to it cost me?". Migrated v1 rows often lack it and must
    not be rejected retroactively, so this stays advisory and is reported by
    postflight against newly authored plans.
    """
    out = []
    for d in decisions:
        if d.get("action") in ACTIVE_ACTIONS and _int((d.get("size") or {}).get("shares")) is None:
            out.append(f"{d.get('ticker')} {d.get('action')}: size.shares missing → unpriceable")
    return out


def validate_plan(plan: dict, path: str | Path | None = None) -> list[str]:
    """Validate an authored plan. Pass ``path`` to also enforce date == filename.

    2026-06-01-plan.json once shipped with date="2026-06-02". Every id downstream
    is derived from that field, so both days minted the same decision_ids: six
    collided, the later day's thesis was silently dropped, and the survivors were
    graded against the wrong session. Nothing caught it for six weeks — the rows
    were individually valid. Callers holding a filename must pass it.
    """
    errors = []
    if plan.get("schema_version") != SCHEMA_VERSION:
        errors.append("top-level schema_version must be 2")
    if not plan.get("date"):
        errors.append("missing date")
    if path is not None:
        expected = Path(path).name[:10]
        if plan.get("date") and plan.get("date") != expected:
            errors.append(f"date {plan.get('date')!r} must match filename ({expected!r})")
    if "actions" in plan:
        errors.append("v1 actions field is forbidden")
    decisions = plan.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        errors.append("decisions must be a non-empty list")
        return errors
    seen = set()
    for i, d in enumerate(decisions):
        for err in validate_decision(d):
            errors.append(f"decision[{i}] {err}")
        did = d.get("decision_id")
        if did in seen:
            errors.append(f"duplicate decision_id {did}")
        seen.add(did)
    return errors


def normalize_authored_plan(plan: dict, ledger_path: Path = LEDGER) -> dict:
    """Fill deterministic v2 ids/defaults before postflight validation."""
    plan_date = plan.get("date") or datetime.now().date().isoformat()
    source = plan.get("decisions") or []
    normalized = [legacy_action_to_decision(item, plan_date, i) for i, item in enumerate(source)]
    existing = load_decisions(ledger_path)
    assign_episode_ids(existing + normalized)
    out = {k: v for k, v in plan.items() if k != "actions"}
    out["schema_version"] = SCHEMA_VERSION
    out["decisions"] = normalized
    return out


def load_decisions(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{n}: {e}") from e
    return out


def write_decisions(decisions: list[dict], path: Path = LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n" for d in decisions)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def upsert_plan_decisions(plan: dict, path: Path = LEDGER) -> tuple[int, int]:
    existing = load_decisions(path)
    by_id = {d.get("decision_id"): d for d in existing}
    inserted = updated = 0
    for d in plan.get("decisions") or []:
        did = d.get("decision_id")
        if did in by_id:
            old = by_id[did]
            # Preserve live evaluation/execution while refreshing authored fields.
            evaluation = old.get("evaluation")
            execution = old.get("execution")
            old.update(d)
            if evaluation:
                old["evaluation"] = evaluation
            if execution:
                old["execution"] = execution
            updated += 1
        else:
            existing.append(d)
            by_id[did] = d
            inserted += 1
    assign_episode_ids(existing)
    write_decisions(existing, path)
    return inserted, updated


_SNAP_CACHE: dict[str, dict | None] = {}


def snapshot_dates() -> list[str]:
    return sorted(p.stem for p in SNAP_DIR.glob("20*.json"))


def load_snapshot(day: str) -> dict | None:
    if day not in _SNAP_CACHE:
        p = SNAP_DIR / f"{day}.json"
        try:
            _SNAP_CACHE[day] = json.loads(p.read_text()) if p.exists() else None
        except Exception:
            _SNAP_CACHE[day] = None
    return _SNAP_CACHE[day]


def holding_from_snapshot(snapshot: dict | None, ticker: str) -> dict | None:
    for region in ("hk_stocks", "us_stocks"):
        for h in (snapshot or {}).get("portfolios", {}).get(region, {}).get("holdings", []):
            if str(h.get("ticker")) == str(ticker):
                return h
    return None


def _price(snapshot: dict | None, ticker: str, field: str = "current_price"):
    return _float((holding_from_snapshot(snapshot, ticker) or {}).get(field))


def condition_execution(decision: dict, snap: dict | None) -> tuple[bool | None, float | None]:
    cond = decision.get("condition") or {}
    ctype = cond.get("type") or "manual"
    action = decision.get("action")
    ticker = decision.get("ticker")
    h = holding_from_snapshot(snap, ticker) or {}
    recorded = _float((decision.get("evaluation") or {}).get("execution_price"))
    recorded = recorded or _float(decision.get("simulated_entry_price"))
    current = _float(h.get("current_price"))
    if action in ("hold_and_watch", "watch"):
        return True, recorded or current
    if ctype in ("always", "open"):
        return True, _float(h.get("day_open")) or recorded or current
    trigger = _float(cond.get("price"))
    if ctype == "price_above" and trigger is not None:
        high = _float(h.get("day_high"))
        return ((high >= trigger), trigger) if high is not None else (None, None)
    if ctype == "price_below" and trigger is not None:
        low = _float(h.get("day_low"))
        return ((low <= trigger), trigger) if low is not None else (None, None)
    # event/manual/index need explicit human evidence; never fabricate a trigger.
    return None, None


def _benefit(action: str, entry: float | None, later: float | None) -> tuple[float | None, float | None]:
    if not entry or later is None:
        return None, None
    underlying = (later - entry) / entry * 100
    advantage = -underlying if action in SELL_ACTIONS else underlying
    return round(underlying, 4), round(advantage, 4)


def settle_decisions(decisions: list[dict], now_date: str | None = None) -> int:
    """Recompute trigger and T+1/T+5 outcomes from snapshots in-place."""
    dates = snapshot_dates()
    today = now_date or datetime.now(timezone.utc).date().isoformat()
    changed = 0
    for d in decisions:
        plan_date = d.get("plan_date")
        if not plan_date or plan_date > today:
            continue
        before = json.dumps(d.get("evaluation"), sort_keys=True)
        same = load_snapshot(plan_date)
        fired, execution_price = condition_execution(d, same)
        sessions = [x for x in dates if x > plan_date]
        ev = d.setdefault("evaluation", {})
        ev.update({
            "triggered": fired,
            "trigger_session": plan_date if fired else None,
            "execution_price": execution_price,
        })
        shares = _int((d.get("size") or {}).get("shares"))
        ev["capital"] = round(execution_price * shares, 2) if execution_price and shares else None
        if fired is False:
            ev.update({"status": "not_triggered", "outcome": "not_triggered",
                       "underlying_return_t1_pct": None, "benefit_t1_pct": None, "benefit_t5_pct": None})
        elif fired is None:
            ev.update({"status": "not_evaluable", "outcome": "unknown",
                       "underlying_return_t1_pct": None, "benefit_t1_pct": None, "benefit_t5_pct": None})
        elif sessions:
            u1, b1 = _benefit(d.get("action"), execution_price, _price(load_snapshot(sessions[0]), d.get("ticker")))
            _, b5 = (None, None)
            if len(sessions) >= 5:
                _, b5 = _benefit(d.get("action"), execution_price, _price(load_snapshot(sessions[4]), d.get("ticker")))
            ev.update({
                "status": "settled" if b1 is not None else "pending",
                "outcome": ("win" if b1 > 0 else "loss") if b1 is not None else "pending",
                "underlying_return_t1_pct": u1,
                "benefit_t1_pct": b1,
                "benefit_t5_pct": b5,
            })
        else:
            ev.update({"status": "pending", "outcome": "pending",
                       "underlying_return_t1_pct": None, "benefit_t1_pct": None, "benefit_t5_pct": None})
        if json.dumps(ev, sort_keys=True) != before:
            changed += 1
    return changed


def episode_representatives(decisions: list[dict], horizon: str = "t1") -> list[dict]:
    """One actually-triggered representative per episode; reaffirmations do not add n."""
    benefit_key = "benefit_t1_pct" if horizon == "t1" else "benefit_t5_pct"
    groups = defaultdict(list)
    for d in decisions:
        groups[d.get("episode_id")].append(d)
    reps = []
    for _, rows in groups.items():
        rows.sort(key=lambda x: (x.get("created_at", ""), x.get("decision_id", "")))
        triggered = [d for d in rows if (d.get("evaluation") or {}).get("triggered") is True]
        if not triggered:
            continue
        rep = triggered[0]
        if _float((rep.get("evaluation") or {}).get(benefit_key)) is not None:
            reps.append(rep)
    reps.sort(key=lambda x: (x.get("plan_date", ""), x.get("decision_id", "")))
    return reps


def _cluster_ci(rows: list[dict], value_fn, samples: int = 1000) -> list[float] | None:
    """Deterministic date-cluster bootstrap CI; repeated same-day calls move together."""
    groups = defaultdict(list)
    for r in rows:
        v = value_fn(r)
        if v is not None:
            groups[r.get("plan_date")].append(float(v))
    dates = sorted(groups)
    if len(dates) < 3:
        return None
    rnd = random.Random(20260714)
    stats = []
    for _ in range(samples):
        vals = []
        for _ in dates:
            vals.extend(groups[rnd.choice(dates)])
        if vals:
            stats.append(sum(vals) / len(vals))
    stats.sort()
    return [round(stats[int(0.025 * (len(stats) - 1))], 4),
            round(stats[int(0.975 * (len(stats) - 1))], 4)]


def _aggregate(rows: list[dict], benefit_key: str) -> dict:
    vals = [(_float((r.get("evaluation") or {}).get(benefit_key)),
             _float((r.get("evaluation") or {}).get("capital"))) for r in rows]
    vals = [(v, c) for v, c in vals if v is not None]
    if not vals:
        return {"n_episodes": 0, "win_rate": None, "avg_benefit_pct": None,
                "capital_weighted_benefit_pct": None, "cluster_ci95": None}
    plain = [v for v, _ in vals]
    weighted = [(v, c) for v, c in vals if c and c > 0]
    cw = sum(v * c for v, c in weighted) / sum(c for _, c in weighted) if weighted else None
    return {
        "n_episodes": len(vals),
        "win_rate": round(sum(v > 0 for v in plain) / len(plain), 4),
        "avg_benefit_pct": round(sum(plain) / len(plain), 4),
        "capital_weighted_benefit_pct": round(cw, 4) if cw is not None else None,
        "capital_coverage_pct": round(100 * len(weighted) / len(vals), 1),
        "cluster_ci95": _cluster_ci(rows, lambda r: _float((r.get("evaluation") or {}).get(benefit_key))),
    }


def _breakdown(rows: list[dict], field_getter, benefit_key: str) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[field_getter(r) or "unknown"].append(r)
    out = {}
    for key, rs in sorted(groups.items()):
        agg = _aggregate(rs, benefit_key)
        ci = agg.get("cluster_ci95")
        agg["edge_significant"] = bool(ci and ci[0] > 0)
        out[key] = agg
    return out


def _compounded_curve(rows: list[dict], benefit_key: str) -> list[dict]:
    """Compound one capital-weighted portfolio-of-decisions return per plan date."""
    by_date = defaultdict(list)
    for r in rows:
        v = _float((r.get("evaluation") or {}).get(benefit_key))
        c = _float((r.get("evaluation") or {}).get("capital"))
        if v is not None:
            by_date[r.get("plan_date")].append((v, c))
    curve = []
    equity = 1.0
    for day in sorted(by_date):
        values = by_date[day]
        weighted = [(v, c) for v, c in values if c and c > 0]
        day_ret = (sum(v * c for v, c in weighted) / sum(c for _, c in weighted)
                   if weighted else sum(v for v, _ in values) / len(values))
        equity *= 1 + day_ret / 100
        curve.append({"date": day, "daily_benefit_pct": round(day_ret, 4),
                      "compounded_benefit_pct": round((equity - 1) * 100, 4)})
    return curve


def _cumulative_win_rate_curve(rows: list[dict], benefit_key: str) -> list[dict]:
    """Cumulative episode hit rate by plan date, for a true win-rate chart."""
    by_date = defaultdict(list)
    for r in rows:
        value = _float((r.get("evaluation") or {}).get(benefit_key))
        if value is not None:
            by_date[r.get("plan_date")].append(value)
    curve = []
    wins = total = 0
    for day in sorted(by_date):
        values = by_date[day]
        wins += sum(v > 0 for v in values)
        total += len(values)
        curve.append({"date": day, "wins": wins, "n_episodes": total,
                      "win_rate": round(wins / total, 4)})
    return curve


def compute_metrics(decisions: list[dict], window_days: int = 30) -> dict:
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=window_days)).isoformat()
    reps = [r for r in episode_representatives(decisions, "t1") if r.get("plan_date", "") >= cutoff]
    conf_rows = [r for r in reps if _float(r.get("confidence")) is not None]
    brier = None
    if conf_rows:
        brier = sum((float(r["confidence"]) - (1 if (r.get("evaluation") or {}).get("outcome") == "win" else 0)) ** 2
                    for r in conf_rows) / len(conf_rows)
    execution = Counter((r.get("execution") or {}).get("status", "unknown") for r in decisions)
    overrides = [r for r in decisions if (r.get("override") or {}).get("status") == "active"]
    active = [r for r in reps if r.get("action") in ACTIVE_ACTIONS]
    passive = [r for r in reps if r.get("action") in ("hold_and_watch", "watch")]
    return {
        "schema_version": SCHEMA_VERSION,
        "method": "episode-level; triggered-only; date-cluster bootstrap; capital-weighted where size exists",
        "window_days": window_days,
        "raw_decisions": len(decisions),
        "episodes": len({d.get("episode_id") for d in decisions}),
        "settled_episodes": len(reps),
        "brier": round(brier, 4) if brier is not None else None,
        "active": _aggregate(active, "benefit_t1_pct"),
        "passive": _aggregate(passive, "benefit_t1_pct"),
        "by_action": _breakdown(reps, lambda r: r.get("action"), "benefit_t1_pct"),
        "by_strategy": _breakdown(reps, lambda r: r.get("strategy_id"), "benefit_t1_pct"),
        "by_driver": _breakdown(reps, lambda r: r.get("driven_by"), "benefit_t1_pct"),
        "by_condition": _breakdown(reps, lambda r: (r.get("condition") or {}).get("type"), "benefit_t1_pct"),
        "execution": dict(execution),
        "active_overrides": len(overrides),
    }


def compute_money_impact(decisions: list[dict], horizon: str = "t1") -> dict:
    """What the AI's active calls were actually worth, in money, per leg.

    ``benefit_pct`` only answers "was the call directionally right": for a sell it
    is the negation of the underlying move, so it climbs while the account bleeds.
    Compounding it (``compute_backtest``) makes that gap worse — it is a
    counterfactual score, not a return, and 108 episodes of it compound into a
    number two orders of magnitude larger than the cash ever at risk.

    ``capital`` (execution_price x shares) turns each call back into money:
    capital x benefit/100 is the cash that call moved versus not acting. Summing
    those is honest because each is an independent one-shot bet, not a reinvested
    position. HKD and USD are never added (FX rule); callers render per leg.

    Decisions without a share count cannot be priced, so ``coverage_pct`` reports
    how much of the record this view can actually see.
    """
    reps = episode_representatives(decisions, horizon)
    key = "benefit_t1_pct" if horizon == "t1" else "benefit_t5_pct"
    active = [r for r in reps if r.get("action") in ACTIVE_ACTIONS]

    def _priced(rows):
        return [r for r in rows
                if _float((r.get("evaluation") or {}).get("capital"))
                and _float((r.get("evaluation") or {}).get(key)) is not None]

    def _money(r):
        return _float(r["evaluation"]["capital"]) * _float(r["evaluation"][key]) / 100

    def bucket(rows):
        priced = _priced(rows)
        return {
            "money": round(sum(_money(r) for r in priced), 2),
            "n_episodes": len(rows),
            "n_priced": len(priced),
            "capital_at_risk": round(sum(_float(r["evaluation"]["capital"]) for r in priced), 2),
        }

    def curve(rows):
        """Cumulative money, added — never compounded.

        Each call is an independent one-shot bet that is entered and settled, not
        a reinvested balance, so compounding them (as the benefit curve does)
        invents growth that no capital ever experienced. Addition is the honest
        operator here, and it keeps the y-axis in currency.
        """
        by_date = defaultdict(float)
        for r in _priced(rows):
            by_date[r.get("plan_date")] += _money(r)
        out, total = [], 0.0
        for day in sorted(by_date):
            total += by_date[day]
            out.append({"date": day, "daily_money": round(by_date[day], 2),
                        "cumulative_money": round(total, 2)})
        return out

    legs = {}
    for leg, currency in (("US", "USD"), ("HK", "HKD")):
        rows = [r for r in active if (r.get("leg") or "") == leg]
        if not rows:
            continue
        followed = [r for r in rows if (r.get("execution") or {}).get("status") == "followed"]
        not_followed = [r for r in rows if (r.get("execution") or {}).get("status") == "not_followed"]
        agg = bucket(rows)
        legs[leg] = {
            "currency": currency,
            "all_active": agg,
            # Already reflected in the real P&L curve — kcn acted on these.
            "followed": bucket(followed),
            # The live counterfactual: what ignoring the AI cost or saved.
            "not_followed": bucket(not_followed),
            "coverage_pct": round(100 * agg["n_priced"] / len(rows), 1) if rows else None,
            "curve": curve(rows),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "horizon": horizon,
        "method": ("capital x benefit per triggered active episode, summed in native currency; "
                   "positive = following the AI beat not acting"),
        "legs": legs,
    }


def compute_backtest(decisions: list[dict]) -> dict:
    horizons = {}
    for horizon, key in (("t1", "benefit_t1_pct"), ("t5", "benefit_t5_pct")):
        reps = episode_representatives(decisions, horizon)
        active = [r for r in reps if r.get("action") in ACTIVE_ACTIONS]
        followed = [r for r in reps if (r.get("execution") or {}).get("status") == "followed"]
        horizons[horizon] = {
            # Keep the complete AI track record, including HOLD/WATCH episodes.
            # This is the v2 continuation of the migrated v1 "all calls" line;
            # `active` remains separate so passive market beta cannot masquerade
            # as evidence that cut/trim/add timing has alpha.
            "all": _aggregate(reps, key),
            "active": _aggregate(active, key),
            "followed": _aggregate(followed, key),
            "by_strategy": _breakdown(reps, lambda r: r.get("strategy_id"), key),
            "all_curve": _compounded_curve(reps, key),
            "active_curve": _compounded_curve(active, key),
            "followed_curve": _compounded_curve(followed, key),
            "all_win_rate_curve": _cumulative_win_rate_curve(reps, key),
            "active_win_rate_curve": _cumulative_win_rate_curve(active, key),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "method": ("one triggered representative per strategy episode; same-day decisions cluster together; "
                   "daily capital-weighted benefit is compounded, never arithmetically summed across calls"),
        "horizons": horizons,
    }


def recent_decisions(decisions: list[dict], limit: int = 20) -> list[dict]:
    out = []
    for d in sorted(decisions, key=lambda x: (x.get("created_at", ""), x.get("decision_id", "")), reverse=True)[:limit]:
        ev = d.get("evaluation") or {}
        out.append({
            "date": d.get("plan_date"), "decision_id": d.get("decision_id"),
            "episode_id": d.get("episode_id"), "ticker": d.get("ticker"),
            "strategy_id": d.get("strategy_id"), "action": d.get("action"),
            "condition": d.get("condition"), "confidence": d.get("confidence"),
            "driven_by": d.get("driven_by"), "status": ev.get("status"),
            "outcome": ev.get("outcome"), "benefit_t1_pct": ev.get("benefit_t1_pct"),
            "execution": (d.get("execution") or {}).get("status", "unknown"),
            "override": d.get("override"),
        })
    return out


def decision_delta(decisions: list[dict]) -> dict:
    dates = sorted({d.get("plan_date") for d in decisions if d.get("plan_date")})
    if not dates:
        return {"as_of": None, "new": [], "changed": [], "triggered": [], "active_overrides": []}
    latest = dates[-1]
    previous = dates[-2] if len(dates) > 1 else None
    cur = [d for d in decisions if d.get("plan_date") == latest]
    prev = [d for d in decisions if d.get("plan_date") == previous]
    prev_by_key = {(d.get("ticker"), d.get("strategy_id")): d for d in prev}
    new, changed = [], []
    for d in cur:
        compact = {"ticker": d.get("ticker"), "strategy_id": d.get("strategy_id"),
                   "action": d.get("action"), "condition": d.get("condition"),
                   "decision_id": d.get("decision_id")}
        old = prev_by_key.get((d.get("ticker"), d.get("strategy_id")))
        if not old:
            new.append(compact)
        elif old.get("action") != d.get("action") or old.get("condition") != d.get("condition"):
            compact["from_action"] = old.get("action")
            changed.append(compact)
    triggered = [{"ticker": d.get("ticker"), "strategy_id": d.get("strategy_id"), "action": d.get("action")}
                 for d in cur if (d.get("evaluation") or {}).get("triggered") is True]
    overrides = [{"ticker": d.get("ticker"), "strategy_id": d.get("strategy_id"),
                  "reason": (d.get("override") or {}).get("reason"),
                  "expires_on": (d.get("override") or {}).get("expires_on")}
                 for d in decisions if (d.get("override") or {}).get("status") == "active"]
    return {"as_of": latest, "previous": previous, "new": new, "changed": changed,
            "triggered": triggered, "active_overrides": overrides,
            "has_material_change": bool(new or changed or triggered or overrides)}
