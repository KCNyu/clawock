#!/usr/bin/env python3
"""
fetch_benchmark_history.py — daily-close history for SPY (US) + HSI/HSTECH (HK).

Used by the Equity Curve widget to overlay a normalized benchmark line so kcn
can see the portfolio's cumulative alpha at a glance.

Sources:
  - SPY:    Polygon aggregates (needs POLYGON_API_KEY)
  - HSI/HSTECH: Tencent web.ifzq.gtimg.cn kline (free, no key)

Output: assets/data/benchmark.json
  {
    "generated_at": "...",
    "window_days": 60,
    "series": {
      "SPY":    [{"date": "2026-04-01", "close": 686.1}, ...],
      "HSI":    [{"date": "2026-04-01", "close": 25294.0}, ...],
      "HSTECH": [...]
    }
  }

Run:
  clawock benchmark            # write file
  clawock benchmark --dry-run  # print, no write
  clawock benchmark --days 90  # custom window
"""
import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests

from clawock.market_data.us_quotes import load_api_keys
from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

WS_ROOT = workspace_root()
OUT_FILE = WS_ROOT / 'assets' / 'data' / 'benchmark.json'
TIMEOUT = 12
DEFAULT_DAYS = 60
# One retry, because the failure this fetcher actually suffers is transient and
# a whole session of benchmark history costs a day to recover: the series is
# re-fetched as a 60-day window, so a single success backfills every gap, and a
# single miss strands one. Polygon's free tier rate-limits (5 req/min) and the
# link to it drops for minutes at a time (2026-09-07: an https connect to
# github.com from this host took 133s and failed, then 0.55s six minutes later).
FETCH_ATTEMPTS = 2
FETCH_RETRY_SLEEP = 3

def _polygon_once(ticker: str, days: int, api_key: str) -> List[Dict]:
    """One Polygon aggregates call. Raises on anything that is not data.

    THE POINT OF RAISING (2026-09-07): this used to read `data.get("results") or
    []` off an unchecked response, so an HTTP 401 / 403 / 429 — whose body is
    `{"status": "ERROR", "error": "..."}` with no `results` key at all — returned
    an empty list indistinguishable from "the market had no sessions in this
    window". `assign()` then retained the prior series and the only trace was one
    stderr line. A dead credential or an exhausted rate limit could sit there
    indefinitely; what surfaced instead was `benchmark freshness` two sessions
    later, and only then because `expected_lag_sessions: 1` masks the first miss.

    Measured against the live API on 2026-09-07: a bad key answers HTTP 401 with
    `{"status": "ERROR", "error": "Unknown API Key"}` — no exception, no results.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    url = (
        f'https://api.polygon.io/v2/aggs/ticker/{ticker}'
        f'/range/1/day/{start.isoformat()}/{end.isoformat()}'
    )
    # Credential goes in a header, never the URL: a query-string secret ends up
    # in proxy logs, crash dumps and Referer, and taints every value derived from
    # the response for any dataflow analysis reading this file.
    r = requests.get(
        url,
        params={'adjusted': 'true', 'sort': 'asc', 'limit': 400},
        headers={'Authorization': f'Bearer {api_key}'},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    # Polygon answers 200 with `status: ERROR` too (a malformed range, a ticker
    # the plan does not cover). Status first, `results` second — the absence of
    # `results` is only "no sessions" once the call is known to have succeeded.
    status = str(data.get('status') or '').upper()
    if status in {'ERROR', 'NOT_AUTHORIZED'}:
        raise RuntimeError(f"polygon {status}: {data.get('error') or data.get('message')}")
    out = []
    for x in data.get('results') or []:
        ts = x.get('t', 0) / 1000
        close = x.get('c')
        if not close:
            continue
        out.append({
            'date':  datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d'),
            'close': round(float(close), 4),
        })
    return out


def fetch_polygon_daily(ticker: str, days: int, api_key: str) -> List[Dict]:
    """Polygon aggregates: daily close for the last N calendar days.

    Still returns `[]` on failure — `assign()`'s retain-the-prior-series contract
    depends on that and must not change. What changes is that the failure is
    retried first and NAMED second, instead of being spelled the same way as an
    empty market.
    """
    if not api_key:
        print(f'  warn: polygon {ticker} skipped: no POLYGON_API_KEY',
              file=sys.stderr)
        return []
    return _fetch_with_retry(f'polygon {ticker}',
                             lambda: _polygon_once(ticker, days, api_key))


# Retrying a 401 is not resilience, it is two failures. Only the classes that
# can differ on the next call are retried: a dropped or slow link, a rate limit,
# a server-side error. A bad credential, a ticker the plan does not cover, or a
# malformed range answers the same way forever and should be reported at once so
# the reason reaches the log while it is still true.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError)):
        return True
    response = getattr(exc, 'response', None)
    return getattr(response, 'status_code', None) in RETRYABLE_STATUS


def _fetch_with_retry(label: str, call) -> List[Dict]:
    """Run `call`, retrying only what a retry could fix; name the failure either way.

    Returns `[]` on failure, deliberately: `assign()`'s retain-the-prior-series
    contract is built on that and is the reason a bad fetch has never destroyed a
    good series. The change is that `[]` now always comes with a printed reason,
    so "the fetch broke" and "the market had no sessions" stop being the same
    output.
    """
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            return call()
        except Exception as e:                    # noqa: BLE001 — reported, not raised
            if attempt < FETCH_ATTEMPTS and _is_retryable(e):
                print(f'  warn: {label} attempt {attempt} failed ({e}) — retrying',
                      file=sys.stderr)
                time.sleep(FETCH_RETRY_SLEEP)
                continue
            print(f'  warn: {label} fetch failed after {attempt} attempt(s): {e}',
                  file=sys.stderr)
            return []
    return []


def _tencent_hk_once(sym: str, days: int) -> List[Dict]:
    """One Tencent kline call. Raises on anything that is not data.

    Same rule as `_polygon_once`: an HTTP error must not be spelled the same way
    as an index with no sessions in the window. This leg has not been the one
    failing (HSI/HSTECH were current through 09-04 while SPY sat at 09-02), but
    it had the identical unchecked-response shape, and a guard that only exists
    on the leg that already broke is the coverage bug this codebase keeps
    re-learning.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    url = (
        'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'
        f'?param={sym},day,{start.isoformat()},{end.isoformat()},400'
    )
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    rows = (d.get('data') or {}).get(sym, {})
    # Tencent sometimes returns "day", sometimes "qfqday" (adjusted); take whichever exists
    series = rows.get('day') or rows.get('qfqday') or []
    out = []
    for row in series:
        if len(row) < 3:
            continue
        try:
            close = float(row[2])
        except (TypeError, ValueError):
            continue
        out.append({'date': row[0], 'close': round(close, 4)})
    return out


