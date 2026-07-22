#!/usr/bin/env python3
"""
fetch_peers.py — fetch current price + 5-day P&L for peer tickers.

Used by brief_preflight to enrich context.json with peer_scan data.

Input: stdin JSON array: [{"ticker": "00020", "region": "hk"}, {"ticker": "NVDA", "region": "us"}, ...]
Output: stdout JSON: {"generated_at": ..., "peers": {ticker: {price, pct_1d, pct_5d, name, source, error_*?}}}

Both regions price off Tencent — `qt.gtimg.cn` for the quote and
`web.ifzq.gtimg.cn` unadjusted daily bars for the 5-day move — which is the same
canonical source `fetch_daily_bars.py` settles against. Nasdaq stays as a US
price fallback. All public, no API key. Failure on a single ticker doesn't fail
the batch — that ticker carries an `error_<source>` field instead and the exit
code stays 0.

Two traps this file has already paid for:
  * US kline symbols need their exchange suffix (`usSOXL.AM`, not `usSOXL`, which
    silently returns a single bar). Tencent self-reports it in quote field 2.
  * Only the unadjusted `day` series may be used, never `fqkline`'s `qfqday`.

Exit codes:
  0  results produced (including an explicit empty `[]` request), or --help
  1  fatal contract error: empty stdin, malformed JSON, bad request schema
  2  unknown command-line arguments
Fatal diagnostics go to stderr; stdout stays machine-readable.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from typing import Dict

import requests

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
HEADERS = {'User-Agent': UA}
TIMEOUT = 8
VALID_REGIONS = ('hk', 'us')
STALE_QUOTE_DAYS = 7
# The only caller runs this as a subprocess under a 120s timeout, so the batch
# must finish comfortably inside that or it returns nothing at all.
DEADLINE_SECONDS = 90
MAX_WORKERS = 8

USAGE = """\
usage: fetch_peers.py [-h]

Reads a JSON array of peer requests on stdin and writes prices to stdout.
This script takes no options other than -h/--help; the request is stdin-only.

stdin:
  [{"ticker": "00020", "region": "hk"}, {"ticker": "NVDA", "region": "us"}]
  region must be "hk" or "us". An empty array [] is valid and returns no peers.

stdout:
  {"generated_at": "...", "requested": N, "priced": N,
   "peers": {"00020": {"price": ..., "pct_1d": ..., "pct_5d": ...,
                       "name": ..., "source": ...}}}

example:
  jq '[.holdings["00100"].listed_peers[]]' memory/peer-map.json \\
    | python3 scripts/data/fetch_peers.py
