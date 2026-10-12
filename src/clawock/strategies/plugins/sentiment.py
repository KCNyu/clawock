"""The `sentiment` service: the attention scan and the statement radar, as the brief reads them.

Two files are produced off-host each morning and committed before the brief:

* `assets/data/sentiment.json` — `market_data.sentiment`: Reddit mentions over
  seven days and Google News titles for every active holding;
* `assets/data/influencer_feed.json` — `automation.influencer`: statements and
  trades by named figures, scored for relevance by one model call.

This service is how those files reach a decision. It does not fetch. It reads
one file, decides whether the reading can be used today, and answers with a
`status` beside the reading, so that "the scan found nothing", "the scan did
not run" and "the scan is too old to use" are three different answers:

    {'status': 'ok' | 'missing' | 'stale' | 'unreadable',
     'reading': {...},        # empty unless status is ok
     'age_hours': float | None, 'detail': {...}}

A reading older than `stale_after_hours` (row config, 36) is not served. Its
age comes from the payload's own `generated_at`: a checkout stamps every file
with a fresh mtime, so the file's clock says nothing about the scan's. A
payload with no readable stamp, or one from further in the future than clock
skew allows, is stale too.

`harness.brief_preflight` keeps `load_macro_and_sentiment` and
`load_influencer_feed`; they call this and turn the status into the console
line and the preflight issue they always produced.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

name = 'sentiment'

STALE_AFTER_HOURS = 36
#: A stamp further ahead of now than this is a broken producer clock, not a
#: fresh scan.
CLOCK_SKEW_HOURS = 2

ATTENTION_FILE = Path('assets') / 'data' / 'sentiment.json'
STATEMENTS_FILE = Path('assets') / 'data' / 'influencer_feed.json'

OK, MISSING, STALE, UNREADABLE = 'ok', 'missing', 'stale', 'unreadable'


def _out(field, unit, window, missing):
    return {'field': field, 'unit': unit, 'window': window, 'missing': missing}


#: `plugin_host.declarations`.
SIGNAL_SOURCE = {
    'id': 'sentiment',
    'family': 'sentiment',
    'summary': 'Retail attention per holding and statements by named figures, read from '
               'the two morning scans with an explicit status.',
    'inputs': [
        {'name': 'sentiment.json', 'what': 'per-holding Reddit mention counts and Google News titles',
         'source': 'market_data.sentiment, run off-host by sentiment-scan; Reddit search RSS and '
                   'Google News RSS, both unauthenticated'},
        {'name': 'influencer_feed.json', 'what': 'statements and trades scored 0-100 for relevance',
         'source': 'automation.influencer, run off-host by influencer-scan; primary feeds, ARK '
                   'trades and news proxies, filtered by one model call'},
        {'name': 'recent_moves', 'what': 'each signalled name\'s move over the last five closed sessions',
         'source': 'the caller; the brief computes it from memory/bars'},
    ],
    'outputs': [
        _out('status', 'ok, missing, stale or unreadable', 'this read', 'never null'),
        _out('age_hours', 'hours since the payload\'s generated_at', 'this read',
             'null when the payload carries no readable stamp, and the reading is then stale'),
        _out('attention.tickers[].reddit_mentions_7d', 'posts', '7 days before the scan',
             'null when Reddit did not answer for the name, with reddit_status saying so; '
             'zero only when it answered and found none'),
        _out('attention.tickers[].news_top', 'up to 3 titles', 'the scan\'s Google News answer',
             'empty list when the scan returned none'),
        _out('attention.tickers[].recent_move', 'percent over n sessions', '5 closed sessions',
             'null when the store has too few closes for the name'),
        _out('statements.held_hits', 'up to 6 items naming a holding', '48 hours before the scan',
             'empty list when none; llm_filter_status says whether the filter ran or kept '
             'the previous scan\'s scored items'),
        _out('statements.new_ideas', 'up to 6 items naming something not held', '48 hours before the scan',
             'empty list when none'),
        _out('statements.sector_hits', 'up to 4 items naming a held sector', '48 hours before the scan',
             'empty list when none'),
        _out('statements.*.relevance', 'model score 0-100; below 45 is not published', 'per item',
             'an unscored item is not published'),
    ],
    'missing': {
        'policy': 'omitted',
        'detail': 'A file that is absent, unparseable, unstamped or older than stale_after_hours '
                  'gives an empty reading and a status that says which. The brief runs without '
                  'the section; the previous day\'s reading is not used in its place.',
        'serves_stale': False,
    },
}


def payload_age_hours(payload, now=None):
    """Hours since the payload's own `generated_at`; None when it has no readable one."""
    stamp = (payload or {}).get('generated_at')
    if not stamp:
        return None
    try:
        at = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - at).total_seconds() / 3600


