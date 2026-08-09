#!/usr/bin/env python3
"""
portfolio_risk_metrics.py — Tier 2 portfolio risk quantification.

Reads `portfolio.json` (current holdings), pulls 30d daily prices from Yahoo
Finance v8 for every active ticker + benchmarks (^GSPC, ^HSI), and computes:

  • β vs benchmark (US -> ^GSPC, HK -> ^HSI)
  • 30d annualised volatility (stdev * sqrt(252))
  • 30d max drawdown
  • 30d Sharpe ratio (rf = 4.5%/yr)
  • leveraged-exposure summary (avg leverage factor, margin-at-risk @ -10%)
  • alerts (high beta / high vol / deep DD / high leverage / negative sharpe)

Writes: assets/data/risk.json
"""
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
from clawock.fetch_fx import get_usdhkd  # noqa: E402
from clawock.instrument_registry import get as get_instrument  # noqa: E402
from clawock.instrument_registry import leverage_map, require as require_instrument  # noqa: E402

WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORTFOLIO_FILE = os.path.join(WS_ROOT, 'portfolio.json')
OUT_FILE = os.path.join(WS_ROOT, 'assets', 'data', 'risk.json')

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36 '
      'clawock-risk-scan/1.0')
HEADERS = {'User-Agent': UA}
TIMEOUT = 15

# ---- API keys (for fallback historical fetch) -------------------------------
API_KEYS_PATH = os.path.join(WS_ROOT, '.api_keys')


def _load_api_keys():
    keys = {}
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


API_KEYS = _load_api_keys()

# Compatibility view for diagnostics; config/instruments.json owns the values.
LEVERAGED = leverage_map()

RISK_FREE_ANNUAL = 0.045
TRADING_DAYS = 252
WINDOW_DAYS = 30  # final window we use for stats
MIN_ACTION_RETURNS = 20
MIN_DATE_COVERAGE = 0.80
NEW_LISTING_RETURNS = 20
EWMA_LAMBDA = 0.94

# Correlation x-ray. `MIN_CORR_SESSIONS` matches MIN_ACTION_RETURNS so a
# correlation number can never be acted on with a thinner sample than a beta.
# `CLUSTER_RHO` is the level at which two names stop being separate bets;
# `CLUSTER_WEIGHT_ALERT_PCT` reuses the existing declared appetite for
# single-factor exposure (brief_preflight's `top2_factor_pct` cap) rather than
# inventing a second, unexplained threshold.
MIN_CORR_SESSIONS = 20
# Correlation deserves a longer sample than the 30-day risk window, and
# fetch_history already returns 60 sessions, so this costs no extra request.
CORR_WINDOW_SESSIONS = 60
CLUSTER_RHO = 0.80
CLUSTER_WEIGHT_ALERT_PCT = 70.0


# ----------------------------------------------------------------------------
# Yahoo v8 helpers
# ----------------------------------------------------------------------------

def hk_yahoo_symbol(ticker: str) -> str:
    """Map portfolio HK ticker (5-digit, leading 0) to Yahoo `NNNN.HK` form.

    Examples: '00100' -> '0100.HK', '02208' -> '2208.HK', '07226' -> '7226.HK'.
    """
    t = ticker.lstrip('0') or '0'
    # Yahoo HK uses 4-digit codes (with leading 0 for sub-1000); keep 4 chars.
    if len(t) < 4:
        t = t.zfill(4)
    return f'{t}.HK'


def _parse_tencent(data_key: str, j: dict):
    """Tencent fqkline payload → list[(ts_epoch, close)]. Returns None if empty."""
    try:
        node = j.get('data', {}).get(data_key, {})
        rows = node.get('day') or node.get('qfqday') or []
        if not rows or len(rows) < 2:
            return None
        from datetime import datetime as _dt, timezone as _tz
        out = []
        for row in rows:
            # ['2026-02-16', open, close, high, low, volume]
            try:
                d = _dt.strptime(row[0], '%Y-%m-%d').replace(tzinfo=_tz.utc)
                out.append((int(d.timestamp()), float(row[2])))
            except Exception:
                continue
        return out or None
    except Exception:
        return None


def _fetch_tencent_history(market_symbol: str):
    """Tencent fqkline endpoint. market_symbol like 'hk00100', 'usRKLB.OQ', 'us.INX', 'hkHSI'."""
    url = ('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
           f'?param={market_symbol},day,,,80,qfq')
    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return _parse_tencent(market_symbol, r.json())
    except Exception:
        return None


def _fetch_tencent_us(ticker: str):
    """Use the pinned venue first, then alternate venues as a data fallback."""
    meta = get_instrument(ticker)
    pinned = meta.get('tencent_symbol') if meta and meta.get('region') == 'US' else None
    if pinned:
        s = _fetch_tencent_history(pinned)
        if s and len(s) >= 5:
            return s
    pinned_suffix = meta.get('venue_suffix') if meta else None
    for suf in ('.OQ', '.N', '.AM', '.K', '.P'):
        if suf == pinned_suffix:
            continue
        s = _fetch_tencent_history(f'us{ticker}{suf}')
        if s and len(s) >= 5:
            return s
    return None


def _fetch_yahoo_history(symbol: str, range_: str = '60d', retries: int = 2):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
    params = {'range': range_, 'interval': '1d'}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
            if r.status_code == 429:
                last_err = f'429 (attempt {attempt+1})'
                time.sleep(5 + attempt * 5)  # 5s,10s,15s,20s
                continue
            if r.status_code != 200:
                last_err = f'HTTP {r.status_code}'
                time.sleep(1)
                continue
            j = r.json()
            res = (j.get('chart', {}).get('result') or [None])[0]
            if not res:
                return None
            ts = res.get('timestamp') or []
            quote = (res.get('indicators', {}).get('quote') or [{}])[0]
            closes = quote.get('close') or []
            series = [(int(t), float(c)) for t, c in zip(ts, closes) if c is not None]
            return series or None
        except Exception as e:
            last_err = str(e)
            time.sleep(1)
    return None, last_err if False else None  # noqa — sentinel below


