"""Point-in-time realized P&L for a historical snapshot.

`clawock realized` sums *every* trade in portfolio.json — correct for the
live portfolio, but wrong for a dated snapshot, where realized must reflect only
the sells that had already settled into that snapshot's holdings. Crediting a
sell too early inflates equity; crediting it too late deflates it.

The canonical portfolio.json `trades[]` ledger is the single source of truth.
A sell is "reflected" in a snapshot when:
  * sell.date <  snapshot.date                              (settled on a prior day), OR
  * sell.date == snapshot.date AND snapshot_shares <= post_sell_balance
    (same-day tie broken by the snapshot's own share count — handles the
     a morning snapshot taken before that day's later market session).

The same-day share check uses the running balance *after* the sell, so a sell is
only counted once the holding has actually been drawn down to (or below) it. The
strict date-`<` branch handles later sell→rebuy cycles without false negatives.
"""
from datetime import date as _date


def _ledger_sells(holdings):
    """Per-ticker chronological sells, each tagged with its post-sell balance.

    Returns {ticker: [ {date, shares, price, realized_pnl, post_bal, seq}, ... ]}.
    `seq` preserves array order so same-date trades replay deterministically.
    """
    by_ticker = {}
    for h in holdings or []:
        ticker = h.get('ticker', '?')
        bal = 0.0
        sells = []
        # Stable order: by (date, original index) so same-day buy-before-sell holds.
        trades = list(enumerate(h.get('trades', []) or []))
        trades.sort(key=lambda it: (it[1].get('date', ''), it[0]))
        for seq, t in trades:
            shares = t.get('shares', 0) or 0
            if t.get('action') == 'buy':
                bal += shares
            else:  # sell (or any realizing action)
                bal -= shares
                if t.get('realized_pnl') is not None:
                    sells.append({
                        'date': t.get('date', ''),
                        'ticker': ticker,
                        'shares': shares,
                        'price': t.get('price', 0),
                        'realized_pnl': t['realized_pnl'],
                        'post_bal': bal,
                    })
        if sells:
            by_ticker[ticker] = sells
    return by_ticker


def session_date(market, day):
    """The trading session a fill belongs to, given the date it was recorded.

    A ledger date is the operator's calendar date. A US session in Hong Kong
    time runs 21:30 to 04:00, so a fill reported at 01:08 HKT on a Saturday
    belongs to *Friday's* session and is stamped with Saturday's date. Comparing
    that raw date against a snapshot named for the session drops the fill from
    the very session that contains it.

    Only non-session dates move, and only when the calendar covers that year —
    a real session date, an unknown market, or a year the holiday tables do not
    reach is returned unchanged rather than guessed at.
    """
    if not market or not isinstance(day, str) or len(day) != 10:
        return day
    from clawock.sessions import (
        MARKET_TZ, covered_years, is_trading_day, previous_trading_day,
    )
    if market not in MARKET_TZ:
        return day
    try:
        parsed = _date.fromisoformat(day)
    except ValueError:
        return day
    if parsed.year not in covered_years(market) or is_trading_day(market, parsed):
        return day
    return previous_trading_day(market, parsed).isoformat()


def realized_as_of(holdings, snap_date, snap_shares, *, market=None):
    """Cumulative realized + chronological note reflected in a snapshot.

    holdings    — canonical portfolio.json region holdings (the ledger).
    snap_date   — 'YYYY-MM-DD' of the snapshot.
    snap_shares — {ticker: shares} recorded in that snapshot (0 if absent).
    market      — calendar to resolve fill dates against ('us'/'hk'). Omitted
                  means the raw ledger dates are compared, which is only right
                  for a market whose session cannot cross a date boundary in the
                  operator's timezone.
    """
    by_ticker = _ledger_sells(holdings)
    reflected = []
    for ticker, sells in by_ticker.items():
        held = snap_shares.get(ticker, 0) or 0
        for s in sells:
            when = session_date(market, s['date'])
            # A negative post-sell balance means this holding's trade list is
            # missing a buy (RKLB records a 5-share sell with no buy beside it),
            # so the level is offset by a constant nobody can recover. Shares
            # cannot be negative, so the drawn-down test is read at zero rather
            # than against an impossible balance — which would otherwise drop a
            # real, fully-closed sell from the session that contains it.
            drawn_down = max(s['post_bal'], 0)
            if when < snap_date or (when == snap_date and held <= drawn_down):
                reflected.append(s)

    reflected.sort(key=lambda x: (x['date'], x['ticker']))
    total = round(sum(s['realized_pnl'] for s in reflected), 2)
    parts = [
        f"{s['ticker']} {s['shares']}股@{s['price']:g}({s['realized_pnl']:+g})"
        for s in reflected
    ]
    return total, ' + '.join(parts)


def snapshot_shares(region_pf):
    """{ticker: shares} from a snapshot region's holdings."""
    out = {}
    for h in region_pf.get('holdings', []) or []:
        tk = h.get('ticker')
        if tk:
            out[tk] = h.get('shares', 0) or 0
    return out
