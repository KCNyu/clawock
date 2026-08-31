"""A mention count that was never fetched must not be published as a number.

The bug these pin (#1237): Reddit's unauthenticated JSON API answered `403` to
every request for the entire recorded life of `sentiment.json` — 87 commits,
2026-05-17 onward, every ticker `0` every day — while three consumers read that
`0` as "nobody is talking about this name". The producer even recorded
`source_status.reddit == 'failed'` correctly; nothing downstream read it.

So the assertions here are mostly about the failure paths, and each one is
driven with data rather than trusted to behave: a green run of the happy path
proves nothing about the branch that only a bad day reaches.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from clawock.decision import packet
from clawock.market_data import sentiment as sp
from clawock.publish import artifacts


REGISTRY = {
    'RKLX': {'name': 'Defiance Daily Target 2X Long RKLB', 'underlying': 'RKLB'},
    'RKLB': {'name': 'Rocket Lab', 'underlying': None},
    '02208': {'name': '金风科技', 'underlying': None},
    '00100': {'name': 'MINIMAX-W', 'underlying': None},
    'CRCL': {'name': 'Circle Internet Group', 'underlying': None},
}


def _rows():
    return [
        {'ticker': 'RKLX', 'name': REGISTRY['RKLX']['name'], 'region': 'us_stocks'},
        {'ticker': '02208', 'name': '金风科技', 'region': 'hk_stocks'},
        {'ticker': '00100', 'name': 'MINIMAX-W', 'region': 'hk_stocks'},
    ]


def _feed(entries):
    """An Atom feed shaped like Reddit's search RSS."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<feed xmlns="http://www.w3.org/2005/Atom">']
    for sub, title, when, content in entries:
        parts.append(
            f'<entry><category term="{sub}"/><title>{title}</title>'
            f'<link href="https://example.invalid/x"/>'
            f'<updated>{when.isoformat()}</updated>'
            f'<content type="html">{content}</content></entry>')
    parts.append('</feed>')
    return ''.join(parts)


class _Response:
    def __init__(self, status_code, text=''):
        self.status_code = status_code
        self.text = text


def test_search_terms_look_through_to_the_name_people_write(monkeypatch):
    """Nobody posts about RKLX; they post about Rocket Lab, which it holds."""
    assert sp.search_terms('RKLX', REGISTRY['RKLX']['name'], REGISTRY) == [
        'RKLB', 'Rocket Lab']
    assert sp.search_terms('CRCL', 'Circle Internet Group', REGISTRY) == [
        'CRCL', 'Circle Internet'], 'the wrapper word must not enter the query'
    assert sp.search_terms('02208', '金风科技', REGISTRY) == ['金风科技']


def test_a_chinese_name_is_matched_without_word_boundaries():
    """`\\b` is defined on word characters, and Chinese has none.

    A boundary-anchored pattern never matches 金风科技, so every Hong Kong name
    would score a silent zero — the same shape of bug as the one being fixed.
    """
    assert sp._matcher('金风科技').search('今天 金风科技 涨了')
    assert sp._matcher('RKLB').search('RKLB is up')
    assert not sp._matcher('RKLB').search('WRKLBX'), (
        'a Latin term still has to be a whole word')


def test_a_throttled_feed_publishes_no_count_at_all():
    """The whole point. `None`, never `0`, and the status says which."""
    rows = _rows()
    sp.scan_reddit(rows, REGISTRY, sleep=lambda _seconds: None,
                   fetch=lambda query, sleep=None: (None, 'throttled'))

    assert [row['reddit_mentions_7d'] for row in rows] == [None, None, None]
    assert {row['reddit_status'] for row in rows} == {'throttled'}
    assert sp.SOURCE_STATUS['reddit'] == 'throttled', (
        'throttled is a source that works; failed is one that does not, and a '
        'single bucket cannot tell anyone which happened')


def test_an_unparseable_feed_also_publishes_no_count():
    rows = _rows()
    sp.scan_reddit(rows, REGISTRY, sleep=lambda _seconds: None,
                   fetch=lambda query, sleep=None: ('not xml at all', 'ok'))

    assert [row['reddit_mentions_7d'] for row in rows] == [None, None, None]
    assert sp.SOURCE_STATUS['reddit'] == 'failed'


def test_a_dictionary_word_in_an_unrelated_subreddit_is_not_a_mention():
    """MINIMAX is a game-theory algorithm and one of this book's holdings.

    Measured on the live book before the subreddit gate: 16 mentions in a week,
    from r/abstractgames and r/PiCodingAgent. Publishing 16 would have replaced
    a false zero with a false sixteen.
    """
    now = datetime.now(timezone.utc)
    rows = _rows()
    feed = _feed([
        ('abstractgames', 'A minimax search idea', now - timedelta(days=1), ''),
        ('PiCodingAgent', 'minimax code found my skills', now - timedelta(hours=3), ''),
        ('stocks', 'RKLB is up 20%', now - timedelta(days=2), 'Rocket Lab earnings'),
        ('u/The_optiontrader', 'MINIMAX update', now - timedelta(days=1), ''),
    ])
    sp.scan_reddit(rows, REGISTRY, now=now, sleep=lambda _s: None,
                   fetch=lambda query, sleep=None: (feed, 'ok'))
    by_ticker = {row['ticker']: row for row in rows}

    assert by_ticker['00100']['reddit_mentions_7d'] == 0
    assert by_ticker['RKLX']['reddit_mentions_7d'] == 1
    assert by_ticker['RKLX']['reddit_posts'][0]['sub'] == 'stocks'
    assert sp.is_finance_sub('u/The_optiontrader') is False, (
        'a user profile is not a community, and it passes the substring test '
        'on "option" alone')


