#!/usr/bin/env python3
"""
fetch_fx.py - USDHKD exchange rate fetcher (3-route fallback, no API key)

Provider chain:
  1. Frankfurter.app  – ECB-sourced, free, no key, daily refresh
  2. exchangerate.host – free, no key, multi-source aggregation
  3. Yahoo HKD=X      – live spot, no key

Usage:
  python3 fetch_fx.py                          # print USDHKD rate
  python3 fetch_fx.py --json                   # JSON output
  python3 fetch_fx.py --convert 10000 HKD USD  # convert amount
"""

import json
import os
import sys
import time
from typing import Optional, Dict
import requests

WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_PATH = os.path.join(WS_ROOT, '.cache', 'fx_rate.json')
# The durable record, one line per day. The cache above is gitignored and
# overwritten, so until #323 the only place a past day's rate survived was the
# commit history of assets/data/dashboard.json — which #314 moved off master.
# Prices are already durable (every snapshot carries current_price per holding);
# this is the rate that COMBINES the two legs, and without it a rebuild of any
# past day silently stamps it with today's rate. `openclaw-fx-rule` says HKD and
# USD cannot be added directly; this is the provenance half of that.
#
# Under memory/ deliberately: `brief_postflight` already runs
# `git add 'memory/'` every morning, so this rides an existing, proven commit
# path rather than needing a new one. Append-only, so a morning that fails to
# commit loses nothing — the next one carries both days.
LEDGER_PATH = os.path.join(WS_ROOT, 'memory', 'fx-rates.jsonl')
CACHE_TTL_HOURS = 4   # FX moves slowly intraday; refresh 6x/day is enough
TIMEOUT = 10

SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) openclaw-fx/1.0'})


def _from_cache(allow_stale: bool = False) -> Optional[Dict]:
    if not os.path.exists(CACHE_PATH):
        return None
    age_h = (time.time() - os.path.getmtime(CACHE_PATH)) / 3600
    if age_h > CACHE_TTL_HOURS and not allow_stale:
        return None
    try:
        with open(CACHE_PATH) as f:
            data = dict(json.load(f))
        # Old cache entries predate the explicit provenance flag. A fresh cached
        # provider quote is not itself a fallback; an expired one is.
        data.setdefault('fallback_used', False)
        if age_h > CACHE_TTL_HOURS:
            data['fallback_used'] = True
            data['source'] = f"{data.get('source', 'cache')} (stale cache; all live sources failed)"
            data['warning'] = 'all live sources failed; using stale cached USDHKD rate'
        return data
    except Exception:
        return None


