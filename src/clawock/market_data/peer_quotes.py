#!/usr/bin/env python3
"""
clawock fetch-peers — current price + 5-day P&L for peer tickers.

Used by brief_preflight to enrich context.json with peer_scan data.

Input: stdin JSON array: [{"ticker": "00020", "region": "hk"}, {"ticker": "NVDA", "region": "us"}, ...]
Output: stdout JSON: {"generated_at": ..., "peers": {ticker: {price, pct_1d, pct_5d, name, source, error_*?}}}

Both regions price off Tencent — `qt.gtimg.cn` for the quote and
`web.ifzq.gtimg.cn` forward-adjusted daily bars for the 5-day move. Nasdaq stays
as a US price fallback. All public, no API key. Failure on a single ticker doesn't fail
the batch — that ticker carries an `error_<source>` field instead and the exit
code stays 0.

Three traps this file has already paid for:
  * US kline symbols need their exchange suffix (`usSOXL.AM`, not `usSOXL`, which
    silently returns a single bar). Tencent self-reports it in quote field 2.
  * A 5-day *return* needs the forward-adjusted series, unlike `fetch_daily_bars.py`
    which stores raw bars because a historical trigger price must stay nominal. A
    split inside the window would otherwise read as a phantom ±50% move.
  * The batch budget must clamp each request's own timeout, or it is advisory
    only — see `_req_timeout`. Even clamped it is not a hard stop: `requests`
    times out on inactivity, not total elapsed time, and executor threads are
    non-daemon, so the process leaves via `hard_exit`.

Exit codes:
  0  results produced (including an explicit empty `[]` request), or --help
  1  fatal contract error: empty stdin, malformed JSON, bad request schema
  2  unknown command-line arguments
Fatal diagnostics go to stderr; stdout stays machine-readable.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from typing import Dict
from zoneinfo import ZoneInfo

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
usage: clawock fetch-peers [-h]

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
    | clawock fetch-peers
"""


class BudgetExhausted(Exception):
    """The batch's shared wall-clock budget ran out before this request."""


def _req_timeout(deadline):
    """Per-request timeout, clamped by whatever is left of the batch budget.

    Without this clamp the budget is advisory only: a worker that starts a
    request just before the deadline can still run TIMEOUT seconds past it, and
    `ThreadPoolExecutor.__exit__` waits for it.
    """
    if deadline is None:
        return TIMEOUT
    left = deadline - time.monotonic()
    if left <= 0:
        raise BudgetExhausted('batch deadline reached before this request')
    return min(TIMEOUT, left)


def _pct(c: float, base: float) -> float:
    return round((c - base) / base * 100, 2) if base else 0.0


def tencent_quote(sym: str, deadline=None):
    """Returns the `~`-split quote fields for a Tencent symbol (hk00700 / usNVDA)."""
    r = requests.get(f'https://qt.gtimg.cn/q={sym}', headers=HEADERS,
                     timeout=_req_timeout(deadline))
    r.encoding = 'gbk'
    line = r.text.strip()
    s, e = line.find('"') + 1, line.rfind('"')
    return line[s:e].split('~') if s > 0 and e > s else []


def tencent_closes(sym: str, sessions: int = 8, deadline=None):
    """Forward-adjusted daily closes, oldest first.

    Deliberately the opposite choice from `fetch_daily_bars.py`, which stores the
    raw `day` series because a historical *trigger price* must stay nominal. This
    is a *return* over a window, and a split inside that window would turn into a
    phantom ±50% move if compared against raw closes. Same qfq source and same
    `qfqday or day` fallback the repo's other return/risk math uses
    (`compute_quant_signals.fetch_bars`).
    """
    url = ('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
           f'?param={sym},day,,,{sessions},qfq')
    j = requests.get(url, headers=HEADERS, timeout=_req_timeout(deadline)).json()
    node = (j.get('data') or {}).get(sym) or {}
    if not isinstance(node, dict):
        return []
    rows = node.get('qfqday') or node.get('day') or []
    return [float(row[2]) for row in rows if len(row) > 2]


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
            # gtimg stamps are Beijing time; a naive subtraction would use this
            # machine's local zone, so the stale gate only ever fired on a
            # UTC+8 host — anywhere else the age came out negative and the
            # quote was treated as fresh forever (#845).
            quoted = datetime.strptime(raw, fmt).replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            age = (datetime.now(timezone.utc) - quoted).days
        except ValueError:
            continue
        if age > STALE_QUOTE_DAYS:
            out['stale_quote'] = f'{raw} ({age}d old)'
        return


def _apply_pct_5d(out: Dict, sym: str, deadline=None) -> None:
    """Fills pct_5d in place from the daily-bar store, or records why not."""
    try:
        closes = tencent_closes(sym, deadline=deadline)
    except BudgetExhausted as e:
        out['error_deadline'] = str(e)
        return
    except Exception as e:
        out['error_kline'] = str(e)[:80]
        return
    if len(closes) < 6:
        out['error_kline'] = f'short history ({len(closes)} bars for {sym})'
        return
    base = out.get('price', closes[-1])
    out['pct_5d'] = _pct(base, closes[-6])