def _answer(status, reading=None, age=None, **detail):
    return {'status': status, 'reading': reading or {}, 'age_hours': age, 'detail': detail}


def _trim_statement(item):
    return {key: item.get(key) for key in
            ('author', 'stance', 'relevance', 'held', 'new_ideas',
             'sector_holdings', 'sectors', 'summary_cn')}


class Sentiment:
    def __init__(self, stale_after_hours):
        self.stale_after_hours = stale_after_hours

    def is_stale(self, age) -> bool:
        """Unknown, too old, or from the future beyond clock skew."""
        return age is None or age > self.stale_after_hours or age < -CLOCK_SKEW_HOURS

    def _read(self, path, build):
        try:
            if not path.exists():
                return _answer(MISSING)
            payload = json.loads(path.read_text())
            age = payload_age_hours(payload)
            if self.is_stale(age):
                return _answer(STALE, age=age)
            return build(payload, age)
        except Exception as exc:
            return _answer(UNREADABLE, error=type(exc).__name__, message=str(exc))

    def attention(self, workspace, recent_moves) -> dict:
        """Mentions and titles per holding. `recent_moves(tickers)` answers
        {ticker: {'px_pct', 'n_sessions'}} for the names that carry a signal."""
        def build(scan, age):
            signalled = [row.get('ticker') for row in scan.get('tickers', [])
                         if row.get('reddit_mentions_7d') or row.get('google_news_en')
                         or row.get('google_news_zh')]
            moves = recent_moves(signalled)
            rows = []
            for row in scan.get('tickers', []):
                mentions = row.get('reddit_mentions_7d')
                reddit_status = row.get('reddit_status') or 'ok'
                english = row.get('google_news_en') or []
                chinese = row.get('google_news_zh') or []
                # Nothing measured on either source is noise. A name whose
                # Reddit lookup did not answer is unknown, not quiet, and
                # dropping it would hide the outage (#1237).
                if not mentions and reddit_status == 'ok' and not english and not chinese:
                    continue
                rows.append({
                    'ticker': row.get('ticker'),
                    'name': row.get('name'),
                    'region': row.get('region'),
                    'reddit_mentions_7d': mentions,
                    'reddit_status': reddit_status,
                    # Title and link only: the search feed carries no score or
                    # comment count, and a default of 0 would read as a post
                    # nobody upvoted.
                    'reddit_top': [{'title': post.get('title'), 'url': post.get('url')}
                                   for post in (row.get('reddit_posts') or [])[:3]],
                    'news_top': [item.get('title') for item in (english + chinese)[:3]
                                 if item.get('title')],
                    'recent_move': moves.get(row.get('ticker')),
                })
            reading = {
                'as_of': scan.get('generated_at'),
                'age_hours': round(age, 1),
                'sources': scan.get('sources', []),
                'tickers': rows,
            }
            return _answer(
                OK, reading, age,
                scanned=len(scan.get('tickers', [])),
                with_signal=sum(1 for row in rows if row['reddit_mentions_7d'] or row['news_top']),
                unanswered=sum(1 for row in rows if row['reddit_status'] != 'ok'))
        return self._read(Path(workspace) / ATTENTION_FILE, build)

    def statements(self, workspace) -> dict:
        """Held hits, new ideas and sector hits from the statement radar."""
        def build(feed, age):
            return _answer(OK, {
                'as_of': feed.get('generated_at'),
                'age_hours': round(age, 1),
                'counts': feed.get('counts', {}),
                'llm_filter_status': feed.get('llm_filter_status'),
                'source_status': feed.get('source_status', {}),
                'sources': feed.get('sources', {}),
                'held_hits': [_trim_statement(item) for item in feed.get('held_hits', [])][:6],
                'new_ideas': [_trim_statement(item) for item in feed.get('new_ideas', [])][:6],
                'sector_hits': [_trim_statement(item) for item in feed.get('sector_hits', [])][:4],
            }, age)
        return self._read(Path(workspace) / STATEMENTS_FILE, build)

    def describe(self) -> dict:
        return {'stale_after_hours': self.stale_after_hours}


def apply(ctx, config):
    hours = config.get('stale_after_hours', STALE_AFTER_HOURS)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not hours > 0:
        raise ValueError(f'sentiment stale_after_hours must be a positive number, got {hours!r}')
    ctx.provide('sentiment', Sentiment(hours))
