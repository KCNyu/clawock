#!/usr/bin/env python3
"""
fetch_macro.py — daily macro sentiment for the brief.

Sources (all free, no API key):
  • VIX                — Yahoo Finance v8 chart API (^VIX), Cboe daily fallback
  • VIX9D / VIX3M / SKEW — Cboe official daily closes and same-session term ratio
  • US Treasury 10Y    — Yahoo v8 (^TNX), official Treasury daily fallback
  • Full par yield curve — US Treasury, 14 maturities, percent yields
  • USD index (DXY)    — Yahoo v8 (DX-Y.NYB)
  • CNN Fear & Greed   — production-api.cnn.com (public, no key)
  • Federal Reserve press releases — federalreserve.gov RSS (last 7 days)

Writes: assets/data/macro.json
"""
import argparse
import math
from concurrent.futures import ThreadPoolExecutor
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from clawock.safe_io import safe_write_json
from clawock.market_data import cboe, treasury
from clawock.sessions import latest_completed_session, market_tz
from clawock.workspace import workspace_root

UA = 'clawock-macro-scan/1.0 (github.com/KCNyu/clawock)'
HEADERS = {'User-Agent': UA}
TIMEOUT = 10


def classify_regime(macro_snapshot):
    """Derive a coarse risk-on/off label from a portable macro snapshot."""
    if not macro_snapshot:
        return None
    score = 0
    reasons = []
    fear_greed = macro_snapshot.get('fear_greed') or {}
    fear_greed_score = fear_greed.get('score')
    if isinstance(fear_greed_score, (int, float)):
        if fear_greed_score >= 60:
            score += 1
            reasons.append(f'F&G {fear_greed_score:.0f} greed')
        elif fear_greed_score <= 40:
            score -= 1
            reasons.append(f'F&G {fear_greed_score:.0f} fear')
    vix = (macro_snapshot.get('vix') or {}).get('price')
    if isinstance(vix, (int, float)):
        if vix < 18:
            score += 1
            reasons.append(f'VIX {vix:.0f} calm')
        elif vix > 25:
            score -= 1
            reasons.append(f'VIX {vix:.0f} stress')
    spx_change = (macro_snapshot.get('spx') or {}).get('change_pct')
    nasdaq_change = (macro_snapshot.get('nasdaq') or {}).get('change_pct')
    if isinstance(spx_change, (int, float)) and isinstance(
        nasdaq_change, (int, float)
    ):
        if spx_change > 0 and nasdaq_change > 0:
            score += 1
            reasons.append('SPX+IXIC 同向上行')
        elif spx_change < 0 and nasdaq_change < 0:
            score -= 1
            reasons.append('SPX+IXIC 同向下行')
    if not reasons:
        return None
    label = 'risk_on' if score >= 2 else ('risk_off' if score <= -2 else 'neutral')
    return {'label': label, 'score': score, 'reasons': reasons}


def _quote(symbol, price, prev, change_pct, source, as_of):
    """One index row. `change_pct` is the day's move or None, never a stand-in.

    Before the open a vendor repeats the last close as both price and previous
    close with a change of 0: that row is the previous session's close, and its
    0.00% belongs to no session. It went into the brief as `HSI 24613.27
    (0.00%)` on a day the index then lost 2.60% (#2347). `as_of` says which
    session or moment the price is from.
    """
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None
    if prev is not None and (not isinstance(prev, (int, float)) or not math.isfinite(prev) or prev <= 0):
        prev = None
    if change_pct is not None and (not isinstance(change_pct, (int, float)) or not math.isfinite(change_pct)):
        change_pct = None
    if isinstance(as_of, str) and re.fullmatch(r'\d{14}', as_of):
        as_of = f'{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}'
    if prev and price == prev and not change_pct:
        change_pct = None
    row = {
        'symbol': symbol,
        'price': round(price, 4),
        'prev': round(prev, 4) if prev else None,
        'change_pct': round(change_pct, 2) if change_pct is not None else None,
        'source': source,
    }
    if as_of and (not isinstance(as_of, str) or re.fullmatch(r'\d{4}-\d{2}-\d{2}', as_of)):
        row['as_of'] = as_of
    return row


