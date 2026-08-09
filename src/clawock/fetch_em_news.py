#!/usr/bin/env python3
"""Chinese-language East Money news for a workspace's active HK holdings.

This complements English/US-skewed news providers with dated company items and
market-wide Chinese headlines. Collection breadth stays separate from whatever
decision policy an external runtime applies to the resulting evidence.

Pulls, into assets/data/em_news.json:
  - per active HK holding discovered from the selected workspace's ledger and
    instrument registry: recent EM company news (catalyst-grade, dated)
  - market 7x24 快讯: a few macro/sector headlines for context

Fail-soft: any source error -> that slice is empty, never raises.
"""
import argparse
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from clawock._em_http import em_get
from clawock.instrument_registry import load_registry
from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
TIMEOUT = 12


def _strip(s):
    return re.sub(r'<[^>]+>', '', str(s or '')).strip()


def em_stock_news(keyword, limit=3):
    """Holding-level Chinese news via Eastmoney search (dated, catalyst-grade)."""
    param = {'uid': '', 'keyword': keyword, 'type': ['cmsArticleWebOld'],
             'pageIndex': 1, 'pageSize': limit,
             'preTag': '', 'postTag': ''}
    url = ('https://search-api-web.eastmoney.com/search/jsonp?cb=x&param='
           + urllib.parse.quote(json.dumps(param, ensure_ascii=False)))
    try:
        r = em_get(url, headers={'User-Agent': UA}, timeout=TIMEOUT, label='em-search')
        if r is None:
            return []
        t = r.text
        m = re.search(r'\((\{.*\})\)\s*;?\s*$', t, re.S)
        d = json.loads(m.group(1))
        arts = (d.get('result') or {}).get('cmsArticleWebOld') or []
        out = []
        for a in arts[:limit]:
            out.append({'title': _strip(a.get('title')),
                        'digest': _strip(a.get('content'))[:160],
                        'date': (a.get('date') or '')[:10],
                        'url': f"https://finance.eastmoney.com/a/{a.get('code')}.html",
                        'origin': 'eastmoney-search'})
        return out
    except Exception as e:
        print(f'  warn: em_stock_news({keyword}) failed: {e}', file=sys.stderr)
        return []


def em_fast_news(limit=6):
    """Market 7x24 快讯 — macro/sector context."""
    url = f'https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_{limit}_1_.html'
    try:
        r = em_get(url, headers={'User-Agent': UA}, timeout=TIMEOUT, label='em-724')
        if r is None:
            return []
        t = r.text
        m = re.search(r'=\s*(\{.*\})\s*;?\s*$', t, re.S)
        d = json.loads(m.group(1))
        out = []
        for it in (d.get('LivesList') or [])[:limit]:
            out.append({'title': _strip(it.get('title')),
                        'digest': _strip(it.get('digest'))[:160],
                        'date': (it.get('showtime') or '')[:16],
                        'url': it.get('url_unique', ''),
                        'origin': 'eastmoney-724'})
        return out
    except Exception as e:
        print(f'  warn: em_fast_news failed: {e}', file=sys.stderr)
        return []


# Leverage markers — a 2x/3x ETF's marketing name keyword-searches into unrelated
# companies, and company news does not apply to a daily-reset index tracker.
# Skip them; market-wide headlines still remain available.
_LEV_MARKERS = ('倍', 'XL二', 'XL三', 'X二', 'X三', '两倍', '三倍', '杠杆',
                'Direxion', 'ProShares', '2X', '3X')


def _is_lev(name):
    return any(m in str(name) for m in _LEV_MARKERS)


def active_hk_names(portfolio_path: Path, registry_path: Path):
    """Return active HK companies from any declared book shape.

    The historical script indexed one fixed desk book key directly, so the
    fetcher went empty as soon as another workspace used a different name.
    Region ownership lives in the instrument registry; book names are
    intentionally irrelevant here.
    """
    try:
        portfolio = json.loads(portfolio_path.read_text())
        registry = load_registry(registry_path, missing_ok=True)
    except Exception:
        return []

    names = []
    for book in (portfolio.get('portfolios') or {}).values():
        for holding in (book or {}).get('holdings') or []:
            ticker = holding.get('ticker')
            meta = registry.get(ticker) or {}
            name = holding.get('name') or meta.get('name') or ticker
            if ((holding.get('shares') or 0) > 0
                    and meta.get('region') == 'HK'
                    and (meta.get('leverage_multiple') or 1) <= 1
                    and not _is_lev(name)):
                names.append((ticker, name))
    return names


def fetch_workspace(workspace: Path, output: Path | None = None):
    workspace = workspace.expanduser().resolve()
    output = output or workspace / 'assets' / 'data' / 'em_news.json'
    by_ticker = {}
    for ticker, name in active_hk_names(
            workspace / 'portfolio.json', workspace / 'config' / 'instruments.json'):
        items = em_stock_news(name)
        if items:
            by_ticker[ticker] = {'name': name, 'items': items}
        # 限速已由 em_get 统一处理(串行 >=1s + 抖动),无需再手 sleep
    out = {
        'generated_at': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
        'source': 'eastmoney (Chinese-language info layer)',
        'holdings_news': by_ticker,
        'market_724': em_fast_news(),
    }
    safe_write_json(str(output), out)
    n = sum(len(v['items']) for v in by_ticker.values())
    print(f'  em_news: {len(by_ticker)} HK holdings · {n} company items · '
          f"{len(out['market_724'])} 快讯 → {output}")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='clawock em-news', description=__doc__)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    workspace = (args.workspace.expanduser().resolve() if args.workspace
                 else workspace_root(Path.cwd()))
    output = args.output.expanduser() if args.output else None
    if output and not output.is_absolute():
        output = (workspace / output).resolve()
    elif output:
        output = output.resolve()
    fetch_workspace(workspace, output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
