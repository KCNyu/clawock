#!/usr/bin/env python3
"""Cheap intraday state snapshot used by OpenClaw's pre-model cron trigger.

The trigger evaluates this script before creating an agent turn. It compares the
returned normalized state with its durable prior state and invokes the LLM only
for a condition delta. The normalized state deliberately excludes raw quote
churn: it carries decision-relevant semantics (signals, setups, plans, primary
events, source health) plus the leverage regime and risk-alert state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from clawock.workspace import workspace_root
from clawock.market_data import sessions as trading_calendar
from clawock.market_data import peer_quotes as fetch_peers
from clawock.automation import cron_heartbeat
from clawock.safe_io import safe_write_json, load_json_cached

WS = workspace_root(Path.cwd())
HKT = ZoneInfo("Asia/Hong_Kong")
ET = ZoneInfo("America/New_York")
PORTFOLIO = WS / "portfolio.json"


def delivered_state_path(workspace, market):
    return Path(workspace) / "memory" / ".tmp" / f"intraday-delivered-state-{market}.json"


def load_delivered_state(workspace, market):
    return _load(delivered_state_path(workspace, market))


def persist_delivered_state(workspace, ctx):
    """Advance the comparison cursor only after a real channel delivery."""
    market = ctx.get("market")
    state = ctx.get("semantic_state")
    if market not in {"hk", "us"} or not isinstance(state, dict):
        return False
    path = delivered_state_path(workspace, market)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_json(str(path), {
        "schema_version": 1,
        "market": market,
        "slot": (ctx.get("heartbeat") or {}).get("slot"),
        "context_id": ctx.get("context_id"),
        "state": state,
    })
    return True


def semantic_state(market, session_date, *, signals_detail, anomalies, setups,
                   plans, active_information):
    """Normalize a slot to decision-relevant state, excluding quote churn."""
    breaches = []
    for row in signals_detail or []:
        ticker, level = row.get("ticker"), row.get("level")
        if ticker and level:
            breaches.append({"ticker": ticker, "kind": "signal", "level": level})
    for row in anomalies or []:
        move = row.get("move_pct")
        if row.get("ticker") and isinstance(move, (int, float)):
            magnitude = abs(move)
            if magnitude >= 12:
                move_level = "dislocation"
            elif magnitude >= 8:
                move_level = "extreme"
            elif magnitude >= 5:
                move_level = "high"
            else:
                move_level = "medium"
            breaches.append({
                "ticker": row["ticker"], "kind": "move",
                "level": move_level,
                "direction": "up" if move > 0 else "down",
            })
    # #610: the price-surface lanes encode their live sub-state in setup_id
    # (opportunity:{breakout|wait_rebreak|near_breakout},
    # early_trend:{state}) and those sub-states flip on raw quote churn around
    # a threshold (close vs prior, zscore20 vs 2.0) — exactly the churn this
    # gate exists to exclude. Compare the lane identity, not the churny
    # sub-state; a row appearing or disappearing still counts as a delta.
    def _stable_setup_id(setup_id):
        if setup_id and ':' in str(setup_id):
            prefix = str(setup_id).split(':', 1)[0]
            if prefix in ('opportunity', 'early_trend'):
                return prefix
        return setup_id

    setup_rows = [{
        "label": row.get("label"),
        "setup_id": _stable_setup_id(row.get("setup_id")),
        "holdings": sorted(row.get("holdings") or []),
    } for row in ((setups or {}).get("rows") or [])]
    plan_rows = [{
        key: row.get(key) for key in (
            "decision_id", "ticker", "action", "condition", "shares", "pct",
            "execution_status",
        )
    } for row in ((plans or {}).get("open") or [])]
    event_rows = {}
    for row in ((active_information or {}).get("candidates") or []):
        if not row.get("event_id"):
            continue
        event_rows[row["event_id"]] = {
            "issuer": row.get("issuer"), "disposition": row.get("disposition"),
            "direction": row.get("direction"), "category": row.get("category"),
            "blockers": sorted(row.get("blockers") or []),
        }
    return {
        "session": f"{market}:{session_date}",
        "breaches": sorted(breaches, key=lambda row: json.dumps(row, sort_keys=True)),
        "setups": sorted(setup_rows, key=lambda row: json.dumps(row, sort_keys=True)),
        "plans": sorted(plan_rows, key=lambda row: json.dumps(row, sort_keys=True)),
        "primary_events": event_rows,
        "primary_source_health": {
            "degraded": sorted((active_information or {}).get("degraded_issuers") or []),
            "partial": sorted(
                (active_information or {}).get("partially_degraded_issuers") or []
            ),
        },
        "regime": _regime_state(market),
    }


def compare_semantic_states(current, previous):
    previous = previous if isinstance(previous, dict) else {}
    keys = ("session", "breaches", "setups", "plans", "primary_events",
            "primary_source_health", "regime")
    components = [key for key in keys if current.get(key) != previous.get(key)]
    old_events = previous.get("primary_events") or {}
    new_events = current.get("primary_events") or {}
    changed_ids = sorted(
        event_id for event_id, row in new_events.items()
        if old_events.get(event_id) != row
    )
    return {
        "changed": bool(components),
        "components": components,
        "changed_event_ids": changed_ids,
        "removed_event_ids": sorted(set(old_events) - set(new_events)),
    }


def market_session_date(market, at):
    """Trading-session date, not the host date that rolls mid-US-session."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=HKT)
    zone = ET if market == "us" else HKT
    return at.astimezone(zone).date().isoformat()

