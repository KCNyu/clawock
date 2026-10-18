#!/usr/bin/env python3
"""Acquire licensed personal research bars; never purchase or publish market data.

Grant JSON: research_use=true, license_evidence=<account entitlement reference>,
derived_public_use=<bool>. Store grants/raw bars privately, not in git.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from clawock.credentials import load_api_keys
from clawock.workspace import workspace_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--grant', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from clawock.strategy_lab.intraday_study import manifest
    plan = manifest(json.loads(args.manifest.read_text()))
    grant = json.loads(args.grant.read_text())
    if grant.get('research_use') is not True or not grant.get('license_evidence'):
        parser.error('verified research-use license evidence required; API access is insufficient')
    if plan['market'] != 'us':
        parser.error('this provider adapter supports US equities only; HK source unresolved')
    ticker = plan['universe'][0]
    if not ticker.isalnum():
        parser.error('plain US symbol required')
    key = load_api_keys(str(workspace_root()/'.api_keys')).get('POLYGON_API_KEY')
    if not key:
        parser.error('existing POLYGON_API_KEY missing; no subscription is created')
    url = f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/5/minute/{plan["start"]}/{plan["end"]}?adjusted=false&sort=asc&limit=50000'
    source_url, raw, sessions = url, [], {}
    for _ in range(12):
        if urlparse(url).hostname != 'api.polygon.io':
            raise ValueError('provider pagination host changed')
        response = requests.get(url, headers={'Authorization': f'Bearer {key}'}, timeout=30)
        if response.status_code != 200:
            raise ValueError(f'provider HTTP {response.status_code}; stopped without retry or purchase')
        page = response.json()
        if page.get('adjusted') is not False or page.get('status') != 'OK':
            raise ValueError('provider did not confirm raw successful bars')
        raw.append(page)
        for bar in page.get('results', []):
            stamp = datetime.fromtimestamp(bar['t']/1000, timezone.utc).astimezone(ZoneInfo('America/New_York'))
            minute = stamp.hour*60 + stamp.minute
            if 570 <= minute < 960:
                day = stamp.date().isoformat()
                sessions.setdefault(day, []).append({'end': (stamp+timedelta(minutes=5)).isoformat(),
                    **{key: bar[src] for key, src in [('open','o'), ('high','h'), ('low','l'), ('close','c'), ('volume','v')]}})
        url = page.get('next_url')
        if not url:
            break
    else:
        raise ValueError('pagination limit; no partial dataset output')
    raw_bytes = json.dumps(raw, sort_keys=True).encode()
    output = {'source': {**grant, 'provider': 'Massive/Polygon', 'url': source_url,
              'retrieved_at': datetime.now(timezone.utc).isoformat(),
              'raw_sha256': hashlib.sha256(raw_bytes).hexdigest(), 'synthetic': False,
              'price_basis': 'unadjusted', 'interval_minutes': 5},
              'sessions': [{'market': 'us', 'ticker': ticker, 'session': day,
              'research_allowed': True, 'forbid_reduce_advice': False, 'bars': bars}
              for day, bars in sorted(sessions.items())]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.raw.json').write_bytes(raw_bytes)
    args.output.write_text(json.dumps(output, indent=2))
    print(f'{len(sessions)} sessions saved privately; no validation or live authorization implied')


if __name__ == '__main__':
    main()
