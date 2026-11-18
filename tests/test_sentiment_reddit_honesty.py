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


def test_missing_community_discards_all_counts(monkeypatch):
    import requests

    now = datetime.now(timezone.utc)
    rows = _rows()
    calls = []

    def fetch(subreddit, *, now):
        calls.append(subreddit)
        if subreddit == 'stocks':
            return [{'title': 'RKLB', 'url': 'https://www.reddit.com/r/stocks/comments/x/',
                     'sub': subreddit, 'created': now}], 1
        response = requests.Response()
        response.status_code = 429
        raise requests.HTTPError(response=response)

    assert sp.scan_reddit(rows, REGISTRY, now=now, fetch=fetch) == 0
    assert calls == ['stocks', 'investing']
    assert all(row['reddit_mentions_7d'] is None for row in rows)
    assert {row['reddit_status'] for row in rows} == {'throttled'}
    assert sp.FEED_SUMMARY == {'entries': None, 'within_window': None}


def test_archive_filters_dates_counts_sample_and_keeps_denominator(monkeypatch):
    now = datetime.now(timezone.utc)
    rows = _rows()
    monkeypatch.setattr(sp, 'REDDIT_LIMIT', 2)

    def fetch(subreddit, *, now):
        if subreddit == 'stocks':
            titles = [('Rocket Lab', 1), ('RKLB', 400)]
        elif subreddit == 'investing':
            titles = [('无关', 1), ('今天金风科技上涨', 2)]
        else:
            titles = [('Rocket Lab today', 0)]
        posts = [{'title': title, 'created': now - timedelta(days=age),
                  'sub': subreddit, 'url': 'https://www.reddit.com/'} for title, age in titles]
        return posts, len(posts)

    assert sp.scan_reddit(rows, REGISTRY, now=now, fetch=fetch) == 2
    by_ticker = {row['ticker']: row for row in rows}
    assert by_ticker['RKLX']['reddit_mentions_7d'] == 2
    assert by_ticker['RKLX']['reddit_posts'][0]['sub'] == 'wallstreetbets'
    assert by_ticker['02208']['reddit_mentions_7d'] == 1
    assert by_ticker['00100']['reddit_mentions_7d'] == 0
    assert all(row['reddit_sampled'] and row['reddit_mentions_capped'] for row in rows)
    assert sp.FEED_SUMMARY == {'entries': 5, 'within_window': 4}


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


def test_the_brief_prints_the_move_the_preflight_actually_wrote():
    """The producer writes {px_pct, n_sessions}; reading `pct_5d` printed — (#1892)."""
    from clawock.harness import brief_render

    def render(move):
        return brief_render.sentiment_section(
            {'sentiment': {'tickers': [{'ticker': '07226', 'recent_move': move,
                                        'news_top': []}]}}, {})

    assert '近 5 日 +2.3%' in render({'px_pct': 2.3, 'n_sessions': 5})
    assert '近 3 日 -1.0%' in render({'px_pct': -1.0, 'n_sessions': 3})
    assert f'近 5 日 {brief_render.MISSING}' in render(None)
