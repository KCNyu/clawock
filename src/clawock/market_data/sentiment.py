#!/usr/bin/env python3
"""Daily retail-chatter and news scan for every active holding.

Sources:
  • Arctic Shift index of recent titles in selected public Reddit communities
  • Google News RSS (English and Chinese)

Reddit's public search RSS returned Atom 404 Not Found for the producer and
the VPS probe. The archive is a bounded sample. Counts cover matching titles
during the last seven days among the newest posts returned by each community.
Incomplete, stale or malformed coverage leaves the count unknown.

Writes: assets/data/sentiment.json
"""

from clawock.safe_io import to_number as _share_number
import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from clawock import instruments
from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

UA = 'clawock-sentiment-scan/1.0 (github.com/KCNyu/clawock)'
HEADERS = {'User-Agent': UA}

REDDIT_INDEX = 'https://arctic-shift.photon-reddit.com/api/posts/search'
REDDIT_SUBREDDITS = ('stocks', 'investing', 'wallstreetbets')
REDDIT_LIMIT = 100
REDDIT_MAX_LAG = timedelta(days=2)
MENTION_WINDOW_DAYS = 7
TIMEOUT = 10

SOURCE_STATUS = {'reddit': 'failed', 'google_news': 'failed'}
FEED_SUMMARY = {'entries': None, 'within_window': None}

#: Trailing words that describe the wrapper rather than the company, stripped
#: from a registry name before it becomes a search term. "SpaceX exposure" has
#: never appeared in a Reddit post; "SpaceX" appears twenty-one times a week.
#: Declared rather than inferred, and the terms actually used are published per
#: ticker so a wrong one is visible instead of buried in a count.
NAME_TAIL_NOISE = (
    'exposure', 'index', 'etf', 'adr', 'group', 'holdings', 'holding',
    'markets', 'market', 'inc', 'corp', 'corporation', 'ltd', 'limited',
    'plc', 'co',
)

def load_tickers(workspace):
    p = json.loads((workspace / "portfolio.json").read_text(encoding="utf-8"))
    out = []
    for region in ('us_stocks', 'hk_stocks'):
        for h in p['portfolios'].get(region, {}).get('holdings', []):
            if (_share_number(h.get('shares', 0)) or 0) > 0:
                out.append({
                    'ticker': h['ticker'],
                    'name':   h.get('name', ''),
                    'region': region,
                })
    return out


def _clean_name(name: str) -> str:
    """Registry name minus the wrapper words and the share-class suffix."""
    text = re.sub(r'-[A-Z]$', '', (name or '').strip())
    parts = text.split()
    while parts and parts[-1].strip('.,').lower() in NAME_TAIL_NOISE:
        parts.pop()
    return ' '.join(parts)


def search_terms(ticker: str, name: str, registry: dict) -> list[str]:
    """What to search Reddit for, on behalf of one holding.

    Derived from `config/instruments.json` rather than a second alias table:
    the look-through symbol is already registered there, and it is the one
    people actually write about. Nobody posts about `RKLX`; they post about
    Rocket Lab, and this book holds RKLX to own RKLB.
    """
    row = registry.get(ticker) or {}
    underlying = row.get('underlying')
    target = registry.get(underlying) if underlying else None
    terms = []
    for candidate in (underlying, ticker if not underlying else None):
        if candidate and re.fullmatch(r'[A-Z]{2,6}', candidate):
            terms.append(candidate)
    for label in ((target or {}).get('name'), name if not target else None):
        cleaned = _clean_name(label or '')
        if len(cleaned) >= 3:
            terms.append(cleaned)
    seen, out = set(), []
    for term in terms:
        if term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out


def _matcher(term: str):
    """Word-bounded for Latin terms, plain containment for CJK.

    `\b` is defined on word characters, and Chinese has none of them, so a
    boundary-anchored pattern never matches 金风科技 at all — a silent zero for
    every Hong Kong name, which is the shape of bug this module is being fixed
    for.
    """
    if re.fullmatch(r'[\x00-\x7f]+', term):
        return re.compile(rf'\b{re.escape(term)}\b', re.I)
    return re.compile(re.escape(term))