def yahoo_quote(symbol):
    """Latest + previous close. Tries Stooq → Tencent gtimg → Yahoo (last resort).

    GH Action IPs are throttled by Yahoo so Stooq + Tencent are primary.
    """
    # 1) Stooq (free, no key, works for SPX/HSI)
    # No '^IXIC' entry (#1548): it used to map to Stooq's '^ndx', the Nasdaq-100,
    # so `nasdaq` read NDX from Stooq but the Composite from Tencent/Yahoo — two
    # indices ~11% apart behind one field and one label.
    stooq_map = {
        '^GSPC': '^spx', '^HSI': '^hsi',
        '^DJI':  '^dji', '^HSTECH': '^hstech',
    }
    stq_sym = stooq_map.get(symbol)
    if stq_sym:
        try:
            r = requests.get(
                f'https://stooq.com/q/l/?s={stq_sym}&f=sd2t2ohlcv&h&e=csv',
                headers=HEADERS, timeout=TIMEOUT,
            )
            if r.status_code == 200 and 'N/D' not in r.text:
                # CSV: Symbol,Date,Time,Open,High,Low,Close,Volume
                parts = r.text.strip().split('\n')[-1].split(',')
                if len(parts) >= 7:
                    close = float(parts[6])
                    # This endpoint has no previous close. The move from the
                    # open used to be published as the day's change with the
                    # open as `prev`; a reader cannot tell that from a real
                    # one, so it is left unknown (#2347).
                    row = _quote(symbol, close, None, None, 'stooq', parts[1])
                    key = next((k for k, value in QUOTE_SYMBOLS.items() if value == symbol), symbol)
                    if quote_status(key, row) == 'ok':
                        return row
        except Exception:
            pass

    # 2) Tencent gtimg (free, no key, works for DJI/IXIC/HSI/HSTECH)
    tencent_map = {
        '^GSPC': 'r_usINX',  # S&P 500 (.INX), not a Nasdaq index
        '^IXIC': 'r_usIXIC', '^DJI': 'r_usDJI',
        '^HSI': 'r_hkHSI', '^HSTECH': 'r_hkHSTECH',
    }
    tc_sym = tencent_map.get(symbol)
    if tc_sym:
        try:
            r = requests.get(f'https://qt.gtimg.cn/q={tc_sym}',
                             headers=HEADERS, timeout=TIMEOUT)
            r.encoding = 'gbk'
            # Parse: v_r_usDJI="...~price~...~prev~...~chg~chg_pct~..."
            text = r.text
            if '="' in text:
                inner = text.split('="', 1)[1].rstrip('";\n')
                parts = inner.split('~')
                if len(parts) > 32:
                    price = float(parts[3]) if parts[3] else None
                    prev = float(parts[4]) if parts[4] else None
                    # parts[31] = change, parts[32] = change_pct
                    if price:
                        chg_pct = float(parts[32]) if parts[32] else None
                        # parts[30] is the vendor's own quote time.
                        return _quote(symbol, price, prev, chg_pct, 'tencent',
                                      parts[30].split(' ')[0].replace('/', '-'))
        except Exception:
            pass

    # 3) Yahoo last resort (likely 429 from GH Action IP)
    try:
        r = requests.get(
            f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}',
            headers=HEADERS, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        j = r.json()
        meta = j.get('chart', {}).get('result', [{}])[0].get('meta', {})
        price = meta.get('regularMarketPrice')
        prev  = meta.get('chartPreviousClose') or meta.get('previousClose')
        if not price:
            return None
        chg = ((price - prev) / prev * 100) if prev else None
        return _quote(symbol, price, prev, chg, 'yahoo', meta.get('regularMarketTime'))
    except Exception as e:
        print(f'  ⚠️ {symbol} 全源失败: {e}', file=sys.stderr)
        return None


