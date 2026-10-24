"""Low-frequency personal research; never added to public scan artifacts.

Finnhub personal plans prohibit redistribution, including derived results.
FRED BAA10Y carries Moody's copyright. These queries use stdout plus an ignored
local cache only; no workflow, brief or dashboard consumes them automatically.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone

import requests

from clawock.credentials import load_api_keys
from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

TTL = timedelta(hours=24)


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _cached(name, fetch, *, workspace=None, at=None):
    current = at or datetime.now(timezone.utc)
    path = (workspace or workspace_root()) / '.cache' / 'private-market-data' / f'{name}.json'
    try:
        data = json.loads(path.read_text())
        age = current - datetime.fromisoformat(data['fetched_at'])
        if timedelta(0) <= age < TTL:
            return data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    data = fetch(current)
    data.update(fetched_at=current.isoformat(), visibility='private_personal_use')
    # Cache only successful/partial observations, never pin a transient outage.
    if data['status'] in ('ok', 'partial'):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe_write_json(path, data)
        path.chmod(0o600)
    return data


def _finnhub(endpoint, symbol, key):
    if not key:
        return 'unconfigured', []
    try:
        response = requests.get(f'https://finnhub.io/api/v1/stock/{endpoint}',
                                params={'symbol': symbol}, headers={'X-Finnhub-Token': key}, timeout=10)
        if response.status_code in (401, 403):
            return 'denied', []
        if response.status_code == 429:
            return 'rate_limited', []
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            return 'unavailable', []
        return 'ok', data
    except (requests.RequestException, ValueError):
        # Never stringify request exceptions: authenticated URLs/headers can leak.
        return 'unavailable', []


def _rows(rows, symbol, fields, current, *, counts=False):
    found = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('symbol') != symbol:
            continue
        try:
            period = date.fromisoformat(row['period'])
        except (KeyError, TypeError, ValueError):
            continue
        if period > current.date():
            continue
        values = {field: _number(row.get(field)) for field in fields}
        if counts and any(v is None or v < 0 or v != int(v) for v in values.values()):
            continue
        if not counts and all(v is None for v in values.values()):
            continue
        found[period] = {'period': period.isoformat(), **values}
    return [found[period] for period in sorted(found, reverse=True)[:4]]


def analysts(symbol, *, workspace=None, at=None):
    symbol = symbol.upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', symbol):
        raise ValueError('analyst research requires a US issuer symbol (not an HK code or ETF look-through guess)')
    root = workspace or workspace_root()

    def fetch(current):
        key = os.environ.get('FINNHUB_API_KEY') or load_api_keys(root / '.api_keys').get('FINNHUB_API_KEY')
        output = {}
        for field, endpoint, names in (
            ('recommendation_trends', 'recommendation', ('strongBuy', 'buy', 'hold', 'sell', 'strongSell')),
            ('reported_earnings', 'earnings', ('estimate', 'actual', 'surprise', 'surprisePercent')),
        ):
            status, data = _finnhub(endpoint, symbol, key)
            rows = _rows(data, symbol, names, current, counts=field == 'recommendation_trends')
            if status == 'ok' and not rows:
                status = 'unavailable'
            if field == 'recommendation_trends' and rows and (current.date() - date.fromisoformat(rows[0]['period'])).days > 62:
                status, rows = 'stale', []
            output[field] = {'status': status, 'rows': rows}
        statuses = [v['status'] for v in output.values()]
        status = 'ok' if all(s == 'ok' for s in statuses) else ('partial' if 'ok' in statuses else 'unavailable')
        return {'symbol': symbol, 'source': 'finnhub', 'status': status, **output,
                'not_provided': ['forward_eps_consensus', 'price_targets'],
                'earnings_scope': 'already_reported_periods; estimates are historical, not forward consensus',
                'url': 'https://finnhub.io/docs/api/recommendation-trends'}
    return _cached(f'analysts-{symbol}', fetch, workspace=root, at=at)


def credit_spread(*, workspace=None, at=None):
    def fetch(current):
        out = {'source': 'fred', 'series': 'BAA10Y', 'status': 'unavailable',
               'url': 'https://fred.stlouisfed.org/series/BAA10Y',
               'definition': "Moody's seasoned Baa yield minus 10-year Treasury; not high-yield OAS",
               'unit': 'percentage_points', 'observation': None}
        try:
            response = requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv',
                                    params={'id': 'BAA10Y', 'cosd': (current.date() - timedelta(days=30)).isoformat()},
                                    timeout=10)
            response.raise_for_status()
            rows = {}
            for row in csv.DictReader(io.StringIO(response.text)):
                try:
                    day = date.fromisoformat(row['observation_date'])
                except (KeyError, TypeError, ValueError):
                    continue
                value = _number(row.get('BAA10Y'))
                if day <= current.date() and value is not None:
                    rows[day] = value
            if rows:
                day = max(rows)
                age = (current.date() - day).days
                out['status'] = 'ok' if age <= 7 else 'stale'
                out['observation'] = {'as_of': day.isoformat(), 'value': rows[day],
                                      'bps': round(rows[day] * 100, 2), 'age_days': age}
        except (requests.RequestException, ValueError):
            pass
        return out
    return _cached('credit-BAA10Y', fetch, workspace=workspace, at=at)
