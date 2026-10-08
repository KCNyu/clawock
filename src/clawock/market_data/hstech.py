"""Tencent HSTECH daily closes shared by live decisions and evaluations."""
from datetime import date

import requests

TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'


def fetch_hstech(start='2021-01-01', end=None, lim=2000):
    """Return dated closes, skipping malformed rows; transport errors propagate."""
    end = end or date.today().isoformat()
    url = f'{TENCENT}?param=hkHSTECH,day,{start},{end},{lim}'
    payload = requests.get(url, timeout=20).json()
    rows = (payload.get('data') or {}).get('hkHSTECH', {})
    out = []
    for row in rows.get('day') or rows.get('qfqday') or []:
        try:
            out.append((row[0], float(row[2])))
        except (IndexError, ValueError, TypeError):
            continue
    return out
