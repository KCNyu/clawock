#!/usr/bin/env python3
"""
fetch_us_stocks.py - Multi-provider US stock price fetcher
Reads active holdings (shares > 0) from portfolio.json.

Provider chain:
  1. Nasdaq API     – JSON, no key, works for stocks + ETFs
  2. Eastmoney      – JSON batch, no key, CN source
  3. Finnhub        – JSON, needs FINNHUB_API_KEY
  4. Yahoo v8 API   – JSON, no key, may rate-limit
  5. yfinance       – library, no key, may rate-limit
  6. Alpha Vantage  – JSON, needs ALPHA_VANTAGE_API_KEY, slow
  7. Polygon        – JSON, needs POLYGON_API_KEY, prev-close only

Usage:
  python3 fetch_us_stocks.py                # update portfolio.json
  python3 fetch_us_stocks.py --dry-run      # print prices, don't write
  python3 fetch_us_stocks.py RKLB SOXL      # specific tickers only
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import requests

WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORTFOLIO_PATH = os.path.join(WS_ROOT, 'portfolio.json')
API_KEYS_PATH  = os.path.join(WS_ROOT, '.api_keys')

# Eastmoney exchange prefix: 105=NASDAQ, 106=NYSE/ARCA
EASTMONEY_PREFIX: Dict[str, str] = {
    # NASDAQ
    'AAPL': '105', 'MSFT': '105', 'NVDA': '105', 'AMZN': '105', 'META': '105',
    'GOOGL': '105', 'GOOG': '105', 'TSLA': '105', 'NFLX': '105', 'AMD': '105',
    'INTC': '105', 'CSCO': '105', 'TQQQ': '105', 'QQQ': '105', 'RKLB': '105',
    # NYSE / NYSE ARCA
    'CRCL': '106', 'PLTR': '106', 'OKLO': '106', 'TCOM': '106', 'HOOD': '106',
    'PLTU': '106', 'SOXL': '106', 'SOXS': '106', 'RKLX': '106',
    'ROBN': '106', 'MSFU': '106', 'FNGU': '106', 'TECL': '106', 'LABU': '106',
    'LABD': '106', 'NVDL': '106', 'NVDS': '106', 'TSLL': '106', 'TSLS': '106',
}

TIMEOUT = 12
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})


# ── helpers ─────────────────────────────────────────────────────────────────

def _parse_price(s) -> Optional[float]:
    if s is None:
        return None
    s = str(s).replace('$', '').replace(',', '').replace('+', '').strip()
    if s in ('', 'N/A', '--', 'null'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pct(c: float, pc: float) -> float:
    return round((c - pc) / pc * 100, 4) if pc else 0.0


def _prev_trading_day(date_str: str) -> str:
    """Calendar prior trading day (skips weekends; ignores holidays — close enough
    for a date label on a reconstructed prev_close)."""
    d = datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=1)
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d -= timedelta(days=1)
    return d.strftime('%Y-%m-%d')


# ── debug instrumentation (③) ──────────────────────────────────────────────────
# US_FETCH_DEBUG=1 dumps raw Nasdaq + Polygon payloads per ticker to
# memory/.tmp/us_fetch_debug_{date}.jsonl. Captures the source JSON so a transient
# provider glitch (e.g. the 2026-05-29 Nasdaq post-close stale-price swap, where
# lastSalePrice lagged a day while PreviousClose held the real close) can be
# reproduced and any future guard tested against the real payload.
DEBUG_DUMP = os.environ.get('US_FETCH_DEBUG', '').strip().lower() not in ('', '0', 'false', 'no')


def _debug_dump(stage: str, ticker: str, payload) -> None:
    if not DEBUG_DUMP:
        return
    try:
        tmp = os.path.join(WS_ROOT, 'memory', '.tmp')
        os.makedirs(tmp, exist_ok=True)
        now = datetime.now(timezone(timedelta(hours=-4)))
        rec = {'ts': now.isoformat(), 'stage': stage, 'ticker': ticker, 'payload': payload}
        path = os.path.join(tmp, f"us_fetch_debug_{now.strftime('%Y-%m-%d')}.jsonl")
        with open(path, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')
    except Exception:
        pass


def load_api_keys() -> Dict[str, str]:
    keys: Dict[str, str] = {}
    try:
        with open(API_KEYS_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    keys[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return keys


# ── provider functions ───────────────────────────────────────────────────────

def get_nasdaq_quote(ticker: str) -> Optional[Dict]:
    """Nasdaq API – JSON, no auth, covers stocks and ETFs."""
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://www.nasdaq.com',
        'Referer': 'https://www.nasdaq.com/',
    }
    for assetclass in ('stocks', 'etf'):
        try:
            url = f"https://api.nasdaq.com/api/quote/{ticker}/info?assetclass={assetclass}"
            r = SESSION.get(url, headers=headers, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            body = (r.json().get('data') or {})
            _debug_dump('nasdaq', ticker, body)
            primary = body.get('primaryData') or {}
            summary = body.get('summaryData') or {}

            price = _parse_price(primary.get('lastSalePrice'))
            if not price or price <= 0:
                continue

            pc = _parse_price((summary.get('PreviousClose') or {}).get('value')) or price
            op = _parse_price((summary.get('OpenPrice') or {}).get('value')) or price

            high, low = price, price
            day_range = (summary.get('TodayHighLow') or {}).get('value') or ''
            if ' - ' in day_range:
                parts = day_range.split(' - ')
                h = _parse_price(parts[1]) if len(parts) > 1 else None
                lo = _parse_price(parts[0]) if parts else None
                if h:  high = h
                if lo: low  = lo

            pct_str = (primary.get('percentageChange') or '').replace('%', '').replace('+', '').strip()
            dp = float(pct_str) if pct_str and pct_str not in ('N/A', '--') else _pct(price, pc)

            vol_str = (summary.get('ShareVolume') or {}).get('value') or ''
            volume = None
            if vol_str and vol_str not in ('N/A', '--'):
                try:
                    volume = int(vol_str.replace(',', ''))
                except ValueError:
                    pass

            result = {
                'c': price, 'h': high, 'l': low, 'o': op, 'pc': pc,
                'dp': round(dp, 4),
                'source': f'Nasdaq API ({assetclass})',
            }
            if volume:
                result['volume'] = volume
            return result
        except Exception:
            continue
    return None


def get_eastmoney_batch(tickers: List[str]) -> Dict[str, Dict]:
    """Eastmoney push2 batch – no rate limit, CN source."""
    if not tickers:
        return {}
    # Try known prefix first; also build a fallback list with swapped prefix
    secids_primary = [f"{EASTMONEY_PREFIX.get(t, '105')}.{t}" for t in tickers]
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        'fltt': 2, 'invt': 2,
        'fields': 'f12,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18',
        'secids': ','.join(secids_primary),
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
    }
    headers = {'Referer': 'https://quote.eastmoney.com/'}
    results: Dict[str, Dict] = {}
    try:
        r = SESSION.get(url, params=params, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        for item in r.json().get('data', {}).get('diff', []):
            ticker = item.get('f12')
            current = item.get('f2')
            if not ticker or not current or current == '-':
                continue
            c  = float(current)
            pc_raw = item.get('f18')
            pc = float(pc_raw) if pc_raw and pc_raw != '-' else c
            dp = float(item.get('f3') or 0)
            vol = item.get('f5')
            results[ticker] = {
                'c': c, 'pc': pc,
                'h': float(item.get('f15') or c),
                'l': float(item.get('f16') or c),
                'o': float(item.get('f17') or c),
                'dp': dp,
                'name': item.get('f14', ''),
                'volume': int(vol) if vol and vol != '-' else None,
                'source': 'Eastmoney',
            }
    except Exception as e:
        print(f"  ⚠️  Eastmoney batch failed: {e}")

    # Retry tickers with swapped exchange prefix (105↔106)
    missing = [t for t in tickers if t not in results]
    if missing:
        swapped = []
        for t in missing:
            original = EASTMONEY_PREFIX.get(t, '105')
            alt = '106' if original == '105' else '105'
            swapped.append(f"{alt}.{t}")
        try:
            params2 = dict(params)
            params2['secids'] = ','.join(swapped)
            r2 = SESSION.get(url, params=params2, headers=headers, timeout=TIMEOUT)
            r2.raise_for_status()
            for item in r2.json().get('data', {}).get('diff', []):
                ticker = item.get('f12')
                current = item.get('f2')
                if not ticker or not current or current == '-' or ticker in results:
                    continue
                c  = float(current)
                pc_raw = item.get('f18')
                pc = float(pc_raw) if pc_raw and pc_raw != '-' else c
                results[ticker] = {
                    'c': c, 'pc': pc,
                    'h': float(item.get('f15') or c),
                    'l': float(item.get('f16') or c),
                    'o': float(item.get('f17') or c),
                    'dp': float(item.get('f3') or 0),
                    'name': item.get('f14', ''),
                    'volume': int(item['f5']) if item.get('f5') and item['f5'] != '-' else None,
                    'source': 'Eastmoney (alt-prefix)',
                }
        except Exception:
            pass

    return results


def get_finnhub_quote(ticker: str, api_key: str) -> Optional[Dict]:
    """Finnhub real-time quote – needs API key."""
    if not api_key:
        return None
    try:
        r = SESSION.get(
            f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={api_key}",
            timeout=TIMEOUT,
        )
        d = r.json()
        c = d.get('c', 0)
        if c <= 0:
            return None
        pc = d.get('pc', c)
        return {
            'c': float(c), 'pc': float(pc),
            'h': float(d.get('h', c)), 'l': float(d.get('l', c)),
            'o': float(d.get('o', c)),
            'dp': _pct(c, pc),
            'source': 'Finnhub',
        }
    except Exception:
        return None


def get_yahoo_v8_quote(ticker: str) -> Optional[Dict]:
    """Yahoo Finance v8 chart API – no key, may rate-limit."""
    try:
        r = SESSION.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={'interval': '1m', 'range': '1d'},
            timeout=TIMEOUT,
        )
        meta = r.json()['chart']['result'][0]['meta']
        c = meta.get('regularMarketPrice') or meta.get('previousClose')
        if not c or float(c) <= 0:
            return None
        c = float(c)
        pc = float(meta.get('regularMarketPreviousClose') or meta.get('previousClose') or c)
        return {
            'c': c, 'pc': pc,
            'h': float(meta.get('regularMarketDayHigh', c)),
            'l': float(meta.get('regularMarketDayLow', c)),
            'o': float(meta.get('regularMarketOpen', c)),
            'dp': _pct(c, pc),
            'source': 'Yahoo v8',
        }
    except Exception:
        return None


def get_yfinance_quote(ticker: str) -> Optional[Dict]:
    """yfinance library – no key, may rate-limit."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        c = info.get('lastPrice') or info.get('regularMarketPrice')
        if not c or float(c) <= 0:
            return None
        c = float(c)
        pc = float(info.get('regularMarketPreviousClose') or c)
        return {
            'c': c, 'pc': pc,
            'h': float(info.get('dayHigh', c)),
            'l': float(info.get('dayLow', c)),
            'o': float(info.get('open', c)),
            'dp': _pct(c, pc),
            'source': 'yfinance',
        }
    except Exception:
        return None


