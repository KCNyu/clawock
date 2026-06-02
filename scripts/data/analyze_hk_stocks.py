#!/usr/bin/env python3
"""
analyze_hk_stocks.py - HK portfolio price refresh + news + signal generation

Provider: Tencent qt.gtimg.cn (no key, real-time, works outside HK)
Indices:  r_hkHSI / r_hkHSTECH via same API
News:     Finnhub (needs FINNHUB_API_KEY in .api_keys)

Usage:
  python3 analyze_hk_stocks.py            # refresh prices + news + report
  python3 analyze_hk_stocks.py --no-fetch # use cached prices, just report
  python3 analyze_hk_stocks.py --no-news  # skip news (faster)
  python3 analyze_hk_stocks.py --dry-run  # print prices, don't write file
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
TIMEOUT = 10
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})

# Known 2x/3x leveraged ETFs for risk labeling
LEVERAGED = {'07226', '03032X', '07709', '07747'}

# HK ticker → Finnhub symbol candidates
def _finnhub_syms(code: str) -> List[str]:
    n = int(code)
    return [f"{n:04d}.HK", f"HK:{n}", f"{code}.HK"]

# ── helpers ──────────────────────────────────────────────────────────────────

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


def _pct(c: float, pc: float) -> float:
    return round((c - pc) / pc * 100, 2) if pc else 0.0


def _parse_gtimg(text: str) -> Optional[Dict]:
    """Parse a single Tencent qtgtimg response line."""
    try:
        start = text.find('"') + 1
        end   = text.rfind('"')
        if start <= 0 or end <= start:
            return None
        parts = text[start:end].split('~')
        if len(parts) < 6:
            return None
        price = float(parts[3])
        pc    = float(parts[4]) if parts[4] else price
        op    = float(parts[5]) if parts[5] else price
        # 日内最高/最低 (Tencent HK fields 33/34) — 之前没取，导致 portfolio 的
        # day_high/day_low/day_open 永远是旧交易日残留值（2026-05-29 审计发现）
        hi    = float(parts[33]) if len(parts) > 34 and parts[33] else None
        lo    = float(parts[34]) if len(parts) > 34 and parts[34] else None
        return {
            'name': parts[1],
            'c': price, 'pc': pc, 'o': op,
            'h': hi, 'l': lo,
            'dp': _pct(price, pc),
        }
    except Exception:
        return None


# ── price fetching ────────────────────────────────────────────────────────────

def _fetch_eastmoney_hk(codes: List[str]) -> Dict[str, Dict]:
    """Eastmoney push2 batch for HK board (secid prefix 116). Independent of Tencent."""
    if not codes:
        return {}
    secids = ','.join(f"116.{c}" for c in codes)
    try:
        r = SESSION.get(
            'https://push2.eastmoney.com/api/qt/ulist.np/get',
            params={
                'fltt': 2, 'invt': 2,
                'fields': 'f12,f14,f2,f3,f15,f16,f17,f18,f5',
                'secids': secids,
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            },
            headers={'Referer': 'https://quote.eastmoney.com/'},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        out: Dict[str, Dict] = {}
        for item in (r.json().get('data') or {}).get('diff') or []:
            t = item.get('f12')
            c = item.get('f2')
            if not t or c in (None, '-'):
                continue
            c = float(c)
            pc_raw = item.get('f18')
            pc = float(pc_raw) if pc_raw not in (None, '-') else c
            out[t] = {
                'name': item.get('f14') or t,
                'c': c, 'pc': pc,
                'o': float(item.get('f17') or c),
                'dp': float(item.get('f3') or _pct(c, pc)),
            }
        return out
    except Exception as e:
        print(f"  ⚠️  Eastmoney HK batch failed: {e}")
        return {}


def _fetch_stooq(code: str) -> Optional[Dict]:
    """Fallback: stooq.com CSV. Returns same-day OHLCV; fails for very new IPOs (e.g. 00100)."""
    try:
        sym = f"{int(code):04d}.hk"  # 4-digit
        r = SESSION.get(
            'https://stooq.com/q/l/',
            params={'s': sym, 'i': 'd', 'f': 'sd2t2ohlcv'},
            timeout=TIMEOUT,
        )
        line = r.text.strip().split('\n')[-1]
        parts = line.split(',')
        if len(parts) < 8 or 'N/D' in parts:
            return None
        # CSV: Symbol,Date,Time,Open,High,Low,Close,Volume
        op    = float(parts[3])
        price = float(parts[6])
        # stooq does NOT include prev_close — approximate from open if no other source
        # Better: leave pc=price to flag "no daily change available"
        return {'name': code, 'c': price, 'pc': op, 'o': op,
                'dp': _pct(price, op), '_pc_quality': 'open-as-pc'}
    except Exception:
        return None


def _fetch_yfinance(code: str) -> Optional[Dict]:
    """Fallback: yfinance (e.g. 0100.HK). Requires the `yfinance` package."""
    try:
        import yfinance as yf  # lazy import
        sym = f"{int(code):04d}.HK"
        t = yf.Ticker(sym)
        info = t.fast_info
        price = float(info.get('lastPrice') or info.get('last_price') or 0)
        pc    = float(info.get('previousClose') or info.get('previous_close') or 0)
        op    = float(info.get('open') or 0)
        if price <= 0 or pc <= 0:
            return None
        return {'name': code, 'c': price, 'pc': pc, 'o': op, 'dp': _pct(price, pc)}
    except Exception:
        return None


def fetch_hk_quotes(codes: List[str]) -> Dict[str, Dict]:
    """Fetch HK stock prices: Tencent (primary) → Eastmoney HK (independent cross-check) →
    stooq → yfinance. When BOTH Tencent and Eastmoney succeed for the same code, cross-check
    c/pc and warn if divergence > 1% — this is the trip-wire for stale-data drift.
    """
    results: Dict[str, Dict] = {}

    # Tier 1: Tencent gtimg batch
    tencent: Dict[str, Dict] = {}
    query_codes = [f'r_hk{c}' for c in codes]
    url = f"https://qt.gtimg.cn/q={','.join(query_codes)}"
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        r.encoding = 'gbk'
        for line in r.text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            eq = line.find('=')
            key_part = line[:eq] if eq > 0 else ''
            code = key_part.replace('v_r_hk', '').replace('v_hk', '')
            parsed = _parse_gtimg(line)
            if parsed and parsed['c'] > 0:
                tencent[code] = parsed
    except Exception as e:
        print(f"  ⚠️  Tencent batch failed: {e}")

    # Tier 1b: Tencent single-code retry (different prefix)
    for code in [c for c in codes if c not in tencent]:
        for prefix in ('r_hk', 'hk'):
            try:
                r = SESSION.get(f"https://qt.gtimg.cn/q={prefix}{code}", timeout=TIMEOUT)
                r.encoding = 'gbk'
                parsed = _parse_gtimg(r.text)
                if parsed and parsed['c'] > 0:
                    tencent[code] = parsed
                    break
            except Exception:
                continue

    # Tier 2: Eastmoney HK batch — runs alongside Tencent so we can cross-check
    eastmoney = _fetch_eastmoney_hk(codes)

    # Cross-check + merge: prefer Tencent when both succeed; record divergence
    for code in codes:
        tq = tencent.get(code)
        eq = eastmoney.get(code)
        if tq and eq:
            c_div = abs(tq['c'] - eq['c']) / max(tq['c'], 0.001) * 100
            pc_div = abs(tq['pc'] - eq['pc']) / max(tq['pc'], 0.001) * 100
            tq['_src'] = 'Tencent+Eastmoney'
            if c_div > 1.0 or pc_div > 1.0:
                tq['_divergence'] = {
                    'tencent': {'c': tq['c'], 'pc': tq['pc']},
                    'eastmoney': {'c': eq['c'], 'pc': eq['pc']},
                    'c_div_pct': round(c_div, 2),
                    'pc_div_pct': round(pc_div, 2),
                }
                print(f"  ⚠️  {code} two-source divergence: "
                      f"Tencent c={tq['c']}/pc={tq['pc']} vs "
                      f"Eastmoney c={eq['c']}/pc={eq['pc']} "
                      f"(c {c_div:.2f}% pc {pc_div:.2f}%)")
            results[code] = tq
        elif tq:
            tq['_src'] = 'Tencent'
            results[code] = tq
        elif eq:
            eq['_src'] = 'Eastmoney'
            results[code] = eq
            print(f"  [fallback] {code} via Eastmoney HK (Tencent missed)")

    # Tier 3: stooq (only for codes still missing — established HK codes only)
    for code in [c for c in codes if c not in results]:
        parsed = _fetch_stooq(code)
        if parsed:
            parsed['_src'] = 'stooq'
            results[code] = parsed
            print(f"  [fallback] {code} via stooq (prev_close ≈ open, low confidence)")

    # Tier 4: yfinance as last resort (often rate-limited)
    for code in [c for c in codes if c not in results]:
        parsed = _fetch_yfinance(code)
        if parsed:
            parsed['_src'] = 'yfinance'
            results[code] = parsed
            print(f"  [fallback] {code} via yfinance")

    if missing := [c for c in codes if c not in results]:
        print(f"  ❌ Could not fetch: {', '.join(missing)} (no fallback covers these)")

    return results


def fetch_indices() -> Dict[str, Dict]:
    """Fetch HSI and HSTECH from gtimg."""
    indices = {}
    for sym, label in [('r_hkHSI', '恒生指数'), ('r_hkHSTECH', '恒生科技')]:
        try:
            r = SESSION.get(f"https://qt.gtimg.cn/q={sym}", timeout=TIMEOUT)
            r.encoding = 'gbk'
            parsed = _parse_gtimg(r.text)
            if parsed and parsed['c'] > 0:
                parsed['label'] = label
                indices[sym] = parsed
        except Exception:
            pass
    return indices


# ── news ─────────────────────────────────────────────────────────────────────

POSITIVE_WORDS = ['上涨', '大涨', '强劲', '盈利', '增长', '突破', '买入', '看多',
                  'rise', 'gain', 'beat', 'surge', 'upgrade', 'buy', 'positive', 'profit']
NEGATIVE_WORDS = ['下跌', '暴跌', '亏损', '减持', '卖出', '看空', '下调', '危机',
                  'fall', 'drop', 'loss', 'miss', 'downgrade', 'sell', 'negative', 'risk']

def get_finnhub_news(code: str, api_key: str, days: int = 7) -> List[Dict]:
    """Fetch company news from Finnhub for an HK stock, trying multiple symbol formats."""
    if not api_key:
        return []
    now  = datetime.now(timezone.utc)
    from_date = (now - timedelta(days=days)).strftime('%Y-%m-%d')
    to_date   = now.strftime('%Y-%m-%d')
    for sym in _finnhub_syms(code):
        try:
            r = SESSION.get(
                'https://finnhub.io/api/v1/company-news',
                params={'symbol': sym, 'from': from_date, 'to': to_date, 'token': api_key},
                timeout=12,
            )
            items = r.json()
            if isinstance(items, list) and items:
                return items[:5]
        except Exception:
            continue
    return []


def news_sentiment(articles: List[Dict]) -> str:
    pos, neg = 0, 0
    for a in articles:
        text = (a.get('headline', '') + ' ' + a.get('summary', '')).lower()
        pos += sum(1 for w in POSITIVE_WORDS if w in text)
        neg += sum(1 for w in NEGATIVE_WORDS if w in text)
    if pos > neg + 1:
        return 'positive'
    if neg > pos + 1:
        return 'negative'
    return 'neutral'


# ── signal generation ─────────────────────────────────────────────────────────

def signal(holding: Dict) -> str:
    dp    = holding.get('today_change_pct', 0)
    pnl_p = holding.get('pnl_percent', 0)
    code  = holding.get('ticker', '')
    is_lev = any(x in code for x in ('07226', '03033', '03032'))

    if dp <= -8:
        return '⚠️ ALERT'
    if dp <= -5:
        return '△ WATCH'
    if pnl_p >= 50 and dp >= 0:
        return '▽ TRIM'
    if pnl_p <= -20:
        return '✋ STOP?'
    if pnl_p <= -10:
        return '─ HOLD'
    if dp >= 5:
        return '▲ HOLD+'
    return '─ HOLD'


# ── portfolio update ──────────────────────────────────────────────────────────

def update_hk_portfolio(dry_run: bool = False) -> Dict:
    with open(PORTFOLIO_PATH, encoding='utf-8') as f:
        data = json.load(f)

    hkt_tz  = timezone(timedelta(hours=8))
    now_hkt = datetime.now(hkt_tz)
    hkt_str = now_hkt.strftime('%Y/%m/%d %H:%M HKT')

    us = data['portfolios']['hk_stocks']
    active = [h for h in us['holdings'] if h.get('shares', 0) > 0]
    codes  = [h['ticker'] for h in active]

    # Zero out snapshot fields on closed positions — refresh skips shares==0
    # holdings, so without this they keep stale cv/pnl from the pre-close run.
    for h in us['holdings']:
        if h.get('shares', 0) == 0:
            for k in ('current_value', 'pnl_abs', 'pnl_percent',
                      'today_change', 'today_change_pct'):
                if h.get(k):
                    h[k] = 0

    print(f"\n{'═'*60}")
    print(f"  HK Portfolio Price Refresh   {now_hkt.strftime('%Y-%m-%d %H:%M HKT')}")
    print(f"  Holdings: {', '.join(codes)}")
    print(f"{'═'*60}")

    quotes = fetch_hk_quotes(codes)
    print(f"  Fetched {len(quotes)}/{len(codes)} prices from Tencent gtimg")

    today_date = now_hkt.strftime('%Y-%m-%d')
    updated, missing = [], []

    for h in active:
        code = h['ticker']
        q = quotes.get(code)
        if not q:
            missing.append(code)
            continue

        c    = q['c']
        pc   = q['pc']
        cost = h['cost_basis']
        shrs = h['shares']

        h['current_price']    = round(c, 3)
        h['prev_close']       = round(pc, 3)
        h['prev_close_date']  = today_date
        h['today_change_pct'] = round(q['dp'], 2)
        h['current_value']    = round(c * shrs, 2)
        h['pnl_abs']          = round((c - cost) * shrs, 2)
        h['pnl_percent']      = round((c - cost) / cost * 100, 2) if cost else 0
        h['today_change']     = round((c - pc) * shrs, 2)
        h['stock_name']       = q.get('name', h.get('stock_name', code))
        h['data_source']      = f"{q.get('_src', 'Tencent')} {now_hkt.strftime('%b %d %H:%M HKT')}"

        # 日内区间 — 仅当本次行情带 open/high/low 时覆盖，避免旧交易日残留值
        # （Tencent 主源有；stooq/yfinance fallback 没有则保持上次真值不写脏数据）
        if q.get('o'): h['day_open'] = round(q['o'], 3)
        if q.get('h'): h['day_high'] = round(q['h'], 3)
        if q.get('l'): h['day_low']  = round(q['l'], 3)

        updated.append(code)
        pnl_s = '+' if h['pnl_abs'] >= 0 else ''
        print(f"  {code} {q.get('name','')[:6]:6s}  HK${c:.3f}  "
              f"({h['today_change_pct']:+.2f}%)  "
              f"P&L: {pnl_s}HK${h['pnl_abs']:.0f} ({pnl_s}{h['pnl_percent']:.1f}%)")

    # Portfolio totals
    total_cost  = sum(h['cost_basis'] * h['shares'] for h in active)
    total_value = sum(h.get('current_value', h['cost_basis'] * h['shares']) for h in active)
    total_pnl   = total_value - total_cost
    today_chg   = sum(h.get('today_change', 0) for h in active)

    us['total_cost']          = round(total_cost, 2)
    us['total_current_value'] = round(total_value, 2)
    us['total_pnl']           = round(total_pnl, 2)
    us['total_pnl_percent']   = round(total_pnl / total_cost * 100, 2) if total_cost else 0
    us['today_total_change']  = round(today_chg, 2)

    # Refresh HK indices_snapshot (HSI/HSTECH) so dashboard Market Snapshot stays fresh.
    # build_dashboard normalizes "chg_pct" → "change_pct" downstream.
    try:
        idx_raw = fetch_indices()
        snap = {}
        for key, short in [('r_hkHSI', 'HSI'), ('r_hkHSTECH', 'HSTECH')]:
            if key in idx_raw:
                r = idx_raw[key]
                snap[short] = {
                    'name':       r.get('label', short),
                    'price':      round(r['c'], 2),
                    'prev_close': round(r.get('pc') or r['c'], 2),
                    'chg_pct':    round(r.get('dp') or 0, 3),
                    'source':     f"Tencent qt.gtimg.cn {hkt_str}",
                }
        if snap:
            us['indices_snapshot'] = snap
    except Exception as e:
        print(f"  ⚠ HK indices snapshot failed (non-fatal): {e}")

    data['last_updated'] = hkt_str

    print(f"{'─'*60}")
    pnl_s = '+' if total_pnl >= 0 else ''
    print(f"  Total:   HK${total_value:>9,.0f}  (cost HK${total_cost:,.0f})")
    print(f"  P&L:     {pnl_s}HK${total_pnl:>8,.0f}  ({pnl_s}{total_pnl/total_cost*100:.1f}%)" if total_cost else "")
    print(f"  Today:   HK${today_chg:>+9,.0f}")

    if missing:
        print(f"  ⚠️  Failed: {', '.join(missing)}")

    if dry_run:
        print("  [dry-run] Not written.\n")
    else:
        from safe_io import safe_write_json
        from recompute_realized import recompute as recompute_realized
        recompute_realized(data)
        safe_write_json(PORTFOLIO_PATH, data)
        print(f"  ✅ Saved → {PORTFOLIO_PATH}")

    print(f"{'═'*60}\n")
    return data


# ── analysis report ───────────────────────────────────────────────────────────

def print_report(data: Dict, news_map: Optional[Dict[str, List]] = None):
    hkt_tz  = timezone(timedelta(hours=8))
    now_hkt = datetime.now(hkt_tz)

    us      = data['portfolios']['hk_stocks']
    active  = [h for h in us['holdings'] if h.get('shares', 0) > 0]

    # Indices
    indices = fetch_indices()

    total_cost  = us.get('total_cost', 0)
    total_value = us.get('total_current_value', 0)
    total_pnl   = us.get('total_pnl', 0)
    today_chg   = us.get('today_total_change', 0)

    print(f"\n{'═'*62}")
    print(f"  港股持仓分析   {now_hkt.strftime('%Y-%m-%d %H:%M HKT')}")
    print(f"{'═'*62}")

    # Index line
    idx_parts = []
    for key in ('r_hkHSI', 'r_hkHSTECH'):
        if key in indices:
            idx = indices[key]
            idx_parts.append(f"{idx['label']} {idx['c']:,.0f}（{idx['dp']:+.2f}%）")
    if idx_parts:
        print("  指数：" + "  |  ".join(idx_parts))

    pnl_s = '+' if total_pnl >= 0 else ''
    print(f"  总市值:  HK${total_value:>10,.0f}  (成本 HK${total_cost:,.0f})")
    print(f"  浮盈亏:  {pnl_s}HK${total_pnl:>9,.0f}  ({pnl_s}{total_pnl/total_cost*100:.1f}%)" if total_cost else "")
    today_s = f"{today_chg:+,.0f}"
    print(f"  今日:    HK${today_s:>10}")

    print(f"{'─'*62}")
    print(f"  {'代码':6s} {'名称':8s} {'现价':>8} {'今日':>7} {'成本':>8} {'浮盈':>8} 信号")
    print(f"  {'─'*6} {'─'*8} {'─'*8} {'─'*7} {'─'*8} {'─'*8} {'─'*6}")

    for h in active:
        code  = h['ticker']
        name  = h.get('stock_name', code)[:6]
        price = h.get('current_price', 0)
        dp    = h.get('today_change_pct', 0)
        cost  = h.get('cost_basis', 0)
        pnl_p = h.get('pnl_percent', 0)
        sig   = signal(h)
        pnl_s = '+' if pnl_p >= 0 else ''
        dp_s  = f'{dp:+.2f}%'
        print(f"  {code:6s} {name:8s} HK${price:>6.3f} {dp_s:>7} HK${cost:>5.2f} {pnl_s}{pnl_p:>6.1f}% {sig}")

    print(f"{'─'*62}")
    print()

    # Detailed signals + news
    print("  详细信号")
    print(f"  {'─'*58}")
    for h in active:
        sig   = signal(h)
        dp    = h.get('today_change_pct', 0)
        pnl   = h.get('pnl_percent', 0)
        name  = h.get('stock_name', h['ticker'])[:8]
        price = h.get('current_price', 0)
        code  = h['ticker']
        articles = (news_map or {}).get(code, [])
        sentiment = news_sentiment(articles) if articles else ''

        print(f"  {sig} [{code}] {name}  HK${price:.3f}  今日{dp:+.1f}%  浮盈{pnl:+.1f}%")
        notes = []
        if abs(dp) >= 5:
            notes.append(f"今日{'大涨' if dp > 0 else '大跌'} {dp:+.1f}%")
        if pnl >= 50:
            notes.append(f"浮盈 {pnl:.0f}%，可考虑减仓")
        if pnl <= -15:
            notes.append(f"浮亏 {pnl:.0f}%，关注止损")
        if '07226' in code or '03032' in code:
            notes.append("2x 杠杆 ETF，波动放大")
        for n in notes:
            print(f"     · {n}")
        if articles:
            senti_label = {'positive': '偏正面', 'negative': '偏负面', 'neutral': '中性'}.get(sentiment, sentiment)
            print(f"     · 新闻 {len(articles)} 条，情绪 {senti_label}")
            for a in articles[:2]:
                headline = a.get('headline', '')[:55]
                source   = a.get('source', '')
                print(f"       → {headline}  [{source}]")

    # Risk summary
    lev_value = sum(h.get('current_value', 0) for h in active
                    if any(x in h['ticker'] for x in ('07226',)))
    lev_pct = lev_value / total_value * 100 if total_value else 0
    loss_count = sum(1 for h in active if h.get('pnl_percent', 0) < 0)

    print(f"  {'─'*58}")
    print(f"  风险摘要")
    print(f"  2x杠杆ETF敞口:  {lev_pct:.1f}%  (HK${lev_value:,.0f})")
    print(f"  亏损持仓:       {loss_count}/{len(active)} 只")
    print(f"{'═'*62}\n")


# ── WeChat-friendly report (mobile/chat format) ───────────────────────────────

def print_wechat_report(data: Dict, news_map: Optional[Dict[str, List]] = None, md_table: bool = False):
    """Compact mobile-friendly format for WeChat/Telegram delivery.

    md_table=True: holdings rendered as markdown table (intraday cron via
    `--md-table`); briefings keep ASCII single-column form.
    """
    hkt_tz  = timezone(timedelta(hours=8))
    now_hkt = datetime.now(hkt_tz)

    us      = data['portfolios']['hk_stocks']
    active  = [h for h in us['holdings'] if h.get('shares', 0) > 0]
    indices = fetch_indices()

    total_cost  = us.get('total_cost', 0)
    total_value = us.get('total_current_value', 0)
    total_pnl   = us.get('total_pnl', 0)
    today_chg   = us.get('today_total_change', 0)
    pnl_pct     = total_pnl / total_cost * 100 if total_cost else 0

    lines: List[str] = []

    # Header
    lines.append(f"🇭🇰 港股盯盘 | {now_hkt.strftime('%m/%d %H:%M HKT')}")

    # Indices
    idx_bits = []
    for key, emoji in [('r_hkHSI','恒指'), ('r_hkHSTECH','恒科')]:
        if key in indices:
            idx = indices[key]
            arrow = '▲' if idx['dp'] >= 0 else '▼'
            idx_bits.append(f"{emoji} {idx['c']:,.0f} {arrow}{abs(idx['dp']):.2f}%")
    if idx_bits:
        lines.append('  ' + '  '.join(idx_bits))

    # Totals — single line so LLM doesn't reformat 3-line→1-line (verbatim violation)
    pnl_sign   = '+' if total_pnl  >= 0 else ''
    today_sign = '+' if today_chg >= 0 else ''
    lines.append('')
    lines.append(
        f"📊 市值 HK${total_value:,.0f}"
        f" | 浮盈 {pnl_sign}{total_pnl:,.0f} ({pnl_sign}{pnl_pct:.1f}%)"
        f" | 今日 {today_sign}{today_chg:,.0f}"
    )

    # Holdings list
    lines.append('')
    if md_table:
        # 7-col visual-width-aligned markdown table — works on raw monospace
        # WeChat mobile (no md table render) and desktop. See _wechat_table.py
        # for the why (CJK chars = 2 visual width, fixed widths per col).
        from _wechat_table import render_holdings_table
        rows = [{
            'code':      h['ticker'],
            'shares':    h.get('shares', 0),
            'cost':      h.get('cost_basis'),
            'price':     h.get('current_price', 0),
            'today_pct': h.get('today_change_pct', 0),
            'pnl_pct':   h.get('pnl_percent', 0),
            'pnl_abs':   h.get('pnl_abs', 0),
        } for h in active]
        lines.extend(render_holdings_table(rows, currency='HKD'))
    else:
        for h in active:
            code  = h['ticker']
            name  = h.get('stock_name', code).replace('-W', '')[:5]
            price = h.get('current_price', 0)
            dp    = h.get('today_change_pct', 0)
            pnl_p = h.get('pnl_percent', 0)
            arrow = '▲' if dp >= 0 else '▼'
            pnl_emoji = '🟢' if pnl_p >= 0 else '🔴'
            lines.append(f"{pnl_emoji} {code} {name}  {price:.3f}  {arrow}{abs(dp):.1f}%  浮{pnl_p:+.1f}%")

    # Actionable signals only (skip plain HOLD)
    alerts: List[str] = []
    for h in active:
        sig = signal(h)
        if 'HOLD' in sig and 'HOLD+' not in sig:
            continue
        dp    = h.get('today_change_pct', 0)
        pnl   = h.get('pnl_percent', 0)
        name  = h.get('stock_name', h['ticker']).replace('-W','')[:6]
        alerts.append(f"  {sig} {h['ticker']} {name} | 今日{dp:+.1f}% 浮{pnl:+.1f}%")
    if alerts:
        lines.append('')
        lines.append('⚠️ 信号')
        lines.extend(alerts)

    # Risk
    lev_value = sum(h.get('current_value', 0) for h in active
                    if any(x in h['ticker'] for x in ('07226',)))
    lev_pct = lev_value / total_value * 100 if total_value else 0
    loss_count = sum(1 for h in active if h.get('pnl_percent', 0) < 0)
    lines.append('')
    lines.append(f"📉 亏损持仓 {loss_count}/{len(active)}  |  2x杠杆敞口 {lev_pct:.0f}%")

    # News — only show stocks with non-empty results, max 2 headlines each
    news_lines: List[str] = []
    for code, articles in (news_map or {}).items():
        if not articles:
            continue
        senti = news_sentiment(articles)
        senti_emoji = {'positive':'📰✅','negative':'📰⚠️','neutral':'📰'}.get(senti, '📰')
        news_lines.append(f"{senti_emoji} {code} ({len(articles)}条)")
        for a in articles[:2]:
            headline = a.get('headline','')[:40]
            news_lines.append(f"   · {headline}")
    if news_lines:
        lines.append('')
        lines.append('📰 新闻')
        lines.extend(news_lines)

    print('\n'.join(lines))


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    no_fetch = '--no-fetch' in sys.argv
    dry_run  = '--dry-run'  in sys.argv
    no_news  = '--no-news'  in sys.argv
    wechat   = '--wechat'   in sys.argv
    md_table = '--md-table' in sys.argv

    if no_fetch:
        with open(PORTFOLIO_PATH, encoding='utf-8') as f:
            data = json.load(f)
        if not wechat:
            print("  [--no-fetch] Using cached prices.")
    else:
        # In wechat mode, suppress the verbose progress prints but still write file
        if wechat:
            import io, contextlib
            _buf = io.StringIO()
            with contextlib.redirect_stdout(_buf):
                data = update_hk_portfolio(dry_run=dry_run)
        else:
            data = update_hk_portfolio(dry_run=dry_run)

    # Fetch news (unless --no-news)
    news_map: Dict[str, List] = {}
    if not no_news:
        keys = load_api_keys()
        finnhub_key = keys.get('FINNHUB_API_KEY', '')
        active_codes = [h['ticker'] for h in data['portfolios']['hk_stocks']['holdings']
                        if h.get('shares', 0) > 0]
        if finnhub_key:
            if not wechat:
                print(f"  [新闻] Finnhub 7天新闻...")
            for code in active_codes:
                articles = get_finnhub_news(code, finnhub_key)
                news_map[code] = articles
                if not wechat:
                    print(f"    {code}: {len(articles)} 条")
        elif not wechat:
            print("  [新闻] 未找到 FINNHUB_API_KEY，跳过新闻")

    if wechat:
        print_wechat_report(data, news_map, md_table=md_table)
    else:
        print_report(data, news_map)
