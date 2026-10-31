"""Bounded HK ordinary-share discovery using the desk's Tencent quote route.

Raw fields stay in memory. This adapter makes no claim of a vendor license.
"""
from datetime import datetime
import re

import requests

from clawock.safe_io import to_finite_number
from clawock.sessions import HKT, HK_HALF_DAYS, latest_completed_session

SOURCE = {"source_id": "tencent_hk", "source_name": "Tencent qt.gtimg.cn",
          "metadata_source": "config/hk-discovery-universe.json"}


def fetch_quotes(codes):
    """One bounded batch on the existing HK quote endpoint; no raw cache."""
    response = requests.get('https://qt.gtimg.cn/q=' + ','.join('r_hk' + c for c in codes),
                            timeout=(5, 12), stream=True)
    with response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_content(16384):
            raw.extend(chunk)
            if len(raw) > 1024 * 1024:
                raise ValueError('quote response exceeds byte budget')
    return raw.decode('gbk')


def parse_quotes(text, universe, now):
    """HK wire: 3 price, 32 change %, 37 turnover HKD, 45 cap in HKD 100m."""
    session = latest_completed_session('HK', at=now)
    if session is None:
        raise ValueError('unknown HK session')
    rows, stamps, failed = {}, {}, {}
    close_hour = 12 if session.isoformat() in HK_HALF_DAYS else 16
    for line in text.splitlines():
        match = re.fullmatch(r'v_(?:r_)?hk([0-9]{5})="([^"\n]*)";?', line.strip())
        if not match or match[1] not in universe:
            continue
        ticker = match[1]
        if ticker in rows or ticker in failed:
            rows.pop(ticker, None)
            failed[ticker] = 'duplicate_quote'
            continue
        try:
            cells = match[2].split('~')
            if cells[2] != ticker:
                raise ValueError('identity mismatch')
            observed = datetime.strptime(cells[30], '%Y/%m/%d %H:%M:%S').replace(tzinfo=HKT)
            if observed > now or observed.date() != session or observed.hour < close_hour:
                failed[ticker] = 'missing_latest_completed_close'
                continue
            values = [to_finite_number(cells[i]) for i in (3, 32, 37, 45)]
            if any(v is None for v in values) or any(values[i] <= 0 for i in (0, 3)) or values[2] < 0:
                raise ValueError('invalid screening metrics')
            price, change, turnover, cap = values
            cap_hkd = to_finite_number(cap * 100_000_000)
            if cap_hkd is None:
                raise ValueError("invalid market capitalization")
            name = cells[1].strip()
            if not name or len(name) > 160:
                raise ValueError('invalid security name')
            rows[ticker] = {**universe[ticker], 'name': name,
                            'price_hkd': price, 'change_pct': change,
                            'turnover_hkd': turnover, 'market_cap_hkd': cap_hkd}
            stamps[ticker] = observed.isoformat()
        except (IndexError, ValueError, TypeError):
            failed[ticker] = 'invalid_quote'
    for ticker in universe.keys() - rows.keys() - failed.keys():
        failed[ticker] = 'missing_quote'
    return list(rows.values()), stamps, failed
