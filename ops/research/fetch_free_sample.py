#!/usr/bin/env python3
"""Fetch FirstRate's explicitly licensed free SPY sample, preserving adjustment.

No purchase, sign-up, credentials or raw-data redistribution. The sample is too
short for the frozen walk-forward and is NOT silently treated as unadjusted.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import zipfile

import requests

URL = 'https://x01.frd-data.com/firstratedata_sample_SPY.zip'
LICENSE = 'https://firstratedata.com/about/license'


def normalize(content):
    sessions = {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        rows = csv.reader(io.StringIO(archive.read('SPY_5min.csv').decode()))
        for row in rows:
            stamp = datetime.fromisoformat(row[0]).replace(tzinfo=ZoneInfo('America/New_York'))
            if 570 <= stamp.hour*60 + stamp.minute < 960:
                sessions.setdefault(stamp.date().isoformat(), []).append({
                    'end': (stamp+timedelta(minutes=5)).isoformat(),
                    **dict(zip(('open', 'high', 'low', 'close', 'volume'), map(float, row[1:])))})
    return {'source': {'provider': 'FirstRate Data', 'url': URL, 'license_evidence': LICENSE,
            'research_use': True, 'derived_public_use': True, 'synthetic': False,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'raw_sha256': hashlib.sha256(content).hexdigest(),
            'price_basis': 'split_adjusted', 'interval_minutes': 5},
            'sessions': [{'market': 'us', 'ticker': 'SPY', 'session': day,
                          'research_allowed': True, 'forbid_reduce_advice': False, 'bars': bars}
                         for day, bars in sorted(sessions.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    response = requests.get(URL, timeout=30)
    if response.status_code != 200:
        parser.error(f'free sample HTTP {response.status_code}; no paid fallback')
    data = normalize(response.content)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.zip').write_bytes(response.content)
    args.output.write_text(json.dumps(data, indent=2))
    print('Free sample saved privately; adjustment and actual dates preserved, not validated performance')


if __name__ == '__main__':
    main()