def get_alpha_vantage_quote(ticker: str, api_key: str) -> Optional[Dict]:
    """Alpha Vantage GLOBAL_QUOTE – needs key, slow (~15s)."""
    if not api_key:
        return None
    try:
        r = SESSION.get(
            'https://www.alphavantage.co/query',
            params={'function': 'GLOBAL_QUOTE', 'symbol': ticker, 'apikey': api_key},
            timeout=25,
        )
        q = r.json().get('Global Quote', {})
        c = _parse_price(q.get('05. price'))
        if not c:
            return None
        pc = _parse_price(q.get('08. previous close')) or c
        return {
            'c': c, 'pc': pc,
            'h': _parse_price(q.get('03. high')) or c,
            'l': _parse_price(q.get('04. low')) or c,
            'o': _parse_price(q.get('02. open')) or c,
            'dp': _pct(c, pc),
            'source': 'Alpha Vantage',
        }
    except Exception:
        return None


def get_polygon_quote(ticker: str, api_key: str) -> Optional[Dict]:
    """Polygon.io prev-close – needs key, last resort."""
    if not api_key:
        return None
    try:
        r = SESSION.get(
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev",
            params={'adjusted': 'true', 'apiKey': api_key},
            timeout=TIMEOUT,
        )
        results = r.json().get('results', [])
        if not results:
            return None
        res = results[0]
        c = float(res['c'])
        return {
            'c': c, 'pc': float(res.get('vw', c)),
            'h': float(res['h']), 'l': float(res['l']), 'o': float(res['o']),
            'dp': 0.0,
            'source': 'Polygon (prev close)',
        }
    except Exception:
        return None


