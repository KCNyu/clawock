#!/usr/bin/env python3
"""Cash-and-inventory shadow portfolio replay.

This module is deliberately independent from ``decision_v2.compute_money_impact``.
It estimates a policy simulation: start both books from the same reconstructed
cash/inventory state, apply every triggered active decision to one book in strict
session order, leave the buy-and-hold book untouched, and mark both books to the
same canonical unadjusted close on each published point.

The result is a simulation, never a reconstruction of the broker account.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import decision_v2  # noqa: E402
from clawock import trading_calendar  # noqa: E402
from clawock.workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
OUT = WS / "assets" / "data" / "shadow_portfolio.json"
SCHEMA_VERSION = 1
ACTIVE_ACTIONS = set(decision_v2.ACTIVE_ACTIONS)
SELL_ACTIONS = set(decision_v2.SELL_ACTIONS)
BUY_ACTIONS = set(decision_v2.ADD_ACTIONS)
LEG_CONFIG = {
    "US": {"portfolio_key": "us_stocks", "currency": "USD", "cash_key": "cash_usd"},
    "HK": {"portfolio_key": "hk_stocks", "currency": "HKD", "cash_key": "cash_hkd"},
}
EXTERNAL_FLOW_WORDS = ("入金", "deposit", "withdraw", "出金", "transfer")
CORPORATE_ACTION_WORDS = ("dividend", "股息", "派息", "split", "拆股")


def _number(value) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _shares(value) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return max(0, int(math.floor(number + 1e-9)))


def _holding_map(portfolio: dict, leg: str) -> dict[str, dict]:
    cfg = LEG_CONFIG[leg]
    holdings = (
        ((portfolio.get("portfolios") or {}).get(cfg["portfolio_key"]) or {})
        .get("holdings") or []
    )
    return {
        str(row.get("ticker") or row.get("code") or ""): row
        for row in holdings
        if row.get("ticker") or row.get("code")
    }


def _lot_size(portfolio: dict, leg: str, ticker: str) -> int:
    raw = (_holding_map(portfolio, leg).get(ticker) or {}).get("lot_size")
    lot = _shares(raw)
    return lot if lot and lot > 0 else 1


def _trade_rows(portfolio: dict, leg: str) -> list[dict]:
    rows = []
    for ticker, holding in _holding_map(portfolio, leg).items():
        for ordinal, trade in enumerate(holding.get("trades") or []):
            row = dict(trade)
            row["ticker"] = ticker
            row["_ordinal"] = ordinal
            rows.append(row)
    return rows


def _cash_adjustments(portfolio: dict, leg: str) -> list[dict]:
    cfg = LEG_CONFIG[leg]
    book = ((portfolio.get("portfolios") or {}).get(cfg["portfolio_key"]) or {})
    rows = []
    for ordinal, adjustment in enumerate(book.get("cash_adjustments") or []):
        amount = _number(adjustment.get("amount"))
        day = str(adjustment.get("date") or "")
        if amount is None or not day:
            continue
        note = str(adjustment.get("note") or "")
        lowered = note.lower()
        kind = (
            "corporate_action"
            if any(word in lowered for word in CORPORATE_ACTION_WORDS)
            else "external_flow"
            if any(word in lowered for word in EXTERNAL_FLOW_WORDS)
            else "unclassified"
        )
        rows.append({
            "date": day,
            "amount": amount,
            "note": note,
            "kind": kind,
            "_ordinal": ordinal,
        })
    return rows


def reconstruct_initial_book(portfolio: dict, leg: str, start_date: str) -> dict:
    """Reverse the actual ledger from today's state to just before ``start_date``.

    Actual post-start trades are used only to recover the seed. They are not
    replayed into either comparison book after the simulation starts.
    """
    cfg = LEG_CONFIG[leg]
    holdings = _holding_map(portfolio, leg)
    inventory = {
        ticker: _shares(row.get("shares")) or 0
        for ticker, row in holdings.items()
    }
    book = ((portfolio.get("portfolios") or {}).get(cfg["portfolio_key"]) or {})
    cash = _number(book.get(cfg["cash_key"]))
    cash_known = cash is not None
    cash = cash or 0.0

    reversed_trades = 0
    for trade in _trade_rows(portfolio, leg):
        if str(trade.get("date") or "") < start_date:
            continue
        ticker = trade["ticker"]
        qty = _shares(trade.get("shares"))
        price = _number(trade.get("price"))
        direction = str(trade.get("action") or "").lower()
        if not qty:
            continue
        if direction == "buy":
            inventory[ticker] = inventory.get(ticker, 0) - qty
            if price is not None:
                cash += qty * price
        elif direction == "sell":
            inventory[ticker] = inventory.get(ticker, 0) + qty
            if price is not None:
                cash -= qty * price
        else:
            continue
        reversed_trades += 1

    reversed_adjustments = 0
    for adjustment in _cash_adjustments(portfolio, leg):
        if adjustment["date"] >= start_date:
            cash -= adjustment["amount"]
            reversed_adjustments += 1

    negative_reconstruction = {
        ticker: qty for ticker, qty in inventory.items() if qty < 0
    }
    inventory = {
        ticker: qty for ticker, qty in inventory.items() if qty > 0
    }
    return {
        "cash": round(cash, 6),
        "cash_known": cash_known,
        "inventory": inventory,
        "source": "portfolio.json reversed through holdings[].trades and cash_adjustments",
        "reversed_trades": reversed_trades,
        "reversed_adjustments": reversed_adjustments,
        "negative_inventory_reconstruction": negative_reconstruction,
    }


def _event_session(decision: dict) -> str | None:
    evaluation = decision.get("evaluation") or {}
    return evaluation.get("trigger_session") or decision.get("plan_date")


def _active_triggered(decisions: list[dict], leg: str) -> list[tuple[int, dict]]:
    rows = []
    for ordinal, decision in enumerate(decisions):
        evaluation = decision.get("evaluation") or {}
        if (
            decision.get("leg") == leg
            and decision.get("action") in ACTIVE_ACTIONS
            and evaluation.get("triggered") is True
            and _event_session(decision)
        ):
            rows.append((ordinal, decision))
    return rows


def _fill_for(
    decision: dict,
    matched: dict[str, dict],
    bar_loader: Callable[[str, str], dict | None],
) -> dict | None:
    actual = matched.get(decision.get("decision_id"))
    if actual:
        price = _number(actual.get("price"))
        if price and price > 0:
            return {
                "price": price,
                "type": "real_trade",
                "model": "real_portfolio_trade",
                "assumed": False,
            }
    evaluation = decision.get("evaluation") or {}
    price = _number(evaluation.get("execution_price"))
    if price and price > 0:
        return {
            "price": price,
            "type": "ohlc_assumption",
            "model": evaluation.get("fill_model") or "daily_ohlc_trigger",
            "assumed": True,
        }
    session = _event_session(decision)
    raw = bar_loader(str(decision.get("ticker") or ""), str(session or ""))
    close = _number((raw or {}).get("close"))
    if close and close > 0:
        return {
            "price": close,
            "type": "canonical_close_fallback",
            "model": "same_session_canonical_close",
            "assumed": True,
        }
    return None


def _requested_shares(
    decision: dict,
    inventory: dict[str, int],
    cash: float,
    price: float,
    lot: int,
) -> int:
    size = decision.get("size") or {}
    authored = _shares(size.get("shares"))
    if authored is not None:
        return authored
    pct = _number(size.get("pct"))
    if pct is None or pct <= 0:
        return 0
    pct = min(pct, 100.0)
    ticker = str(decision.get("ticker") or "")
    if decision.get("action") in SELL_ACTIONS:
        raw = inventory.get(ticker, 0) * pct / 100
    else:
        raw = cash * pct / 100 / price
    return int(math.floor(raw / lot)) * lot


def _leg_provenance(decision: dict) -> dict:
    """The two labels a fill needs to be attributable back to a rule.

    Without them a leg is an anonymous cash movement: the sidecar could say the
    plan beat buy-and-hold but not which kind of decision did it. `driven_by` is
    the canonical strategy label (`risk_rule` for disciplinary rebalancing);
    `execution_status` is whether the real book actually followed.

    `decision_id` is deliberately not published here. Visitors download this
    sidecar, it measured 7KB across ~200 legs, and nothing reads it — the same
    argument that removed 27KB of consumer-less calibrator state from the
    dashboard payload.
    """
    return {
        "driven_by": str(decision.get("driven_by") or "unknown"),
        "execution_status": str(
            (decision.get("execution") or {}).get("status") or "unknown"),
    }


def _execute_sell(
    state: dict,
    decision: dict,
    fill: dict,
    portfolio: dict,
) -> dict:
    ticker = str(decision.get("ticker") or "")
    inventory = state["inventory"]
    available = inventory.get(ticker, 0)
    lot = _lot_size(portfolio, decision["leg"], ticker)
    requested = _requested_shares(
        decision, inventory, state["cash"], fill["price"], lot)
    qty = min(requested, available)
    qty = int(math.floor(qty / lot)) * lot
    if qty <= 0:
        return {
            "ticker": ticker, "direction": "sell", "requested_shares": requested,
            "filled_shares": 0, "price": fill["price"], "status": "skipped_no_inventory",
            "fill_type": fill["type"], "fill_model": fill["model"],
            **_leg_provenance(decision),
        }
    inventory[ticker] = available - qty
    state["cash"] += qty * fill["price"]
    return {
        "ticker": ticker, "direction": "sell", "requested_shares": requested,
        "filled_shares": qty, "price": fill["price"], "notional": round(qty * fill["price"], 6),
        "status": "filled" if qty == requested else "partial_inventory_cap",
        "fill_type": fill["type"], "fill_model": fill["model"],
        **_leg_provenance(decision),
    }


def _execute_buy(
    state: dict,
    decision: dict,
    fill: dict,
    portfolio: dict,
    budget: float | None = None,
) -> dict:
    ticker = str(decision.get("ticker") or "")
    inventory = state["inventory"]
    lot = _lot_size(portfolio, decision["leg"], ticker)
    available_cash = state["cash"] if budget is None else min(state["cash"], budget)
    requested = _requested_shares(
        decision, inventory, available_cash, fill["price"], lot)
    affordable = int(math.floor(available_cash / fill["price"] / lot)) * lot
    qty = min(requested, affordable)
    if qty <= 0:
        return {
            "ticker": ticker, "direction": "buy", "requested_shares": requested,
            "filled_shares": 0, "price": fill["price"], "status": "skipped_no_cash",
            "fill_type": fill["type"], "fill_model": fill["model"],
            **_leg_provenance(decision),
        }
    cost = qty * fill["price"]
    state["cash"] -= cost
    inventory[ticker] = inventory.get(ticker, 0) + qty
    return {
        "ticker": ticker, "direction": "buy", "requested_shares": requested,
        "filled_shares": qty, "price": fill["price"], "notional": round(cost, 6),
        "status": "filled" if qty == requested else "partial_cash_cap",
        "fill_type": fill["type"], "fill_model": fill["model"],
        **_leg_provenance(decision),
    }


def _execute_swap_group(
    state: dict,
    rows: list[dict],
    fills: dict[str, dict],
    portfolio: dict,
) -> list[dict]:
    """Sell first, then spend only that group's proceeds on its buy leg(s)."""
    legs = []
    cash_before = state["cash"]
    sell_rows = [row for row in rows if row.get("action") in SELL_ACTIONS]
    buy_rows = [row for row in rows if row.get("action") in BUY_ACTIONS]
    for decision in sell_rows:
        fill = fills.get(decision.get("decision_id"))
        if fill:
            legs.append(_execute_sell(state, decision, fill, portfolio))
    proceeds = max(0.0, state["cash"] - cash_before)
    remaining = proceeds
    for index, decision in enumerate(buy_rows):
        fill = fills.get(decision.get("decision_id"))
        if not fill:
            continue
        # One target receives all proceeds. Multiple targets divide the still
        # available swap pot evenly; they never borrow the pre-existing cash.
        targets_left = len(buy_rows) - index
        budget = remaining if targets_left == 1 else remaining / targets_left
        leg = _execute_buy(state, decision, fill, portfolio, budget=budget)
        legs.append(leg)
        remaining -= _number(leg.get("notional")) or 0.0
    return legs


