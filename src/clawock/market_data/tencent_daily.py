"""Tencent dated daily closes with one malformed-row policy."""
from datetime import date

import requests

TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'


def parse_daily_closes(rows):
    """Skip unusable close cells; keep the provider's dates and valid closes."""
    out = []
    for row in rows:
        try:
            out.append((row[0], float(row[2])))
        except (IndexError, ValueError, TypeError, KeyError):
            continue
    return out


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
