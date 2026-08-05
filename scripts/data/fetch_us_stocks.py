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
import fcntl
import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bar_checks  # noqa: E402  shared "is this bar believable" contract
from _em_http import em_get  # noqa: E402
from instrument_registry import INSTRUMENTS  # noqa: E402
import trading_calendar  # noqa: E402

WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORTFOLIO_PATH = os.path.join(WS_ROOT, 'portfolio.json')
API_KEYS_PATH  = os.path.join(WS_ROOT, '.api_keys')
POLYGON_PREV_CACHE_DIR = Path(WS_ROOT) / 'memory' / '.tmp' / 'polygon-prev-close'
POLYGON_CACHE_SCHEMA_VERSION = 1

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
# Registry entries override the broad fallback table for held/canonical names.
EASTMONEY_PREFIX.update({
    symbol: meta['eastmoney_secid'].split('.', 1)[0]
    for symbol, meta in INSTRUMENTS.items()
    if meta['region'] == 'US' and meta.get('eastmoney_secid')
})

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


def _parse_nasdaq_ts(s) -> Optional[str]:
    """'Jul 27, 2026 9:34 AM ET' / 'Jul 23, 2026' -> '2026-07-27' / '2026-07-23'.

    Nasdaq stamps every quote with the time of the print it is serving, and for
    thin instruments that print can be days old (verified 2026-07-27 11:12 ET:
    SPCH was still serving a Jul 22 10:22 ET trade, PLTU and CRCL a Jul 23 one).
    This is the direct, unambiguous staleness signal and nothing was reading it.
    """
    if not s:
        return None
    text = str(s).strip().replace(' ET', '')
    for fmt in ('%b %d, %Y %I:%M %p', '%b %d, %Y'):
        try:
            return datetime.strptime(text, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None


def _quote_is_fresh(q: Optional[Dict], today_et_date: str) -> bool:
    """False only when the provider itself dates the print before today.

    Deliberately not inferred from the numbers: a provider that tells you the
    trade is four days old is stating a fact, whereas `current_price ==
    prev_close` is only a strong hint. Quotes that carry no timestamp are
    treated as fresh — absence of evidence must not fail a healthy provider.
    """
    if not q:
        return False
    asof = q.get('asof_date')
    return not (asof and asof < today_et_date)


def _quote_is_complete(q: Optional[Dict]) -> bool:
    """A quote is usable on its own only if it carries a real prior close AND a
    real intraday range.

    Nasdaq `/info` returns neither (see get_nasdaq_quote), so before this check
    existed it always won the provider race at position #1 and Eastmoney /
    Finnhub — which both return true o/h/l/pc — were never reached. An
    incomplete quote is still better than nothing, so the caller keeps it as a
    last resort rather than discarding it.
    """
    if not q:
        return False
    return q.get('pc') is not None and q.get('h') is not None and q.get('l') is not None


def _prev_trading_day(date_str: str) -> str:
    """Actual prior US trading session from the shared exchange calendar."""
    return trading_calendar.previous_trading_day(
        'us', date.fromisoformat(date_str)
    ).isoformat()


def _us_quote_session_date(at: Optional[datetime] = None) -> str:
    """US session represented by a live/latest quote at wall-clock ``at``.

    Before 09:30 ET (and on closed days), providers still describe the latest
    completed session. Treating midnight Tuesday as Tuesday's session stamps a
    Monday close against Monday itself and rejects Friday's valid prior close.
    """
    et = at.astimezone(ZoneInfo('America/New_York')) if at else \
        datetime.now(ZoneInfo('America/New_York'))
    current = et.date()
    regular_open = (et.hour, et.minute) >= (9, 30)
    if regular_open and trading_calendar.is_trading_day('us', current):
        return current.isoformat()
    return trading_calendar.previous_trading_day('us', current).isoformat()


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
    """Nasdaq API – JSON, no auth, covers stocks and ETFs.

    The `/info` endpoint carries NO `summaryData` block (verified 2026-07-27 for
    stocks and etf assetclasses: its data keys are symbol/companyName/stockType/
    exchange/isNasdaqListed/isNasdaq100/isHeld/primaryData/secondaryData/
    marketStatus/assetClass/keyStats/notifications). PreviousClose / OpenPrice /
    TodayHighLow live on the separate `/summary` endpoint. The previous
    `_parse_price(...) or price` fallbacks therefore fired on EVERY call and
    silently manufactured `o == h == l == c == pc` — which (a) made the
    degenerate-range alarm fire for 100% of tickers, so it warned about nothing,
    and (b) let a stale `lastSalePrice` sail through as "unchanged today".

    So: report only what the payload actually contains. Missing fields stay
    None and the caller decides (see `_quote_is_complete` → try a richer
    provider). `nc` (netChange) is kept because it is exact and is the only
    reliable way to rebuild a prior close from this endpoint.
    """
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

            # No `or price` fallbacks: absent means absent (see docstring).
            pc = _parse_price((summary.get('PreviousClose') or {}).get('value'))
            op = _parse_price((summary.get('OpenPrice') or {}).get('value'))

            high = low = None
            day_range = (summary.get('TodayHighLow') or {}).get('value') or ''
            if ' - ' in day_range:
                parts = day_range.split(' - ')
                high = _parse_price(parts[1]) if len(parts) > 1 else None
                low  = _parse_price(parts[0]) if parts else None

            nc = _parse_price(primary.get('netChange'))
            pct_str = (primary.get('percentageChange') or '').replace('%', '').replace('+', '').strip()
            if pct_str and pct_str not in ('N/A', '--'):
                dp = float(pct_str)
            elif pc:
                dp = _pct(price, pc)
            else:
                dp = 0.0

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
            if nc is not None:
                result['nc'] = nc
            asof = _parse_nasdaq_ts(primary.get('lastTradeTimestamp'))
            if asof:
                result['asof_date'] = asof
            if volume:
                result['volume'] = volume
            return result
        except Exception:
            continue
    return None


def get_eastmoney_batch(tickers: List[str]) -> Dict[str, Dict]:
    """Eastmoney push2 batch through the shared serialized anti-ban client."""
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
        r = em_get(url, params=params, headers=headers, timeout=TIMEOUT,
                   label='US quote batch')
        if r is None:
            raise RuntimeError('shared Eastmoney client exhausted retries')
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
            r2 = em_get(url, params=params2, headers=headers, timeout=TIMEOUT,
                        label='US quote alt-prefix batch')
            if r2 is None:
                raise RuntimeError('shared Eastmoney client exhausted retries')
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
    """Alpha Vantage GLOBAL_QUOTE – needs key, slow (~15s).

    GLOBAL_QUOTE is a DAILY-BAR endpoint, not a live tick: mid-session it can
    still be serving yesterday's completed bar, and every field in the payload
    then belongs to that prior session — including `10. change percent`, whose
    baseline is the close *before* it. 2026-08-05 12:01 ET it answered PLTU with
    the 08-04 bar (price 44.82, previous close 28.39, +57.87%) while the stock
    was actually trading at 43.65.

    `07. latest trading day` is the payload's own statement of which session it
    describes, and nothing was reading it — so the quote carried no `asof_date`
    and `_quote_is_fresh` (correctly) treated a timestamp-less quote as current.
    Reporting it lets the freshness gate do its job, and lets the stale-last
    guard see that this quote's %change is measured against a different close
    than ours (see the baseline check in update_us_portfolio).
    """
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
        quote = {
            'c': c, 'pc': pc,
            'h': _parse_price(q.get('03. high')) or c,
            'l': _parse_price(q.get('04. low')) or c,
            'o': _parse_price(q.get('02. open')) or c,
            'dp': _pct(c, pc),
            'source': 'Alpha Vantage',
        }
        asof = (q.get('07. latest trading day') or '').strip()
        if asof:
            quote['asof_date'] = asof
        return quote
    except Exception:
        return None


def get_polygon_quote(ticker: str, api_key: str) -> Optional[Dict]:
    """Polygon.io prev-close – needs key, last resort.

    This endpoint returns the PRIOR SESSION's daily bar. Every field it gives
    back therefore describes that session: `c` is yesterday's close, `o/h/l` is
    yesterday's range. Reported as-is it reads exactly like a healthy live quote
    that happens to be flat, which is what it did on 2026-08-05 14:30 ET when it
    was the only provider left standing: PLTU showed 44.82 / +0.00% against a
    real 43.04 / -3.97%, and yesterday's low (36.265) went into today's range
    accumulator, where it survives the rest of the session (#336).

    So it states its own age (`asof_date` from the bar's timestamp) and lets the
    freshness gate decide. Two related corrections:

    * `pc` is None, not `vw`. The volume-weighted average price of the prior
      session is not the close before it — it was never a prior close, and the
      only reason it never produced a wrong day-change is that `dp` is hardcoded
      to 0. Absent means absent (#139).
    * `dp` stays 0.0 and is honest: with no live price there is no move to report.
    """
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
        quote = {
            'c': float(res['c']), 'pc': None,
            'h': float(res['h']), 'l': float(res['l']), 'o': float(res['o']),
            'dp': 0.0,
            'source': 'Polygon (prev close)',
        }
        bar_ms = res.get('t')
        if bar_ms:
            quote['asof_date'] = datetime.fromtimestamp(
                bar_ms / 1000, ZoneInfo('America/New_York')).date().isoformat()
        return quote
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
    except Exception as e:
        print(f"  ⚠ Polygon prev-close {ticker} failed: {type(e).__name__}: {e}",
              file=sys.stderr)
        return None


def _polygon_cache_path(session_date: str, cache_dir: Optional[Path] = None) -> Path:
    return Path(cache_dir or POLYGON_PREV_CACHE_DIR) / f'{session_date}.json'


def _load_polygon_cache(session_date: str, cache_dir: Optional[Path] = None):
    path = _polygon_cache_path(session_date, cache_dir)
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        closes = payload.get('closes')
        if (
            payload.get('schema_version') != POLYGON_CACHE_SCHEMA_VERSION
            or payload.get('session_date') != session_date
            or payload.get('source') != 'Polygon grouped'
            or not isinstance(closes, dict)
            or not closes
            or payload.get('result_count') != len(closes)
            or any(not isinstance(value, (int, float)) or value <= 0
                   for value in closes.values())
        ):
            return None
        datetime.fromisoformat(payload['fetched_at'])
        return payload
    except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError, ValueError,
            TypeError):
        return None


