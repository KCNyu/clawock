"""Bounded HK ordinary-share discovery using the desk's Tencent quote route.

Raw fields stay in memory. This adapter makes no claim of a vendor license.
"""
import re

import requests

from clawock.safe_io import to_finite_number
from .hk_discovery_quotes import normalize, parse_observed


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
    rows, stamps, failed = {}, {}, {}
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
            observed = parse_observed(cells[30])
            name = cells[1].strip()
            if not name or len(name) > 160:
                raise ValueError('invalid_quote')
            cap = to_finite_number(cells[45])
            rows[ticker] = normalize({**universe[ticker], 'name': name}, observed=observed,
                                    price=cells[3], previous=cells[4], turnover=cells[37],
                                    cap=cap * 100_000_000 if cap is not None else None,
                                    change=cells[32], source='tencent_hk', now=now)
            stamps[ticker] = observed.isoformat()
        except (IndexError, ValueError, TypeError) as exc:
            failed[ticker] = str(exc) if str(exc) in {
                'missing_current_session_quote', 'future_or_nontrading_observation',
                'stale_intraday_quote'} else 'invalid_quote'
    for ticker in universe.keys() - rows.keys() - failed.keys():
        failed[ticker] = 'missing_quote'
    return list(rows.values()), stamps, failed
