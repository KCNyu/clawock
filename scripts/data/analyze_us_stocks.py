#!/usr/bin/env python3
"""
analyze_us_stocks.py - US portfolio analysis for active holdings
Steps:
  1. Fetch fresh prices via fetch_us_stocks (multi-provider)
  2. Pull RSI from Yahoo daily history (free, no rate limit)
  3. Pull recent news headlines via Finnhub
  4. Generate per-holding signals + portfolio risk summary

Usage:
  python3 analyze_us_stocks.py             # full analysis
  python3 analyze_us_stocks.py --no-fetch  # skip price refresh (use cached)
  python3 analyze_us_stocks.py --no-news   # skip Finnhub news
"""

import json, os, sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
import requests

# ── imports from sibling script ─────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_us_stocks import (
    update_us_portfolio, load_api_keys,
    PORTFOLIO_PATH, SESSION, TIMEOUT
)

ET_TZ  = timezone(timedelta(hours=-4))
HKT_TZ = timezone(timedelta(hours=8))


# ── technical indicators ─────────────────────────────────────────────────────

def get_daily_closes_polygon(ticker: str, api_key: str, days: int = 90) -> List[float]:
    """Polygon.io daily closes — free tier, historical, no rate-limit surprise."""
    if not api_key:
        return []
    from datetime import date
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    end   = today.isoformat()
    try:
        r = SESSION.get(
            f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
            params={'adjusted': 'true', 'sort': 'asc', 'limit': 150, 'apiKey': api_key},
            timeout=TIMEOUT,
        )
        return [x['c'] for x in r.json().get('results', [])]
    except Exception:
        return []


def get_daily_closes_av(ticker: str, api_key: str) -> List[float]:
    """Alpha Vantage TIME_SERIES_DAILY compact — fallback if Polygon has no data."""
    if not api_key:
        return []
    try:
        r = SESSION.get(
            'https://www.alphavantage.co/query',
            params={'function': 'TIME_SERIES_DAILY', 'symbol': ticker,
                    'outputsize': 'compact', 'apikey': api_key},
            timeout=25,
        )
        ts = r.json().get('Time Series (Daily)', {})
        closes = [float(v['4. close']) for v in list(ts.values())[:60]]
        return list(reversed(closes))  # oldest first
    except Exception:
        return []


def compute_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI from a list of closing prices."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    rs = avg_g / avg_l if avg_l > 0 else float('inf')
    return round(100 - 100 / (1 + rs), 1)


def compute_ma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 4)


def get_technicals(ticker: str, keys: Dict) -> Dict:
    """RSI-14, MA-20, MA-50. Source: Polygon → Alpha Vantage fallback."""
    import time
    closes = get_daily_closes_polygon(ticker, keys.get('POLYGON_API_KEY', ''))
    src = 'Polygon'
    if len(closes) < 20:
        closes = get_daily_closes_av(ticker, keys.get('ALPHA_VANTAGE_API_KEY', ''))
        src = 'AV'
        time.sleep(0.5)   # AV: stay within 5 calls/min free tier
    if not closes:
        return {}
    return {
        'rsi14':   compute_rsi(closes),
        'ma20':    compute_ma(closes, 20),
        'ma50':    compute_ma(closes, 50),
        'close_n': len(closes),
        'src':     src,
    }


# ── news ─────────────────────────────────────────────────────────────────────

def get_news(ticker: str, api_key: str, days: int = 7) -> List[Dict]:
    """Fetch recent news headlines via Finnhub."""
    if not api_key:
        return []
    now   = datetime.now(ET_TZ)
    start = (now - timedelta(days=days)).strftime('%Y-%m-%d')
    end   = now.strftime('%Y-%m-%d')
    try:
        r = SESSION.get(
            f"https://finnhub.io/api/v1/company-news?symbol={ticker}"
            f"&from={start}&to={end}&token={api_key}",
            timeout=TIMEOUT,
        )
        return r.json()[:5] if isinstance(r.json(), list) else []
    except Exception:
        return []


POSITIVE = {'surge', 'soar', 'rally', 'gain', 'beat', 'upgrade', 'strong',
            'bullish', 'breakthrough', 'record', 'profit', 'growth'}
