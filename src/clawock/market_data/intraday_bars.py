"""Read-only unadjusted five-minute bars using an existing entitlement."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from clawock.credentials import load_api_keys
from clawock.sessions import MARKET_TZ


def fetch(workspace, ticker, day):
    if not ticker.isalnum():
        raise ValueError('plain US ticker required')
    key = load_api_keys(workspace / '.api_keys').get('POLYGON_API_KEY')
    if not key:
        raise ValueError('existing Polygon key unavailable')
    url = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/5/minute/{day}/{day}'
    response = requests.get(url, params={'adjusted': 'false', 'sort': 'asc', 'limit': 500},
                            headers={'Authorization': f'Bearer {key}'}, timeout=6)
    if response.status_code != 200:
        raise ValueError(f'Polygon HTTP {response.status_code}')
    page = response.json()
    if page.get('status') != 'OK' or page.get('adjusted') is not False or page.get('next_url'):
        raise ValueError('Polygon raw complete response unavailable')
    bars = []
    for row in page.get('results', []):
        start = datetime.fromtimestamp(row['t'] / 1000, timezone.utc).astimezone(ZoneInfo(MARKET_TZ['us']))
        if start.date().isoformat() == day and 570 <= start.hour * 60 + start.minute < 960:
            bars.append({'end': (start + timedelta(minutes=5)).isoformat(),
                         **{key: row[src] for key, src in [('open', 'o'), ('high', 'h'),
                             ('low', 'l'), ('close', 'c'), ('volume', 'v')]}})
    return {'provider': 'Massive/Polygon', 'url': url, 'bars': bars}
