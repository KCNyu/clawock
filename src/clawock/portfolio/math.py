"""Pure portfolio-ledger arithmetic shared by validation and reconciliation."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from datetime import date
import re


def number(value: Any) -> float | None:
    """Return a numeric ledger value as float, or None when it is unusable."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ledger_date(value: Any) -> str:
    """A hand-entered ledger date, or '' (undated) when it is not a string.

    `get("date", "")` only covers a missing key; a present null or a number
    reaches the comparisons and sorts below and raises, taking the integrity
    gate and the dashboard build down with it (#2171, #2179). Not `str()`:
    `str(20260929) > "2026-09-29"` would put an adjustment in the wrong window.
    """
    return value if isinstance(value, str) else ""


def active_holdings(holdings: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Holdings with a strictly positive numeric share balance."""
    return [holding for holding in ledger_rows(holdings)
            if (number(holding.get("shares")) or 0) > 0]


def moving_average_cost(trades: Iterable[Mapping[str, Any]]) -> tuple[float | None, float]:
    """Replay buys/sells and return the remaining moving-average cost and shares."""
    shares = 0.0
    cost = 0.0
    ordered = sorted(enumerate(ledger_rows(list(trades))), key=lambda item: (
        ledger_date(item[1].get("date")), item[0]))
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


def ledger_rows(rows: Any) -> list[Mapping[str, Any]]:
    """The object rows of a hand-entered ledger list (`holdings`, `trades`, `cash_adjustments`).

    One row that is not a JSON object used to raise in every reader and take the
    whole money gate down with it (#2273). Readers skip it; `integrity.check`
    names it as `LEDGER_ROW_INVALID`, so the skip is never silent.
    """
    return [row for row in (rows or []) if isinstance(row, Mapping)] \
        if isinstance(rows, (list, tuple)) else []


def trade_cashflow_after(
    holdings: Iterable[Mapping[str, Any]], after_date: str,
) -> tuple[float, int]:
    """Cash flow from trades strictly after an ISO reconciliation date."""
    flow = 0.0
    count = 0
    for holding in ledger_rows(holdings):
        for trade in ledger_rows(holding.get("trades")):
            trade_date = ledger_date(trade.get("date"))
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
    for adjustment in ledger_rows(book.get("cash_adjustments")):
        adjustment_date = ledger_date(adjustment.get("date"))
        if adjustment_date and adjustment_date > baseline_date:
            adjustments += number(adjustment.get("amount")) or 0
    return round(baseline + flow + adjustments, 2), baseline, baseline_date, count


_MONTHS = {m: i for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
_ASOF_RE = re.compile(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})(?:,\s*(\d{4}))?')


def holding_session(h, snapshot_date, market=None):
    """The market session one holding's quote belongs to, or None.

    The row's own `day_session_date` (written by the US fetcher) wins. Otherwise
    the date is read off `data_source`, which is the FETCH time: fetchers run on
    closed days too, so a date the market did not trade is folded back to the
    last session that did (#2269). `market` None keeps the raw stamp.
    """
    market = {'us_stocks': 'us', 'hk_stocks': 'hk'}.get(market, market)
    own = h.get('day_session_date')
    if isinstance(own, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', own):
        return own
    m = _ASOF_RE.search(h.get('data_source') or '')
    if not m:
        return None
    mon, day = _MONTHS[m.group(1)], int(m.group(2))
    raw_date = str(snapshot_date or '').replace('/', '-')
    if len(raw_date) < 4:
        return None
    yr = int(m.group(3) or raw_date[:4])
    if not m.group(3) and len(raw_date) >= 10:
        anchor = date.fromisoformat(raw_date[:10])
        candidates = []
        for candidate_year in (yr - 1, yr, yr + 1):
            try:
                candidate = date(candidate_year, mon, day)
            except ValueError:
                continue
            if candidate <= anchor:
                candidates.append(candidate)
        if candidates:
            yr = max(candidates).year
    try:
        stamped = date(yr, mon, day)
    except ValueError:
        return None
    if market:
        from clawock import sessions as _tc
        try:
            if _tc.closed_reason(market, stamped) is not None:
                stamped = _tc.previous_trading_day(market, stamped)
        except Exception:
            pass
    return stamped.isoformat()



def day_pnl(holding: Mapping[str, Any], session: str | None, *, current=None) -> tuple[float, float]:
    """Day P&L of the remaining position and its matching reference capital.

    Old shares start at prior close; shares bought in this quote session start
    at their fill. Replay same-session sells oldest first so a buy/sell/rebuy
    does not count sold shares as a remaining new lot. Realized sells remain
    in the realized ledger, outside this mark of the currently held position.
    """
    shares = number(holding.get('shares')) or 0
    current = number(holding.get('current_price') if current is None else current) or 0
    prev = number(holding.get('prev_close')) or 0
    trades = [t for t in ledger_rows(holding.get('trades'))
              if session and ledger_date(t.get('date')) == session
              and t.get('action') in ('buy', 'sell')
              and (number(t.get('shares')) or 0) > 0
              and number(t.get('price')) is not None]
    bought = sum(number(t.get('shares')) for t in trades if t.get('action') == 'buy')
    sold = sum(number(t.get('shares')) for t in trades if t.get('action') == 'sell')
    old = max(0, shares - bought + sold)
    lots = []
    for trade in trades:
        quantity = number(trade.get('shares'))
        if trade.get('action') == 'buy':
            lots.append([quantity, number(trade.get('price'))])
        else:
            from_old = min(old, quantity)
            old -= from_old
            quantity -= from_old
            for lot in lots:
                taken = min(lot[0], quantity)
                lot[0] -= taken
                quantity -= taken
    # An incomplete opening ledger cannot create more marked shares than held.
    remaining = shares
    new_base = new_shares = 0
    for quantity, price in reversed(lots):
        used = min(remaining, quantity)
        new_base += used * price
        new_shares += used
        remaining -= used
    base = (shares - new_shares) * prev + new_base
    return shares * current - base, base