NEGATIVE = {'fall', 'drop', 'decline', 'loss', 'miss', 'downgrade', 'weak',
            'bearish', 'crash', 'concern', 'risk', 'warning', 'lawsuit'}


def news_sentiment(items: List[Dict]) -> Tuple[int, str]:
    score = 0
    for n in items:
        text = (n.get('headline', '') + ' ' + n.get('summary', '')).lower()
        score += sum(1 for w in POSITIVE if w in text)
        score -= sum(1 for w in NEGATIVE if w in text)
    if   score >= 3:  label = 'positive'
    elif score <= -3: label = 'negative'
    else:             label = 'neutral'
    return score, label


# ── signal logic ─────────────────────────────────────────────────────────────

def generate_signal(holding: Dict, tech: Dict, news_items: List[Dict]) -> Tuple[str, List[str]]:
    """
    Returns (signal_label, [reason, ...]).
    Labels: STRONG-BUY / BUY / HOLD / WATCH / TRIM / STOP-LOSS
    """
    reasons: List[str] = []
    score   = 0   # positive = bullish

    pnl_pct   = holding.get('pnl_percent', 0)
    day_pct   = holding.get('today_change_pct', 0)
    rsi       = tech.get('rsi14')
    price     = holding.get('current_price', 0)
    ma20      = tech.get('ma20')
    ma50      = tech.get('ma50')
    name      = holding.get('name', holding['ticker'])
    is_lev    = any(x in name for x in ('2X', '3X', 'Bull', 'Bear', 'Daily Target', 'Leveraged'))
    lev_mult  = 3 if '3X' in name else 2 if '2X' in name else 1

    # RSI signals
    if rsi is not None:
        if   rsi >= 80: reasons.append(f"RSI {rsi} 极度超买"); score -= 2
        elif rsi >= 70: reasons.append(f"RSI {rsi} 超买区");   score -= 1
        elif rsi <= 25: reasons.append(f"RSI {rsi} 极度超卖"); score += 2
        elif rsi <= 35: reasons.append(f"RSI {rsi} 超卖区");   score += 1

    # Price vs MA
    if ma20 and price:
        if   price > ma20 * 1.10: reasons.append(f"价格高于MA20 +{(price/ma20-1)*100:.1f}%"); score -= 1
        elif price < ma20 * 0.95: reasons.append(f"价格低于MA20 {(price/ma20-1)*100:.1f}%"); score += 1
    if ma50 and price:
        if   price > ma50: reasons.append("站上MA50")
        else:              reasons.append("跌破MA50")

    # P&L thresholds
    if   pnl_pct >= 80:  reasons.append(f"浮盈 {pnl_pct:+.1f}% 考虑分批止盈"); score -= 2
    elif pnl_pct >= 40:  reasons.append(f"浮盈 {pnl_pct:+.1f}%");              score -= 1
    elif pnl_pct <= -20: reasons.append(f"浮亏 {pnl_pct:.1f}% 警惕止损");       score -= 2
    elif pnl_pct <= -10: reasons.append(f"浮亏 {pnl_pct:.1f}%");               score -= 1

    # Today's move
    if   day_pct >=  8: reasons.append(f"今日暴涨 +{day_pct:.1f}%，注意回调")
    elif day_pct >=  5: reasons.append(f"今日强涨 +{day_pct:.1f}%")
    elif day_pct <= -5: reasons.append(f"今日大跌 {day_pct:.1f}%")

    # Leverage flag
    if is_lev:
        reasons.append(f"{lev_mult}x 杠杆 ETF，波动放大")
        if pnl_pct <= -15: score -= 1  # leverage losses compound

    # News
    if news_items:
        _, sentiment = news_sentiment(news_items)
        if   sentiment == 'positive': reasons.append("近期新闻偏正面"); score += 1
        elif sentiment == 'negative': reasons.append("近期新闻偏负面"); score -= 1

    # Determine label
    if pnl_pct <= -20 and is_lev:
        label = 'STOP-LOSS'
    elif score >= 2:
        label = 'BUY'
    elif score == 1:
        label = 'HOLD+'
    elif score == 0 or score == -1:
        label = 'HOLD'
    elif score == -2:
        label = 'WATCH'
    else:
        label = 'TRIM'

    return label, reasons