def get_tencent_us_index(symbol: str) -> Optional[Dict]:
    """Fetch a REAL US index level (not an ETF proxy) from Tencent gtimg.

    symbol: 'usINX' (S&P 500), 'usNDX' (Nasdaq-100), 'usDJI' (Dow Jones).
    Tencent returns the actual index points (e.g. SPX 7563, NDX 30223, DJI 50668),
    unlike the SPY/QQQ/DIA ETF proxies whose prices (~754/~735/~507) are NOT index
    points — feeding ETF prices straight into indices_snapshot as the index level
    was the 2026-05-29 bug (DJI showed 507 instead of 50668).

    Returns {'c': price, 'pc': prev_close, 'dp': change_pct} or None.
    """
    try:
        r = SESSION.get(f'https://qt.gtimg.cn/q={symbol}', timeout=TIMEOUT)
        r.encoding = 'utf-8'
        if '="' not in r.text:
            return None
        val = r.text.split('="', 1)[1].split('"', 1)[0]
        f = val.split('~')
        if len(f) < 5:
            return None
        c = _parse_price(f[3]); pc = _parse_price(f[4])
        if c is None or pc is None:
            return None
        return {'c': c, 'pc': pc, 'dp': _pct(c, pc)}
    except Exception:
        return None


def fetch_us_indices() -> Dict[str, Dict]:
    """Fetch SPX / NDX / DJI live quotes — REAL index points, not ETF proxy prices.

    Order: (1) Tencent gtimg real index symbol (usINX/usNDX/usDJI) — works from
    server IPs and returns true index points; (2) yfinance raw index symbol
    (often rate-limited from cloud IPs); (3) last-resort ETF proxy (SPY/QQQ/DIA)
    — its change_pct ≈ the index, but its price is the ETF price, NOT an index
    level, so it's tagged is_etf_proxy and must not be read as a point level.

    Returns dict keyed by short symbol (SPX/NDX/DJI).
    """
    # (tencent_sym, yahoo_idx, etf_proxy, short, display_name)
    symbols = [
        ('usINX', '^GSPC', 'SPY', 'SPX', 'S&P 500'),
        ('usNDX', '^NDX',  'QQQ', 'NDX', 'Nasdaq 100'),
        ('usDJI', '^DJI',  'DIA', 'DJI', 'Dow Jones'),
    ]
    out = {}
    now_et = datetime.now(timezone(timedelta(hours=-4))).strftime('%Y-%m-%d %H:%M ET')
    for tx_sym, yh_sym, etf, short, name in symbols:
        # 1. Tencent real index points (preferred)
        q = get_tencent_us_index(tx_sym)
        src_tag = f'Tencent {tx_sym} index @ {now_et}'
        # 2. yfinance raw index symbol
        if not q or q.get('c') is None:
            q = get_yfinance_quote(yh_sym)
            src_tag = f'yfinance {yh_sym} @ {now_et}'
        # 3. last-resort ETF proxy (price is ETF price, NOT an index level)
        is_proxy = False
        if not q or q.get('c') is None:
            q = get_nasdaq_quote(etf)
            src_tag = f'Nasdaq API {etf} ETF proxy @ {now_et}'
            is_proxy = True
        if not q or q.get('c') is None:
            continue
        entry = {
            'name':       name,
            'price':      round(q['c'], 2),
            'prev_close': round(q.get('pc') or q['c'], 2),
            'change_pct': round(q.get('dp') or 0, 3),
            'source':     src_tag,
        }
        if is_proxy:
            entry['is_etf_proxy'] = etf
            entry['note'] = f'点位为 {etf} ETF 价（真实指数源不可用），仅涨跌%近似指数'
        out[short] = entry
    return out