def test_a_mention_older_than_the_window_does_not_count():
    """`sort=new&t=week` is ignored by the endpoint — probed entries ran to 2012."""
    now = datetime.now(timezone.utc)
    rows = _rows()
    feed = _feed([
        ('stocks', 'Rocket Lab in 2012', now - timedelta(days=400), ''),
        ('investing', 'Rocket Lab today', now - timedelta(days=1), ''),
    ])
    sp.scan_reddit(rows, REGISTRY, now=now, sleep=lambda _s: None,
                   fetch=lambda query, sleep=None: (feed, 'ok'))

    assert {r['ticker']: r['reddit_mentions_7d'] for r in rows}['RKLX'] == 1


def test_a_full_feed_reports_the_count_as_a_floor():
    now = datetime.now(timezone.utc)
    rows = _rows()
    feed = _feed([('stocks', 'Rocket Lab', now - timedelta(hours=index), '')
                  for index in range(sp.REDDIT_LIMIT)])
    sp.scan_reddit(rows, REGISTRY, now=now, sleep=lambda _s: None,
                   fetch=lambda query, sleep=None: (feed, 'ok'))

    assert all(row['reddit_mentions_capped'] for row in rows), (
        'there is no page two, so a busier week looks like this one'
    )


def test_the_producer_retries_a_throttle_before_giving_up(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return _Response(429) if len(calls) < 3 else _Response(200, _feed([]))

    monkeypatch.setattr(sp.requests, 'get', get)
    text, status = sp.fetch_reddit('RKLB', sleep=lambda _seconds: None)

    assert (status, len(calls)) == ('ok', 3)
    assert text is not None


def test_the_validator_refuses_a_number_from_a_source_that_did_not_answer(tmp_path):
    portfolio = tmp_path / 'portfolio.json'
    portfolio.write_text(json.dumps({'portfolios': {
        'us_stocks': {'holdings': [{'ticker': 'RKLX', 'shares': 1}]},
        'hk_stocks': {'holdings': []}}}), encoding='utf-8')
    snapshot = tmp_path / 'sentiment.json'
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sources': ['reddit-search-rss', 'google-news-rss'],
        'source_status': {'reddit': 'throttled', 'google_news': 'ok'},
        'tickers': [{
            'ticker': 'RKLX', 'name': 'x', 'region': 'us_stocks',
            'reddit_mentions_7d': 0, 'reddit_status': 'throttled',
            'reddit_posts': [], 'google_news_en': [{'title': 't'}],
            'google_news_zh': [],
        }],
    }
    snapshot.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(AssertionError, match='must be null, not a number'):
        artifacts.validate_sentiment(snapshot, portfolio)

    payload['tickers'][0]['reddit_mentions_7d'] = None
    snapshot.write_text(json.dumps(payload), encoding='utf-8')
    artifacts.validate_sentiment(snapshot, portfolio)


def test_the_decision_packet_does_not_turn_an_absent_count_into_zero():
    """`int(x or 0)` is what told the model nobody was talking, for 87 days."""
    assert packet._mention_count(None) is None
    assert packet._mention_count(0) == 0
    assert packet._mention_count(4) == 4

    view = packet._sentiment_view(
        [{'ticker': 'RKLX', 'reddit_mentions_7d': None,
          'reddit_status': 'throttled', 'news_top': []}], 'RKLX', 'RKLX')
    assert view['reddit_mentions_7d'] is None
    assert view['reddit_status'] == 'throttled'
    assert packet._sentiment_view([], 'RKLX', 'RKLX')['reddit_status'] == 'missing'


def test_the_brief_prints_a_dash_not_a_zero_for_a_count_it_does_not_have():
    """`0 mentions` went out in a published report every day for three months."""
    from clawock.harness import brief_render

    def render(count):
        return brief_render.sentiment_section(
            {'sentiment': {'tickers': [{'ticker': '07226',
                                        'reddit_mentions_7d': count,
                                        'news_top': []}]}}, {})

    assert '0 mentions' in render(0)
    assert 'mentions' not in render(None) and brief_render.MISSING in render(None)


def test_the_retry_backoff_is_reachable_by_a_test_that_patches_this_module(monkeypatch):
    """A `sleep=time.sleep` default is captured at import, not at call.

    Measured before this was fixed: `test_sentiment_producer_marks_total_http_outage_failed`
    spent **105 seconds** sleeping through the real 35s + 70s backoff, because
    it patches `sentiment.time.sleep` and the signature default had already
    bound the real one.
    """
    slept = []
    monkeypatch.setattr(sp.time, 'sleep', slept.append)
    monkeypatch.setattr(sp.requests, 'get', lambda *a, **k: _Response(429))

    text, status = sp.fetch_reddit('RKLB')

    assert (text, status) == (None, 'throttled')
    assert slept == [w for w in sp.REDDIT_RETRY_WAITS if w], (
        'the backoff has to go through the module attribute a test can reach'
    )