# ── report ────────────────────────────────────────────────────────────────────

SIGNAL_COLOR = {
    'BUY':       '▲',
    'HOLD+':     '▲',
    'HOLD':      '─',
    'WATCH':     '△',
    'TRIM':      '▽',
    'STOP-LOSS': '▼',
}


def print_report(data: Dict, analyses: List[Dict]):
    us    = data['portfolios']['us_stocks']
    now   = datetime.now(ET_TZ)
    now_h = datetime.now(HKT_TZ)

    w = 64
    print(f"\n{'═'*w}")
    print(f"  US Portfolio Analysis")
    print(f"  ET:  {now.strftime('%Y-%m-%d %H:%M %Z')}  |  HKT: {now_h.strftime('%H:%M HKT')}")
    print(f"{'═'*w}")

    tc   = us.get('total_cost', 0)
    tv   = us.get('total_current_value', 0)
    pnl  = us.get('total_pnl', 0)
    pnl_ = us.get('total_pnl_percent', 0)
    day  = us.get('today_total_change', 0)
    real = us.get('realized_pnl', 0)

    sign = lambda x: '+' if x >= 0 else ''
    print(f"  总市值:  ${tv:>10,.2f}  (成本 ${tc:,.2f})")
    print(f"  浮盈亏:  {sign(pnl)}${pnl:>9,.2f}  ({sign(pnl_)}{pnl_:.2f}%)")
    print(f"  今日:    {sign(day)}${day:>9,.2f}")
    print(f"  已实现:  +${real:,.2f}")
    print(f"{'─'*w}")

    # Header
    print(f"  {'代码':<7} {'价格':>8} {'今日':>8} {'成本':>8} {'浮盈':>9} {'RSI':>5}  {'信号'}")
    print(f"  {'─'*6} {'─'*8} {'─'*8} {'─'*8} {'─'*9} {'─'*5}  {'─'*8}")

    signal_rows = []
    for a in analyses:
        h     = a['holding']
        tech  = a['tech']
        sig   = a['signal']
        reasons = a['reasons']

        rsi_s = f"{tech['rsi14']:.0f}" if tech.get('rsi14') else ' -- '
        arr   = SIGNAL_COLOR.get(sig, '?')

        print(
            f"  {h['ticker']:<7} "
            f"${h['current_price']:>7.2f} "
            f"{h['today_change_pct']:>+7.2f}% "
            f"${h['cost_basis']:>7.2f} "
            f"{h['pnl_percent']:>+8.2f}% "
            f"{rsi_s:>5}  "
            f"{arr} {sig}"
        )
        signal_rows.append((sig, h['ticker'], reasons, h, tech, a['news']))

    print(f"{'─'*w}")

    # Detailed signals
    print(f"\n  详细信号")
    print(f"{'─'*w}")
    for sig, ticker, reasons, h, tech, news_items in signal_rows:
        arr = SIGNAL_COLOR.get(sig, '?')
        print(f"\n  {arr} [{sig}] {ticker}  ${h['current_price']:.2f}"
              f"  今日 {h['today_change_pct']:+.2f}%  P&L {h['pnl_percent']:+.1f}%")
        if reasons:
            for r in reasons:
                print(f"     · {r}")
        if news_items:
            _, sentiment = news_sentiment(news_items)
            print(f"     · 新闻 ({len(news_items)}条，情绪: {sentiment})")
            for n in news_items[:2]:
                hl = n.get('headline', '')
                src = n.get('source', '')
                print(f"       → {hl[:65]}{'...' if len(hl)>65 else ''}  [{src}]")

    # Risk summary
    print(f"\n{'─'*w}")
    print(f"  风险摘要")
    active = [h for h in us['holdings'] if h.get('shares', 0) > 0]
    lev_val   = sum(h.get('current_value', 0) for h in active
                    if any(x in h.get('name', '') for x in ('2X', '3X', 'Bull', 'Target')))
    lev_pct   = lev_val / tv * 100 if tv else 0
    losing    = [h for h in active if h.get('pnl_percent', 0) < 0]
    lose_val  = sum(abs(h.get('pnl_abs', 0)) for h in losing)

    print(f"  杠杆ETF敞口:  {lev_pct:.1f}%  (${lev_val:,.0f})  "
          + ("⚠️ 偏高" if lev_pct > 50 else ""))
    print(f"  亏损持仓:     {len(losing)}/{len(active)} 只，合计浮亏 ${lose_val:,.0f}")
    stop_loss_alerts = [a for a in analyses if a['signal'] == 'STOP-LOSS']
    if stop_loss_alerts:
        tks = ', '.join(a['holding']['ticker'] for a in stop_loss_alerts)
        print(f"  ⚠️  止损警报: {tks}")

    print(f"{'═'*w}\n")


