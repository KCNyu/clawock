"""Read-side session keys for legacy setup and factor histories.

Explicit source dates win. Legacy wall-clock labels move only when a nearby,
not-future local daily bar corroborates the recorded close; drifting holiday
quotes keep their original label and remain subject to the closed-session gate.
No history or bar file is rewritten and no network request is made.
"""
from datetime import date, datetime, timedelta
import math

from clawock import instruments, sessions
from clawock.market_data import bars


def normalize_days(records):
    """Last logged row per ticker/source session, preserving legacy fallbacks."""
    cached = {}
    by_day = {}
    for record in records:
        fallback = record.get('as_of')
        if not fallback:
            continue
        for ticker, row in (record.get('rows') or {}).items():
            explicit = row.get('session_date') or row.get('row_as_of')
            key = explicit or fallback
            if not explicit:
                if ticker not in cached:
                    try:
                        cached[ticker] = bars.load_bars(ticker).get('bars') or {}
                    except (OSError, ValueError, TypeError):
                        cached[ticker] = {}
                key = _legacy_key(record, ticker, row, cached[ticker]) or fallback
            by_day.setdefault(key, {})[ticker] = row
    return [{'as_of': day, 'rows': by_day[day]} for day in sorted(by_day)]


def _legacy_key(record, ticker, row, daily_bars):
    try:
        market = instruments.market_for_symbol(ticker)
        upper = date.fromisoformat(record['as_of'][:10])
        if record.get('ts'):
            at = datetime.fromisoformat(record['ts'].replace('Z', '+00:00'))
            if at.tzinfo is None:
                return None  # An unzoned clock does not prove a market date.
            upper = at.astimezone(sessions.market_tz(market)).date()
        close = float(row['close'])
        if not math.isfinite(close) or close <= 0:
            return None
        # A recent exact price match is evidence; a distant coincidental match
        # is not. The existing frozen-price and closed-session gates still apply.
        for offset in range(8):
            day = upper - timedelta(days=offset)
            bar = daily_bars.get(day.isoformat()) or {}
            if (sessions.is_trading_day(market, day)
                    and math.isclose(close, float(bar.get('close', 0)), rel_tol=0, abs_tol=1e-8)):
                return day.isoformat()
    except (KeyError, TypeError, ValueError):
        pass
    return None