def cnn_fear_greed():
    """CNN Fear & Greed — uses production-API endpoint. CNN 418 bot-blocks
    default UA; use a full browser UA + Origin header to get through.
    """
    full_browser_ua = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
        '(KHTML, like Gecko) Version/17.0 Safari/605.1.15'
    )
    try:
        r = requests.get(
            'https://production.dataviz.cnn.io/index/fearandgreed/graphdata',
            headers={
                'User-Agent': full_browser_ua,
                'Accept': 'application/json, text/plain, */*',
                'Origin': 'https://www.cnn.com',
                'Referer': 'https://www.cnn.com/',
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            print(f'  ⚠️ CNN F&G: HTTP {r.status_code}', file=sys.stderr)
            return None
        j = r.json()
        cur = (j.get('fear_and_greed') or {})
        score = cur.get('score')
        if score is None:
            return None
        rating = cur.get('rating', '')
        prev_close = cur.get('previous_close')
        prev_1w    = cur.get('previous_1_week')
        return {
            'score':       round(score, 1),
            'rating':      rating,
            'prev_close':  round(prev_close, 1) if prev_close else None,
            'prev_1_week': round(prev_1w, 1) if prev_1w else None,
            'as_of':       cur.get('timestamp'),
        }
    except Exception as e:
        print(f'  ⚠️ CNN F&G: {e}', file=sys.stderr)
        return None


def fed_press_releases(days=7):
    """Federal Reserve press releases RSS — keep last `days` items."""
    import xml.etree.ElementTree as ET
    from datetime import timedelta
    try:
        r = requests.get('https://www.federalreserve.gov/feeds/press_all.xml',
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        root = ET.fromstring(r.content)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        items = []
        for it in root.findall('.//item'):
            title = it.findtext('title') or ''
            date_str = it.findtext('pubDate') or ''
            link = it.findtext('link') or ''
            try:
                from email.utils import parsedate_to_datetime
                pub = parsedate_to_datetime(date_str)
                if pub < cutoff:
                    continue
                items.append({'date': pub.strftime('%Y-%m-%d'),
                              'title': title.strip()[:200],
                              'url': link})
            except Exception:
                continue
        items.sort(key=lambda x: x['date'], reverse=True)
        return items[:15]
    except Exception as e:
        print(f'  ⚠️ Fed RSS: {e}', file=sys.stderr)
        return None


QUOTE_SYMBOLS = {'vix': '^VIX', 'treasury_10y': '^TNX', 'dxy': 'DX-Y.NYB',
                 'hsi': '^HSI', 'hstech': '^HSTECH', 'spx': '^GSPC', 'nasdaq': '^IXIC'}


def quote_status(key, row, *, at=None):
    """Per-series health; one fresh index cannot conceal another stale one."""
    if not isinstance(row, dict):
        return 'unavailable'
    price = row.get('price')
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return 'invalid'
    market = 'hk' if key in ('hsi', 'hstech') else 'us'
    stamp = row.get('as_of')
    try:
        if isinstance(stamp, str):
            day = datetime.strptime(stamp[:10], '%Y-%m-%d').date()
        elif isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            day = datetime.fromtimestamp(stamp, market_tz(market)).date()
        else:
            return 'unknown_date'
        current = at or datetime.now(timezone.utc)
        if day > current.astimezone(market_tz(market)).date():
            return 'invalid_date'
        expected = latest_completed_session(market, current)
        return 'ok' if expected is not None and day >= expected else 'stale'
    except (ValueError, OverflowError, OSError):
        return 'invalid_date'


def collect(*, at=None):
    """Bounded parallel scan, preserving missing/lagging series explicitly."""
    current = at or datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        quotes = {key: pool.submit(yahoo_quote, symbol) for key, symbol in QUOTE_SYMBOLS.items()}
        official = {symbol: pool.submit(cboe.fetch_quote, symbol, at=current) for symbol in cboe.SYMBOLS}
        curve = pool.submit(treasury.fetch_curve, at=current)
        fear = pool.submit(cnn_fear_greed)
        fed = pool.submit(fed_press_releases, days=7)
        out = {key: future.result() for key, future in quotes.items()}
        volatility = {symbol.lower(): future.result() for symbol, future in official.items()}
        out.update(fear_greed=fear.result(), fed_press=fed.result(), treasury_curve=curve.result())
    if quote_status('vix', out['vix'], at=current) != 'ok' and volatility['vix']:
        out['vix'] = volatility['vix']
    if out['treasury_10y']:
        raw = out['treasury_10y']['price']
        out['treasury_10y']['yield_pct'] = round(raw / 10 if raw > 10 else raw, 3)
    curve = out['treasury_curve']
    if quote_status('treasury_10y', out['treasury_10y'], at=current) != 'ok' and curve:
        value = curve['yields'].get('10y')
        row = _quote('US10Y', value, None, None, 'us_treasury', curve['as_of'])
        if quote_status('treasury_10y', row, at=current) == 'ok':
            out['treasury_10y'] = dict(row, yield_pct=value)
    out['volatility'] = volatility
    out['volatility_term_structure'] = cboe.term_structure(volatility['vix'], volatility['vix3m'])
    out['coverage'] = {key: quote_status(key, out[key], at=current) for key in QUOTE_SYMBOLS}
    out['coverage'].update({key: quote_status(key, row, at=current) for key, row in volatility.items()
                            if key != 'vix'})
    out['coverage']['treasury_curve'] = (curve or {}).get('status', 'unavailable')
    out['generated_at'] = current.isoformat()
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog='clawock macro', description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--credit-spreads", action="store_true", help="private personal-use FRED credit spread query; no public snapshot write")
    args = parser.parse_args(argv)
    workspace = workspace_root(args.workspace)
    if args.credit_spreads:
        if args.output:
            parser.error('--credit-spreads does not support public output files')
        import json
        from clawock.market_data.private_research import credit_spread
        print(json.dumps(credit_spread(workspace=workspace), ensure_ascii=False, indent=2))
        return 0
    output = args.output or workspace / "assets" / "data" / "macro.json"
    if not output.is_absolute():
        output = workspace / output

    out = collect()

    output.parent.mkdir(parents=True, exist_ok=True)
    safe_write_json(output, out)

    # Print summary
    print('=== macro snapshot ===')
    for k, v in out.items():
        if k in ('generated_at', 'coverage', 'volatility', 'volatility_term_structure', 'treasury_curve'): continue
        if v is None:
            print(f'  {k:14s}  ⚠️ failed')
        elif k == 'fed_press':
            print(f'  {k:14s}  {len(v)} press releases (last 7d)')
            for r in v[:3]:
                print(f'    [{r["date"]}] {r["title"][:80]}')
        elif k == 'fear_greed':
            print(f'  {k:14s}  {v["score"]} ({v["rating"]})  · prev close {v.get("prev_close")}, 1w {v.get("prev_1_week")}')
        elif k == 'treasury_10y':
            change = v.get('change_pct')
            print(f'  {k:14s}  {v["yield_pct"]}%  ' + (f'({change:+.2f}%)' if change is not None else '(当日涨跌未知)'))
        else:
            change = v.get("change_pct")
            print(f'  {k:14s}  {v["price"]:>10}  '
                  + (f'({change:+.2f}%)' if change is not None else '(当日涨跌未知)'))
    print(f'\n✓ wrote {output} ({output.stat().st_size:,} bytes)')


if __name__ == '__main__':
    sys.exit(main() or 0)
