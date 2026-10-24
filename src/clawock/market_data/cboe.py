"""Official daily volatility closes; observations, not intraday spot quotes.

Public CSVs require no key. Keep the observation date and reject a lagging
series rather than stamping an old close with the time of this download.
"""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone

import requests

from clawock.sessions import latest_completed_session

BASE = 'https://cdn.cboe.com/api/global/us_indices/daily_prices'
SYMBOLS = ('VIX', 'VIX9D', 'VIX3M', 'SKEW')


def parse_history(text, symbol, *, at=None):
    """Latest completed US session, with a genuine prior session close if present."""
    if symbol not in SYMBOLS:
        raise ValueError(f'unsupported Cboe series: {symbol}')
    expected = latest_completed_session('us', at or datetime.now(timezone.utc))
    if expected is None:
        return None
    rows = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            day = datetime.strptime(row['DATE'], '%m/%d/%Y').date()
            value = float(row['SKEW' if symbol == 'SKEW' else 'CLOSE'])
        except (KeyError, TypeError, ValueError):
            continue
        if day <= expected and math.isfinite(value) and value > 0:
            rows[day] = value
    if expected not in rows:
        return None
    # A missing intervening session must not become a multi-day daily change.
    from clawock.sessions import previous_trading_day
    previous = previous_trading_day('us', expected)
    prior = rows.get(previous)
    return {
        'symbol': symbol, 'price': rows[expected], 'prev': prior,
        'change_pct': (round((rows[expected] / prior - 1) * 100, 2)
                       if prior and rows[expected] != prior else None),
        'source': 'cboe', 'as_of': expected.isoformat(),
        'previous_as_of': previous.isoformat() if prior else None,
        'frequency': 'daily_close', 'url': f'{BASE}/{symbol}_History.csv',
    }


def fetch_quote(symbol, *, at=None):
    if symbol not in SYMBOLS:
        raise ValueError(f'unsupported Cboe series: {symbol}')
    try:
        response = requests.get(f'{BASE}/{symbol}_History.csv', timeout=10,
                                headers={'User-Agent': 'clawock-macro/1.0'})
        response.raise_for_status()
        return parse_history(response.text, symbol, at=at)
    except (requests.RequestException, ValueError):
        return None


def term_structure(vix, vix3m):
    """Same-session short/medium implied-volatility ratio; no signal thresholds."""
    if not vix or not vix3m or vix.get('as_of') != vix3m.get('as_of'):
        return None
    return {'vix_to_vix3m': round(vix['price'] / vix3m['price'], 4),
            'as_of': vix['as_of'], 'source': 'cboe', 'frequency': 'daily_close'}