def _apply_external_flow(state: dict, amount: float) -> None:
    state["cash"] += amount


def _mark(
    state: dict,
    day: str,
    bar_loader: Callable[[str, str], dict | None],
) -> tuple[float | None, list[str]]:
    value = state["cash"]
    missing = []
    for ticker, qty in state["inventory"].items():
        if qty <= 0:
            continue
        close = _number((bar_loader(ticker, day) or {}).get("close"))
        if close is None or close <= 0:
            missing.append(ticker)
            continue
        value += qty * close
    return (None if missing else round(value, 6), missing)


def _market_as_of_date(as_of: str | None, leg: str) -> str | None:
    """Convert a build timestamp to the leg's local market date."""
    if not as_of:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        return as_of
    parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        market = leg.lower()
        parsed = parsed.astimezone(ZoneInfo(trading_calendar.MARKET_TZ[market]))
    return parsed.date().isoformat()


def _expected_trading_dates(
    leg: str,
    start_date: str,
    end_date: str,
) -> list[str]:
    """Return every calendar-expected session, independent of bar availability."""
    market = leg.lower()
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    dates = []
    while current <= end:
        if trading_calendar.is_trading_day(market, current):
            dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def attribute_fills(events: list[dict], final_prices: dict[str, float]) -> dict:
    """Split the policy-vs-buy-and-hold gap into per-fill contributions.

    Both books start from the same seed and only the followed book trades, so
    the final gap is exactly the sum of what each fill did to it. For a fill of
    `q` shares against a final mark `P`:

        buy   →  q·P − notional   (paid `notional`, holds shares worth q·P)
        sell  →  notional − q·P   (banked `notional`, gave up q·P of stock)

    External cash flows are applied to both books and cancel; every traded
    ticker is still held by one of the two books at the end, so it always has a
    final mark. That makes this an identity, not an estimate — which is the
    whole point. `identity.residual` is published rather than absorbed: a
    non-zero residual means the simulation and this decomposition disagree, and
    that is information, not a rounding nuisance.

    Arithmetic only — no LLM, no re-simulation — so every number here is
    reproducible from the sidecar it ships in.

    Args:
        events: the `events` list from `simulate_leg`.
        final_prices: `{ticker: close}` on the final published mark date.

    Returns:
        JSON-safe dict of contributions grouped by driver, direction, execution
        status and ticker, plus turnover and the identity check.
    """
    by_driver: dict[str, float] = defaultdict(float)
    by_direction: dict[str, float] = defaultdict(float)
    by_execution: dict[str, float] = defaultdict(float)
    by_ticker: dict[str, dict] = {}
    unpriced: set[str] = set()
    sell_notional = buy_notional = 0.0
    filled_legs = 0
    total = 0.0

    for event in events:
        for leg_fill in event.get("legs") or []:
            qty = leg_fill.get("filled_shares") or 0
            if qty <= 0:
                continue
            ticker = str(leg_fill.get("ticker") or "")
            notional = _number(leg_fill.get("notional")) or 0.0
            filled_legs += 1
            if leg_fill.get("direction") == "sell":
                sell_notional += notional
            else:
                buy_notional += notional

            price = _number(final_prices.get(ticker))
            if price is None or price <= 0:
                # Never guess a mark: an unpriced ticker breaks the identity and
                # must say so instead of contributing a silent zero.
                unpriced.add(ticker)
                continue

            terminal = qty * price
            contribution = (
                notional - terminal if leg_fill.get("direction") == "sell"
                else terminal - notional
            )
            total += contribution
            by_driver[str(leg_fill.get("driven_by") or "unknown")] += contribution
            by_direction[str(leg_fill.get("direction") or "unknown")] += contribution
            by_execution[str(leg_fill.get("execution_status") or "unknown")] += contribution
            row = by_ticker.setdefault(
                ticker, {"ticker": ticker, "contribution": 0.0, "fills": 0,
                         "gross_notional": 0.0})
            row["contribution"] += contribution
            row["fills"] += 1
            row["gross_notional"] += notional

    ranked = sorted(
        ({**row, "contribution": round(row["contribution"], 2),
          "gross_notional": round(row["gross_notional"], 2)}
         for row in by_ticker.values()),
        key=lambda row: -abs(row["contribution"]),
    )
    return {
        "basis": "per-fill contribution to the final gap, marked to the same "
                 "canonical closes both books are marked to",
        "filled_legs": filled_legs,
        "total_contribution": round(total, 2),
        "by_driver": {k: round(v, 2) for k, v in sorted(by_driver.items())},
        "by_direction": {k: round(v, 2) for k, v in sorted(by_direction.items())},
        "by_execution_status": {k: round(v, 2) for k, v in sorted(by_execution.items())},
        "by_ticker": ranked,
        "turnover": {
            "sell_notional": round(sell_notional, 2),
            "buy_notional": round(buy_notional, 2),
            "gross_notional": round(sell_notional + buy_notional, 2),
        },
        "unpriced_tickers": sorted(unpriced),
    }


