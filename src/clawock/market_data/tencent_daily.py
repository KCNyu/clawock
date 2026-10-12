"""Tencent dated daily closes with one malformed-row policy."""
from datetime import date

import requests

from .daily_prices import clean_bars, positive_price

TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'


def parse_daily_closes(rows):
    """Skip unusable close cells; keep the provider's dates and valid closes."""
    out = []
    for row in rows:
        try:
            close = positive_price(row[2])
            if close is not None:
                out.append((row[0], close))
        except (IndexError, ValueError, TypeError, KeyError):
            continue
    return out


def parse_daily_bars(rows):
    """Tencent [date, open, close, high, low, ...] using the daily-price policy."""
    out = []
    for row in rows:
        try:
            out.append({'date': row[0], 'open': row[1], 'close': row[2],
                        'high': row[3], 'low': row[4]})
        except (IndexError, ValueError, TypeError, KeyError):
            continue
    return clean_bars(out)


def fetch_hk_daily_closes(sym, start, end=None, lim=2000, *, headers=None,
                          adjusted_first=False):
    """Return dated HK closes; transport errors propagate to the caller."""
    end = end or date.today().isoformat()
    url = f'{TENCENT}?param={sym},day,{start},{end},{lim}'
    kwargs = {'timeout': 20}
    if headers is not None:
        kwargs['headers'] = headers
    payload = requests.get(url, **kwargs).json()
    node = (payload.get('data') or {}).get(sym, {})
    keys = ('qfqday', 'day') if adjusted_first else ('day', 'qfqday')
    return parse_daily_closes(node.get(keys[0]) or node.get(keys[1]) or [])


TENCENT_ADJUSTED = 'https://web.ifzq.gtimg.cn/appstock/app/{market}fqkline/get'


def fetch_adjusted_daily_bars(sym, count=800, *, headers=None):
    """(bars, adjusted) from the per-market forward-adjusted endpoint.

    `adjusted` is True only when the provider answered under `qfqday`. The
    market-less `fqkline/get` path answers the same request under `day` with
    raw prices, so the key is read as the provider's own statement of what it
    sent rather than assumed from the request. Transport errors propagate.
    """
    market = sym[:2]
    if market not in ('hk', 'us'):
        raise ValueError(f'no adjusted daily endpoint for {sym!r}')
    url = f'{TENCENT_ADJUSTED.format(market=market)}?param={sym},day,,,{count},qfq'
    kwargs = {'timeout': 20}
    if headers is not None:
        kwargs['headers'] = headers
    payload = requests.get(url, **kwargs).json()
    node = (payload.get('data') or {}).get(sym) or {}
    adjusted = bool(node.get('qfqday'))
    return parse_daily_bars(node.get('qfqday') or node.get('day') or []), adjusted
