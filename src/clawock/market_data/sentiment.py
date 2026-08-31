#!/usr/bin/env python3
"""Daily retail-chatter and news scan for every active holding.

Sources (both free, neither needs a key):
  • Reddit search RSS — site-wide `search.rss`, one request per name
  • Google News RSS   — US tickers in English, HK names in Chinese

There is no Yahoo Finance source here despite three months of this docstring
claiming one; the `sources` list never held it.

**Reddit's unauthenticated JSON API is gone.** `reddit.com/r/<sub>/search.json`
returns `403 Blocked` — measured 2026-08-31 on both `www` and `old` — and has
returned nothing for the entire recorded history of this artifact: across all 87
commits of `sentiment.json` since 2026-05-17, every ticker's mention count is 0.
The old code caught the failure, set `SOURCE_STATUS['reddit'] = 'failed'`, and
then published `0` anyway, so three consumers — the decision packet, the brief
and the dashboard — have been reading "nobody is talking about this name" off a
request that was never answered. The two are not the same sentence.

What replaces it: `search.rss`, which still answers without credentials. It is
rate limited hard (a second request within ~30s returns 429 with no
`Retry-After`), so the scan sweeps once, retries what bounced with backoff, and
stops at a wall-clock budget. **A name the scan could not reach gets `None`, not
`0`** — that distinction is the whole point of this module's rewrite.

Two things the RSS endpoint changes about the numbers:

* `sort=new&t=week` is ignored — a probe returned entries dated 2012 through
  today — so the seven-day window is applied here, on each entry's `updated`.
  The field has carried a `_7d` suffix since it was written; this is the first
  version where that suffix is true.
* score and comment counts are not in the feed, so `reddit_posts` no longer
  carries them. A post with `score: 0` because the feed does not say is the
  same lie in smaller print.

Writes: assets/data/sentiment.json
"""
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

#: One request for the whole book, not one per name. Reddit answers an
#: unauthenticated feed roughly once every thirty seconds — a paced ten-name
#: sweep measured 1/10 answered — so ten requests is a scan that mostly reports
#: nothing. An `OR` of every holding's search terms fits in one.
REDDIT_SEARCH = 'https://www.reddit.com/search.rss'

#: Reddit's search is the recall stage and it is loose: an `OR` of the book's
#: terms came back with a post about a dental crown. The precision stage is
#: local — every returned entry is matched against the terms again, here, and an
#: entry matching none of them is not counted for anyone. Measured on the live
#: book: 98 entries returned, 97 inside the window, **42** actually naming a
#: holding.
REDDIT_LIMIT = 100
REDDIT_RETRY_WAITS = (0, 35, 70)
TIMEOUT = 10

#: The declared bot UA is the one that works. A browser-shaped UA was rate
#: limited on the same request that the bot UA got a 200 for (measured
#: 2026-08-31), so pretending to be Chrome here would be both dishonest and
#: worse.
SOURCE_STATUS = {'reddit': 'failed', 'google_news': 'failed'}

#: How far back a mention counts. Applied here, on each entry's timestamp,
#: because the endpoint's own `t=week` is ignored under `sort=new` — a probe
#: returned entries dated 2012 through today.
MENTION_WINDOW_DAYS = 7

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

#: Where a mention has to have been made to count. Reddit's site-wide search
#: is the only endpoint left, and it does not honour a subreddit filter next to
#: an `OR` of terms, so the scope the old code got from asking three investing
#: subs directly is reapplied here, on the way back.
#:
#: This is not tidying. Measured on the live book without it, `MINIMAX` scored
#: 16 mentions in a week — from r/abstractgames and r/PiCodingAgent, because
#: minimax is a game-theory algorithm and one of this book's holdings happens
#: to share its name. Publishing 16 would have replaced a false zero with a
#: false sixteen.
#:
#: Substrings, matched case-insensitively against the subreddit name, and
#: published in the artifact so an undercount is auditable rather than assumed.
#: It undercounts on purpose: r/spacecapital is a real investing community and
#: this list misses it. A declared undercount is a number a reader can correct;
#: an overcount from a dictionary word is not.
FINANCE_SUBREDDIT_MARKS = (
    'stock', 'invest', 'wallstreetbets', 'wsb', 'trading', 'trader',
    'finance', 'option', 'dividend', 'bogle', 'market', 'equit', 'shares',
    'securityanalysis', 'valu',
)

