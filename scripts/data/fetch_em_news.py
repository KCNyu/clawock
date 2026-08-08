#!/usr/bin/env python3
"""fetch_em_news.py — Chinese-language news source (Eastmoney) for the info layer.

clawock's news_digest is Finnhub + Google News — English / US-skewed. clawock is
half a Hong-Kong book, so its biggest information gap is *Chinese-source* news and
holding-level catalysts. Eastmoney gives both, free + no key, and is reachable
here. Inspired by UZI-Skill's data-source breadth (github.com/wbh604/UZI-Skill):
information-gathering is what an LLM is *best* at, so widen the inputs — this is a
separate axis from decision/debate breadth (which the calibration deliberately
keeps narrow).

Pulls, into assets/data/em_news.json:
  - per active HK holding: recent EM company news (catalyst-grade, dated)
  - market 7x24 快讯: a few macro/sector headlines for context

Fail-soft: any source error -> that slice is empty, never raises.
"""
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
_CHECKOUT = Path(__file__).resolve().parents[2]
WS = workspace_root(Path(__file__).resolve().parents[2])
PORTFOLIO = WS / 'portfolio.json'
OUT = WS / 'assets' / 'data' / 'em_news.json'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
TIMEOUT = 12

sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
from _em_http import em_get  # noqa: E402  统一请求节流出口
try:
    from safe_io import safe_write_json
except Exception:
    def safe_write_json(path, data, indent=2):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=indent))


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


# Leverage markers — a 2x/3x ETF's marketing name ("XL二南方恒科") keyword-
# searches into junk (name collisions like 万恒科技) AND, per clawock's existing
# rule, company news doesn't apply to a daily-reset index tracker. Skip them;
# they're covered by the 7x24 feed + the regime dial.
_LEV_MARKERS = ('倍', 'XL二', 'XL三', 'X二', 'X三', '两倍', '三倍', '杠杆',
                'Direxion', 'ProShares', '2X', '3X')


def _is_lev(name):
    return any(m in str(name) for m in _LEV_MARKERS)


def active_hk_names():
    try:
        pf = json.loads(PORTFOLIO.read_text())
        hk = (pf.get('portfolios', {}).get('hk_stocks', {}) or {}).get('holdings', []) or []
        return [(h.get('ticker'), h.get('name') or h.get('ticker'))
                for h in hk
                if (h.get('shares') or 0) > 0 and not _is_lev(h.get('name'))]
    except Exception:
        return []


def main():
    by_ticker = {}
    for ticker, name in active_hk_names():
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
    safe_write_json(str(OUT), out)
    n = sum(len(v['items']) for v in by_ticker.values())
    print(f'  em_news: {len(by_ticker)} HK holdings · {n} company items · '
          f"{len(out['market_724'])} 快讯 → {OUT}")


if __name__ == '__main__':
    main()