def _load(path):
    try:
        value = load_json_cached(path)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _active_holdings(market):
    portfolio = _load(PORTFOLIO)
    leg = "hk_stocks" if market == "hk" else "us_stocks"
    return [
        holding for holding in
        portfolio.get("portfolios", {}).get(leg, {}).get("holdings", [])
        if (holding.get("shares") or 0) > 0
    ]


def _severity(pnl_pct):
    if pnl_pct <= -18:
        return "hard_stop"
    if pnl_pct <= -12:
        return "trim"
    if pnl_pct <= -8:
        return "watch"
    return None


def normalized_breaches(holdings, quotes):
    """Stable condition set: no raw prices, only threshold buckets."""
    rows = []
    for holding in holdings:
        ticker = holding.get("ticker")
        quote = quotes.get(ticker) or {}
        price = quote.get("price")
        cost = holding.get("cost_basis")
        if isinstance(price, (int, float)) and isinstance(cost, (int, float)) and cost > 0:
            pnl_pct = (price / cost - 1) * 100
            if level := _severity(pnl_pct):
                rows.append({"ticker": ticker, "kind": "pnl", "level": level})
        move = quote.get("pct_1d")
        if isinstance(move, (int, float)) and abs(move) >= 3:
            rows.append({
                "ticker": ticker,
                "kind": "move",
                "level": "high" if abs(move) >= 5 else "medium",
                "direction": "up" if move > 0 else "down",
            })
    return sorted(rows, key=lambda row: (
        row["ticker"], row["kind"], row["level"], row.get("direction", "")
    ))


def _event_state(market, active_tickers):
    """Local event provenance only; no extra news request in the cheap gate."""
    paths = [WS / "assets" / "data" / "catalysts.json"]
    if market == "us":
        paths.append(WS / "assets" / "data" / "us_news_digest.json")
    state = []
    for path in paths:
        doc = _load(path)
        # generated_at changes when the event producer publishes new evidence.
        # Matching ticker mentions makes a newly relevant held-name event visible
        # even when a producer preserves its outer timestamp during retries.
        raw = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        mentioned = sorted(ticker for ticker in active_tickers if ticker in raw)
        state.append({
            "source": path.name,
            "generated_at": doc.get("generated_at"),
            "mentioned": mentioned,
            "content_hash": hashlib.sha256(raw.encode()).hexdigest(),
        })
    return state


def _regime_state(market):
    regime = _load(WS / "assets" / "data" / "lev_regime.json")
    risk = _load(WS / "assets" / "data" / "risk.json")
    leg = regime.get(market) or {}
    names = [
        {"etf": row.get("etf"), "state": row.get("state")}
        for row in (leg.get("names") or [])
    ]
    alerts = sorted({
        (row.get("type"), row.get("severity"))
        for row in risk.get("alerts", [])
        if row.get("type") and row.get("severity")
    })
    return {
        "portfolio_tier": regime.get("tier"),
        "leg_tier": leg.get("tier"),
        "lev_cap_mult": leg.get("lev_cap_mult"),
        "leg_trend_on": leg.get("trend_on"),
        "names": names,
        "risk_alerts": [list(row) for row in alerts],
    }


def snapshot(market, *, at=None, fetcher=fetch_peers.fetch_all):
    at = at or datetime.now(timezone.utc)
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    local = at.astimezone(HKT)
    job, slot = cron_heartbeat.slot_for(market, at)
    closed = trading_calendar.closed_reason(market, local.date())
    holdings = _active_holdings(market)
    requests = [
        {"ticker": holding["ticker"], "region": market}
        for holding in holdings if holding.get("ticker")
    ]
    quotes = {} if closed else fetcher(requests, deadline_s=12, workers=8)
    prices = {
        ticker: {
            "price": round(row["price"], 4),
            "pct_1d": round(row.get("pct_1d") or 0, 2),
        }
        for ticker, row in sorted(quotes.items())
        if isinstance(row.get("price"), (int, float)) and not row.get("stale_quote")
    }
    active_tickers = sorted(
        holding["ticker"] for holding in holdings if holding.get("ticker")
    )
    conditions = {
        "breaches": normalized_breaches(holdings, quotes),
        "events": _event_state(market, active_tickers),
        "regime": _regime_state(market),
    }
    condition_hash = hashlib.sha256(
        json.dumps(conditions, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "market": market,
        "job": job,
        "slot": slot,
        "session": f"{market}:{local.date().isoformat()}",
        "market_closed": bool(closed),
        "closed_reason": closed,
        "condition_hash": condition_hash,
        "conditions": conditions,
        "prices": prices,
        "quote_coverage": {"priced": len(prices), "active": len(active_tickers)},
        "error": None if closed or len(prices) == len(active_tickers) else (
            f"quote coverage {len(prices)}/{len(active_tickers)}"
        ),
    }


def record_gate(market, state, slot, reason, state_hash=None):
    try:
        slot_at = datetime.fromisoformat(slot)
    except ValueError:
        slot_at = None
    return cron_heartbeat.record(
        market,
        state,
        job_name=cron_heartbeat.slot_for(market, slot_at)[0],
        slot=slot,
        should_alert=False,
        reasoning_invoked=False,
        trigger_reason=reason,
        state_hash=state_hash,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=["hk", "us"], required=True)
    parser.add_argument("--record", choices=["no_change", "market_closed"])
    parser.add_argument("--slot")
    parser.add_argument("--reason", default="unchanged")
    parser.add_argument("--state-hash")
    args = parser.parse_args()
    if args.record:
        if not args.slot:
            parser.error("--slot is required with --record")
        print(json.dumps(record_gate(
            args.market, args.record, args.slot, args.reason, args.state_hash
        ), ensure_ascii=False))
        return 0
    print(json.dumps(snapshot(args.market), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