ATOM = {'a': 'http://www.w3.org/2005/Atom'}


def is_finance_sub(sub: str) -> bool:
    """A subreddit, and one about markets.

    `u/...` is a user profile, not a community: Reddit returns profile posts in
    site-wide search and one of them (`u/The_optiontrader`) would pass the
    substring test on `option` alone.
    """
    name = (sub or '').strip().lower()
    if not name or name.startswith('u/'):
        return False
    return any(mark in name for mark in FINANCE_SUBREDDIT_MARKS)


def load_tickers(workspace):
    p = json.loads((workspace / "portfolio.json").read_text(encoding="utf-8"))
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


def _within_window(created: str, cutoff: datetime) -> bool:
    try:
        stamp = datetime.fromisoformat((created or '').replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp >= cutoff


def _feed_entries(text: str, cutoff: datetime) -> tuple[list[dict], int]:
    """(entries inside the window, total entries returned).

    No score and no comment count: the search feed does not carry them. The
    previous shape defaulted both to zero, which rendered on the dashboard as a
    post nobody upvoted rather than a number nobody fetched.
    """
    root = ET.fromstring(text)
    total = 0
    kept = []
    for entry in root.findall('a:entry', ATOM):
        total += 1
        created = (entry.findtext('a:updated', default='', namespaces=ATOM) or '').strip()
        if not _within_window(created, cutoff):
            continue
        link = entry.find('a:link', ATOM)
        category = entry.find('a:category', ATOM)
        title = (entry.findtext('a:title', default='', namespaces=ATOM) or '')
        kept.append({
            'sub': (category.get('term') if category is not None else '') or '',
            'title': title[:200],
            'url': (link.get('href') if link is not None else '') or '',
            'created': created,
            '_blob': f'{title} {entry.findtext("a:content", default="", namespaces=ATOM) or ""}',
        })
    return kept, total


def fetch_reddit(query: str, *, sleep=None):
    """(feed text, status). `status` is `ok`, `throttled` or `failed`.

    A 429 is kept distinct from every other failure on purpose: throttled means
    the source works and this run was unlucky, blocked means it does not work
    from here at all. The first is worth retrying tomorrow; the second is worth
    moving the scan somewhere else, and a single `failed` bucket cannot tell
    anyone which one happened.
    """
    # Resolved at call time, not bound in the signature: a default of
    # `time.sleep` is captured at import, so a test patching this module's
    # `time.sleep` would still sleep through the real backoff — measured at 105
    # seconds in one suite run before this line existed.
    sleep = sleep or time.sleep
    url = f'{REDDIT_SEARCH}?q={quote(query)}&sort=new&limit={REDDIT_LIMIT}'
    status = 'failed'
    for wait in REDDIT_RETRY_WAITS:
        if wait:
            sleep(wait)
        try:
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except Exception as exc:
            print(f'  ⚠️ reddit: {exc}', file=sys.stderr)
            continue
        if response.status_code == 200:
            return response.text, 'ok'
        status = 'throttled' if response.status_code == 429 else 'failed'
        print(f'  ⚠️ reddit: HTTP {response.status_code}', file=sys.stderr)
    return None, status


def scan_reddit(rows, registry, *, now=None, sleep=None, fetch=None):
    """Fill every row's Reddit fields from one search, or mark them unfetched.

    The contract that matters is the failure one: when the feed does not come
    back, every count stays `None`. A zero here reads as "nobody is talking
    about this name", and that sentence was published for every holding every
    day from 2026-05-17 to 2026-08-31 while the old JSON endpoint answered 403
    to every request (#1237).
    """
    sleep = sleep or time.sleep
    terms = {row['ticker']: search_terms(row['ticker'], row['name'], registry)
             for row in rows}
    for row in rows:
        row['reddit_mentions_7d'] = None
        row['reddit_posts'] = []
        row['reddit_status'] = 'not_attempted'
        row['reddit_mentions_capped'] = False
        row['reddit_query_terms'] = terms[row['ticker']]

    query = ' OR '.join(sorted({
        f'"{term}"' if ' ' in term else term
        for values in terms.values() for term in values}))
    if not query:
        SOURCE_STATUS['reddit'] = 'failed'
        return 0
    text, status = (fetch or fetch_reddit)(query, sleep=sleep)
    if status != 'ok' or text is None:
        for row in rows:
            row['reddit_status'] = status
        SOURCE_STATUS['reddit'] = status if status == 'throttled' else 'failed'
        return 0

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=MENTION_WINDOW_DAYS)
    try:
        entries, total = _feed_entries(text, cutoff)
    except ET.ParseError as exc:
        print(f'  ⚠️ reddit: unparseable feed ({exc})', file=sys.stderr)
        for row in rows:
            row['reddit_status'] = 'failed'
        SOURCE_STATUS['reddit'] = 'failed'
        return 0

    SOURCE_STATUS['reddit'] = 'ok'
    # The count is a floor whenever the feed was full and none of it aged out:
    # there is no page two, so a busier week is indistinguishable from this one
    # at the top of the list. Saying so beats publishing a total that is not one.
    capped = total >= REDDIT_LIMIT and len(entries) == total
    for row in rows:
        patterns = [_matcher(term) for term in terms[row['ticker']]]
        matched = [entry for entry in entries
                   if is_finance_sub(entry['sub'])
                   and any(pattern.search(entry['_blob']) for pattern in patterns)]
        row['reddit_status'] = 'ok'
        row['reddit_mentions_7d'] = len(matched)
        row['reddit_mentions_capped'] = capped
        row['reddit_posts'] = [
            {key: entry[key] for key in ('sub', 'title', 'url', 'created')}
            for entry in matched[:6]]
    return sum(1 for row in rows if row['reddit_mentions_7d'])


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
    """Per-ticker news scan. Reddit is a separate pass — see `scan_reddit`.

    The two sources are no longer interleaved because their rate limits are not
    comparable: Google News answers every time, Reddit answers about half the
    time and has to be asked again. Sweeping them together made the whole scan
    move at the slower one's pace.
    """
    tk = t['ticker']
    name = t['name']
    region = t['region']

    print(f'  [{region[:2]}] {tk} {name[:18]}', end='  ', flush=True)
    result = {
        'ticker': tk,
        'name':   name,
        'region': region,
        # Reddit fields are filled by `scan_reddit`; `None` until then, because
        # a name that has not been asked about has no mention count.
        'reddit_mentions_7d': None,
        'reddit_posts':       [],
        'reddit_status':      'not_attempted',
        'reddit_mentions_capped': False,
        'reddit_query_terms': [],
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    workspace = workspace_root(args.workspace)
    output = args.output or workspace / "assets" / "data" / "sentiment.json"
    if not output.is_absolute():
        output = workspace / output

    SOURCE_STATUS.update(reddit='failed', google_news='failed')
    tickers = load_tickers(workspace)
    print(f'Scanning {len(tickers)} active tickers …')

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sources': ['reddit-search-rss', 'google-news-rss'],
        'mention_window_days': MENTION_WINDOW_DAYS,
        'reddit_subreddit_marks': list(FINANCE_SUBREDDIT_MARKS),
        'tickers': [],
    }

    for t in tickers:
        out['tickers'].append(scan_ticker(t))
        time.sleep(0.3)  # global rate-limit safety

    # Explicit path, `missing_ok`: this producer takes `--workspace`, so the
    # module-level default (resolved from cwd at import) would read another
    # book's registry — and a workspace that has registered nothing yet must
    # still get its news scan rather than an exception.
    registry = instruments.load_registry(
        workspace / 'config' / 'instruments.json', missing_ok=True)
    named = scan_reddit(out['tickers'], registry)
    if SOURCE_STATUS['reddit'] == 'ok':
        print(f'  reddit: {named}/{len(out["tickers"])} names mentioned in the '
              f'last {MENTION_WINDOW_DAYS} days')
    else:
        print(f'  reddit: {SOURCE_STATUS["reddit"]} — every count is null, '
              f'which is not the same as zero')
    out['source_status'] = dict(SOURCE_STATUS)

    output.parent.mkdir(parents=True, exist_ok=True)
    safe_write_json(output, out)
    print(f'\n✓ wrote {output} ({len(out["tickers"])} tickers, {output.stat().st_size:,} bytes)')


if __name__ == '__main__':
    sys.exit(main() or 0)