def _fetch_polygon_history(ticker: str, days: int = 60):
    """Polygon.io daily aggregates fallback (US tickers, free key)."""
    key = API_KEYS.get('POLYGON_API_KEY', '')
    if not key:
        return None
    from datetime import date, timedelta
    today = date.today()
    start = (today - timedelta(days=days + 5)).isoformat()
    end = today.isoformat()
    try:
        r = requests.get(
            f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}',
            params={'adjusted': 'true', 'sort': 'asc', 'limit': 200, 'apiKey': key},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        rows = r.json().get('results') or []
        # t is ms-epoch; c is close
        return [(int(x['t'] // 1000), float(x['c'])) for x in rows if x.get('c') is not None]
    except Exception:
        return None


def _fetch_av_history(ticker: str):
    """Alpha Vantage TIME_SERIES_DAILY fallback (US tickers, slow but reliable)."""
    key = API_KEYS.get('ALPHA_VANTAGE_API_KEY', '')
    if not key:
        return None
    try:
        r = requests.get(
            'https://www.alphavantage.co/query',
            params={'function': 'TIME_SERIES_DAILY', 'symbol': ticker,
                    'outputsize': 'compact', 'apikey': key},
            timeout=25,
        )
        if r.status_code != 200:
            return None
        ts = (r.json() or {}).get('Time Series (Daily)') or {}
        if not ts:
            return None
        # AV gives dates as 'YYYY-MM-DD'
        from datetime import datetime as _dt, timezone as _tz
        out = []
        for d, row in ts.items():
            try:
                epoch = int(_dt.strptime(d, '%Y-%m-%d').replace(tzinfo=_tz.utc).timestamp())
                out.append((epoch, float(row['4. close'])))
            except Exception:
                continue
        out.sort()
        return out or None
    except Exception:
        return None


def fetch_history(symbol: str, range_: str = '60d', retries: int = 2,
                  us_fallback_ticker: str = None, hk_raw_ticker: str = None,
                  is_index: str = None):
    """Fetch daily close series with fallback chain (Tencent → Yahoo → Polygon/AV).

    - `symbol` is the Yahoo-style symbol (e.g. 'RKLB', '0100.HK', '^GSPC').
    - `us_fallback_ticker` is the bare US ticker (defaults to `symbol`).
    - `hk_raw_ticker` is the original 5-digit HK code (e.g. '00100') used to
      build Tencent's `hk00100` symbol.
    - `is_index` is one of 'us_spx', 'hk_hsi' or None.

    Returns list[(ts_epoch, close_float)] sorted ascending, or None.
    """
    # ---- Tencent first (no API key, broad coverage, no rate-limit issues) ----
    tencent = None
    if is_index == 'us_spx':
        tencent = _fetch_tencent_history('us.INX')
    elif is_index == 'hk_hsi':
        tencent = _fetch_tencent_history('hkHSI')
    elif hk_raw_ticker:
        tencent = _fetch_tencent_history(f'hk{hk_raw_ticker}')
    elif '.HK' in symbol:
        # e.g. '0100.HK' → 'hk00100' (zero-pad to 5)
        code = symbol.replace('.HK', '').zfill(5)
        tencent = _fetch_tencent_history(f'hk{code}')
    elif not symbol.startswith('^'):
        tencent = _fetch_tencent_us(us_fallback_ticker or symbol)
    if tencent and len(tencent) >= 5:
        return tencent

    # ---- Yahoo as secondary ----
    series = _fetch_yahoo_history(symbol, range_=range_, retries=retries)
    if isinstance(series, tuple):
        series = series[0]
    if series:
        return series

    # ---- Polygon / AV for US tickers ----
    fb_ticker = us_fallback_ticker or symbol
    if '.HK' in symbol or symbol.startswith('^'):
        print(f'  WARN history {symbol}: all sources exhausted (HK/index)', file=sys.stderr)
        return None
    p = _fetch_polygon_history(fb_ticker)
    if p:
        print(f'  INFO history {symbol}: fell back to Polygon ({len(p)} rows)', file=sys.stderr)
        return p
    a = _fetch_av_history(fb_ticker)
    if a:
        print(f'  INFO history {symbol}: fell back to AlphaVantage ({len(a)} rows)', file=sys.stderr)
        return a
    print(f'  WARN history {symbol}: all sources failed', file=sys.stderr)
    return None


# ----------------------------------------------------------------------------
# Stats helpers
# ----------------------------------------------------------------------------

def daily_returns(closes: np.ndarray) -> np.ndarray:
    """(close_i - close_{i-1}) / close_{i-1}."""
    if closes.size < 2:
        return np.array([])
    return (closes[1:] - closes[:-1]) / closes[:-1]


def max_drawdown(returns: np.ndarray) -> float:
    """Max drawdown over the cumulative-return path. Returns a negative float."""
    if returns.size == 0:
        return 0.0
    # Anchor the wealth path to the pre-return baseline (1.0) so a drawdown that
    # begins on the first period — i.e. day 0 is the peak — is counted, not lost.
    cum = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return float(dd.min())


def sharpe(returns: np.ndarray, vol_annual: float) -> float:
    if returns.size == 0 or vol_annual == 0:
        return 0.0
    mean_annual = float(returns.mean()) * TRADING_DAYS
    return (mean_annual - RISK_FREE_ANNUAL) / vol_annual


def beta(port_rets: np.ndarray, bench_rets: np.ndarray) -> float:
    """Cov(p, b) / Var(b). Aligns to common length (tail)."""
    n = min(port_rets.size, bench_rets.size)
    if n < 5:
        return None
    p = port_rets[-n:]
    b = bench_rets[-n:]
    var_b = float(np.var(b, ddof=1))
    if var_b == 0:
        return None
    cov = float(np.cov(p, b, ddof=1)[0, 1])
    return cov / var_b


# ----------------------------------------------------------------------------
# Portfolio aggregation
# ----------------------------------------------------------------------------

def active_holdings(portfolio: dict, key: str):
    """Return the live positions plus the ledger needed for historical weights."""
    bucket = portfolio.get('portfolios', {}).get(key, {})
    out = []
    for h in bucket.get('holdings', []):
        shares = h.get('shares') or 0
        cv = h.get('current_value') or 0
        if shares <= 0 or cv <= 0:
            continue
        ticker = h.get('ticker')
        lev = require_instrument(ticker)['leverage_multiple']
        if key == 'hk_stocks':
            yahoo_sym = h.get('ticker_finnhub') or hk_yahoo_symbol(ticker)
        else:
            yahoo_sym = ticker
        out.append({
            'ticker': ticker,
            'current_value': float(cv),
            'current_price': float(h.get('current_price') or (cv / shares)),
            'shares': float(shares),
            'trades': list(h.get('trades') or []),
            'leverage': lev,
            'yahoo_symbol': yahoo_sym,
        })
    return out


def align_to_dates(series_by_ticker: dict):
    """Given {ticker: [(ts, close), ...]}, return (dates, {ticker: np.array(closes)})
    aligned on the intersection of trading dates. ts -> date(UTC) string.

    Yahoo timestamps are 'beginning of trading day' so date conversion is stable.
    """
    if not series_by_ticker:
        return [], {}
    # convert ts to YYYY-MM-DD strings, build date->close map per ticker
    per_ticker_map = {}
    for tk, series in series_by_ticker.items():
        m = {}
        for ts, c in series:
            d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
            m[d] = c
        per_ticker_map[tk] = m
    # intersect dates
    common = set.intersection(*(set(m.keys()) for m in per_ticker_map.values()))
    dates = sorted(common)
    aligned = {tk: np.array([m[d] for d in dates], dtype=float)
               for tk, m in per_ticker_map.items()}
    return dates, aligned


def _date_close_map(series):
    return {
        datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d'): float(close)
        for ts, close in (series or [])
    }


def _shares_on(holding: dict, as_of: str) -> float:
    """Reconstruct close-of-day shares from today's shares and later trades."""
    shares = float(holding.get('shares') or 0)
    for trade in holding.get('trades') or []:
        trade_date = str(trade.get('date') or '')[:10]
        if not trade_date or trade_date <= as_of:
            continue
        qty = float(trade.get('shares') or 0)
        action = str(trade.get('action') or '').lower()
        if action in ('buy', 'bought'):
            shares -= qty
        elif action in ('sell', 'sold'):
            shares += qty
    return max(shares, 0.0)


def _return_map(series):
    closes = _date_close_map(series)
    dates = sorted(closes)
    out = {}
    for previous, current in zip(dates, dates[1:]):
        if closes[previous] > 0:
            out[current] = {
                'return': closes[current] / closes[previous] - 1,
                'previous_date': previous,
                'previous_close': closes[previous],
                'close': closes[current],
            }
    return out


def ewma_volatility(returns: np.ndarray, decay: float = EWMA_LAMBDA):
    if returns.size < 2:
        return None
    weights = decay ** np.arange(returns.size - 1, -1, -1, dtype=float)
    weights /= weights.sum()
    mean = float(np.sum(weights * returns))
    variance = float(np.sum(weights * (returns - mean) ** 2))
    return math.sqrt(max(variance, 0.0) * TRADING_DAYS)


def expected_shortfall(returns: np.ndarray, confidence: float = 0.95):
    if returns.size < 2:
        return None
    tail_n = max(1, int(math.ceil((1 - confidence) * returns.size)))
    return float(np.mean(np.sort(returns)[:tail_n]))


def ewma_correlation(left: np.ndarray, right: np.ndarray,
                     decay: float = EWMA_LAMBDA):
    n = min(left.size, right.size)
    if n < 5:
        return None
    x, y = left[-n:], right[-n:]
    weights = decay ** np.arange(n - 1, -1, -1, dtype=float)
    weights /= weights.sum()
    dx, dy = x - np.sum(weights * x), y - np.sum(weights * y)
    vx, vy = np.sum(weights * dx * dx), np.sum(weights * dy * dy)
    if vx <= 0 or vy <= 0:
        return None
    return float(np.sum(weights * dx * dy) / math.sqrt(vx * vy))


def _round_finite(value, digits: int = 4):
    """Round for publication, or `None` when the value is not a finite float.

    Every metric here is a ratio, and one non-finite input poisons the whole
    window: `np.std` over an array containing a single `nan` returns `nan`, so
    vol, drawdown, Sharpe and expected shortfall all go non-finite together and
    the card reads as broken rather than as missing. Publishing `null` says
    "not computable" in a way `JSON.parse` survives.
    """
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return round(out, digits) if math.isfinite(out) else None


def _stream_stats(return_by_date: dict, coverage_by_date: dict,
                  benchmark_return_by_date=None):
    observed_dates = sorted(return_by_date)[-WINDOW_DAYS:]
    eligible_dates = [
        date for date in observed_dates
        if coverage_by_date.get(date, 0.0) >= MIN_DATE_COVERAGE
    ]
    # A non-finite daily return (a zero or absurd close that survived the
    # per-date guards) is dropped rather than carried: it would otherwise make
    # every statistic below non-finite at once. The dropped dates are published
    # next to the low-coverage ones so the exclusion stays visible.
    # `_round_finite` is reused as the predicate so a None or a junk value is
    # excluded rather than raising: np.array(..., dtype=float) used to turn both
    # into nan silently, and this must not be the step that starts crashing.
    non_finite_dates = [
        d for d in eligible_dates if _round_finite(return_by_date[d]) is None
    ]
    if non_finite_dates:
        eligible_dates = [d for d in eligible_dates if d not in set(non_finite_dates)]
    returns = np.array([return_by_date[d] for d in eligible_dates], dtype=float)
    vol = (float(np.std(returns, ddof=1) * np.sqrt(TRADING_DAYS))
           if returns.size > 1 else None)
    result = {
        'n_returns': int(returns.size),
        'n_returns_observed': len(observed_dates),
        'actual_window': {
            'first': eligible_dates[0] if eligible_dates else None,
            'last': eligible_dates[-1] if eligible_dates else None,
            'target_returns': WINDOW_DAYS,
            'observed_returns': len(observed_dates),
            'used_returns': int(returns.size),
        },
        'missingness': {
            'minimum_date_coverage_required': MIN_DATE_COVERAGE,
            'mean_value_coverage_pct': (
                round(100 * float(np.mean([coverage_by_date[d]
                                           for d in observed_dates])), 1)
                if observed_dates else None
            ),
            'minimum_value_coverage_pct': (
                round(100 * min(coverage_by_date[d] for d in observed_dates), 1)
                if observed_dates else None
            ),
            'excluded_low_coverage_dates': [
                d for d in observed_dates
                if d not in eligible_dates and d not in set(non_finite_dates)
            ],
            'excluded_non_finite_dates': non_finite_dates,
            'per_date_value_coverage_pct': {
                d: round(100 * coverage_by_date[d], 1) for d in observed_dates
            },
        },
        'vol_30d_annualized': _round_finite(vol),
        'ewma_vol_annualized': (
            _round_finite(ewma_volatility(returns)) if returns.size > 1 else None
        ),
        'max_dd_30d': _round_finite(max_drawdown(returns)) if returns.size else None,
        'sharpe_30d': (
            _round_finite(sharpe(returns, vol)) if vol not in (None, 0) else None
        ),
        'expected_shortfall_95': (
            _round_finite(expected_shortfall(returns)) if returns.size > 1 else None
        ),
        'threshold_eligible': bool(returns.size >= MIN_ACTION_RETURNS),
        'threshold_min_returns': MIN_ACTION_RETURNS,
        'regime_basis': (
            'dynamic_historical_weights'
            if returns.size >= MIN_ACTION_RETURNS
            else 'insufficient_observations'
        ),
    }
    if benchmark_return_by_date is not None:
        common = [d for d in eligible_dates if d in benchmark_return_by_date]
        port = np.array([return_by_date[d] for d in common], dtype=float)
        bench = np.array([benchmark_return_by_date[d] for d in common], dtype=float)
        result['benchmark_n_returns'] = len(common)
        result['beta_threshold_eligible'] = bool(
            len(common) >= MIN_ACTION_RETURNS
        )
        b = beta(port, bench)
        c = ewma_correlation(port, bench)
        result['beta'] = _round_finite(b)
        result['ewma_benchmark_correlation'] = _round_finite(c)
    return result


def build_dynamic_return_stream(holdings: list, fetched: dict,
                                include_tickers=None):
    """Build returns on the union of dates using reconstructed, date-varying weights.

    A missing quote does not become a zero return and does not truncate every other
    name. Available names are renormalised for that date and the omitted value is
    published as coverage, so action thresholds can reject weak dates.
    """
    include = set(include_tickers or fetched)
    selected = []
    for holding in holdings:
        ticker = holding.get('ticker')
        if ticker not in fetched or ticker not in include:
            continue
        normalized = dict(holding)
        if float(normalized.get('shares') or 0) <= 0:
            closes = _date_close_map(fetched[ticker])
            reference_price = (
                float(normalized.get('current_price') or 0)
                or (closes[max(closes)] if closes else 0)
            )
            normalized['shares'] = (
                float(normalized.get('current_value') or 0) / reference_price
                if reference_price > 0 else 0.0
            )
            normalized.setdefault('trades', [])
        selected.append(normalized)
    return_maps = {h['ticker']: _return_map(fetched[h['ticker']]) for h in selected}
    close_maps = {h['ticker']: _date_close_map(fetched[h['ticker']]) for h in selected}
    dates = sorted(set().union(*(set(m) for m in return_maps.values())))[-WINDOW_DAYS:]
    return_by_date, coverage_by_date, value_by_date = {}, {}, {}
    for date in dates:
        available_value = 0.0
        expected_value = 0.0
        weighted_return = 0.0
        for holding in selected:
            ticker = holding['ticker']
            row = return_maps[ticker].get(date)
            prior_dates = [d for d in close_maps[ticker] if d < date]
            latest_prior = max(prior_dates) if prior_dates else None
            prior_calendar_date = (
                datetime.strptime(date, '%Y-%m-%d').date() - timedelta(days=1)
            ).isoformat()
            shares = _shares_on(holding, row['previous_date'] if row else
                                (latest_prior or prior_calendar_date))
            if shares <= 0:
                continue
            if latest_prior:
                estimated_value = shares * close_maps[ticker][latest_prior]
            else:
                current_shares = float(holding.get('shares') or 0)
                estimated_value = (
                    holding['current_value'] * shares / current_shares
                    if current_shares > 0 else 0.0
                )
            expected_value += estimated_value
            if row:
                value = shares * row['previous_close']
                available_value += value
                weighted_return += value * row['return']
        if available_value <= 0:
            continue
        return_by_date[date] = weighted_return / available_value
        coverage_by_date[date] = (
            min(1.0, available_value / expected_value) if expected_value > 0 else 1.0
        )
        value_by_date[date] = expected_value
    return {
        'return_by_date': return_by_date,
        'coverage_by_date': coverage_by_date,
        'value_by_date': value_by_date,
    }


def compute_bucket(holdings: list, bench_series, label: str, sleep_between: float = 0.3):
    """Fetch histories and compute a union-date, historical-weight risk view."""
    if not holdings:
        return None, {'fetched': [], 'failed': []}

    fetched = {}
    failed = []
    for h in holdings:
        sym = h['yahoo_symbol']
        if '.HK' in sym:
            series = fetch_history(sym, hk_raw_ticker=h['ticker'])
        else:
            series = fetch_history(sym, us_fallback_ticker=h['ticker'])
        if series is None or len(series) < 5:
            failed.append(sym)
            continue
        fetched[h['ticker']] = series
        time.sleep(sleep_between)

    if not fetched:
        return None, {'fetched': list(fetched.keys()), 'failed': failed}

    stream = build_dynamic_return_stream(holdings, fetched)
    if len(stream['return_by_date']) < 2:
        return None, {'fetched': list(fetched), 'failed': failed,
                      'note': 'too few portfolio return dates'}
    benchmark_returns = _return_map(bench_series) if bench_series else {}
    benchmark_return_by_date = {
        d: row['return'] for d, row in benchmark_returns.items()
    }
    stats = _stream_stats(
        stream['return_by_date'], stream['coverage_by_date'],
        benchmark_return_by_date,
    )

    current_value = sum(h['current_value'] for h in holdings)
    fetched_value = sum(h['current_value'] for h in holdings if h['ticker'] in fetched)
    excluded_tickers = [h['ticker'] for h in holdings if h['ticker'] not in fetched]
    established = [
        ticker for ticker, series in fetched.items()
        if len(_return_map(series)) >= NEW_LISTING_RETURNS
    ]
    new_listing = [ticker for ticker in fetched if ticker not in established]

    def sleeve(tickers):
        if not tickers:
            return None
        sleeve_stream = build_dynamic_return_stream(
            holdings, fetched, include_tickers=tickers
        )
        sleeve_stats = _stream_stats(
            sleeve_stream['return_by_date'], sleeve_stream['coverage_by_date']
        )
        return {'tickers': tickers, **sleeve_stats}

    beta_key = f'beta_{"spx" if label == "us" else "hsi"}'
    bucket_out = {
        beta_key: stats.pop('beta', None),
        **stats,
        'sleeves': {
            'established': sleeve(established),
            'new_listing': sleeve(new_listing),
        },
        'current_value': round(current_value, 2),
        'history_coverage': {
            'holdings_fetched': len(fetched),
            'holdings_total': len(holdings),
            'current_value_pct': (round(100 * fetched_value / current_value, 1)
                                  if current_value > 0 else None),
            'excluded_tickers': excluded_tickers,
        },
        'weight_method': 'date_varying_shares_x_previous_close',
        'weight_reconstruction': 'current shares reversed through dated trade ledger',
    }
    # naming detail: US uses USD field name
    if label == 'us':
        bucket_out['current_value_usd'] = bucket_out.pop('current_value')
    else:
        bucket_out['current_value_hkd'] = bucket_out.pop('current_value')

    meta = {
        'fetched': list(fetched.keys()),
        # Per-ticker close series, for callers that need co-movement rather than
        # the aggregated stream. Internal only — `main` publishes named keys from
        # meta, never meta itself, so this never reaches risk.json.
        'series': fetched,
        'failed': failed,
        'n_holdings': len(holdings),
        'n_returns': stats['n_returns'],
        'dates_first': stats['actual_window']['first'],
        'dates_last': stats['actual_window']['last'],
        **stream,
    }
    return bucket_out, meta


def correlation_xray(holdings_by_leg, series_by_leg, fx_hkd_to_usd):
    """Measure how many *bets* the book holds, not how many tickers.

    Concentration here has always been weight-only: HHI and Top2 over dollar
    weights, with `top2_factor_pct` standing in as a proxy for "these are one
    factor". That proxy fails in both directions. Two names that are the same
    bet — a 2x ETF and its 1x underlying, or the 07226 / 03033 / 00100 HSTECH
    cluster — look diversified the moment a third name pushes them out of the
    Top 2, and two genuinely unrelated leaders trip the cap for no reason. The
    2026-06 drawdown is on record as a construction problem ("HK 85% one
    factor"), which is precisely the quantity that was never measured.

    Everything here is computed from realised returns, so it is descriptive, not
    predictive:

      effective_names   1/HHI — the old weight-only count, kept for contrast
      effective_bets    1/(wᵀρw) — collapses toward 1 as the book co-moves
      diversification_ratio  Σwᵢσᵢ / σ_portfolio — 1.0 means no diversification
      clusters          single-linkage groups at |ρ| ≥ CLUSTER_RHO, by weight
      var_95 / es_95    historical tail of the weighted book

    Both legs are converted to USD before weighting, per the standing rule that
    HKD and USD are never added. Correlation needs contemporaneous returns, so
    the sample is the *intersection* of sessions both markets traded.
    """
    weights, returns_by_ticker = {}, {}
    for leg, holdings in holdings_by_leg.items():
        rate = 1.0 if leg == 'us' else fx_hkd_to_usd
        series_map = series_by_leg.get(leg) or {}
        for holding in holdings:
            ticker = holding['ticker']
            series = series_map.get(ticker)
            if not series:
                continue
            value_usd = float(holding['current_value']) * float(rate)
            if value_usd <= 0:
                continue
            weights[ticker] = value_usd
            returns_by_ticker[ticker] = {
                date: row['return'] for date, row in _return_map(series).items()
            }

    book_value = sum(weights.values())
    excluded = sorted(
        holding['ticker']
        for leg, holdings in holdings_by_leg.items()
        for holding in holdings
        if holding['ticker'] not in weights
    )

    # A recent listing must not truncate the established names — the same rule
    # `build_dynamic_return_stream` already follows. Requiring every holding to
    # share every session let one 16-session name (SKHY) cap the whole sample at
    # 15 and produce nothing at all.
    short_history = sorted(
        ticker for ticker, returns in returns_by_ticker.items()
        if len(returns) < MIN_CORR_SESSIONS
    )
    for ticker in short_history:
        returns_by_ticker.pop(ticker)

    def _unavailable(reason):
        return {
            'effective_names': None, 'effective_bets': None,
            'diversification_ratio': None, 'var_95': None,
            'expected_shortfall_95': None, 'clusters': [], 'top_pairs': [],
            'n_common_sessions': 0, 'tickers': sorted(returns_by_ticker),
            'excluded_no_history': excluded,
            'excluded_short_history': short_history,
            'reason': reason,
        }

    if len(returns_by_ticker) < 2:
        return _unavailable('needs at least two holdings with enough history')

    common = sorted(set.intersection(
        *(set(dates) for dates in returns_by_ticker.values())))[-CORR_WINDOW_SESSIONS:]
    if len(common) < MIN_CORR_SESSIONS:
        return _unavailable(
            f'{len(common)} sessions common to the {len(returns_by_ticker)} '
            f'holdings with history; {MIN_CORR_SESSIONS} required')

    tickers = sorted(returns_by_ticker)
    total = sum(weights[t] for t in tickers)
    w = np.array([weights[t] / total for t in tickers], dtype=float)
    matrix = np.array(
        [[returns_by_ticker[t][d] for t in tickers] for d in common], dtype=float)
    if not np.isfinite(matrix).all():
        return _unavailable('non-finite return in the aligned matrix')

    sigmas = matrix.std(axis=0, ddof=1)
    if not (sigmas > 0).all():
        # A name that never moved has undefined correlation; naming it beats
        # publishing a matrix with silent NaN columns.
        flat = [t for t, s in zip(tickers, sigmas) if not s > 0]
        return _unavailable(f'zero-variance holding(s): {", ".join(flat)}')

    rho = np.corrcoef(matrix, rowvar=False)
    portfolio = matrix @ w
    sigma_p = float(portfolio.std(ddof=1))

    hhi = float(np.sum(w ** 2))
    quadratic = float(w @ rho @ w)
    weighted_sigma = float(np.sum(w * sigmas))

    pairs = []
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            pairs.append({'pair': [tickers[i], tickers[j]],
                          'rho': _round_finite(rho[i, j], 3),
                          'combined_weight_pct': _round_finite(
                              (w[i] + w[j]) * 100, 2)})
    pairs = [p for p in pairs if p['rho'] is not None]
    pairs.sort(key=lambda p: -abs(p['rho']))

    return {
        'effective_names': _round_finite(1.0 / hhi if hhi > 0 else None, 2),
        'effective_bets': _round_finite(
            1.0 / quadratic if quadratic > 0 else None, 2),
        'diversification_ratio': _round_finite(
            weighted_sigma / sigma_p if sigma_p > 0 else None, 3),
        'var_95': _round_finite(float(np.percentile(portfolio, 5))),
        'expected_shortfall_95': _round_finite(_tail_mean(portfolio, 0.05)),
        'clusters': _correlation_clusters(tickers, rho, w),
        'top_pairs': pairs[:5],
        'n_common_sessions': len(common),
        'first_session': common[0],
        'last_session': common[-1],
        'tickers': tickers,
        'excluded_no_history': excluded,
        'excluded_short_history': short_history,
        # How much of the book the numbers above actually describe. Excluding a
        # name is not free, and a reader must be able to see that a 60%-covered
        # x-ray is a different claim from a 99%-covered one.
        'covered_weight_pct': _round_finite(
            100 * total / book_value if book_value > 0 else None, 2),
        'cluster_rho': CLUSTER_RHO,
        'basis': 'USD-converted current weights over sessions both legs traded',
    }


def _tail_mean(returns: np.ndarray, alpha: float):
    """Mean of the worst `alpha` tail — expected shortfall, historical."""
    if returns.size < 2:
        return None
    cutoff = max(1, int(math.ceil(alpha * returns.size)))
    return float(np.sort(returns)[:cutoff].mean())


def _correlation_clusters(tickers, rho, weights):
    """Single-linkage groups at |ρ| >= CLUSTER_RHO, heaviest first.

    Single linkage on purpose: A~B and B~C makes one cluster even when A and C
    are not directly correlated, because that is still one chain of shared
    exposure. It over-groups rather than under-groups, and for a risk readout
    the conservative error is the right one.
    """
    parent = list(range(len(tickers)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            if abs(rho[i, j]) >= CLUSTER_RHO:
                parent[find(i)] = find(j)

    grouped = defaultdict(list)
    for index, ticker in enumerate(tickers):
        grouped[find(index)].append(index)

    clusters = []
    for members in grouped.values():
        clusters.append({
            'tickers': [tickers[i] for i in sorted(members)],
            'weight_pct': _round_finite(
                sum(weights[i] for i in members) * 100, 2),
        })
    clusters.sort(key=lambda c: -(c['weight_pct'] or 0))
    return clusters


def compute_combined(us_meta, hk_meta, holdings_all, fx_hkd_to_usd=None):
    """Build combined returns on the union of US/HK sessions and dynamic values."""
    if (holdings_all.get('hk') and hk_meta
            and (fx_hkd_to_usd is None or fx_hkd_to_usd <= 0)):
        raise ValueError('USDHKD rate required to combine HKD and USD risk buckets')

    def has_current_stream(meta):
        return bool(meta and meta.get('return_by_date'))

    # A one-leg portfolio is valid; a two-leg portfolio with one failed return
    # stream is not. The old fallback silently returned the surviving leg's vol
    # and Sharpe under the public label "combined", which can sharply understate
    # risk when the missing leg is the volatile one.
    if holdings_all.get('us') and not has_current_stream(us_meta):
        return None
    if holdings_all.get('hk') and not has_current_stream(hk_meta):
        return None

    series_list = []
    if has_current_stream(us_meta):
        series_list.append(('us', us_meta, 1.0))
    if has_current_stream(hk_meta):
        series_list.append(('hk', hk_meta, fx_hkd_to_usd))

    if not series_list:
        return None

    dates = sorted(set().union(*(
        set(meta['return_by_date']) for _, meta, _ in series_list
    )))[-WINDOW_DAYS:]
    combined_returns, combined_coverage = {}, {}
    for date in dates:
        weighted_return = total_value = covered_value = 0.0
        for _, meta, currency_factor in series_list:
            value_dates = [d for d in meta['value_by_date'] if d <= date]
            if not value_dates:
                continue
            value = meta['value_by_date'][max(value_dates)] * currency_factor
            total_value += value
            if date in meta['return_by_date']:
                weighted_return += value * meta['return_by_date'][date]
                covered_value += value * meta['coverage_by_date'].get(date, 0.0)
            else:
                # A closed market contributes a true zero for that session.
                covered_value += value
        if total_value > 0:
            combined_returns[date] = weighted_return / total_value
            combined_coverage[date] = min(1.0, covered_value / total_value)
    out = _stream_stats(combined_returns, combined_coverage)
    out['weight_method'] = 'date_varying_market_values_on_union_of_market_sessions'
    out['closed_market_return_treatment'] = 'zero'
    return out


def compute_leverage(holdings_all, fx_hkd_to_usd):
    us = holdings_all['us']
    hk = holdings_all['hk']

    def avg_lev(holdings):
        tot = sum(h['current_value'] for h in holdings)
        if tot <= 0:
            return 0.0
        return sum(h['current_value'] * h['leverage'] for h in holdings) / tot

    us_avg = avg_lev(us)
    hk_avg = avg_lev(hk)

    # combined: convert HK USD-equivalent and weight
    us_v = sum(h['current_value'] for h in us)
    hk_v_usd = sum(h['current_value'] for h in hk) * fx_hkd_to_usd
    combined_total = us_v + hk_v_usd
    combined_avg = 0.0
    if combined_total > 0:
        us_lev_dollars = sum(h['current_value'] * h['leverage'] for h in us)
        hk_lev_dollars = sum(h['current_value'] * h['leverage'] for h in hk) * fx_hkd_to_usd
        combined_avg = (us_lev_dollars + hk_lev_dollars) / combined_total

    # margin-at-risk: assume each holding's underlying drops 10%, ETF moves
    # -10% * leverage_factor; weighted by USD-equivalent value.
    margin_at_risk_pct = 0.0
    if combined_total > 0:
        loss_dollars = 0.0
        for h in us:
            loss_dollars += h['current_value'] * (-0.10 * h['leverage'])
        for h in hk:
            loss_dollars += h['current_value'] * fx_hkd_to_usd * (-0.10 * h['leverage'])
        # express as positive percentage of total exposure
        margin_at_risk_pct = abs(loss_dollars) / combined_total * 100

    return {
        'us_leverage_factor_avg': round(us_avg, 4),
        'hk_leverage_factor_avg': round(hk_avg, 4),
        'combined_avg': round(combined_avg, 4),
        'margin_at_risk_pct': round(margin_at_risk_pct, 4),
    }


def build_alerts(us, hk, combined, leverage, correlation=None):
    alerts = []
    for label, block in (('US', us), ('HK', hk)):
        if not isinstance(block, dict):
            continue
        coverage = block.get('history_coverage') or {}
        pct = coverage.get('current_value_pct')
        excluded = coverage.get('excluded_tickers') or []
        if block.get('stale'):
            alerts.append({
                'type': 'risk_data_stale',
                'severity': 'high',
                'detail': (f'{label} 30d risk history fetch failed; showing the previous '
                           f'block from {block.get("stale_since") or "unknown"}. '
                           'Combined vol/Sharpe are withheld.'),
            })
        elif pct is not None and pct < 100:
            alerts.append({
                'type': 'risk_data_coverage',
                'severity': 'medium',
                'detail': (f'{label} beta/vol history covers {pct:.1f}% of current position '
                           f'value; excludes {", ".join(excluded) or "unknown ticker(s)"}.'),
            })
        if block.get('threshold_eligible') is False:
            alerts.append({
                'type': 'insufficient_observations',
                'severity': 'medium',
                'detail': (
                    f'{label} risk window has {block.get("n_returns", 0)} usable '
                    f'returns; {block.get("threshold_min_returns", MIN_ACTION_RETURNS)} '
                    'required for beta/volatility threshold actions.'
                ),
            })
        elif (label == 'US'
              and block.get('beta_threshold_eligible') is False):
            alerts.append({
                'type': 'insufficient_observations',
                'severity': 'medium',
                'detail': (
                    f'US beta has {block.get("benchmark_n_returns", 0)} aligned '
                    f'returns; {MIN_ACTION_RETURNS} required for threshold actions.'
                ),
            })
    combined_eligible = bool(combined and combined.get('threshold_eligible', True))
    us_eligible = bool(
        us and us.get('threshold_eligible', True)
        and us.get('beta_threshold_eligible', True)
    )
    if (us_eligible and us.get('beta_spx') is not None
            and us['beta_spx'] > 3.0):
        alerts.append({'type': 'high_beta', 'severity': 'high',
                       'detail': f'US β vs S&P 500 = {us["beta_spx"]} (> 3.0)'})
    if (combined_eligible and combined.get('vol_30d_annualized') is not None
            and combined['vol_30d_annualized'] > 0.50):
        alerts.append({'type': 'high_vol', 'severity': 'high',
                       'detail': f'Combined 30d annualised vol = {combined["vol_30d_annualized"]*100:.1f}% (> 50%)'})
    if (combined_eligible and combined.get('max_dd_30d') is not None
            and combined['max_dd_30d'] < -0.10):
        alerts.append({'type': 'deep_dd', 'severity': 'medium',
                       'detail': f'Combined 30d max DD = {combined["max_dd_30d"]*100:.1f}% (< -10%)'})
    if leverage and leverage.get('combined_avg', 0) > 2.0:
        alerts.append({'type': 'high_leverage', 'severity': 'high',
                       'detail': f'Combined avg leverage factor = {leverage["combined_avg"]} (> 2.0)'})
    if (combined_eligible and combined.get('sharpe_30d') is not None
            and combined['sharpe_30d'] < 0):
        alerts.append({'type': 'negative_sharpe', 'severity': 'medium',
                       'detail': f'Combined 30d Sharpe = {combined["sharpe_30d"]} (< 0)'})
    alerts.extend(_correlation_alerts(correlation))
    return alerts


def _correlation_alerts(correlation):
    """Co-movement findings. Reports, never suppresses.

    This is deliberately an alert and not a hard cap. The guardrail's caps are
    mandatory trim directives the brief must act on; changing what the book is
    required to sell is kcn's call on thresholds, not a side effect of adding a
    measurement. What this can say is that the measured cluster is larger than
    the declared appetite for single-factor exposure.
    """
    if not correlation:
        return []
    if correlation.get('reason'):
        return [{
            'type': 'insufficient_observations', 'severity': 'medium',
            'detail': f'correlation x-ray unavailable: {correlation["reason"]}',
        }]

    alerts = []
    clusters = correlation.get('clusters') or []
    biggest = clusters[0] if clusters else None
    if (biggest and len(biggest.get('tickers') or []) > 1
            and (biggest.get('weight_pct') or 0) > CLUSTER_WEIGHT_ALERT_PCT):
        alerts.append({
            'type': 'correlated_cluster', 'severity': 'high',
            'detail': (
                f'{biggest["weight_pct"]}% of the book moves as one cluster '
                f'({", ".join(biggest["tickers"])}) at |ρ| ≥ '
                f'{correlation.get("cluster_rho", CLUSTER_RHO)} '
                f'(> {CLUSTER_WEIGHT_ALERT_PCT}%)'
            ),
        })

    names = correlation.get('effective_names')
    bets = correlation.get('effective_bets')
    if names is not None and bets is not None and bets < names / 2:
        alerts.append({
            'type': 'diversification_illusion', 'severity': 'medium',
            'detail': (
                f'{names} effective names but only {bets} effective bets — '
                'weight-based concentration understates the real exposure'
            ),
        })
    return alerts


def load_canonical_fx():
    """Return HKD→USD plus provenance from the shared fetch_fx source."""
    fx = get_usdhkd()
    rate = float(fx.get('rate') or 0)
    if not 7.0 < rate < 9.0:
        raise ValueError(f'invalid USDHKD rate from fetch_fx: {rate!r}')
    return 1.0 / rate, {
        'pair': fx.get('pair') or 'USDHKD',
        'rate': rate,
        'source': fx.get('source') or 'unknown',
        'fetched_at': fx.get('fetched_at'),
        'fallback_used': bool(fx.get('fallback_used', False)),
        'warning': fx.get('warning'),
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    if not os.path.exists(PORTFOLIO_FILE):
        print(f'ERROR: portfolio not found at {PORTFOLIO_FILE}', file=sys.stderr)
        return 1
    with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
        portfolio = json.load(f)

    us_holdings = active_holdings(portfolio, 'us_stocks')
    hk_holdings = active_holdings(portfolio, 'hk_stocks')

    print(f'Active US holdings: {len(us_holdings)}  '
          f'({", ".join(h["ticker"] for h in us_holdings)})')
    print(f'Active HK holdings: {len(hk_holdings)}  '
          f'({", ".join(h["ticker"] for h in hk_holdings)})')

    # Fetch benchmarks
    print('Fetching benchmarks (^GSPC, ^HSI)...')
    spx_series = fetch_history('^GSPC', is_index='us_spx')
    time.sleep(0.3)
    hsi_series = fetch_history('^HSI', is_index='hk_hsi')
    time.sleep(0.3)
    bench_status = {'^GSPC': spx_series is not None, '^HSI': hsi_series is not None}
    print(f'  ^GSPC {"OK" if bench_status["^GSPC"] else "FAIL"} | '
          f'^HSI {"OK" if bench_status["^HSI"] else "FAIL"}')

    # Compute bucket stats
    print(f'\nFetching US bucket ({len(us_holdings)} tickers)...')
    us_out, us_meta = compute_bucket(us_holdings, spx_series, label='us')
    print(f'\nFetching HK bucket ({len(hk_holdings)} tickers)...')
    hk_out, hk_meta = compute_bucket(hk_holdings, hsi_series, label='hk')

    # --- Hardening: a transient price-history fetch failure (yahoo 429/flaky)
    # can null out a whole bucket even though we still hold positions there.
    # Publishing a single-market view is misleading (the 2026-06-23 "missing US"
    # bug). Instead fall back to the previous good block and flag it stale
    # (merge-not-overwrite, same pattern as the dashboard sidecar guard).
    # The position VALUE never depends on the risk fetch — it comes straight from
    # portfolio.json — so we always refresh it from current holdings even when the
    # rest of the block (β/vol/sharpe) is stale.
    prev = {}
    if os.path.exists(OUT_FILE):
        try:
            prev = json.load(open(OUT_FILE, 'r', encoding='utf-8'))
        except Exception:
            prev = {}

    def _preserve_stale(out_block, holdings, prev_block, value_key, value):
        """If this run produced no stats but we still hold positions, reuse the
        last good stats and mark stale; always refresh the live position value."""
        if out_block is not None or not holdings:
            return out_block, False
        if not isinstance(prev_block, dict):
            return out_block, False
        revived = dict(prev_block)
        revived['stale'] = True
        revived['stale_since'] = prev.get('generated_at')
        revived[value_key] = round(value, 2)  # live value, never stale
        return revived, True

    us_value = sum(h['current_value'] for h in us_holdings)
    hk_value = sum(h['current_value'] for h in hk_holdings)
    us_out, us_stale = _preserve_stale(us_out, us_holdings, prev.get('us'),
                                       'current_value_usd', us_value)
    hk_out, hk_stale = _preserve_stale(hk_out, hk_holdings, prev.get('hk'),
                                       'current_value_hkd', hk_value)
    if us_stale:
        print('  WARN: US risk fetch empty — kept previous β/vol block (stale), '
              'value refreshed from holdings', file=sys.stderr)
    if hk_stale:
        print('  WARN: HK risk fetch empty — kept previous β/vol block (stale), '
              'value refreshed from holdings', file=sys.stderr)

    # Canonical USDHKD source: fetch_fx owns cache, provider order and fallback.
    fx_hkd_to_usd, fx_meta = load_canonical_fx()
    if fx_meta['fallback_used']:
        print(f'  WARN: FX fallback in use: {fx_meta["source"]}', file=sys.stderr)

    combined_out = compute_combined(us_meta, hk_meta,
                                    holdings_all={'us': us_holdings, 'hk': hk_holdings},
                                    fx_hkd_to_usd=fx_hkd_to_usd)
    leverage_out = compute_leverage({'us': us_holdings, 'hk': hk_holdings},
                                    fx_hkd_to_usd=fx_hkd_to_usd)
    correlation_out = correlation_xray(
        {'us': us_holdings, 'hk': hk_holdings},
        {'us': (us_meta or {}).get('series') or {},
         'hk': (hk_meta or {}).get('series') or {}},
        fx_hkd_to_usd,
    )
    alerts = build_alerts(us_out, hk_out, combined_out, leverage_out,
                          correlation_out)

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'as_of': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'us': us_out,
        'hk': hk_out,
        'combined': combined_out,
        'correlation': correlation_out,
        'leveraged_exposure': leverage_out,
        'alerts': alerts,
        'meta': {
            'fx_hkd_to_usd_used': round(fx_hkd_to_usd, 6),
            'fx': {
                **fx_meta,
                'hkd_to_usd': round(fx_hkd_to_usd, 8),
            },
            'risk_free_annual': RISK_FREE_ANNUAL,
            'window_days': WINDOW_DAYS,
            'trading_days_per_year': TRADING_DAYS,
            'benchmark_status': bench_status,
            'us_fetch': {
                'fetched': (us_meta or {}).get('fetched', []),
                'failed': (us_meta or {}).get('failed', []),
                'n_returns': (us_meta or {}).get('n_returns'),
                'dates_first': (us_meta or {}).get('dates_first'),
                'dates_last': (us_meta or {}).get('dates_last'),
                'stale': us_stale,
            },
            'hk_fetch': {
                'fetched': (hk_meta or {}).get('fetched', []),
                'failed': (hk_meta or {}).get('failed', []),
                'n_returns': (hk_meta or {}).get('n_returns'),
                'dates_first': (hk_meta or {}).get('dates_first'),
                'dates_last': (hk_meta or {}).get('dates_last'),
                'stale': hk_stale,
            },
        },
    }

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from clawock.safe_io import safe_write_json
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    safe_write_json(OUT_FILE, out)

    # ---- summary print ----
    print('\n=== Portfolio Risk Summary ===')
    def fmt(v, pct=False, suffix=''):
        if v is None:
            return 'N/A'
        if pct:
            return f'{v*100:+.2f}%'
        return f'{v}{suffix}'

    if us_out:
        print(f'US  : β={fmt(us_out.get("beta_spx"))}  '
              f'vol={fmt(us_out.get("vol_30d_annualized"), pct=True)}  '
              f'DD={fmt(us_out.get("max_dd_30d"), pct=True)}  '
              f'Sharpe={fmt(us_out.get("sharpe_30d"))}  '
              f'value=${us_out.get("current_value_usd")}')
    if hk_out:
        print(f'HK  : β={fmt(hk_out.get("beta_hsi"))}  '
              f'vol={fmt(hk_out.get("vol_30d_annualized"), pct=True)}  '
              f'DD={fmt(hk_out.get("max_dd_30d"), pct=True)}  '
              f'Sharpe={fmt(hk_out.get("sharpe_30d"))}  '
              f'value=HK${hk_out.get("current_value_hkd")}')
    if combined_out:
        print(f'COMB: vol={fmt(combined_out.get("vol_30d_annualized"), pct=True)}  '
              f'DD={fmt(combined_out.get("max_dd_30d"), pct=True)}  '
              f'Sharpe={fmt(combined_out.get("sharpe_30d"))}')
    print(f'LEV : US_avg={leverage_out["us_leverage_factor_avg"]}  '
          f'HK_avg={leverage_out["hk_leverage_factor_avg"]}  '
          f'combined={leverage_out["combined_avg"]}  '
          f'margin@-10%={leverage_out["margin_at_risk_pct"]:.2f}%')
    if alerts:
        print(f'\nALERTS ({len(alerts)}):')
        for a in alerts:
            print(f'  [{a["severity"]:6s}] {a["type"]:18s} {a["detail"]}')
    else:
        print('\nNo alerts triggered.')

    print(f'\nWrote {OUT_FILE} ({os.path.getsize(OUT_FILE):,} bytes)')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
