#!/usr/bin/env python3
"""
fetch_macro.py — daily macro sentiment for the brief.

Sources (all free, no API key):
  • VIX                — Yahoo Finance v8 chart API (^VIX)
  • US Treasury 10Y    — Yahoo v8 (^TNX, divide by 10 for %)
  • USD index (DXY)    — Yahoo v8 (DX-Y.NYB)
  • CNN Fear & Greed   — production-api.cnn.com (public, no key)
  • Federal Reserve press releases — federalreserve.gov RSS (last 7 days)

Writes: assets/data/macro.json
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from clawock.safe_io import safe_write_json
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
            reasons.append('SPX+NDX 同向上行')
        elif spx_change < 0 and nasdaq_change < 0:
            score -= 1
            reasons.append('SPX+NDX 同向下行')
    if not reasons:
        return None
    label = 'risk_on' if score >= 2 else ('risk_off' if score <= -2 else 'neutral')
    return {'label': label, 'score': score, 'reasons': reasons}


def yahoo_quote(symbol):
    """Latest + previous close. Tries Stooq → Tencent gtimg → Yahoo (last resort).

    GH Action IPs are throttled by Yahoo so Stooq + Tencent are primary.
    """
    # 1) Stooq (free, no key, works for SPX/NDX/HSI)
    stooq_map = {
        '^GSPC': '^spx', '^IXIC': '^ndx', '^HSI': '^hsi',
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
                    open_p = float(parts[3])
                    close = float(parts[6])
                    chg = ((close - open_p) / open_p * 100) if open_p else 0
                    return {
                        'symbol': symbol, 'price': round(close, 4),
                        'prev': round(open_p, 4),  # rough proxy: today open
                        'change_pct': round(chg, 2),
                        'source': 'stooq',
                    }
        except Exception:
            pass

    # 2) Tencent gtimg (free, no key, works for DJI/IXIC/HSI/HSTECH)
    tencent_map = {
        '^GSPC': None,  # Tencent doesn't have SPX
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
                        chg_pct = float(parts[32]) if parts[32] else 0
                        return {
                            'symbol': symbol, 'price': round(price, 4),
                            'prev': round(prev, 4) if prev else None,
                            'change_pct': round(chg_pct, 2),
                            'source': 'tencent',
                        }
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
        chg = ((price - prev) / prev * 100) if prev else 0
        return {
            'symbol': symbol,
            'price':  round(price, 4),
            'prev':   round(prev or price, 4),
            'change_pct': round(chg, 2),
            'as_of': meta.get('regularMarketTime'),
            'source': 'yahoo',
        }
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    workspace = workspace_root(args.workspace)
    output = args.output or workspace / "assets" / "data" / "macro.json"
    if not output.is_absolute():
        output = workspace / output

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'vix':            yahoo_quote('^VIX'),
        'treasury_10y':   yahoo_quote('^TNX'),     # actually 10Y * 10 in price units
        'dxy':            yahoo_quote('DX-Y.NYB'),
        'fear_greed':     cnn_fear_greed(),
        'hsi':            yahoo_quote('^HSI'),
        'hstech':         yahoo_quote('^HSTECH'),
        'spx':            yahoo_quote('^GSPC'),
        'nasdaq':         yahoo_quote('^IXIC'),
        'fed_press':      fed_press_releases(days=7),
    }

    # 10Y treasury yield — source format differs:
    #   Yahoo legacy ^TNX: price = yield * 10 (e.g. 44.93 means 4.493%)
    #   Yahoo current + Stooq + Tencent: price = yield directly (e.g. 4.493%)
    # Sustained US 10Y > 10% is historically unrealistic (last seen 1979-1985),
    # so use that as the format-discriminator.
    if out['treasury_10y']:
        raw = out['treasury_10y']['price']
        out['treasury_10y']['yield_pct'] = round(raw / 10 if raw > 10 else raw, 3)

    output.parent.mkdir(parents=True, exist_ok=True)
    safe_write_json(output, out)

    # Print summary
    print('=== macro snapshot ===')
    for k, v in out.items():
        if k == 'generated_at': continue
        if v is None:
            print(f'  {k:14s}  ⚠️ failed')
        elif k == 'fed_press':
            print(f'  {k:14s}  {len(v)} press releases (last 7d)')
            for r in v[:3]:
                print(f'    [{r["date"]}] {r["title"][:80]}')
        elif k == 'fear_greed':
            print(f'  {k:14s}  {v["score"]} ({v["rating"]})  · prev close {v.get("prev_close")}, 1w {v.get("prev_1_week")}')
        elif k == 'treasury_10y':
            print(f'  {k:14s}  {v["yield_pct"]}%  ({v["change_pct"]:+.2f}%)')
        else:
            print(f'  {k:14s}  {v["price"]:>10}  ({v["change_pct"]:+.2f}%)')
    print(f'\n✓ wrote {output} ({output.stat().st_size:,} bytes)')


if __name__ == '__main__':
    sys.exit(main() or 0)
