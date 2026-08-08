#!/usr/bin/env python3
"""
fetch_sentiment.py — daily sentiment scan for every active holding.

Sources (all free, no API key):
  • Reddit JSON       — r/wallstreetbets r/stocks r/investing (US tickers only)
  • Google News RSS   — covers both US tickers AND HK Chinese-name search
  • Yahoo Finance RSS — supplement, includes analyst headlines

Writes: assets/data/sentiment.json
"""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_FILE = os.path.join(WS_ROOT, 'assets', 'data', 'sentiment.json')

UA = 'clawock-sentiment-scan/1.0 (github.com/KCNyu/clawock)'
HEADERS = {'User-Agent': UA}

REDDIT_SUBS = ['wallstreetbets', 'stocks', 'investing']
TIMEOUT = 10
SOURCE_STATUS = {'reddit': 'failed', 'google_news': 'failed'}


def load_tickers():
    p = json.load(open(os.path.join(WS_ROOT, 'portfolio.json'), encoding='utf-8'))
    out = []
    for region in ('us_stocks', 'hk_stocks'):
        for h in p['portfolios'].get(region, {}).get('holdings', []):
            if h.get('shares', 0) > 0:
                out.append({
                    'ticker': h['ticker'],
                    'name':   h.get('name', ''),
                    'region': region,
                })
    return out


def fetch_reddit(ticker, mentions_only=False):
    """Returns (mention_count, top_posts[]). US-leaning."""
    if not re.match(r'^[A-Z]+$', ticker):
        return 0, []  # HK numeric tickers not on Reddit
    total = 0
    posts = []
    for sub in REDDIT_SUBS:
        try:
            url = f'https://www.reddit.com/r/{sub}/search.json?q={ticker}&restrict_sr=1&sort=new&limit=10'
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            SOURCE_STATUS['reddit'] = 'ok'
            children = r.json().get('data', {}).get('children', [])
            total += len(children)
            if mentions_only:
                continue
            for c in children[:3]:
                d = c.get('data', {})
                posts.append({
                    'sub':          sub,
                    'title':        d.get('title', '')[:200],
                    'score':        d.get('score', 0),
                    'num_comments': d.get('num_comments', 0),
                    'created_utc':  d.get('created_utc'),
                })
            time.sleep(0.6)
        except Exception as e:
            print(f'  ⚠️ reddit {ticker} @ {sub}: {e}', file=sys.stderr)
    return total, posts[:6]


def fetch_google_news(query, hl='en-US', gl='US', limit=8, return_status=False):
    """Returns up to `limit` recent headlines from Google News RSS."""
    try:
        url = f'https://news.google.com/rss/search?q={quote(query)}&hl={hl}&gl={gl}&ceid={gl}:{hl.split("-")[0]}'
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return ([], 'failed') if return_status else []
        SOURCE_STATUS['google_news'] = 'ok'
        root = ET.fromstring(r.text)
        items = []
        for it in root.findall('.//item')[:limit]:
            title = (it.findtext('title') or '').strip()
            pub   = (it.findtext('pubDate') or '').strip()
            src   = ''
            src_el = it.find('source')
            if src_el is not None:
                src = (src_el.text or '').strip()
            link = (it.findtext('link') or '').strip()
            # Strip " - source" suffix in title
            if ' - ' in title:
                title = title.rsplit(' - ', 1)[0]
            items.append({
                'title': title,
                'source': src,
                'published': pub,
                'url': link,
            })
        if return_status:
            return items, ('ok' if items else 'success_empty')
        return items
    except Exception as e:
        print(f'  ⚠️ google-news {query}: {e}', file=sys.stderr)
        return ([], 'failed') if return_status else []


def scan_ticker(t):
    """Aggregate per-ticker sentiment from all sources."""
    tk = t['ticker']
    name = t['name']
    region = t['region']

    print(f'  [{region[:2]}] {tk} {name[:18]}', end='  ', flush=True)
    result = {
        'ticker': tk,
        'name':   name,
        'region': region,
        'reddit_mentions_7d': 0,
        'reddit_posts':       [],
        'google_news_en':     [],
        'google_news_zh':     [],
    }

    if region == 'us_stocks':
        result['reddit_mentions_7d'], result['reddit_posts'] = fetch_reddit(tk)
        result['google_news_en'] = fetch_google_news(f'{tk} stock', hl='en-US', gl='US', limit=6)
        print(f'reddit={result["reddit_mentions_7d"]} en_news={len(result["google_news_en"])}', flush=True)
    else:  # hk_stocks
        # HK: search by Chinese name first (richer signal than ticker number)
        if name:
            result['google_news_zh'] = fetch_google_news(name, hl='zh-CN', gl='HK', limit=6)
        # Also English search using "{ticker} HK" gives institutional coverage
        result['google_news_en'] = fetch_google_news(f'{tk} HK stock', hl='en-US', gl='US', limit=4)
        print(f'zh_news={len(result["google_news_zh"])} en_news={len(result["google_news_en"])}', flush=True)

    return result


def main():
    SOURCE_STATUS.update(reddit='failed', google_news='failed')
    tickers = load_tickers()
    print(f'Scanning {len(tickers)} active tickers …')

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sources': ['reddit-json-public', 'google-news-rss'],
        'tickers': [],
    }

    for t in tickers:
        out['tickers'].append(scan_ticker(t))
        time.sleep(0.3)  # global rate-limit safety
    out['source_status'] = dict(SOURCE_STATUS)

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    # Atomic write
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from clawock.safe_io import safe_write_json
    safe_write_json(OUT_FILE, out)
    print(f'\n✓ wrote {OUT_FILE} ({len(out["tickers"])} tickers, {os.path.getsize(OUT_FILE):,} bytes)')


if __name__ == '__main__':
    sys.exit(main() or 0)
