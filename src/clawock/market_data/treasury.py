"""Official US Treasury daily par curve; percent yields, not tradable quotes."""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone

import requests

from clawock.sessions import market_tz

BASE = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates'
MATURITIES = {'1 Mo': '1m', '1.5 Month': '1.5m', '2 Mo': '2m', '3 Mo': '3m',
              '4 Mo': '4m', '6 Mo': '6m', '1 Yr': '1y', '2 Yr': '2y', '3 Yr': '3y',
              '5 Yr': '5y', '7 Yr': '7y', '10 Yr': '10y', '20 Yr': '20y', '30 Yr': '30y'}
MAX_AGE_DAYS = 7  # Bond-market holidays differ from the equity calendar.


def observation_status(as_of, *, at=None):
    try:
        day = datetime.strptime(as_of, '%Y-%m-%d').date()
        today = (at or datetime.now(timezone.utc)).astimezone(market_tz('us')).date()
        age = (today - day).days
        return 'ok' if 0 <= age <= MAX_AGE_DAYS else 'stale'
    except (ValueError, TypeError):
        return 'unavailable'


def parse_curve(text, *, at=None):
    current = at or datetime.now(timezone.utc)
    today = current.astimezone(market_tz('us')).date()
    dated = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            day = datetime.strptime(row['Date'], '%m/%d/%Y').date()
        except (KeyError, TypeError, ValueError):
            continue
        if day <= today:
            dated[day] = row
    if not dated:
        return None
    day = max(dated)
    row = dated[day]
    values = {}
    for column, maturity in MATURITIES.items():
        try:
            value = float(row.get(column, ''))
            values[maturity] = value if math.isfinite(value) else None
        except (ValueError, TypeError):
            values[maturity] = None
    if all(value is None for value in values.values()):
        return None

    def spread(short):
        long, short_value = values['10y'], values[short]
        return round((long - short_value) * 100, 2) if long is not None and short_value is not None else None

    return {'source': 'us_treasury', 'as_of': day.isoformat(),
            'status': observation_status(day.isoformat(), at=current),
            'age_days': (today - day).days, 'unit': 'percent',
            'frequency': 'daily_par_yield', 'yields': values,
            'missing_maturities': [k for k, v in values.items() if v is None],
            'spread_10y_2y_bps': spread('2y'), 'spread_10y_3m_bps': spread('3m'),
            'url': f'{BASE}/TextView?type=daily_treasury_yield_curve&field_tdr_date_value={day.year}'}


def fetch_curve(*, at=None):
    current = at or datetime.now(timezone.utc)
    year = current.astimezone(market_tz('us')).year
    # A new year's empty file must not conceal December's last observation.
    for requested_year in (year, year - 1):
        try:
            response = requests.get(
                f'{BASE}/daily-treasury-rates.csv/{requested_year}/all',
                params={'type': 'daily_treasury_yield_curve',
                        'field_tdr_date_value': requested_year, '_format': 'csv'},
                headers={'User-Agent': 'clawock-macro/1.0'}, timeout=10)
            response.raise_for_status()
            row = parse_curve(response.text, at=current)
            if row is not None:
                return row
        except requests.RequestException:
            return None
        if current.month != 1:
            break
    return None