"""


def _pct(c: float, base: float) -> float:
    return round((c - base) / base * 100, 2) if base else 0.0


def tencent_quote(sym: str):
    """Returns the `~`-split quote fields for a Tencent symbol (hk00700 / usNVDA)."""
    r = requests.get(f'https://qt.gtimg.cn/q={sym}', headers=HEADERS, timeout=TIMEOUT)
    r.encoding = 'gbk'
    line = r.text.strip()
    s, e = line.find('"') + 1, line.rfind('"')
    return line[s:e].split('~') if s > 0 and e > s else []


def tencent_closes(sym: str, sessions: int = 8):
    """Unadjusted daily closes, oldest first.

    `kline/kline` returns the raw `day` series. `fqkline/get?...,qfq` is
    forward-adjusted and must never be used for a historical comparison — the
    same rule fetch_daily_bars.py settles under.
    """
    url = ('https://web.ifzq.gtimg.cn/appstock/app/kline/kline'
           f'?param={sym},day,,,{sessions}')
    j = requests.get(url, headers=HEADERS, timeout=TIMEOUT).json()
    node = (j.get('data') or {}).get(sym) or {}
    if not isinstance(node, dict):
        return []
    return [float(row[2]) for row in (node.get('day') or []) if len(row) > 2]


def _apply_quote_age(out: Dict, parts) -> None:
    """Records the feed's own quote timestamp and flags a frozen line.

    A delisted/renamed ticker does not error here — Tencent keeps answering with
    the last quote it ever saw (usSQ still returns Block at its 2026-02-06 price,
    pct_1d 0.00%), which is worse than missing data because it reads as a real
    flat session. The timestamp is the only thing that gives it away.
    """
    raw = parts[30] if len(parts) > 30 else ''
    if not raw:
        return
    out['quote_time'] = raw
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S'):
        try:
            age = (datetime.now() - datetime.strptime(raw, fmt)).days
        except ValueError:
            continue
        if age > STALE_QUOTE_DAYS:
            out['stale_quote'] = f'{raw} ({age}d old)'
        return


def _apply_pct_5d(out: Dict, sym: str) -> None:
    """Fills pct_5d in place from the daily-bar store, or records why not."""
    try:
        closes = tencent_closes(sym)
    except Exception as e:
        out['error_kline'] = str(e)[:80]
        return
    if len(closes) < 6:
        out['error_kline'] = f'short history ({len(closes)} bars for {sym})'
        return
    base = out.get('price', closes[-1])
    out['pct_5d'] = _pct(base, closes[-6])


def fetch_hk_one(ticker: str) -> Dict:
    """Returns {price, pct_1d, pct_5d, name, source, error_*?}."""
    out = {'ticker': ticker, 'region': 'hk'}
    sym = f'hk{ticker}'
    try:
        parts = tencent_quote(f'r_{sym}')
        if len(parts) >= 6 and parts[3]:
            price = float(parts[3])
            pc = float(parts[4]) if parts[4] else price
            out.update({
                'price': price,
                'prev_close': pc,
                'pct_1d': _pct(price, pc),
                'name': parts[1],
                'source': 'tencent',
            })
            _apply_quote_age(out, parts)
        else:
            # A short/malformed payload used to leave no trace at all.
            out['error_tencent'] = f'unexpected payload ({len(parts)} fields)'
    except Exception as e:
        out['error_tencent'] = str(e)[:80]

    _apply_pct_5d(out, sym)
    return out


def _fetch_us_nasdaq(ticker: str, out: Dict) -> None:
    """Nasdaq fallback; fills `out` in place when it can price the ticker."""
    try:
        for assetclass in ('stocks', 'etf'):
            rr = requests.get(
                f'https://api.nasdaq.com/api/quote/{ticker}/info?assetclass={assetclass}',
                headers={**HEADERS, 'Origin': 'https://www.nasdaq.com'}, timeout=TIMEOUT,
            )
            if rr.status_code == 200:
                data = (rr.json().get('data') or {})
                pd = data.get('primaryData') or {}
                summary = data.get('summaryData') or {}
                price_s = (pd.get('lastSalePrice') or '').replace('$', '').replace(',', '')
                if price_s:
                    price = float(price_s)
                    pc_s = ((summary.get('PreviousClose') or {}).get('value') or '').replace('$', '').replace(',', '')
                    pc = float(pc_s) if pc_s else price
                    out.update({
                        'price': price, 'prev_close': pc,
                        'pct_1d': _pct(price, pc),
                        'source': f'nasdaq-{assetclass}',
                    })
                    return
    except Exception as e2:
        out['error_nasdaq'] = str(e2)[:80]


def fetch_us_one(ticker: str) -> Dict:
    """Returns {price, pct_1d, pct_5d, name, source, error_*?}."""
    out = {'ticker': ticker, 'region': 'us'}
    kline_sym = None
    try:
        parts = tencent_quote(f'us{ticker}')
        if len(parts) >= 6 and parts[3]:
            price = float(parts[3])
            pc = float(parts[4]) if parts[4] else price
            out.update({
                'price': round(price, 4),
                'prev_close': round(pc, 4),
                'pct_1d': _pct(price, pc),
                'name': parts[1],
                'source': 'tencent',
            })
            _apply_quote_age(out, parts)
            # Field 2 self-reports the suffixed symbol (NVDA.OQ / SOXL.AM); the
            # kline endpoint needs it or it hands back a single bar.
            if parts[2]:
                kline_sym = f'us{parts[2]}'
        else:
            out['error_tencent'] = f'unexpected payload ({len(parts)} fields)'
    except Exception as e:
        out['error_tencent'] = str(e)[:80]

    if 'price' not in out:
        _fetch_us_nasdaq(ticker, out)

    if kline_sym:
        _apply_pct_5d(out, kline_sym)
    else:
        out['error_kline'] = 'no suffixed symbol from quote feed'
    return out


def fetch_all(peers, deadline_s: float = DEADLINE_SECONDS, workers: int = MAX_WORKERS):
    """Fetches every peer under one shared wall-clock budget.

    Sequentially, each ticker could burn two TIMEOUT-second requests, so a bad
    provider day used to blow past the caller's own 120s subprocess timeout and
    discard the whole batch — the failure mode being that *nobody* gets peer data
    because one provider was slow. Whatever has landed when the budget runs out
    is returned; the rest carry `error_deadline` and the batch still exits 0.

    Results keep request order regardless of completion order.
    """
    results = {p['ticker']: None for p in peers}
    if not peers:
        return {}

    def one(p):
        if p.get('region', 'us') == 'hk':
            return fetch_hk_one(p['ticker'])
        return fetch_us_one(p['ticker'])

    with ThreadPoolExecutor(max_workers=min(workers, len(peers))) as pool:
        futures = {pool.submit(one, p): p for p in peers}
        try:
            for fut in as_completed(futures, timeout=deadline_s):
                p = futures[fut]
                try:
                    results[p['ticker']] = fut.result()
                except Exception as e:
                    results[p['ticker']] = {'ticker': p['ticker'],
                                            'region': p.get('region', 'us'),
                                            'error_fetch': str(e)[:80]}
        except FuturesTimeout:
            for fut, p in futures.items():
                fut.cancel()

    late = [t for t, r in results.items() if r is None]
    for t in late:
        p = next(p for p in peers if p['ticker'] == t)
        results[t] = {'ticker': t, 'region': p.get('region', 'us'),
                      'error_deadline': f'not returned within {deadline_s:.0f}s budget'}
    if late:
        print(f'fetch_peers.py: warning: {len(late)}/{len(peers)} tickers hit the '
              f'{deadline_s:.0f}s budget: {",".join(late)}', file=sys.stderr)
    return results


def parse_request(raw: str):
    """Returns (peers, error). `error` is a human-readable string when invalid."""
    if not raw.strip():
        return None, ('empty stdin; this script reads its request from stdin. '
                      'Pass [] explicitly to request nothing. See --help.')
    try:
        peers = json.loads(raw)
    except Exception as e:
        return None, f'stdin is not valid JSON: {e}'
    if not isinstance(peers, list):
        return None, f'expected a JSON array, got {type(peers).__name__}'
    for i, p in enumerate(peers):
        if not isinstance(p, dict):
            return None, f'item {i}: expected an object, got {type(p).__name__}'
        t = p.get('ticker')
        if not isinstance(t, str) or not t.strip():
            return None, f'item {i}: missing or empty "ticker"'
        r = p.get('region', 'us')
        if r not in VALID_REGIONS:
            return None, f'item {i} ({t}): region must be one of {VALID_REGIONS}, got {r!r}'
    return peers, None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        if argv[0] in ('-h', '--help'):
            print(USAGE)
            return 0
        # Unknown args must NOT silently succeed: a typo alongside valid piped
        # input would otherwise look like a fetch that quietly did nothing.
        print(f'fetch_peers.py: unrecognized arguments: {" ".join(argv)}\n', file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    peers, err = parse_request(sys.stdin.read())
    if err:
        print(f'fetch_peers.py: {err}', file=sys.stderr)
        return 1

    results = fetch_all(peers)

    priced = [t for t, r in results.items() if 'price' in r]
    if peers and not priced:
        print(f'fetch_peers.py: warning: 0/{len(results)} tickers priced', file=sys.stderr)

    print(json.dumps({
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'requested': len(results),
        'priced': len(priced),
        'peers': results,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
