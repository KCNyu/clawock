"""One shared contract for "is this bar believable", used by every fetcher.

Why this exists
---------------
Each fetcher grew its own idea of a bad bar, and the strongest check ended up
guarding the weakest place:

* `fetch_daily_bars.sane()` — the gate on the **canonical** store the decision
  ledger settles against — only checked ordering (`low <= open,close <= high`,
  positive prices). A bar where `open == high == low == close` passes that
  cleanly.
* `fetch_us_stocks` has warned about exactly that shape mid-session since the
  2026-05-29 stale-quote swap, because a provider that manufactures it is how
  the US zero-change bug happened.
* `analyze_hk_stocks` carries a third rule: the live price must fall inside the
  same quote's own `[low, high]`, after a provider bad tick put 03033 below its
  day range while its 2x sibling moved the other way.

Three detectors, three files, no shared definition — so the canonical store
accepted the very shape the live path alarms on.

What is shared, and what is not
-------------------------------
**Detection** is shared: this module decides what is structurally impossible and
what is merely suspicious. **Policy** stays with the caller, because it really
does differ — a degenerate bar is a bug in a live regular-session quote and is
perfectly legitimate for a halted or untraded session.

Findings are graded:

* `fatal` — the bar cannot be true of any real session (close outside
  `[low, high]`, non-positive price, a non-finite number). Callers reject.
* `flags` — the bar may be true but is worth carrying forward
  (`degenerate_range`, `implausible_move`, `stale_session`). Callers record and
  surface; they must not silently drop the bar, and they must not silently
  invent a range for it either.

Stdlib only, no I/O: every fetcher imports this, including the ones that run
before numpy is available.
"""
from __future__ import annotations

import math

# Scripts that ingest bars or quotes and must route detection through this
# module. `tests/test_bar_checks.py` fails when one of them stops importing it,
# so a future fetcher cannot quietly re-grow a private copy of these rules.
BAR_CONSUMERS = (
    'fetch_daily_bars.py',
    'fetch_us_stocks.py',
    'analyze_hk_stocks.py',
)

# A live quote may sit this far outside its own reported [low, high] before it
# counts as a bad tick — absolute floor plus a relative term, so a HK$0.5 name
# is not flagged by rounding alone. Taken from the existing analyze_hk_stocks
# guard so behaviour there is unchanged.
RANGE_TOLERANCE_ABS = 0.005
RANGE_TOLERANCE_REL = 0.002

# Session-over-session move beyond this is flagged, never rejected: real names
# do move 50% on a takeover. It is here so one definition covers every market.
IMPLAUSIBLE_MOVE_PCT = 50.0

_OHLC_KEYS = ('open', 'high', 'low', 'close')


def _finite_number(value):
    """Return the value as a finite float, or None if it is not one."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def range_tolerance(price: float) -> float:
    """Absolute tolerance allowed when testing a price against a quoted range."""
    return max(RANGE_TOLERANCE_ABS, abs(price) * RANGE_TOLERANCE_REL)


def is_degenerate(bar) -> bool:
    """True when open == high == low == close.

    Not an error on its own. It is what a halted or never-traded session looks
    like, and it is also what a frozen provider quote looks like — which is why
    the caller, not this function, decides what to do about it.
    """
    values = [_finite_number(bar.get(k)) for k in _OHLC_KEYS]
    if any(v is None for v in values):
        return False
    return values[0] == values[1] == values[2] == values[3]


def check_bar(bar, *, prev_close=None, session_date=None, last_closed=None):
    """Grade one OHLC bar. Returns `{'fatal': [...], 'flags': [...]}`.

    Args:
        bar: mapping with `open`/`high`/`low`/`close`, optionally `date`.
        prev_close: previous session's close, for the move check.
        session_date: the session this bar claims to belong to; compared with
            `bar['date']` when both are present.
        last_closed: newest session that has finished. A bar dated after it is
            a live bar wearing a completed session's clothes.
    """
    fatal: list[str] = []
    flags: list[str] = []

    values = {}
    for key in _OHLC_KEYS:
        value = _finite_number(bar.get(key))
        if value is None:
            fatal.append(f'{key} is missing or not a finite number: {bar.get(key)!r}')
        else:
            values[key] = value

    if len(values) == len(_OHLC_KEYS):
        low, high = values['low'], values['high']
        if low > high:
            fatal.append(f'low {low} above high {high}')
        for key in ('open', 'close'):
            if not (low <= values[key] <= high):
                fatal.append(f'{key} {values[key]} outside [{low}, {high}]')
        if low <= 0 or high <= 0:
            fatal.append(f'non-positive price in [{low}, {high}]')

        if not fatal and is_degenerate(bar):
            flags.append('degenerate_range')

        previous = _finite_number(prev_close)
        if previous and previous > 0 and not fatal:
            move_pct = abs(values['close'] / previous - 1) * 100
            if move_pct > IMPLAUSIBLE_MOVE_PCT:
                flags.append(f'implausible_move {move_pct:.1f}%')

    bar_date = bar.get('date')
    if bar_date and session_date and str(bar_date)[:10] != str(session_date)[:10]:
        flags.append(f'session_mismatch bar={bar_date} session={session_date}')
    if bar_date and last_closed and str(bar_date)[:10] > str(last_closed)[:10]:
        flags.append(f'unfinished_session bar={bar_date} last_closed={last_closed}')

    return {'fatal': fatal, 'flags': flags}


def is_structurally_sane(bar) -> bool:
    """The old `fetch_daily_bars.sane()` predicate, now one call site of many."""
    return not check_bar(bar)['fatal']


def price_outside_quoted_range(price, low, high):
    """Reason string when a live price falls outside its own quote's range.

    Same-quote comparison only: a stored `day_low`/`day_high` from an earlier
    fetch is a different vintage and cannot judge this print.
    """
    price = _finite_number(price)
    low = _finite_number(low)
    high = _finite_number(high)
    if price is None or low is None or high is None:
        return None
    if low <= 0 or high <= 0:
        return None
    tol = range_tolerance(price)
    if price < low - tol:
        return f'{price} below quoted low {low}'
    if price > high + tol:
        return f'{price} above quoted high {high}'
    return None


def gap_safe_returns(bars, *, skip_degenerate: bool = True):
    """Close-to-close returns with halted sessions omitted, not zeroed.

    A halted or untraded session has no return to observe. Emitting `0.0` for it
    — which is what forward-filling a close does — is not a neutral choice: it
    injects a zero-variance observation and deflates realised volatility, and
    volatility is an input to the leverage dial. Omitting the session says "no
    observation" instead of "the price did not move".

    Args:
        bars: date-ordered sequence of bar mappings, or a `{date: bar}` mapping.
        skip_degenerate: drop sessions whose OHLC has collapsed to one price.

    Returns:
        List of `(date, return)` pairs. The return spans whatever gap the
        omissions leave, so it stays a true close-to-close move.
    """
    if isinstance(bars, dict):
        ordered = [dict(bar, date=date) for date, bar in sorted(bars.items())]
    else:
        ordered = list(bars)

    usable = []
    for bar in ordered:
        close = _finite_number(bar.get('close'))
        if close is None or close <= 0:
            continue
        if skip_degenerate and is_degenerate(bar):
            continue
        usable.append((bar.get('date'), close))

    out = []
    for (_, previous), (date, close) in zip(usable, usable[1:]):
        out.append((date, close / previous - 1))
    return out