def _attribution_identity(attribution: dict, cumulative_diff) -> dict:
    """Does the decomposition reproduce the published gap?

    Tolerance is 1 currency unit: the curve is published rounded to cents and
    every fill contributes its own rounding. Anything larger is a real
    disagreement between the simulation and this decomposition, and it is
    published as `closes: false` rather than quietly rescaled to fit.
    """
    total = attribution.get("total_contribution")
    if cumulative_diff is None or total is None:
        return {"closes": None, "reason": "no published final point"}
    residual = round(float(cumulative_diff) - float(total), 2)
    closes = abs(residual) <= 1.0 and not attribution.get("unpriced_tickers")
    out = {
        "cumulative_diff": round(float(cumulative_diff), 2),
        "sum_of_contributions": round(float(total), 2),
        "residual": residual,
        "tolerance": 1.0,
        "closes": closes,
    }
    if attribution.get("unpriced_tickers"):
        out["reason"] = (
            "traded tickers without a final mark: "
            + ", ".join(attribution["unpriced_tickers"])
        )
    return out


def simulate_leg(
    portfolio: dict,
    decisions: list[dict],
    leg: str,
    *,
    start_date: str | None = None,
    as_of_date: str | None = None,
    bar_loader: Callable[[str, str], dict | None] = decision_v2.bar,
    bar_map_loader: Callable[[str], dict] = decision_v2.load_ticker_bars,
    matched: dict[str, dict] | None = None,
) -> dict | None:
    active = _active_triggered(decisions, leg)
    if not active:
        return None
    start_date = start_date or min(_event_session(row) for _, row in active)
    seed = reconstruct_initial_book(portfolio, leg, start_date)
    followed = {"cash": float(seed["cash"]), "inventory": deepcopy(seed["inventory"])}
    buy_hold = {"cash": float(seed["cash"]), "inventory": deepcopy(seed["inventory"])}
    matched = matched if matched is not None else decision_v2.match_real_executions(
        decisions, portfolio)

    by_session_group: dict[str, dict[str, list[tuple[int, dict]]]] = defaultdict(
        lambda: defaultdict(list))
    for ordinal, decision in active:
        if _event_session(decision) < start_date:
            continue
        group_id = str(
            decision.get("decision_group_id")
            or decision.get("decision_id")
            or f"ungrouped:{ordinal}"
        )
        by_session_group[_event_session(decision)][group_id].append((ordinal, decision))

    event_tickers = {
        str(decision.get("ticker") or "") for _, decision in active
    }
    tickers = set(seed["inventory"]) | event_tickers
    available_dates = {
        day
        for ticker in tickers
        for day in (bar_map_loader(ticker) or {})
        if day >= start_date
    }
    event_dates = {
        session for session in by_session_group if session >= start_date
    }
    end_date = as_of_date or max(
        available_dates | event_dates | {start_date})
    expected_dates = set(_expected_trading_dates(leg, start_date, end_date))
    # Event sessions remain replayable for backward compatibility with already
    # authored ledgers, but only calendar-expected sessions count toward mark
    # coverage.  Future events beyond the build's as-of date are never replayed.
    dates = sorted(expected_dates | {
        session for session in event_dates if session <= end_date
    })

    adjustments_by_date = defaultdict(list)
    ignored_corporate_actions = []
    for adjustment in _cash_adjustments(portfolio, leg):
        if adjustment["date"] < start_date:
            continue
        if adjustment["kind"] == "corporate_action":
            ignored_corporate_actions.append(adjustment)
        elif adjustment["kind"] in {"external_flow", "unclassified"}:
            adjustments_by_date[adjustment["date"]].append(adjustment)

    events = []
    fill_counts = Counter()
    unpaired_swap_like = 0
    swap_pattern = re.compile(r"(?:换仓|全换|换1x|换 1x|→)")
    for day in dates:
        for adjustment in adjustments_by_date.get(day, []):
            _apply_external_flow(followed, adjustment["amount"])
            _apply_external_flow(buy_hold, adjustment["amount"])

        groups = by_session_group.get(day) or {}
        ordered_groups = sorted(
            groups.items(),
            key=lambda item: min(ordinal for ordinal, _ in item[1]),
        )
        for group_id, indexed_rows in ordered_groups:
            indexed_rows.sort(
                key=lambda item: (
                    item[1].get("created_at") or "",
                    item[0],
                )
            )
            rows = [row for _, row in indexed_rows]
            fills = {
                row.get("decision_id"): _fill_for(row, matched, bar_loader)
                for row in rows
            }
            has_sell = any(row.get("action") in SELL_ACTIONS for row in rows)
            has_buy = any(row.get("action") in BUY_ACTIONS for row in rows)
            paired_swap = has_sell and has_buy
            if paired_swap:
                legs = _execute_swap_group(followed, rows, fills, portfolio)
            else:
                legs = []
                for row in rows:
                    fill = fills.get(row.get("decision_id"))
                    if not fill:
                        legs.append({
                            "ticker": row.get("ticker"),
                            "direction": (
                                "sell" if row.get("action") in SELL_ACTIONS else "buy"
                            ),
                            "requested_shares": _shares((row.get("size") or {}).get("shares")),
                            "filled_shares": 0,
                            "status": "skipped_no_fill_price",
                            "fill_type": "missing",
                            "fill_model": "none",
                            **_leg_provenance(row),
                        })
                        continue
                    if row.get("action") in SELL_ACTIONS:
                        legs.append(_execute_sell(followed, row, fill, portfolio))
                    else:
                        legs.append(_execute_buy(followed, row, fill, portfolio))
                if any(
                    swap_pattern.search(
                        " ".join([
                            str(row.get("rationale") or ""),
                            str((row.get("size") or {}).get("note") or ""),
                        ])
                    )
                    for row in rows
                ):
                    unpaired_swap_like += 1

            for leg_fill in legs:
                if leg_fill.get("filled_shares", 0) > 0:
                    fill_counts[leg_fill.get("fill_type") or "missing"] += 1
                else:
                    fill_counts["skipped"] += 1
            filled_legs = sum(leg_fill.get("filled_shares", 0) > 0 for leg_fill in legs)
            events.append({
                "date": day,
                "decision_group_id": group_id,
                "kind": "paired_swap" if paired_swap else "decision_group",
                "simulated": True,
                "execution_statuses": sorted({
                    str((row.get("execution") or {}).get("status") or "unknown")
                    for row in rows
                }),
                "status": (
                    "filled" if filled_legs == len(legs) and legs
                    else "partial" if filled_legs
                    else "skipped"
                ),
                "legs": legs,
            })

        followed_value, followed_missing = _mark(followed, day, bar_loader)
        baseline_value, baseline_missing = _mark(buy_hold, day, bar_loader)
        if followed_value is None or baseline_value is None:
            continue
        # A point is written only when both books use exact same-date closes.
        yield_point = {
            "date": day,
            "followed_sim": round(followed_value, 2),
            "buy_and_hold": round(baseline_value, 2),
            "cumulative_diff": round(followed_value - baseline_value, 2),
        }
        events[-1]["mark"] = yield_point if events and events[-1]["date"] == day else None

    # Re-mark in a simple second pass to keep the curve independent from event
    # serialization details and to include quiet sessions.
    followed = {"cash": float(seed["cash"]), "inventory": deepcopy(seed["inventory"])}
    buy_hold = {"cash": float(seed["cash"]), "inventory": deepcopy(seed["inventory"])}
    events_by_date = defaultdict(list)
    for event in events:
        events_by_date[event["date"]].append(event)
    curve = []
    missing_marks = []
    for day in dates:
        for adjustment in adjustments_by_date.get(day, []):
            _apply_external_flow(followed, adjustment["amount"])
            _apply_external_flow(buy_hold, adjustment["amount"])
        for event in events_by_date.get(day, []):
            for leg_fill in event["legs"]:
                qty = leg_fill.get("filled_shares") or 0
                if qty <= 0:
                    continue
                ticker = leg_fill["ticker"]
                notional = _number(leg_fill.get("notional")) or 0.0
                if leg_fill["direction"] == "sell":
                    followed["inventory"][ticker] = max(
                        0, followed["inventory"].get(ticker, 0) - qty)
                    followed["cash"] += notional
                else:
                    followed["inventory"][ticker] = (
                        followed["inventory"].get(ticker, 0) + qty)
                    followed["cash"] -= notional
        followed_value, followed_missing = _mark(followed, day, bar_loader)
        baseline_value, baseline_missing = _mark(buy_hold, day, bar_loader)
        missing = sorted(set(followed_missing) | set(baseline_missing))
        if missing:
            if day in expected_dates:
                required = {
                    ticker
                    for state in (followed, buy_hold)
                    for ticker, qty in state["inventory"].items()
                    if qty > 0
                }
                available = {
                    ticker for ticker in required
                    if (_number((bar_loader(ticker, day) or {}).get("close")) or 0) > 0
                }
                reason = "no_bar" if required and not available else "partial_coverage"
                missing_marks.append({
                    "date": day,
                    "reason": reason,
                    "tickers": missing,
                })
                curve.append({
                    "date": day,
                    "followed_sim": None,
                    "buy_and_hold": None,
                    "cumulative_diff": None,
                    "gap_reason": reason,
                })
            continue
        curve.append({
            "date": day,
            "followed_sim": round(followed_value, 2),
            "buy_and_hold": round(baseline_value, 2),
            "cumulative_diff": round(followed_value - baseline_value, 2),
        })

    published = [
        point for point in curve if point.get("cumulative_diff") is not None
    ]
    final_point = published[-1] if published else None
    final_diff = final_point["cumulative_diff"] if final_point else None

    # Attribution marks every fill to the same closes the final curve point uses,
    # so the buckets and the headline number cannot drift apart.
    traded_tickers = {
        str(leg_fill.get("ticker") or "")
        for event in events
        for leg_fill in event.get("legs") or []
        if (leg_fill.get("filled_shares") or 0) > 0
    }
    final_prices = {}
    if final_point:
        for ticker in traded_tickers:
            close = _number((bar_loader(ticker, final_point["date"]) or {}).get("close"))
            if close is not None:
                final_prices[ticker] = close
    attribution = attribute_fills(events, final_prices)
    attribution["as_of"] = final_point["date"] if final_point else None
    attribution["identity"] = _attribution_identity(attribution, final_diff)

    return {
        "leg": leg,
        "currency": LEG_CONFIG[leg]["currency"],
        "start_date": start_date,
        "end_date": final_point["date"] if final_point else None,
        "initial": seed,
        "curve": curve,
        "cumulative_diff": final_diff,
        "attribution": attribution,
        "final": {
            "followed_sim": final_point["followed_sim"] if final_point else None,
            "buy_and_hold": final_point["buy_and_hold"] if final_point else None,
        },
        "events": events,
        "counts": {
            "triggered_active_decisions": len(active),
            "decision_groups": len(events),
            "paired_swap_groups": sum(event["kind"] == "paired_swap" for event in events),
            "unpaired_swap_like_groups": unpaired_swap_like,
            "fill_types": {
                "real_trade": fill_counts["real_trade"],
                "ohlc_assumption": fill_counts["ohlc_assumption"],
                "canonical_close_fallback": fill_counts["canonical_close_fallback"],
                "skipped": fill_counts["skipped"],
            },
        },
        "mark_coverage": {
            "expected_sessions": len(expected_dates),
            "published_points": len(published),
            "skipped_dates": missing_marks,
            "rule": "publish only when both books can be marked to exact same-date canonical closes",
        },
        "corporate_actions": {
            "applied": [],
            "ignored_detected_cash_adjustments": ignored_corporate_actions,
        },
    }


