"""Pure portfolio-ledger arithmetic shared by validation and reconciliation."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def number(value: Any) -> float | None:
    """Return a numeric ledger value as float, or None when it is unusable."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def active_holdings(holdings: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Holdings with a strictly positive numeric share balance."""
    return [holding for holding in holdings
            if (number(holding.get("shares")) or 0) > 0]


def moving_average_cost(trades: Iterable[Mapping[str, Any]]) -> tuple[float | None, float]:
    """Replay buys/sells and return the remaining moving-average cost and shares."""
    shares = 0.0
    cost = 0.0
    ordered = sorted(enumerate(trades), key=lambda item: (
        item[1].get("date", ""), item[0]))
    for _, trade in ordered:
        quantity = number(trade.get("shares")) or 0
        price = number(trade.get("price")) or 0
        action = trade.get("action")
        if action == "buy":
            shares += quantity
            cost += quantity * price
        elif action == "sell":
            if shares > 0:
                cost -= quantity * (cost / shares)
            shares -= quantity
    return (cost / shares if shares else None), shares


def trade_cashflow_after(
    holdings: Iterable[Mapping[str, Any]], after_date: str,
) -> tuple[float, int]:
    """Cash flow from trades strictly after an ISO reconciliation date."""
    flow = 0.0
    count = 0
    for holding in holdings or []:
        for trade in holding.get("trades", []) or []:
            trade_date = trade.get("date", "")
            if not trade_date or trade_date <= after_date:
                continue
            quantity = number(trade.get("shares")) or 0
            price = number(trade.get("price")) or 0
            if trade.get("action") == "sell":
                flow += quantity * price
            elif trade.get("action") == "buy":
                flow -= quantity * price
            else:
                continue
            count += 1
    return flow, count


def derive_cash(book: Mapping[str, Any]) -> tuple[float, float, str, int] | None:
    """Cash from a reconciled baseline, later trades, and later adjustments."""
    baseline = number(book.get("cash_reconciled"))
    baseline_date = book.get("cash_reconciled_date")
    if baseline is None or not isinstance(baseline_date, str) or not baseline_date:
        return None
    flow, count = trade_cashflow_after(book.get("holdings", []), baseline_date)
    adjustments = 0.0
    for adjustment in book.get("cash_adjustments", []) or []:
        adjustment_date = adjustment.get("date", "")
        if adjustment_date and adjustment_date > baseline_date:
            adjustments += number(adjustment.get("amount")) or 0
    return round(baseline + flow + adjustments, 2), baseline, baseline_date, count