# ── WeChat-friendly report ───────────────────────────────────────────────────

def print_wechat_report(data: Dict, analyses: List[Dict], md_table: bool = False):
    """Compact mobile-friendly US report for WeChat/Telegram delivery.

    When md_table=True, the holdings block is emitted as a markdown table
    (mobile-aligned via :---: markers + padded cells). Used by intraday
    cron via `--md-table`; briefings keep the ASCII single-column form.
    """
    us    = data['portfolios']['us_stocks']
    now   = datetime.now(ET_TZ)

    tc   = us.get('total_cost', 0)
    tv   = us.get('total_current_value', 0)
    pnl  = us.get('total_pnl', 0)
    pnl_ = us.get('total_pnl_percent', 0)
    day  = us.get('today_total_change', 0)
    real = us.get('realized_pnl', 0)

    lines: List[str] = []
    lines.append(f"🇺🇸 美股盯盘 | {now.strftime('%m/%d %H:%M ET')}")

    # Totals — single line so LLM doesn't reformat 3-line→1-line (verbatim violation)
    sgn  = lambda x: '+' if x >= 0 else ''
    lines.append('')
    totals = (
        f"📊 市值 ${tv:,.0f}"
        f" | 浮盈 {sgn(pnl)}${pnl:,.0f} ({sgn(pnl_)}{pnl_:.1f}%)"
        f" | 今日 {sgn(day)}${day:,.0f}"
    )
    if real:
        totals += f" | ✅ 已实现 +${real:,.0f}"
    lines.append(totals)

    # Holdings
    lines.append('')
    if md_table:
        # 7-col visual-width-aligned markdown table — see _wechat_table.py.
        # Stays consistent line-width on mobile WeChat (no md render there).
        from _wechat_table import render_holdings_table
        rows = [{
            'code':      a['holding']['ticker'],
            'shares':    a['holding'].get('shares', 0),
            'cost':      a['holding'].get('cost_basis'),
            'price':     a['holding'].get('current_price', 0),
            'today_pct': a['holding'].get('today_change_pct', 0),
            'pnl_pct':   a['holding'].get('pnl_percent', 0),
            'pnl_abs':   a['holding'].get('pnl_abs', 0),
        } for a in analyses]
        lines.extend(render_holdings_table(rows, currency='USD'))
    else:
        for a in analyses:
            h     = a['holding']
            tech  = a['tech']
            dp    = h.get('today_change_pct', 0)
            pnl_p = h.get('pnl_percent', 0)
            rsi   = tech.get('rsi14')
            arr   = '▲' if dp >= 0 else '▼'
            emo   = '🟢' if pnl_p >= 0 else '🔴'
            rsi_s = f" RSI{rsi:.0f}" if rsi else ''
            lines.append(f"{emo} {h['ticker']:<5} ${h['current_price']:.2f}  {arr}{abs(dp):.1f}%  浮{pnl_p:+.1f}%{rsi_s}")

    # Actionable signals only (BUY / WATCH / TRIM / STOP-LOSS)
    alerts = []
    for a in analyses:
        sig = a['signal']
        if sig in ('HOLD', 'HOLD+'):
            continue
        h = a['holding']
        arr = SIGNAL_COLOR.get(sig, '?')
        alerts.append(f"  {arr} {sig} {h['ticker']} | 今日{h['today_change_pct']:+.1f}% 浮{h['pnl_percent']:+.1f}%")
        for r in a['reasons'][:2]:
            alerts.append(f"     · {r}")
    if alerts:
        lines.append('')
        lines.append('⚠️ 信号')
        lines.extend(alerts)

    # Risk
    active = [h for h in us['holdings'] if h.get('shares', 0) > 0]
    lev_val = sum(h.get('current_value', 0) for h in active
                  if any(x in h.get('name', '') for x in ('2X', '3X', 'Bull', 'Target')))
    lev_pct = lev_val / tv * 100 if tv else 0
    losing  = sum(1 for h in active if h.get('pnl_percent', 0) < 0)
    lines.append('')
    lines.append(f"📉 亏损持仓 {losing}/{len(active)}  |  杠杆ETF敞口 {lev_pct:.0f}%")

    # News
    news_lines = []
    for a in analyses:
        if not a['news']:
            continue
        _, sentiment = news_sentiment(a['news'])
        senti_emoji = {'positive':'📰✅','negative':'📰⚠️','neutral':'📰'}.get(sentiment, '📰')
        news_lines.append(f"{senti_emoji} {a['holding']['ticker']} ({len(a['news'])}条)")
        for n in a['news'][:2]:
            hl = n.get('headline','')[:45]
            news_lines.append(f"   · {hl}")
    if news_lines:
        lines.append('')
        lines.append('📰 新闻')
        lines.extend(news_lines)

    print('\n'.join(lines))