def build_shadow_portfolio(
    portfolio: dict,
    decisions: list[dict],
    *,
    as_of: str | None = None,
    start_dates: dict[str, str] | None = None,
    bar_loader: Callable[[str, str], dict | None] = decision_v2.bar,
    bar_map_loader: Callable[[str], dict] = decision_v2.load_ticker_bars,
    matched: dict[str, dict] | None = None,
) -> dict:
    """Build the public sidecar. USD and HKD are intentionally never combined."""
    as_of = as_of or datetime.now().astimezone().isoformat(timespec="seconds")
    matched = matched if matched is not None else decision_v2.match_real_executions(
        decisions, portfolio)
    curves = {}
    for leg in ("US", "HK"):
        result = simulate_leg(
            portfolio,
            decisions,
            leg,
            start_date=(start_dates or {}).get(leg),
            as_of_date=_market_as_of_date(as_of, leg),
            bar_loader=bar_loader,
            bar_map_loader=bar_map_loader,
            matched=matched,
        )
        if result:
            curves[result["currency"]] = result
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "label": "模拟·非实盘",
        "estimand": (
            "跟随全部已触发主动建议的政策模拟净值，相对同起点、同日收盘计价的"
            "买入持有基线；累计差为模拟 timing alpha"
        ),
        "curves": curves,
        "cumulative_diff": {
            currency: result["cumulative_diff"]
            for currency, result in curves.items()
        },
        "fill_counts": {
            kind: sum(
                result["counts"]["fill_types"][kind] for result in curves.values()
            )
            for kind in (
                "real_trade", "ohlc_assumption",
                "canonical_close_fallback", "skipped",
            )
        },
        "fx_policy": {
            "combined_curve": False,
            "reason": "USD and HKD are separate; no naked cross-currency addition",
            "daily_fx_required_for_combination": True,
            "today_fx_for_history_forbidden": True,
        },
        "methodology": {
            "books": "two independent cash+inventory ledgers with identical reconstructed seeds",
            "action_scope": "every triggered active decision, including execution.status=not_followed",
            "ordering": "trigger session, then authored created_at, then ledger order",
            "constraints": "sell capped by live inventory; buy capped by live cash; prior legs mutate the next leg",
            "swaps": (
                "sell+buy rows sharing decision_group_id are one paired group; only sale proceeds "
                "fund the target and target shares are price/lot-derived"
            ),
            "fills": (
                "strict unique portfolio trade when available; otherwise evaluation.execution_price "
                "OHLC assumption; otherwise same-session canonical close"
            ),
            "marks": "both books marked on the same date using exact canonical raw close",
            "baseline": "same initial holdings and cash, no strategy actions",
            "external_flows": "identified deposits/withdrawals applied equally to both books",
            "right_censoring": (
                "mark-to-latest-bar: older suggestions have longer observation windows; "
                "published points are frozen to each bar date, while future builds append/recompute "
                "only from canonical dated inputs"
            ),
        },
        "limitations": [
            (
                "Policy simulation, not broker performance: unexecuted advice is intentionally "
                "simulated and must never be described as live/real-account alpha."
            ),
            (
                "Canonical bars are unadjusted. No authoritative split/dividend event feed is "
                "available; detected dividend-like cash adjustments are disclosed but not allocated "
                "to simulated share counts, so the long-hold baseline may be biased."
            ),
            (
                "Initial state is reconstructed backward from portfolio.json trades/cash adjustments; "
                "missing trades, fees, taxes or unclassified cash flows can bias both books."
            ),
            (
                "Daily OHLC cannot recover intraday ordering. Same-session groups follow authored "
                "created_at/ledger order; only a shared decision_group_id creates a paired swap."
            ),
            (
                "Current historical rows without a shared swap decision_group_id are not inferred "
                "from prose and remain independent cash-constrained actions."
            ),
            (
                "USD and HKD stay separate. A combined curve would require point-in-time daily FX, "
                "which this sidecar deliberately does not synthesize."
            ),
        ],
    }


def write_shadow_portfolio(
    portfolio: dict,
    decisions: list[dict],
    out_path: Path | str = OUT,
    **kwargs,
) -> dict:
    result = build_shadow_portfolio(portfolio, decisions, **kwargs)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from clawock.safe_io import safe_write_text
        safe_write_text(
            str(path), json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except ImportError:
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


def main() -> int:
    portfolio_path = WS / "portfolio.json"
    if not portfolio_path.exists():
        raise SystemExit("portfolio.json missing")
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    decisions = decision_v2.load_decisions()
    decision_v2.settle_decisions(decisions)
    out_path = Path(os.environ.get("SHADOW_PORTFOLIO_OUT") or OUT)
    result = write_shadow_portfolio(portfolio, decisions, out_path)
    points = sum(
        (book.get("mark_coverage") or {}).get("published_points", 0)
        for book in result["curves"].values()
    )
    print(f"✓ wrote {out_path} ({points} marked points; 模拟·非实盘)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
