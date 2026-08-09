#!/usr/bin/env python3
"""Cheap intraday state snapshot used by OpenClaw's pre-model cron trigger.

The trigger evaluates this script before creating an agent turn. It compares the
returned normalized state with its durable prior state and invokes the LLM only
for a condition delta, a material reprice, or a low-frequency forced review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402
from clawock import fetch_peers, trading_calendar  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
_CHECKOUT = Path(__file__).resolve().parents[2]
WS = workspace_root(Path(__file__).resolve().parents[2])
HKT = ZoneInfo("Asia/Hong_Kong")
PORTFOLIO = WS / "portfolio.json"

sys.path.insert(0, str(_CHECKOUT / "scripts" / "data"))
import cron_heartbeat  # noqa: E402


def _load(path):
    try:
        value = json.loads(Path(path).read_text())
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