def fetch_tencent_hk_daily(sym: str, days: int) -> List[Dict]:
    """Tencent kline: HK index daily close for the last N calendar days.

    sym is the Tencent symbol form, e.g. 'hkHSI' / 'hkHSTECH'.
    """
    return _fetch_with_retry(f'tencent {sym}',
                             lambda: _tencent_hk_once(sym, days))


SERIES_MARKET = {'SPY': 'us', 'HSI': 'hk', 'HSTECH': 'hk'}


def _freshness(series: Dict[str, List[Dict]]) -> Dict[str, Dict]:
    """How many completed sessions each series is behind, per market.

    Retaining the previous bars when a fetch comes back empty is the right
    behaviour ([[openclaw-fetcher-merge-not-overwrite]]) and it is also silent:
    on 2026-08-26 the file was written at 00:03Z with HSI/HSTECH through 08-25
    and **SPY still at 08-21**, two completed US sessions behind, and nothing
    anywhere said so. The equity-curve overlay drew today's portfolio against a
    two-day-old benchmark, and `regime.py` computed the US leverage regime from
    the same stale series.

    One session behind is the normal Polygon shape for this key and is not
    reported as a problem; the number is published either way so the reader can
    see what the last point actually is.
    """
    from clawock import sessions

    out: Dict[str, Dict] = {}
    for key, rows in (series or {}).items():
        market = SERIES_MARKET.get(key)
        last = (rows or [])[-1].get('date') if rows else None
        behind = None
        if market and last:
            try:
                probe = sessions.latest_completed_session(market)
                behind = 0
                while probe is not None and probe.isoformat() > last:
                    behind += 1
                    probe = sessions.previous_trading_day(market, probe)
                    if behind > 30:      # broken table, not a stale feed
                        behind = None
                        break
            except Exception:
                behind = None
        out[key] = {
            'market': market,
            'last_session': last,
            'sessions_behind': behind,
            # Polygon's aggregates for this key land one session late as a rule,
            # so one is the floor of normal rather than evidence of a failure.
            'expected_lag_sessions': 1 if market == 'us' else 0,
        }
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=DEFAULT_DAYS,
                        help='Calendar-day lookback window (default: 60)')
    parser.add_argument('--dry-run', action='store_true', help='Print, do not write file')
    args = parser.parse_args(argv)

    keys = load_api_keys()
    series: Dict[str, List[Dict]] = {}

    # Load the previous file so a transient single-leg fetch failure doesn't
    # clobber a good series. Polygon's free tier rate-limits / times out
    # intermittently (verified 2026-05-29: 08:02 HKT brief run dropped SPY
    # entirely, leaving the equity-curve benchmark line blank). Merge instead of
    # overwrite: empty fetch → retain prior series.
    prev_series: Dict[str, List[Dict]] = {}
    if OUT_FILE.exists():
        try:
            prev_series = (json.loads(OUT_FILE.read_text()).get('series') or {})
        except Exception as e:
            print(f'  warn: could not read prior benchmark.json: {e}', file=sys.stderr)

    def assign(key, fresh):
        """Use fresh data if non-empty, else keep the prior series (non-destructive)."""
        if fresh:
            series[key] = fresh
            print(f'  {key}: {len(fresh)} bars ({fresh[0]["date"]} → {fresh[-1]["date"]})')
        elif prev_series.get(key):
            series[key] = prev_series[key]
            kept = prev_series[key]
            print(f'  {key}: fetch empty — RETAINED prior {len(kept)} bars '
                  f'(last {kept[-1]["date"]})', file=sys.stderr)
        else:
            print(f'  {key}: skipped (no data, no prior to retain)')

    # SPY (S&P 500 ETF) — primary US benchmark
    assign('SPY', fetch_polygon_daily('SPY', args.days, keys.get('POLYGON_API_KEY', '')))
    # HSI (恒生指数) — primary HK benchmark
    assign('HSI', fetch_tencent_hk_daily('hkHSI', args.days))
    # HSTECH — secondary HK benchmark (tracks tech beta closer to kcn's HK leg)
    assign('HSTECH', fetch_tencent_hk_daily('hkHSTECH', args.days))

    out = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        'window_days': args.days,
        'series': series,
        'freshness': _freshness(series),
    }

    if args.dry_run:
        print(json.dumps(out, indent=2)[:800])
        return 0

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    safe_write_json(str(OUT_FILE), out)
    print(f'  ✅ Wrote {OUT_FILE} ({sum(len(s) for s in series.values())} total bars)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
