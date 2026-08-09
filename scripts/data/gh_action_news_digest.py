#!/usr/bin/env python3
"""
gh_action_news_digest.py — daily 21:00 HKT US news digest.

Fetches news for active US holdings (past 48h), calls MiniMax M3 with an optional
Xiaomi fallback to distill actionable bullets, and writes
assets/data/us_news_digest.json.

News source chain (per-ticker fallback):
  1. Finnhub company-news (rich: headline + summary + source attribution)
  2. Google News RSS (free, no key; title-only; used when Finnhub key absent
     or returns empty for a ticker)

Env: MINIMAX_API_KEY required; XIAOMI_API_KEY and FINNHUB_API_KEY optional.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
from clawock.portfolio import instruments as instrument_registry  # noqa: E402
from xiaomi_llm import chat
from clawock.market_data.sentiment import fetch_google_news


def _fetch_finnhub(ticker, since, until, key):
    """Returns list of dicts (may be empty) or None on error."""
    try:
        r = requests.get(
            'https://finnhub.io/api/v1/company-news',
            params={'symbol': ticker, 'from': since, 'to': until, 'token': key},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        items = r.json() or []
        return [
            {
                'headline': it.get('headline', '')[:200],
                'summary':  (it.get('summary', '') or '')[:400],
                'datetime': it.get('datetime'),
                'source':   it.get('source', ''),
                'origin':   'finnhub',
                'url':      it.get('url', ''),
            }
            for it in items[:5]
        ]
    except Exception:
        return None


def _fetch_gnews(ticker):
    """Google News RSS fallback. Title-only; no summary."""
    items, status = fetch_google_news(
        f'{ticker} stock', hl='en-US', gl='US', limit=5, return_status=True)
    news = [
        {
            'headline': it.get('title', '')[:200],
            'summary':  '',  # GNews RSS doesn't carry body
            'datetime': it.get('published'),
            'source':   it.get('source', '') or 'Google News',
            'origin':   'gnews-rss',
            'url':      it.get('url', ''),
        }
        for it in items
    ]
    return news, status


def fetch_news(tickers, since_days=2):
    finnhub_key = os.environ.get('FINNHUB_API_KEY')
    today = date.today()
    since = (today - timedelta(days=since_days)).isoformat()
    until = today.isoformat()
    out = {}
    source_status = {}
    for t in tickers:
        items = None
        statuses = {
            'finnhub': 'not_configured' if not finnhub_key else 'not_attempted',
            'google_news': 'not_attempted',
        }
        if finnhub_key:
            items = _fetch_finnhub(t, since, until, finnhub_key)
            statuses['finnhub'] = (
                'failed' if items is None
                else ('success' if items else 'success_empty')
            )
        # Fall back to GNews if Finnhub absent, errored, or returned empty list
        if not items:
            why = 'no FINNHUB_KEY' if not finnhub_key else ('error' if items is None else 'empty')
            gn, gn_status = _fetch_gnews(t)
            statuses['google_news'] = (
                'success' if gn_status == 'ok' else gn_status)
            print(f'  {t}: 0 finnhub ({why}) → {len(gn)} gnews')
            out[t] = gn
        else:
            print(f'  {t}: {len(items)} finnhub')
            out[t] = items
        source_status[t] = statuses
    return out, source_status


def _write_artifact(tickers, raw, source_status, *, digest='', no_material_news=False,
                    held_via=None):
    source_per_ticker = {
        ticker: (items[0]['origin'] if items else 'none')
        for ticker, items in raw.items()
    }
    out = {
        'generated_at': datetime.now().isoformat(),
        'lookback_hours': 48,
        'tickers': tickers,
        # which held fund each issuer is being read for (PLTR is in the list
        # because we hold PLTU); empty when the holding reports for itself
        'held_via': held_via or {},
        'digest_markdown': digest.strip(),
        'raw_news_counts': {ticker: len(items) for ticker, items in raw.items()},
        # Persist only licensable evidence metadata. Summaries/article bodies stay
        # in-memory for digest generation and are deliberately excluded here.
        'raw_news_evidence': {
            ticker: [
                {
                    key: item.get(key)
                    for key in (
                        'headline', 'datetime', 'source', 'origin', 'url'
                    )
                }
                for item in items
            ]
            for ticker, items in raw.items()
        },
        'news_source_per_ticker': source_per_ticker,
        'source_status': source_status,
        'no_material_news': no_material_news,
    }
    os.makedirs('assets/data', exist_ok=True)
    with open('assets/data/us_news_digest.json', 'w') as handle:
        json.dump(out, handle, ensure_ascii=False, indent=2)
    return out


def main():
    pf = json.load(open('portfolio.json'))
    held = [h['ticker'] for h in pf['portfolios']['us_stocks']['holdings']
            if h.get('shares', 0) > 0]
    # Ask about the company, not the fund. A 2x single-stock ETF publishes nothing:
    # Finnhub returned success_empty for PLTU/RKLX/SPCH every day and Google News
    # filled the gap with ETF marketing copy, which the digest then dutifully
    # summarised as "no company-level news". An index fund has no issuer at all.
    tickers, held_via = [], {}
    for holding in held:
        resolved = instrument_registry.look_through(holding)
        issuer = resolved['issuer']
        if not issuer:
            continue                                  # index/sector fund: nobody reports
        if issuer not in tickers:
            tickers.append(issuer)
        if resolved['kind'] == 'look_through':
            held_via.setdefault(issuer, []).append(holding)

    raw, source_status = fetch_news(tickers, since_days=2)
    if not any(raw.values()):
        successful_empty = any(
            status == 'success_empty'
            for ticker_status in source_status.values()
            for status in ticker_status.values()
        )
        if tickers and not successful_empty:
            raise RuntimeError('news: all sources failed')
        _write_artifact(
            tickers, raw, source_status, no_material_news=True, held_via=held_via)
        print('all sources returned no material news — wrote explicit empty digest')
        return 0

    system = "You are Rick, kcn's stock analyst. Distill US holding news into actionable bullets."

    user = (
        "下面 US holdings 过去 48h 新闻 (来源 Finnhub 或 Google News RSS, "
        "每条 `origin` 字段标注). 提炼成 markdown digest:\n\n"
        "## 格式 (严格遵守)\n\n"
        "### Top 3-5 移动信号 (跨 ticker 排序)\n"
        "- TICKER: 1 行核心 fact + 1 行 implication for kcn's position\n"
        "- ...\n\n"
        "### Per-ticker 简报 (有新闻才列)\n"
        "- TICKER: 关键事件 - 影响判断 (1 行)\n\n"
        "### 风险 watch (若有)\n"
        "- 任何 financial guidance / regulatory / 大股东减持 / 失败合约 等 risk 关键词\n\n"
        "要求:\n"
        "- 总长 ≤ 500 字 (digest 不是 brief)\n"
        "- 重复 / 营销稿 / 通用市场新闻 -> 忽略\n"
        "- 优先 ticker-specific catalyst (财报 / 合约 / 监管 / 大单)\n"
        "- gnews-rss 项只有标题没 summary, 要靠标题关键词判断, 不要编造细节\n"
        "- 不许说 \"需要进一步研究\" 这种废话\n"
        + (f"- 持仓映射: 以下公司是通过杠杆 ETF 持有的 {json.dumps(held_via, ensure_ascii=False)};"
           " 写 implication 时点明持有的是哪只 ETF, 并说明 2x 会放大该消息\n" if held_via else "")
        + "- 直接出 markdown\n\n"
        +
        f"Raw news (JSON):\n```json\n{json.dumps(raw, ensure_ascii=False)[:25000]}\n```\n"
    )

    # News digest: short output but enable thinking helps prioritize signal vs noise
    digest = chat(system=system, user=user, max_tokens=32000, temperature=0.5)

    _write_artifact(tickers, raw, source_status, digest=digest, held_via=held_via)
    print(f'  digest size: {len(digest)} chars')
    return 0


if __name__ == '__main__':
    main()