def fetch_hk_one(ticker: str, deadline=None) -> Dict:
    """Returns {price, pct_1d, pct_5d, name, source, error_*?}."""
    out = {'ticker': ticker, 'region': 'hk'}
    sym = f'hk{ticker}'
    try:
        parts = tencent_quote(f'r_{sym}', deadline=deadline)
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
    except BudgetExhausted as e:
        out['error_deadline'] = str(e)
        return out
    except Exception as e:
        out['error_tencent'] = str(e)[:80]

    _apply_pct_5d(out, sym, deadline=deadline)
    return out


def _fetch_us_nasdaq(ticker: str, out: Dict, deadline=None) -> None:
    """Nasdaq fallback; fills `out` in place when it can price the ticker."""
    try:
        for assetclass in ('stocks', 'etf'):
            rr = requests.get(
                f'https://api.nasdaq.com/api/quote/{ticker}/info?assetclass={assetclass}',
                headers={**HEADERS, 'Origin': 'https://www.nasdaq.com'},
                timeout=_req_timeout(deadline),
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
    except BudgetExhausted as e2:
        out['error_deadline'] = str(e2)
    except Exception as e2:
        out['error_nasdaq'] = str(e2)[:80]


def fetch_us_one(ticker: str, deadline=None) -> Dict:
    """Returns {price, pct_1d, pct_5d, name, source, error_*?}."""
    out = {'ticker': ticker, 'region': 'us'}
    kline_sym = None
    try:
        parts = tencent_quote(f'us{ticker}', deadline=deadline)
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
    except BudgetExhausted as e:
        out['error_deadline'] = str(e)
        return out
    except Exception as e:
        out['error_tencent'] = str(e)[:80]

    if 'price' not in out:
        _fetch_us_nasdaq(ticker, out, deadline=deadline)

    if kline_sym:
        _apply_pct_5d(out, kline_sym, deadline=deadline)
    else:
        out['error_kline'] = 'no suffixed symbol from quote feed'
    return out


def dedupe(peers):
    """First occurrence of each ticker wins; returns (unique, dropped).

    Results are keyed by ticker, so a repeated ticker would collapse into one
    entry and — once the batch runs concurrently — whichever future happened to
    finish last would win. peer-map legitimately lists the same ticker under more
    than one holding, so this is reachable; resolve it deterministically here
    rather than leaving it to thread scheduling.
    """
    unique, dropped, seen = [], [], set()
    for p in peers:
        if p['ticker'] in seen:
            dropped.append(p['ticker'])
            continue
        seen.add(p['ticker'])
        unique.append(p)
    return unique, dropped


def fetch_all(peers, deadline_s: float = DEADLINE_SECONDS, workers: int = MAX_WORKERS):
    """Fetches every peer under one shared wall-clock budget.

    Sequentially, each ticker could burn several TIMEOUT-second requests, so a bad
    provider day used to blow past the caller's own 120s subprocess timeout and
    discard the whole batch — the failure mode being that *nobody* gets peer data
    because one provider was slow. Whatever has landed when the budget runs out
    is returned; the rest carry `error_deadline` and the batch still exits 0.

    The budget is enforced in two places, and needs both: `as_completed` stops us
    waiting, while `_req_timeout` clamps each in-flight request so an already
    running worker cannot overrun it (executor shutdown waits for running
    workers, and `Future.cancel()` does not stop one that has started).

    Results keep request order regardless of completion order.
    """
    if not peers:
        return {}
    peers, dropped = dedupe(peers)
    if dropped:
        print(f'fetch_peers.py: warning: dropped {len(dropped)} duplicate ticker(s): '
              f'{",".join(dropped)}', file=sys.stderr)

    results = {p['ticker']: None for p in peers}
    deadline = time.monotonic() + deadline_s

    def one(p):
        if p.get('region', 'us') == 'hk':
            return fetch_hk_one(p['ticker'], deadline=deadline)
        return fetch_us_one(p['ticker'], deadline=deadline)

    pool = ThreadPoolExecutor(max_workers=min(workers, len(peers)))
    try:
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
            pass
    finally:
        # Drop queued work immediately and do not block on stragglers; their own
        # requests are already clamped to the exhausted budget.
        pool.shutdown(wait=False, cancel_futures=True)

    late = [t for t, r in results.items() if r is None]
    by_ticker = {p['ticker']: p for p in peers}
    for t in late:
        results[t] = {'ticker': t, 'region': by_ticker[t].get('region', 'us'),
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


def hard_exit(code: int):
    """Leave the process now, even if a provider thread is still trickling.

    Two things conspire to make `fetch_all` returning on time insufficient:
    `requests`' `timeout=` is an *inactivity* timeout rather than a total
    wall-clock one, so a provider that dribbles bytes can outlive its clamp; and
    `ThreadPoolExecutor` threads are non-daemon, so the interpreter joins them at
    exit no matter what `shutdown(wait=False, cancel_futures=True)` asked for. The
    caller reads our stdout to EOF, so a lingering thread holds *its* 120s
    timeout open and the JSON we already finished writing gets discarded. Flush
    what we produced, then stop the process outright.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == '__main__':
    hard_exit(main())