def fetch_reddit_community(subreddit, *, now=None, get=None):
    """Read and validate the newest indexed submissions for one community."""
    now = now or datetime.now(timezone.utc)
    response = (get or requests.get)(
        REDDIT_INDEX, params={
            'subreddit': subreddit, 'sort': 'desc', 'limit': REDDIT_LIMIT,
            'fields': 'subreddit,title,id,created_utc,author',
        }, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    posts = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(posts, list) or not posts:
        raise ValueError(f'r/{subreddit}: no indexed submissions')

    entries, newest = {}, None
    for post in posts:
        if not isinstance(post, dict) or str(post.get('subreddit')).lower() != subreddit:
            raise ValueError(f'r/{subreddit}: invalid submission community')
        stamp = post.get('created_utc')
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            raise ValueError(f'r/{subreddit}: invalid submission timestamp')
        created = datetime.fromtimestamp(stamp, timezone.utc)
        if created > now:
            raise ValueError(f'r/{subreddit}: future submission timestamp')
        newest = max(newest, created) if newest else created
        title, post_id = post.get('title'), post.get('id')
        if post.get('author') == '[deleted]' or title in ('[deleted]', '[removed]'):
            continue
        if (not isinstance(title, str) or not title.strip() or not isinstance(post_id, str)
                or not re.fullmatch(r'[a-z0-9]+', post_id)):
            raise ValueError(f'r/{subreddit}: invalid submission title or ID')
        url = f'https://www.reddit.com/r/{subreddit}/comments/{post_id}/'
        entries[url] = {'title': title, 'url': url, 'sub': subreddit, 'created': created}
    if now - newest > REDDIT_MAX_LAG:
        raise ValueError(f'r/{subreddit}: newest indexed submission is stale')
    if not entries:
        raise ValueError(f'r/{subreddit}: no usable indexed titles')
    return list(entries.values()), len(posts)


def scan_reddit(rows, registry, *, now=None, fetch=None):
    """Publish sample counts only after every configured community answered."""
    now = now or datetime.now(timezone.utc)
    fetch = fetch or fetch_reddit_community
    SOURCE_STATUS['reddit'] = 'failed'
    FEED_SUMMARY.update(entries=None, within_window=None)
    for row in rows:
        row.update(reddit_mentions_7d=None, reddit_posts=[], reddit_status='not_attempted',
                   reddit_mentions_capped=False, reddit_sampled=True,
                   reddit_query_terms=search_terms(row['ticker'], row['name'], registry))
    if not any(row['reddit_query_terms'] for row in rows):
        return 0

    cutoff = now - timedelta(days=MENTION_WINDOW_DAYS)
    entries, total, capped = [], 0, False
    for subreddit in REDDIT_SUBREDDITS:
        try:
            posts, size = fetch(subreddit, now=now)
        except (requests.RequestException, ValueError, OverflowError, OSError) as exc:
            response = getattr(exc, 'response', None)
            status = 'throttled' if response is not None and response.status_code == 429 else 'failed'
            SOURCE_STATUS['reddit'] = status
            for row in rows:
                row['reddit_status'] = status
            print(f'  ⚠️ reddit archive: {exc}', file=sys.stderr)
            return 0
        entries.extend(post for post in posts if post['created'] >= cutoff)
        total += size
        capped |= size >= REDDIT_LIMIT and all(post['created'] >= cutoff for post in posts)

    entries.sort(key=lambda post: post['created'], reverse=True)
    SOURCE_STATUS['reddit'] = 'ok'
    FEED_SUMMARY.update(entries=total, within_window=len(entries))
    for row in rows:
        patterns = [_matcher(term) for term in row['reddit_query_terms']]
        matched = [entry for entry in entries if any(p.search(entry['title']) for p in patterns)]
        row.update(reddit_status='ok', reddit_mentions_7d=len(matched), reddit_mentions_capped=capped)
        row['reddit_posts'] = [
            {**post, 'title': post['title'][:200], 'created': post['created'].isoformat()}
            for post in matched[:6]]
    return sum(1 for row in rows if row['reddit_mentions_7d'])


def google_news_url(query, hl='en-US', gl='US', ceid=None):
    """The Google News RSS search URL. `ceid` defaults to `<gl>:<language>`;
    Google redirects that for Chinese editions (`CN:zh` → `CN:zh-Hans`), so a
    caller on a time budget names it."""
    ceid = ceid or f'{gl}:{hl.split("-")[0]}'
    return f'https://news.google.com/rss/search?q={quote(query)}&hl={hl}&gl={gl}&ceid={ceid}'


def parse_google_news(text, limit=8):
    """Headlines from one Google News RSS answer (raises on a non-feed body)."""
    root = ET.fromstring(text)
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
    return items


def fetch_google_news(query, hl='en-US', gl='US', limit=8, return_status=False):
    """Returns up to `limit` recent headlines from Google News RSS."""
    try:
        url = google_news_url(query, hl=hl, gl=gl)
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return ([], 'failed') if return_status else []
        SOURCE_STATUS['google_news'] = 'ok'
        items = parse_google_news(r.text, limit)
        if return_status:
            return items, ('ok' if items else 'success_empty')
        return items
    except Exception as e:
        print(f'  ⚠️ google-news {query}: {e}', file=sys.stderr)
        return ([], 'failed') if return_status else []


def scan_ticker(t):
    """Fetch per-ticker Google News fields."""
    tk = t['ticker']
    name = t['name']
    region = t['region']

    print(f'  [{region[:2]}] {tk} {name[:18]}', end='  ', flush=True)
    result = {
        'google_news_en':     [],
        'google_news_zh':     [],
    }

    if region == 'us_stocks':
        result['google_news_en'] = fetch_google_news(f'{tk} stock', hl='en-US', gl='US', limit=6)
        print(f'en_news={len(result["google_news_en"])}', flush=True)
    else:  # hk_stocks
        # HK: search by Chinese name first (richer signal than ticker number)
        if name:
            result['google_news_zh'] = fetch_google_news(name, hl='zh-CN', gl='HK', limit=6)
        # Also English search using "{ticker} HK" gives institutional coverage
        result['google_news_en'] = fetch_google_news(f'{tk} HK stock', hl='en-US', gl='US', limit=4)
        print(f'zh_news={len(result["google_news_zh"])} en_news={len(result["google_news_en"])}', flush=True)

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog='clawock sentiment', description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    workspace = workspace_root(args.workspace)
    output = args.output or workspace / "assets" / "data" / "sentiment.json"
    if not output.is_absolute():
        output = workspace / output

    SOURCE_STATUS['google_news'] = 'failed'
    tickers = load_tickers(workspace)
    print(f'Scanning {len(tickers)} active tickers …')

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sources': ['arctic-shift-reddit', 'google-news-rss'],
        'mention_window_days': MENTION_WINDOW_DAYS,
        'reddit_subreddits': list(REDDIT_SUBREDDITS),
        'tickers': tickers,
    }

    for row in tickers:
        row.update(scan_ticker(row))
        time.sleep(0.3)

    # Explicit path, `missing_ok`: this producer takes `--workspace`, so the
    # module-level default (resolved from cwd at import) would read another
    # book's registry — and a workspace that has registered nothing yet must
    # still get its news scan rather than an exception.
    registry = instruments.load_registry(
        workspace / 'config' / 'instruments.json', missing_ok=True)
    named = scan_reddit(out['tickers'], registry)
    if SOURCE_STATUS['reddit'] == 'ok':
        print(f'  reddit: {named}/{len(out["tickers"])} names mentioned in sampled titles from the '
              f'last {MENTION_WINDOW_DAYS} days')
    else:
        print(f'  reddit: {SOURCE_STATUS["reddit"]} — every count is null, '
              f'which is not the same as zero')
    out['source_status'] = dict(SOURCE_STATUS)
    out['reddit_feed'] = dict(FEED_SUMMARY)

    output.parent.mkdir(parents=True, exist_ok=True)
    safe_write_json(output, out)
    print(f'\n✓ wrote {output} ({len(out["tickers"])} tickers, {output.stat().st_size:,} bytes)')


if __name__ == '__main__':
    sys.exit(main() or 0)