# ── main ─────────────────────────────────────────────────────────────────────

def run_analysis(fetch: bool = True, include_news: bool = True):
    no_fetch = '--no-fetch' in sys.argv
    no_news  = '--no-news'  in sys.argv
    wechat   = '--wechat'   in sys.argv
    md_table = '--md-table' in sys.argv
    if not fetch:   no_fetch = True
    if not include_news: no_news = True

    # Helper to silence verbose progress in wechat mode
    def _say(msg: str):
        if not wechat:
            print(msg)

    # 1. Price refresh
    if not no_fetch:
        _say("[ 1/3 ] 更新最新价格...")
        if wechat:
            import io, contextlib
            _buf = io.StringIO()
            with contextlib.redirect_stdout(_buf):
                data = update_us_portfolio()
        else:
            data = update_us_portfolio()
    else:
        _say("[ 1/3 ] 跳过价格刷新，使用缓存")
        with open(PORTFOLIO_PATH, encoding='utf-8') as f:
            data = json.load(f)

    keys    = load_api_keys()
    us      = data['portfolios']['us_stocks']
    active  = [h for h in us['holdings'] if h.get('shares', 0) > 0]

    _say(f"[ 2/3 ] 拉取技术指标 (Polygon RSI-14 / MA)...")
    tech_cache: Dict[str, Dict] = {}
    for h in active:
        ticker = h['ticker']
        tech   = get_technicals(ticker, keys)
        tech_cache[ticker] = tech
        if not wechat:
            rsi_s = f"{tech['rsi14']:.0f}" if tech.get('rsi14') else 'n/a'
            sys.stdout.write(f"  {ticker}: RSI={rsi_s}({tech.get('src','?')})  ")
            sys.stdout.flush()
    if not wechat:
        print()

    _say(f"[ 3/3 ] {'拉取新闻 (Finnhub 7天)...' if not no_news else '跳过新闻'}")
    analyses = []
    for h in active:
        ticker     = h['ticker']
        tech       = tech_cache[ticker]
        news_items = get_news(ticker, keys.get('FINNHUB_API_KEY', '')) if not no_news else []
        signal, reasons = generate_signal(h, tech, news_items)
        analyses.append({
            'holding': h,
            'tech':    tech,
            'news':    news_items,
            'signal':  signal,
            'reasons': reasons,
        })
        if not no_news and not wechat:
            sys.stdout.write(f"  {ticker}: {len(news_items)} news  ")
            sys.stdout.flush()
    if not no_news and not wechat:
        print()

    if wechat:
        print_wechat_report(data, analyses, md_table=md_table)
    else:
        print_report(data, analyses)
    return analyses


if __name__ == '__main__':
    run_analysis()