def get_prev_close_polygon(ticker: str, api_key: str) -> Optional[tuple]:
    """
    Return (prev_trading_day_close, 'YYYY-MM-DD') from Polygon historical.
    Uses the same /prev endpoint but extracts the date from the timestamp,
    giving us a reliable date-stamped previous close separate from live quotes.
    """
    if not api_key:
        return None
    try:
        r = SESSION.get(
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev",
            params={'adjusted': 'true', 'apiKey': api_key},
            timeout=TIMEOUT,
        )
        raw = r.json()
        _debug_dump('polygon_prev', ticker, raw)
        results = raw.get('results', [])
        if not results:
            return None
        res = results[0]
        close = float(res['c'])
        ts_ms = res.get('t', 0)
        if ts_ms:
            date_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
        else:
            date_str = (datetime.now(timezone(timedelta(hours=-4))) - timedelta(days=1)).strftime('%Y-%m-%d')
        return (close, date_str)
    except Exception:
        return None


# ── main fetch logic ─────────────────────────────────────────────────────────

def fetch_us_quotes(tickers: List[str], keys: Dict[str, str]) -> Dict[str, Dict]:
    """
    Fetch US stock quotes using multi-provider fallback.
    Returns {ticker: quote_dict} for all successfully fetched tickers.
    """
    results: Dict[str, Dict] = {}
    remaining = list(tickers)

    def _done(ticker: str, quote: Dict):
        results[ticker] = quote
        remaining.remove(ticker)

    # 1. Nasdaq API (per-ticker, handles stocks + ETFs without prefix guessing)
    print("  [1] Nasdaq API...")
    for t in list(remaining):
        q = get_nasdaq_quote(t)
        if q:
            _done(t, q)
            print(f"      ✓ {t}: ${q['c']:.4f} ({q['dp']:+.2f}%) [{q['source']}]")
    if not remaining:
        return results

    # 2. Eastmoney batch (for whatever Nasdaq missed)
    print(f"  [2] Eastmoney batch for: {', '.join(remaining)}")
    em = get_eastmoney_batch(remaining)
    for t in list(remaining):
        if t in em:
            q = em[t]
            _done(t, q)
            print(f"      ✓ {t}: ${q['c']:.4f} ({q['dp']:+.2f}%) [{q['source']}]")
    if not remaining:
        return results

    # 3. Finnhub
    print(f"  [3] Finnhub for: {', '.join(remaining)}")
    for t in list(remaining):
        q = get_finnhub_quote(t, keys.get('FINNHUB_API_KEY', ''))
        if q:
            _done(t, q)
            print(f"      ✓ {t}: ${q['c']:.4f} ({q['dp']:+.2f}%) [{q['source']}]")
    if not remaining:
        return results

    # 4. Yahoo Finance v8 API
    print(f"  [4] Yahoo v8 for: {', '.join(remaining)}")
    for t in list(remaining):
        q = get_yahoo_v8_quote(t)
        if q:
            _done(t, q)
            print(f"      ✓ {t}: ${q['c']:.4f} ({q['dp']:+.2f}%) [{q['source']}]")
    if not remaining:
        return results

    # 5. yfinance library
    print(f"  [5] yfinance for: {', '.join(remaining)}")
    for t in list(remaining):
        q = get_yfinance_quote(t)
        if q:
            _done(t, q)
            print(f"      ✓ {t}: ${q['c']:.4f} ({q['dp']:+.2f}%) [{q['source']}]")
    if not remaining:
        return results

    # 6. Alpha Vantage (slow, rate-limited at 25 calls/day on free tier)
    print(f"  [6] Alpha Vantage for: {', '.join(remaining)}")
    for t in list(remaining):
        q = get_alpha_vantage_quote(t, keys.get('ALPHA_VANTAGE_API_KEY', ''))
        if q:
            _done(t, q)
            print(f"      ✓ {t}: ${q['c']:.4f} ({q['dp']:+.2f}%) [{q['source']}]")
    if not remaining:
        return results

    # 7. Polygon (prev-close, last resort)
    print(f"  [7] Polygon for: {', '.join(remaining)}")
    for t in list(remaining):
        q = get_polygon_quote(t, keys.get('POLYGON_API_KEY', ''))
        if q:
            _done(t, q)
            print(f"      ✓ {t}: ${q['c']:.4f} (prev close) [{q['source']}]")

    if remaining:
        print(f"  ✗ All providers failed: {', '.join(remaining)}")

    return results


