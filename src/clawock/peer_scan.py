#!/usr/bin/env python3
"""
peer_scan.py — per-holding peer/rotation comparison shared by the preflights.

`brief_preflight` (Mode 7 daily deep brief) and `report_preflight` (Mode 6
briefings) both need the same thing: for each active holding, how its listed
peers moved today and over 5 sessions, plus a divergence flag. Mode 6 used to
have no deterministic peer data at all even though its SKILL asks for a sector
Top 5, which left the agent hand-rolling `clawock fetch-peers` invocations at runtime
— that is how a `--help` probe reddened the 2026-07-22 09:30 cron.

The peer-map is semi-manual and drifts (tickers get reused, companies rename,
lines get delisted), so two guards live here rather than in the caller:
  * the fetched company name wins over the configured one, and a disagreement is
    reported instead of silently relabelling another company's price;
  * a stale quote (a delisted line still echoing its last-ever price at 0.00%)
    is dropped from the comparison rather than read as a flat session.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from clawock.portfolio.instruments import get as get_instrument
from clawock.suggest_peers import suggest_auto_peers
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())


def _has_cjk(s):
    return any('一' <= ch <= '鿿' for ch in s)


def _names_agree(fetched, configured):
    """Loose company-name comparison for the peer-map tripwire.

    Only meaningful when both names are written in the same script — peer-map
    uses Chinese names for US tickers whose feeds return English ones, and that
    is not a mismatch worth reporting.
    """
    if _has_cjk(fetched) != _has_cjk(configured):
        return True

    def norm(s):
        # peer-map annotates some entries ("Palantir (underlying)", "Block (原
        # Square/SQ)"); those are notes to us, not part of the company name.
        s = re.sub(r'[(（][^)）]*[)）]', '', s)
        s = s.lower().replace(' ', '').replace('　', '')
        for junk in ('-w', '-sw', '-s', 'etf', 'inc.', 'inc', 'corporation', 'corp.', 'corp', ','):
            s = s.replace(junk, '')
        return s

    a, b = norm(fetched), norm(configured)
    return bool(a) and bool(b) and (a in b or b in a)


def _run_fetch(peer_request):
    """Price curated and auto peers in one existing-budget subprocess."""
    return subprocess.run(
        [sys.executable, '-m', 'clawock.cli', 'fetch-peers'],
        input=json.dumps(peer_request), capture_output=True, text=True, timeout=120,
    )


def collect(portfolio, log=print, legs=None):
    """For each active holding with a peer entry in peer-map.json, fetch peer
    prices and flag divergence (peer up significantly while holding flat/down).

    `legs` optionally limits which declared portfolio books are scanned. A
    single-market caller must pass its own leg: filtering the *result* instead
    would still pay the full cross-market network fan-out first.
    """
    peer_map_path = WS / 'memory' / 'peer-map.json'
    if not peer_map_path.exists():
        return {}
    try:
        pmap = json.loads(peer_map_path.read_text()).get('holdings', {})
    except Exception as e:
        log(f'   ⚠️  peer-map.json parse failed: {e}')
        return {}

    # Index holdings by ticker for self-pct lookup
    h_by_ticker = {}
    books = portfolio.get('portfolios') or {}
    for book_key in (legs or tuple(books)):
        for h in books.get(book_key, {}).get('holdings', []):
            if h.get('shares', 0) > 0:
                instrument = get_instrument(h.get('ticker')) or {}
                market = str(instrument.get('region') or '').lower()
                h_by_ticker[h['ticker']] = {
                    'pct_1d': h.get('today_change_pct', 0),
                    'pnl_pct': h.get('pnl_percent', 0),
                    'region': market,
                }

    # Suggest first, then price curated + auto peers in ONE fetch-peers batch.
    # Curated requests remain first, so the existing 8-worker/90s budget gives
    # the hand-maintained map priority if the combined list is large.
    auto_by_ticker = {}
    for ticker, info in pmap.items():
        if ticker not in h_by_ticker:
            continue
        region = h_by_ticker[ticker]['region']
        curated = [p.get('ticker') for p in info.get('listed_peers', [])]
        try:
            suggested = suggest_auto_peers(ticker, region, curated)
            auto_by_ticker[ticker] = suggested if isinstance(suggested, list) else []
            if not isinstance(suggested, list):
                log(f'   ⚠️  auto peers {ticker} returned {type(suggested).__name__}, ignored')
        except Exception as e:
            # suggest_auto_peers itself is fail-safe; this second guard protects
            # the curated scan from import/test/provider regressions around it.
            log(f'   ⚠️  auto peers {ticker} failed: {e}')
            auto_by_ticker[ticker] = []

    # Collect all peer tickers we need.
    peer_request = []
    seen = set()
    for ticker, info in pmap.items():
        if ticker not in h_by_ticker:  # holding inactive, skip
            continue
        for p in info.get('listed_peers', []):
            key = (p['ticker'], p['region'])
            if key not in seen:
                seen.add(key)
                peer_request.append({'ticker': p['ticker'], 'region': p['region']})
    for ticker, suggestions in auto_by_ticker.items():
        for p in suggestions:
            key = (p['ticker'], p['region'])
            if key not in seen:
                seen.add(key)
                peer_request.append({'ticker': p['ticker'], 'region': p['region']})

    if not peer_request:
        return {}

    # Call the installed package command via subprocess.
    try:
        r = _run_fetch(peer_request)
        if r.returncode != 0:
            # Old versions of the script printed their error to stdout, not stderr.
            log(f'   ⚠️  clawock fetch-peers failed (rc={r.returncode}): {(r.stderr or r.stdout)[-300:]}')
            return {}
        fetched = json.loads(r.stdout)['peers']
        if not isinstance(fetched, dict):
            log(f'   ⚠️  clawock fetch-peers returned a malformed peers block: {type(fetched).__name__}')
            return {}
        missing = [p['ticker'] for p in peer_request if 'price' not in fetched.get(p['ticker'], {})]
        log(f'   peers priced {len(peer_request) - len(missing)}/{len(peer_request)}'
              + (f'; missing {",".join(missing)}' if missing else ''))
    except Exception as e:
        log(f'   ⚠️  peer fetch error: {e}')
        return {}

    # Build per-holding peer scan
    scan = {}
    for ticker, info in pmap.items():
        if ticker not in h_by_ticker:
            continue
        self_pct = h_by_ticker[ticker]['pct_1d'] or 0
        peer_results = []
        for p in info.get('listed_peers', []):
            pdata = fetched.get(p['ticker'], {})
            if pdata.get('stale_quote'):
                # A renamed/delisted peer keeps returning its last-ever quote at
                # 0.00%, which would read as a genuinely flat session and drag the
                # rotation comparison toward nothing. Drop it and say so.
                log(f'   ⚠️  peer {p["ticker"]} quote is stale ({pdata["stale_quote"]}), dropped')
                continue
            if 'price' in pdata:
                # Trust the fetched name over the configured one: a stale/typo'd
                # ticker in peer-map.json would otherwise label another company's
                # price with the name we expected to see.
                fetched_name = pdata.get('name')
                entry = {
                    'ticker': p['ticker'],
                    'name': fetched_name or p['name'],
                    'rel': p['rel'],
                    'pct_1d': pdata.get('pct_1d'),
                    'pct_5d': pdata.get('pct_5d'),
                }
                if fetched_name and not _names_agree(fetched_name, p['name']):
                    entry['name_mismatch'] = f'peer-map says {p["name"]}, feed says {fetched_name}'
                    log(f'   ⚠️  peer-map name mismatch {p["ticker"]}: '
                          f'configured {p["name"]} vs feed {fetched_name}')
                peer_results.append(entry)

        # Sort by 1d pct desc, unpriced last. NOT `or -999`: a genuinely flat
        # peer (0.0) would sort below every loser.
        peer_results.sort(
            key=lambda x: x['pct_1d'] if x.get('pct_1d') is not None else float('-inf'),
            reverse=True)

        # Divergence: best peer outperformed holding by ≥3% today
        best_peer = peer_results[0] if peer_results else None
        divergence = None
        if best_peer and best_peer.get('pct_1d') is not None:
            diff = best_peer['pct_1d'] - self_pct
            if diff >= 3.0:
                divergence = f'{best_peer["ticker"]} {best_peer["name"]} {best_peer["pct_1d"]:+.1f}% vs self {self_pct:+.1f}% (gap {diff:+.1f}pp)'

        auto_results = []
        for p in auto_by_ticker.get(ticker, []):
            pdata = fetched.get(p['ticker'], {})
            if pdata.get('stale_quote'):
                log(f'   ⚠️  auto peer {p["ticker"]} quote is stale '
                    f'({pdata["stale_quote"]}), dropped')
                continue
            if 'price' not in pdata:
                continue
            auto_results.append({
                'ticker': p['ticker'],
                'name': pdata.get('name') or p.get('name') or p['ticker'],
                'label': '同行业·自动',
                'source': p.get('source'),
                'pct_1d': pdata.get('pct_1d'),
                'pct_5d': pdata.get('pct_5d'),
            })
        auto_results.sort(
            key=lambda x: x['pct_1d'] if x.get('pct_1d') is not None else float('-inf'),
            reverse=True)

        scan[ticker] = {
            'theme':            info.get('theme'),
            'self_pct_1d':      round(self_pct, 2),
            'self_pnl_pct':     h_by_ticker[ticker]['pnl_pct'],
            'listed_peers':     peer_results,
            'auto_peers':       auto_results,
            'private_peers':    info.get('private_peers', []),
            'divergence_signal': divergence,
            'key_news_keywords': info.get('key_news_keywords', []),
        }
    return scan