def _write_polygon_cache(payload: Dict, cache_dir: Optional[Path] = None) -> None:
    path = _polygon_cache_path(payload['session_date'], cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f'.tmp.{os.getpid()}')
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n',
        encoding='utf-8',
    )
    os.replace(tmp, path)


def _cached_polygon_result(payload: Dict, tickers: List[str], cache_hit: bool):
    session_date = payload['session_date']
    fetched = datetime.fromisoformat(payload['fetched_at'])
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age = max(0, int((datetime.now(timezone.utc) - fetched).total_seconds()))
    print(
        f"  [PC] cache_hit={str(cache_hit).lower()} session={session_date} "
        f"source={payload['source']} age={age}s "
        f"rows={payload.get('result_count', len(payload['closes']))} "
        f"bytes={payload.get('response_bytes', 0)}"
    )
    return {
        ticker: (float(payload['closes'][ticker]), session_date)
        for ticker in tickers
        if ticker in payload['closes']
    }


def get_prev_closes_polygon_grouped(
    tickers: List[str], api_key: str, quote_session_date: str,
    max_lookback: int = 6, cache_dir: Optional[Path] = None,
) -> tuple:
    """Return prior closes from one session-keyed grouped snapshot.

    ``quote_session_date`` is the trading session represented by current quotes,
    not necessarily today's wall-clock date. Its actual previous US session is
    resolved before selecting the cache. The cache stores the complete Polygon
    map (not only today's holdings), so every scheduled/manual caller shares one
    immutable download.

    Returns ``(ticker_map, rate_limited, snapshot_valid)``. Per-ticker fallback
    is allowed only when ``snapshot_valid`` is true and the symbol is genuinely
    absent from that grouped snapshot.
    """
    del max_lookback  # retained for call compatibility; calendar owns lookback
    if not api_key or not tickers:
        return {}, False, False
    session_date = _prev_trading_day(quote_session_date)
    cached = _load_polygon_cache(session_date, cache_dir)
    if cached:
        return _cached_polygon_result(cached, tickers, True), False, True

    cache_path = _polygon_cache_path(session_date, cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = cache_path.with_suffix('.lock')
    with lock_path.open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        # Another process may have populated the session while this caller waited.
        cached = _load_polygon_cache(session_date, cache_dir)
        if cached:
            return _cached_polygon_result(cached, tickers, True), False, True
        try:
            r = SESSION.get(
                f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{session_date}",
                params={'adjusted': 'true', 'apiKey': api_key},
                timeout=max(TIMEOUT, 30),
            )
            if r.status_code == 429:
                print(
                    f"  ⚠ Polygon grouped {session_date}: HTTP 429 rate limited — "
                    "cache unchanged",
                    file=sys.stderr,
                )
                return {}, True, False
            if r.status_code != 200:
                print(
                    f"  ⚠ Polygon grouped {session_date}: HTTP {r.status_code} "
                    f"{getattr(r, 'text', '')[:120]} — cache unchanged",
                    file=sys.stderr,
                )
                return {}, False, False
            raw = r.json()
        except Exception as exc:
            print(
                f"  ⚠ Polygon grouped {session_date} failed: "
                f"{type(exc).__name__}: {exc} — cache unchanged",
                file=sys.stderr,
            )
            return {}, False, False

        results = raw.get('results') or []
        closes = {}
        for result in results:
            ticker, close = result.get('T'), result.get('c')
            try:
                close = float(close)
            except (TypeError, ValueError):
                continue
            if ticker and close > 0:
                closes[str(ticker)] = close
        if not closes:
            print(
                f"  ⚠ Polygon grouped {session_date}: empty/invalid snapshot — "
                "cache unchanged",
                file=sys.stderr,
            )
            return {}, False, False

        try:
            response_bytes = len(r.content)
        except Exception:
            response_bytes = len(json.dumps(raw, separators=(',', ':')).encode())
        payload = {
            'schema_version': POLYGON_CACHE_SCHEMA_VERSION,
            'session_date': session_date,
            'source': 'Polygon grouped',
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'result_count': len(closes),
            'response_bytes': response_bytes,
            'closes': closes,
        }
        _write_polygon_cache(payload, cache_dir)
        _debug_dump('polygon_grouped', session_date, {'resultsCount': len(closes)})
        return _cached_polygon_result(payload, tickers, False), False, True


# ── main fetch logic ─────────────────────────────────────────────────────────

def fetch_us_quotes(tickers: List[str], keys: Dict[str, str]) -> Dict[str, Dict]:
    """
    Fetch US stock quotes using multi-provider fallback.
    Returns {ticker: quote_dict} for all successfully fetched tickers.

    A provider only *wins* a ticker with a complete quote (prior close + real
    intraday range). Incomplete quotes are parked in `partial` and applied at
    the end for whatever no richer provider could serve, so Nasdaq's
    range-less payload no longer blocks Eastmoney/Finnhub.
    """
    results: Dict[str, Dict] = {}
    partial: Dict[str, Dict] = {}
    stale: Dict[str, Dict] = {}
    today_et_date = _us_quote_session_date()
    remaining = list(tickers)

    def _done(ticker: str, quote: Dict):
        results[ticker] = quote
        remaining.remove(ticker)

    def _offer(ticker: str, quote: Optional[Dict]) -> bool:
        """Accept a fresh, complete quote; park anything else and keep looking."""
        if not quote:
            return False
        if not _quote_is_fresh(quote, today_et_date):
            # The provider dated this print before today. Park it far behind an
            # incomplete-but-current quote: a rangeless price from this session
            # beats an exact price from four sessions ago.
            stale.setdefault(ticker, quote)
            print(f"      ✗ {ticker}: ${quote['c']:.4f} [{quote['source']}] "
                  f"last trade dated {quote['asof_date']} (< {today_et_date}) "
                  f"— stale print, rejected", file=sys.stderr)
            return False
        if _quote_is_complete(quote):
            _done(ticker, quote)
            print(f"      ✓ {ticker}: ${quote['c']:.4f} ({quote['dp']:+.2f}%) [{quote['source']}]")
            return True
        partial.setdefault(ticker, quote)
        missing = [k for k in ('pc', 'h', 'l') if quote.get(k) is None]
        print(f"      ~ {ticker}: ${quote['c']:.4f} ({quote['dp']:+.2f}%) [{quote['source']}] "
              f"incomplete (no {'/'.join(missing)}) — trying a richer provider")
        return False

    # 1. Nasdaq API (per-ticker, handles stocks + ETFs without prefix guessing)
    print("  [1] Nasdaq API...")
    for t in list(remaining):
        _offer(t, get_nasdaq_quote(t))
    if not remaining:
        return results

    # 2. Eastmoney batch (for whatever Nasdaq missed)
    print(f"  [2] Eastmoney batch for: {', '.join(remaining)}")
    em = get_eastmoney_batch(remaining)
    for t in list(remaining):
        if t in em:
            _offer(t, em[t])
    if not remaining:
        return results

    # 3. Finnhub
    print(f"  [3] Finnhub for: {', '.join(remaining)}")
    for t in list(remaining):
        _offer(t, get_finnhub_quote(t, keys.get('FINNHUB_API_KEY', '')))
    if not remaining:
        return results

    # 4. Yahoo Finance v8 API
    print(f"  [4] Yahoo v8 for: {', '.join(remaining)}")
    for t in list(remaining):
        _offer(t, get_yahoo_v8_quote(t))
    if not remaining:
        return results

    # 5. yfinance library
    print(f"  [5] yfinance for: {', '.join(remaining)}")
    for t in list(remaining):
        _offer(t, get_yfinance_quote(t))
    if not remaining:
        return results

    # 6. Alpha Vantage (slow, rate-limited at 25 calls/day on free tier)
    print(f"  [6] Alpha Vantage for: {', '.join(remaining)}")
    for t in list(remaining):
        _offer(t, get_alpha_vantage_quote(t, keys.get('ALPHA_VANTAGE_API_KEY', '')))
    if not remaining:
        return results

    # 7. Polygon (prev-close, last resort)
    #
    # Through `_offer` like every other provider. This branch used to call
    # `_done` directly, which is the whole of #336: a prior-session daily bar
    # skipped both the freshness and the completeness gate and was recorded as a
    # healthy, flat, current quote — price, range and all. It still gets used
    # when nothing else answered; it now arrives at step 8 labelled, so the
    # range accumulator and the stale-quote guard can both see what it is.
    print(f"  [7] Polygon for: {', '.join(remaining)}")
    for t in list(remaining):
        _offer(t, get_polygon_quote(t, keys.get('POLYGON_API_KEY', '')))

    # 8. fall back to the best quote we had to reject — a price without a range
    #    still beats no price, but it must be labelled so the caller does not
    #    read the missing fields as "flat today". Current-but-incomplete first;
    #    a print from an earlier session is the true last resort.
    for t in list(remaining):
        if t in partial:
            q = dict(partial[t])
            q['incomplete'] = True
            _done(t, q)
            print(f"      ⚠ {t}: ${q['c']:.4f} ({q['dp']:+.2f}%) [{q['source']}] "
                  f"— incomplete quote, no richer provider answered")
        elif t in stale:
            q = dict(stale[t])
            q['incomplete'] = True
            q['stale_asof'] = q.get('asof_date')
            _done(t, q)
            print(f"      ⚠ {t}: ${q['c']:.4f} [{q['source']}] — every provider "
                  f"failed; using a print dated {q['stale_asof']}", file=sys.stderr)

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
    et_tz  = ZoneInfo('America/New_York')
    hkt_tz = ZoneInfo('Asia/Hong_Kong')
    now_et  = datetime.now(et_tz)
    now_hkt = datetime.now(hkt_tz)

    # The quote's session can differ from the wall-clock date before 09:30 ET,
    # on weekends, and after holidays. Every range/prev-close date below is keyed
    # to the quote session, never to midnight.
    today_et_date = _us_quote_session_date(now_et)
    expected_prev_session = _prev_trading_day(today_et_date)

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
        print(f"  [PC] Polygon prev-close (grouped)...")
        prev_closes, rate_limited, snapshot_valid = get_prev_closes_polygon_grouped(
            tickers, polygon_key, today_et_date)
        for t, result in prev_closes.items():
            print(f"       ✓ {t}: ${result[0]:.4f} ({result[1]})")
        # Per-ticker fallback for anything the grouped session did not list
        # (rare: non-NMS venues). Bounded to the misses, so the 5/min free-tier
        # limit stays out of reach — and skipped entirely once we know the quota
        # is already gone, since those calls would just 429 as well.
        missing = [t for t in tickers if t not in prev_closes]
        if missing and rate_limited:
            print(f"       ⚠ Polygon rate limited — no dated prior close for "
                  f"{', '.join(missing)}; prev_close falls back to the quote "
                  f"provider's own field", file=sys.stderr)
        elif missing and snapshot_valid:
            for t in missing:
                result = get_prev_close_polygon(t, polygon_key)
                if result and result[1] == expected_prev_session:
                    prev_closes[t] = result
                    print(f"       ✓ {t}: ${result[0]:.4f} ({result[1]}) [per-ticker]")
                elif result:
                    print(
                        f"       ✗ {t}: per-ticker Polygon bar {result[1]} "
                        f"does not match expected prior session "
                        f"{expected_prev_session}",
                        file=sys.stderr,
                    )
                else:
                    print(f"       ✗ {t}: no Polygon prior close", file=sys.stderr)
        elif missing:
            print(
                f"       ⚠ Polygon grouped snapshot unavailable — skip per-ticker "
                f"fallback because absence of {', '.join(missing)} is unproven",
                file=sys.stderr,
            )

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
        if poly_pc and poly_pc[1] < expected_prev_session:
            print(f"  ⚠ {t}: Polygon prev_close dated {poly_pc[1]} "
                  f"(< expected session {expected_prev_session}) "
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
                        existing_pc_date == expected_prev_session:
                    pc, pc_date = existing_pc, existing_pc_date
                elif api_dp and abs(api_dp) > 0.01:
                    pc = round(c / (1 + api_dp / 100), 4)
                    pc_date = expected_prev_session
                # else: leave pc = today's close (today_change falls back to 0, safe)
        else:
            # A prior close belongs to the PRIOR session, so it is stamped with
            # _prev_trading_day() — never today. Stamping today_et_date here (the
            # old behaviour) produced holdings whose prev_close_date equalled
            # day_session_date, an impossible state that also tripped
            # preflight_integrity's `opened_this_session` exemption and switched
            # off the TODAY_LEG gate for exactly the rows this bug had touched.
            prev_session = expected_prev_session
            api_pc = q.get('pc')
            existing_pc      = holding.get('prev_close', 0)
            existing_pc_date = holding.get('prev_close_date', '')
            api_dp = q.get('dp', 0)
            if api_pc is not None and api_pc != c:
                pc, pc_date = api_pc, prev_session
            elif api_dp and abs(api_dp) > 0.01:
                pc = round(c / (1 + api_dp / 100), 4)
                pc_date = prev_session
            elif (existing_pc > 0 and existing_pc != c
                  and existing_pc_date == expected_prev_session):
                pc, pc_date = existing_pc, existing_pc_date
            else:
                pc, pc_date = c, prev_session

        # ── stale-last guard ④: last price identical to the PRIOR session close ──
        # Nasdaq's lastSalePrice intermittently reverts to the prior close for
        # thin / leveraged instruments. When it does, `c == pc` and every derived
        # number agrees with every other one — today_change is 0, TODAY_LEG's
        # `today_change == shares*(cur-prev_close)` holds exactly, and STALENESS
        # passes because the data_source *timestamp* is fresh even though the
        # *price* is not. A self-consistent lie clears every existing gate.
        #
        # Two independent prices matching to four decimals is ~impossible for a
        # normally traded instrument, so treat it as stale whenever the provider
        # itself reports a move. netChange rebuilds the true last exactly
        # (2026-07-27 PLTU: pc 27.35 + nc 1.47 = 28.82, the real print, against a
        # reported 27.35 that showed the position as flat on a +6.3% day);
        # percentageChange is the rounder fallback.
        #
        # The rebuild is arithmetic only while the provider measured its move
        # against the SAME prior close we hold. When it did not, `pc + nc` /
        # `pc × (1+dp)` composes two different sessions and INVENTS a price that
        # never traded — a far worse failure than the flat reading this guard
        # exists to fix, and one that is just as self-consistent afterwards
        # (2026-08-06 PLTU, #332: Alpha Vantage served the 08-04 daily bar —
        # price 44.82, its own previous close 28.39, +57.87% — against our
        # correct 08-04 close of 44.82, and the guard rebuilt $70.7585 on a day
        # the stock traded 42.61–46.76). So the repair requires the provider's
        # own prior close to agree with ours, and refuses outright on a quote
        # the fetch layer already knows is a print from an earlier session.
        # A refused repair still surfaces: `current_price == prev_close` is
        # exactly what preflight_integrity's STALE_PRICE gate reports.
        stale_repair = None
        api_dp_now = q.get('dp') or 0
        provider_pc = q.get('pc')
        prior_session_print = bool(q.get('stale_asof'))
        baseline_matches = provider_pc is None or (
            pc and abs(provider_pc - pc) / pc <= 0.005)
        if (pc and pc_date < today_et_date and abs(c - pc) < 1e-4
                and abs(api_dp_now) > 0.05
                and not prior_session_print and baseline_matches):
            nc = q.get('nc')
            if nc is not None and abs(nc) > 1e-9:
                repaired = round(pc + nc, 4)
                basis = 'netChange'
            else:
                repaired = round(pc * (1 + api_dp_now / 100), 4)
                basis = 'percentageChange'
            print(f"  ⚠ {t}: last ${c:.4f} == prior close ${pc:.4f} ({pc_date}) but "
                  f"{q['source']} reports {api_dp_now:+.2f}% → stale last price; "
                  f"rebuilt to ${repaired:.4f} from {basis} (stale-quote guard ④)",
                  file=sys.stderr)
            stale_repair = {'reported': c, 'repaired': repaired, 'basis': basis,
                            'source': q['source'], 'at': now_et.strftime('%Y-%m-%d %H:%M ET')}
            c = repaired
        elif (pc and pc_date < today_et_date and abs(c - pc) < 1e-4
                and abs(api_dp_now) > 0.05):
            why = (f"the quote is a print dated {q.get('stale_asof')}"
                   if prior_session_print else
                   f"its %change is measured against ${provider_pc:.4f}, not ${pc:.4f}")
            print(f"  ⚠ {t}: last ${c:.4f} == prior close ${pc:.4f} ({pc_date}) and "
                  f"{q['source']} reports {api_dp_now:+.2f}%, but {why} → NOT rebuilding "
                  f"(would compose two sessions, #332); today reads flat and "
                  f"preflight's STALE_PRICE will say so", file=sys.stderr)

        # ③ degenerate-range warning: a live regular-session quote with
        # open==high==low==close has no intraday range → likely a stale/frozen
        # quote (the tell-tale signature of the 2026-05-29 swap). Warn-only.
        # This alarm was dead until now: get_nasdaq_quote defaulted o/h/l to the
        # last price, so it fired for every ticker on every fetch and meant
        # nothing. Now that absent fields stay None, a flat range is once again
        # a real signal from the provider rather than our own fabrication.
        if 9 <= now_et.hour < 16:
            o_, h_, l_ = q.get('o'), q.get('h'), q.get('l')
            if None not in (o_, h_, l_) and bar_checks.is_degenerate(
                    {'open': o_, 'high': h_, 'low': l_, 'close': q['c']}):
                print(f"  ⚠ {t}: degenerate range (o=h=l=c=${q['c']:.4f}) mid-session "
                      f"— possible stale quote (run with US_FETCH_DEBUG=1 to capture payload)",
                      file=sys.stderr)

        holding['current_price']    = round(c, 4)
        holding['prev_close']       = round(pc, 4)
        holding['prev_close_date']  = pc_date
        # Quality flags travel with the holding so downstream gates and the
        # dashboard can see a repaired/incomplete quote instead of inferring
        # health from numbers that were made to agree with each other.
        if stale_repair:
            holding['stale_price_repair'] = stale_repair
        else:
            holding.pop('stale_price_repair', None)
        if q.get('incomplete'):
            holding['quote_incomplete'] = True
        else:
            holding.pop('quote_incomplete', None)
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
        # A quote the fetch layer already identified as an earlier session's
        # print describes THAT session's envelope, not today's. Feeding its
        # o/h/l in here writes a price that never traded today into the running
        # range, and the accumulator then keeps it for the rest of the session —
        # 2026-08-06 PLTU carried day_low 36.265 (the 08-04 bar's low) on a day
        # whose real low was 42.61. Its last price is still the best number we
        # have, so keep that and drop only the range fields.
        if q.get('stale_asof'):
            api_h = api_l = api_o = None
        else:
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