# ── portfolio update ─────────────────────────────────────────────────────────

def update_us_portfolio(
    portfolio_path: str = PORTFOLIO_PATH,
    dry_run: bool = False,
    tickers_override: Optional[List[str]] = None,
) -> Dict:
    """
    Fetch latest US stock prices and write them back to portfolio.json.

    Args:
        portfolio_path:   path to portfolio.json
        dry_run:          if True, print prices but don't write to file
        tickers_override: if given, only fetch these tickers (must still exist in portfolio)
    """
    with open(portfolio_path, encoding='utf-8') as f:
        data = json.load(f)

    keys = load_api_keys()
    us   = data['portfolios']['us_stocks']

    active_holdings = [h for h in us['holdings'] if h.get('shares', 0) > 0]
    all_active      = [h['ticker'] for h in active_holdings]
    tickers         = tickers_override if tickers_override else all_active

    # Zero out snapshot fields on closed positions — refresh skips shares==0
    # holdings, so without this they keep stale cv/pnl from the pre-close run.
    for h in us['holdings']:
        if h.get('shares', 0) == 0:
            for k in ('current_value', 'pnl_abs', 'pnl_percent',
                      'today_change', 'today_change_pct'):
                if h.get(k):
                    h[k] = 0

    # Timezone helpers
    et_tz  = timezone(timedelta(hours=-4))   # EDT; adjust to -5 for EST
    hkt_tz = timezone(timedelta(hours=8))
    now_et  = datetime.now(et_tz)
    now_hkt = datetime.now(hkt_tz)

    today_et_date  = now_et.strftime('%Y-%m-%d')
    three_days_ago = (now_et - timedelta(days=3)).strftime('%Y-%m-%d')

    et_str  = now_et.strftime('%Y-%m-%d %H:%M %Z')
    hkt_str = now_hkt.strftime('%Y/%m/%d %H:%M HKT')

    print(f"\n{'═'*62}")
    print(f"  US Portfolio Price Refresh")
    print(f"  ET:  {et_str}  |  HKT: {hkt_str}")
    print(f"  Tickers: {', '.join(tickers)}")
    print(f"{'═'*62}")

    quotes = fetch_us_quotes(tickers, keys)

    # Fetch dated prev_close from Polygon historical (authoritative, avoids
    # the after-hours trap where live-quote APIs set pc = today's close)
    prev_closes: Dict[str, tuple] = {}
    polygon_key = keys.get('POLYGON_API_KEY', '')
    if polygon_key:
        print(f"  [PC] Polygon prev-close...")
        for t in tickers:
            result = get_prev_close_polygon(t, polygon_key)
            if result:
                prev_closes[t] = result
                print(f"       ✓ {t}: ${result[0]:.4f} ({result[1]})")

    print(f"\n{'─'*62}")
    updated: List[str] = []
    missing: List[str] = []
    source_counts: Dict[str, int] = {}

    for holding in us['holdings']:
        t = holding['ticker']
        if t not in tickers:
            continue
        q = quotes.get(t)
        if not q:
            missing.append(t)
            print(f"  ✗ {t}: no data from any provider")
            continue

        old_price = holding.get('current_price', 0)
        c    = q['c']
        cost = holding['cost_basis']
        shrs = holding['shares']

        # Resolve prev_close with date-stamping:
        # 1st: Polygon historical (date-stamped, immune to after-hours confusion)
        # 2nd: API's pc field if it differs from c (real PreviousClose returned)
        # 3rd: Reconstruct from API's own reported %change — authoritative for "today"
        #      (must come BEFORE the keep-existing branch; otherwise a stale prev_close
        #       set last trading day silently survives into new days when Nasdaq's
        #       PreviousClose field is missing — see ROBN/MSFU 2026-05-18 bug)
        # 4th: keep existing prev_close if it's fresh and we have no other source
        # Ticker-reuse / fresh-IPO trap (SPCX 2026-06-12): a "previous close" bar
        # dated weeks ago is the *old* instrument that used to own this ticker —
        # a day-change computed against it is fiction (SPCX showed +637%).
        poly_pc = prev_closes.get(t)
        if poly_pc and poly_pc[1] < three_days_ago:
            print(f"  ⚠ {t}: Polygon prev_close dated {poly_pc[1]} (< {three_days_ago}) "
                  f"— stale bar / ticker reuse, ignoring")
            poly_pc = None
        if poly_pc:
            pc, pc_date = poly_pc
            # ── Post-close authority + stale-current guard (①②) ──────────────────
            # When Polygon's "prev close" date == today, the market has closed and
            # Polygon's bar IS today's official close (not yesterday's). Two traps
            # follow — see memory/openclaw-us-postclose-stale-price-swap.md (2026-05-29):
            #   ① Nasdaq lastSalePrice can lag at a stale prior-day value while
            #      Polygon holds the real close (MSFU 28.01 vs real 29.92) →
            #      trust Polygon's official close as current_price.
            #   ② With pc == today's close, today_change collapses to 0 → rebuild the
            #      real prev_close from the prior session.
            if pc_date == today_et_date:
                poly_close = pc
                if poly_close > 0 and abs(c - poly_close) / poly_close > 0.005:
                    print(f"  ⚠ {t}: Nasdaq last ${c:.4f} deviates "
                          f"{(c - poly_close) / poly_close * 100:+.2f}% from Polygon close "
                          f"${poly_close:.4f} → using Polygon (stale-quote guard ①)")
                    c = poly_close
                # ② prior-session close: prefer the existing dated prev_close (an
                # independent capture from a run before today's bar finalized — robust
                # even if Nasdaq's %change is also stale), then Nasdaq dp, then no-op.
                existing_pc      = holding.get('prev_close', 0)
                existing_pc_date = holding.get('prev_close_date', '')
                api_dp           = q.get('dp', 0)
                if existing_pc > 0 and existing_pc_date and \
                        three_days_ago <= existing_pc_date < today_et_date:
                    pc, pc_date = existing_pc, existing_pc_date
                elif api_dp and abs(api_dp) > 0.01:
                    pc = round(c / (1 + api_dp / 100), 4)
                    pc_date = _prev_trading_day(today_et_date)
                # else: leave pc = today's close (today_change falls back to 0, safe)
        else:
            api_pc = q.get('pc', c)
            existing_pc      = holding.get('prev_close', 0)
            existing_pc_date = holding.get('prev_close_date', '')
            api_dp = q.get('dp', 0)
            if api_pc != c:
                pc, pc_date = api_pc, today_et_date
            elif api_dp and abs(api_dp) > 0.01:
                pc = round(c / (1 + api_dp / 100), 4)
                pc_date = today_et_date
            elif existing_pc > 0 and existing_pc != c and existing_pc_date >= three_days_ago:
                pc, pc_date = existing_pc, existing_pc_date
            else:
                pc, pc_date = c, today_et_date

        # ③ degenerate-range warning: a live regular-session quote with
        # open==high==low==close has no intraday range → likely a stale/frozen
        # quote (the tell-tale signature of the 2026-05-29 swap). Warn-only.
        if 9 <= now_et.hour < 16:
            o_, h_, l_ = q.get('o'), q.get('h'), q.get('l')
            if None not in (o_, h_, l_) and o_ == h_ == l_ == q['c']:
                print(f"  ⚠ {t}: degenerate range (o=h=l=c=${q['c']:.4f}) mid-session "
                      f"— possible stale quote (run with US_FETCH_DEBUG=1 to capture payload)")

        holding['current_price']    = round(c, 4)
        holding['prev_close']       = round(pc, 4)
        holding['prev_close_date']  = pc_date
        # Fresh-lot detection: when the ENTIRE current position was acquired
        # today, prev_close belongs to a lot you no longer hold — either an IPO
        # reference price you never got (SPCX 2026-06-12, prev_close was a stale
        # reused-ticker bar → +637%), or a pre-clearance close from before a
        # same-day re-entry (RKLX 2026-06-12: re-bought 10@52.3 after the April
        # lot was fully sold; prev_close 61.67 from 6/11 made today_change read
        # -21.7% vs the real -7.6% from entry). Compare held shares against
        # shares bought today; old sold-out buys still in trades[] don't count
        # because they net to zero against their matching sells. Using a simple
        # "all buy trades are today" test misses this re-entry case.
        shares_bought_today = sum(
            (t.get('shares') or 0)
            for t in (holding.get('trades') or [])
            if t.get('action') == 'buy' and t.get('date') == today_et_date)
        all_bought_today = shares_bought_today > 0 and shares_bought_today >= shrs
        tc_ref = cost if all_bought_today else pc
        holding['today_change_pct'] = round(_pct(c, tc_ref), 4)

        # ── session-aware running day range ───────────────────────────────────
        # Nasdaq's quote payload often carries no real intraday h/l/o (the old
        # `q.get('h', c)` fallback flattened them to the last price each fetch →
        # o==h==l==c, and after any move even day_high < current_price — visibly
        # impossible numbers on the dashboard's Today's Range card). The */30min
        # intraday cadence lets us accumulate the true session envelope locally:
        # first capture of the ET day pins the open, every later fetch stretches
        # high/low with both the API values and the live price. The live price
        # only grows the range during regular session hours so a stray
        # pre/post-market print doesn't fake an intraday extreme.
        api_h, api_l, api_o = q.get('h'), q.get('l'), q.get('o')
        in_session   = 9 <= now_et.hour < 16
        same_session = holding.get('day_session_date') == today_et_date
        cands_h = [v for v in (api_h, c if in_session else None) if v]
        cands_l = [v for v in (api_l, c if in_session else None) if v]
        if same_session:
            if holding.get('day_high'):
                cands_h.append(holding['day_high'])
            if holding.get('day_low'):
                cands_l.append(holding['day_low'])
            day_o = holding.get('day_open') or api_o or c
        else:
            day_o = api_o or c
        holding['day_high'] = round(max(cands_h) if cands_h else c, 4)
        holding['day_low']  = round(min(cands_l) if cands_l else c, 4)
        holding['day_open'] = round(day_o, 4)
        holding['day_session_date'] = today_et_date
        holding['current_value']    = round(c * shrs, 2)
        holding['pnl_abs']          = round((c - cost) * shrs, 2)
        holding['pnl_percent']      = round((c - cost) / cost * 100, 4)
        holding['today_change']     = round((c - tc_ref) * shrs, 2)
        if q.get('volume'):
            holding['volume'] = q['volume']

        ts = now_et.strftime('%b %d, %Y %H:%M ET')
        holding['data_source'] = f"{q['source']} {ts}"

        src = q['source']
        source_counts[src] = source_counts.get(src, 0) + 1
        updated.append(t)

        arrow = '↑' if c >= old_price else '↓'
        pnl_sign = '+' if holding['pnl_abs'] >= 0 else ''
        print(f"  {t:7s}  ${old_price:.4f} {arrow} ${c:.4f}  "
              f"({holding['today_change_pct']:+.2f}%)  "
              f"P&L: {pnl_sign}${holding['pnl_abs']:.2f} ({pnl_sign}{holding['pnl_percent']:.2f}%)")

    # Recompute portfolio totals from all active holdings
    all_active_h = [h for h in us['holdings'] if h.get('shares', 0) > 0]
    total_cost  = sum(h['cost_basis'] * h['shares'] for h in all_active_h)
    total_value = sum(h.get('current_value', h['cost_basis'] * h['shares']) for h in all_active_h)
    total_pnl   = total_value - total_cost
    today_chg   = sum(h.get('today_change', 0) for h in all_active_h)

    us['total_cost']          = round(total_cost, 2)
    us['total_current_value'] = round(total_value, 2)
    us['total_pnl']           = round(total_pnl, 2)
    us['total_pnl_percent']   = round(total_pnl / total_cost * 100, 4) if total_cost else 0
    us['today_total_change']  = round(today_chg, 2)

    # Determine session label
    h_et = now_et.hour
    if   4  <= h_et <  9:  session = 'premarket'
    elif 9  <= h_et < 16:  session = 'open'
    elif 16 <= h_et < 20:  session = 'afterhours'
    else:                   session = 'closed'

    status = {
        'attempted_all_holdings': all_active,
        'active_holdings':        tickers,
        'updated':                updated,
        'missing_after_fallback': missing,
        'source_counts':          source_counts,
        'updated_at':             et_str,
        'note': (
            f"Multi-provider fetch. Sources: "
            + ', '.join(f"{v}x {k}" for k, v in source_counts.items())
        ),
    }
    us[f'{session}_fetch_status']    = status
    us[f'last_{session}_attempted']  = et_str

    data['last_updated'] = hkt_str

    print(f"{'─'*62}")
    pnl_sign = '+' if total_pnl >= 0 else ''
    print(f"  Total value:    ${total_value:>10,.2f}  (cost: ${total_cost:,.2f})")
    print(f"  Total P&L:      {pnl_sign}${total_pnl:>9,.2f}  ({pnl_sign}{total_pnl/total_cost*100:.2f}%)" if total_cost else "")
    print(f"  Today change:   ${today_chg:>+10,.2f}")
    print(f"  Updated:        {', '.join(updated)}")
    if missing:
        print(f"  ⚠️  Failed:    {', '.join(missing)}")

    # Refresh US indices_snapshot (SPX/NDX/DJI) — was a manual web-search stub before
    try:
        idx = fetch_us_indices()
        if idx:
            us['indices_snapshot'] = idx
            summary = ' · '.join(
                f"{k} {v['price']} ({v['change_pct']:+.2f}%)"
                for k, v in idx.items()
            )
            print(f"  Indices:        {summary}")
    except Exception as e:
        print(f"  ⚠ US indices fetch failed (non-fatal): {e}")

    if dry_run:
        print("\n  [dry-run] portfolio.json NOT written.\n")
    else:
        from safe_io import mutate_json
        from recompute_realized import recompute as recompute_realized
        recompute_realized(data)
        # 锁内重读、只覆盖自己拥有的 us_stocks 区 + 顶层 last_updated 戳，保住并发
        # 写者(gold/hk)的字段 [cut #2]（last_updated 是顶层键，别随 region-overlay 丢）
        mutate_json(portfolio_path, lambda d: {
            **d, 'last_updated': data.get('last_updated', d.get('last_updated')),
            'portfolios': {**d.get('portfolios', {}),
                           'us_stocks': data['portfolios']['us_stocks']}})
        print(f"\n  ✅ Saved → {portfolio_path}")

    print(f"{'═'*62}\n")
    return data


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    args      = [a for a in sys.argv[1:] if not a.startswith('--')]
    dry_run   = '--dry-run' in sys.argv
    overrides = args if args else None
    update_us_portfolio(dry_run=dry_run, tickers_override=overrides)