def _save_cache(data: Dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w') as f:
        json.dump(data, f)
    _record_rate(data)


def _ledger_day(entry: Dict) -> str:
    """The UTC day an entry belongs to, from its fetch time."""
    stamp = (entry.get('fetched_at') or '')[:10]
    return stamp or time.strftime('%Y-%m-%d', time.gmtime())


def read_rate_ledger(path: str = None) -> Dict[str, Dict]:
    """day -> the rate recorded for it. Last write for a day wins.

    Tolerates a corrupt line rather than refusing the whole file: this is a
    provenance record appended to over months, and one bad line must not make
    every other day unreadable.
    """
    path = path or LEDGER_PATH
    out: Dict[str, Dict] = {}
    try:
        with open(path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get('day'):
                    out[entry['day']] = entry
    except OSError:
        return out
    return out


def _record_rate(data: Dict, path: str = None):
    """Append today's rate, unless the same rate for the same day is already there.

    Idempotent per (day, rate) because the fetcher runs up to 6x/day on a 4-hour
    TTL and a re-fetch that agrees carries no new information. A rate that
    CHANGED within the day is appended — that is a real observation, and the
    reader takes the last one.

    Never raises: a provenance record must not be able to fail a price fetch.
    """
    path = path or LEDGER_PATH
    try:
        rate = data.get('rate')
        if rate is None:
            return
        day = _ledger_day(data)
        existing = read_rate_ledger(path).get(day)
        if existing and existing.get('rate') == rate:
            return
        entry = {
            'day': day,
            'rate': rate,
            'pair': data.get('pair', 'USDHKD'),
            'source': data.get('source'),
            'fetched_at': data.get('fetched_at'),
            'fallback_used': data.get('fallback_used'),
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a') as handle:
            handle.write(json.dumps(entry, sort_keys=True) + '\n')
    except Exception:
        return


def _get_frankfurter() -> Optional[float]:
    try:
        r = SESSION.get('https://api.frankfurter.app/latest',
                        params={'from': 'USD', 'to': 'HKD'}, timeout=TIMEOUT)
        return float(r.json()['rates']['HKD'])
    except Exception:
        return None


def _get_exchangerate_host() -> Optional[float]:
    try:
        r = SESSION.get('https://api.exchangerate.host/latest',
                        params={'base': 'USD', 'symbols': 'HKD'}, timeout=TIMEOUT)
        return float(r.json()['rates']['HKD'])
    except Exception:
        return None


def _get_yahoo() -> Optional[float]:
    try:
        r = SESSION.get('https://query1.finance.yahoo.com/v8/finance/chart/HKD=X',
                        params={'interval': '1m', 'range': '1d'}, timeout=TIMEOUT)
        meta = r.json()['chart']['result'][0]['meta']
        return float(meta.get('regularMarketPrice') or meta.get('previousClose'))
    except Exception:
        return None


def get_usdhkd(force_refresh: bool = False) -> Dict:
    """
    Returns {'rate': 7.81, 'source': 'Frankfurter', 'fetched_at': iso}.
    Falls back through 3 providers. Uses 4h cache to avoid hammering.
    """
    if not force_refresh:
        cached = _from_cache()
        if cached:
            return cached

    providers = (
        ('Frankfurter',         _get_frankfurter),
        ('exchangerate.host',   _get_exchangerate_host),
        ('Yahoo HKD=X',         _get_yahoo),
    )
    for provider_index, (name, fn) in enumerate(providers):
        rate = fn()
        if rate and 7.0 < rate < 9.0:   # sanity check (HKD pegged ~7.75-7.85)
            from datetime import datetime, timezone
            data = {
                'rate':       round(rate, 5),
                'source':     name,
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'pair':       'USDHKD',
                'fallback_used': provider_index > 0,
            }
            _save_cache(data)
            return data

    # All providers failed — fall back to cached even if stale
    cached = _from_cache(allow_stale=True)
    if cached:
        return cached

    # Last-resort hard-coded peg midpoint
    from datetime import datetime, timezone
    return {
        'rate':       7.80,
        'source':     'HARDCODED_PEG_FALLBACK',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'pair':       'USDHKD',
        'fallback_used': True,
        'warning':    'all live sources failed; using hard-coded HKD peg midpoint',
    }


def convert(amount: float, from_ccy: str, to_ccy: str) -> Dict:
    """Convert between USD and HKD. Other currencies not supported."""
    if from_ccy == to_ccy:
        return {'amount': amount, 'rate': 1.0, 'source': 'identity'}
    fx = get_usdhkd()
    rate = fx['rate']
    if from_ccy == 'USD' and to_ccy == 'HKD':
        return {'amount': round(amount * rate, 2), 'rate': rate, 'source': fx['source']}
    if from_ccy == 'HKD' and to_ccy == 'USD':
        return {'amount': round(amount / rate, 2), 'rate': rate, 'source': fx['source']}
    raise ValueError(f"unsupported pair {from_ccy}->{to_ccy}; only USD<->HKD")


if __name__ == '__main__':
    as_json = '--json' in sys.argv
    if '--convert' in sys.argv:
        idx = sys.argv.index('--convert')
        amount   = float(sys.argv[idx + 1])
        from_ccy = sys.argv[idx + 2].upper()
        to_ccy   = sys.argv[idx + 3].upper()
        result = convert(amount, from_ccy, to_ccy)
        if as_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{amount} {from_ccy} = {result['amount']} {to_ccy}  "
                  f"(rate {result['rate']}, {result['source']})")
    else:
        fx = get_usdhkd()
        if as_json:
            print(json.dumps(fx, indent=2))
        else:
            print(f"USDHKD: {fx['rate']}  [{fx['source']}, {fx['fetched_at']}]")
            if 'warning' in fx:
                print(f"  ⚠️  {fx['warning']}")
