"""Focused producer tests for quiet runs versus genuine source outages."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.data import fetch_influencer_feed
from scripts.data import gh_action_news_digest
from clawock.publish import artifacts as validate_sidecars
from clawock.market_data import sentiment as fetch_sentiment


class _Empty200:
    status_code = 200
    text = '<rss><channel></channel></rss>'

    @staticmethod
    def json():
        return {'data': {'children': []}}


def _portfolio(path):
    path.write_text(json.dumps({
        'portfolios': {
            'us_stocks': {'holdings': [{'ticker': 'AAPL', 'shares': 1}]},
            'hk_stocks': {'holdings': []},
        },
    }), encoding='utf-8')
    return path


def _run_sentiment(tmp_path, monkeypatch, get):
    output = tmp_path / 'sentiment.json'
    monkeypatch.setattr(fetch_sentiment, 'load_tickers', lambda _workspace: [{
        'ticker': 'AAPL', 'name': 'Apple', 'region': 'us_stocks',
    }])
    monkeypatch.setattr(fetch_sentiment.requests, 'get', get)
    monkeypatch.setattr(fetch_sentiment.time, 'sleep', lambda _seconds: None)
    fetch_sentiment.main(['--workspace', str(tmp_path), '--output', str(output)])
    return output, json.loads(output.read_text(encoding='utf-8'))


def test_sentiment_producer_marks_successful_empty_http_sources_ok(
        tmp_path, monkeypatch):
    output, payload = _run_sentiment(
        tmp_path, monkeypatch, lambda *args, **kwargs: _Empty200())

    assert payload['source_status'] == {
        'reddit': 'ok',
        'google_news': 'ok',
    }
    validate_sidecars.validate_sentiment(
        output, _portfolio(tmp_path / 'portfolio.json'))


def test_sentiment_producer_marks_total_http_outage_failed(
        tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('network unavailable')

    output, payload = _run_sentiment(tmp_path, monkeypatch, fail)

    assert payload['source_status'] == {
        'reddit': 'failed',
        'google_news': 'failed',
    }
    with pytest.raises(AssertionError, match='sentiment: all sources failed'):
        validate_sidecars.validate_sentiment(
            output, _portfolio(tmp_path / 'portfolio.json'))


def _run_influencer(tmp_path, monkeypatch, statuses, previous=None):
    output = tmp_path / 'influencer.json'
    if previous is not None:
        output.write_text(json.dumps(previous), encoding='utf-8')
    monkeypatch.setattr(fetch_influencer_feed, 'OUT_FILE', str(output))
    monkeypatch.setattr(
        fetch_influencer_feed, 'fetch_trump',
        lambda _cutoff: ([], statuses['trump']))
    monkeypatch.setattr(
        fetch_influencer_feed, 'fetch_musk',
        lambda: ([], statuses['musk']))
    monkeypatch.setattr(
        fetch_influencer_feed, 'fetch_serenity',
        lambda _cutoff: ([], statuses['serenity']))
    monkeypatch.setattr(fetch_influencer_feed, 'load_holdings', lambda: [])
    monkeypatch.setattr(
        fetch_influencer_feed, 'llm_filter',
        lambda _candidates, _held: {})
    fetch_influencer_feed.main()
    return output, json.loads(output.read_text(encoding='utf-8'))


def test_influencer_producer_quiet_success_empty_passes(tmp_path, monkeypatch):
    output, payload = _run_influencer(tmp_path, monkeypatch, {
        'trump': 'success_empty',
        'musk': 'success_empty',
        'serenity': 'failed',
    })

    assert payload['items'] == []
    validate_sidecars.validate_influencer(output)


def test_influencer_producer_total_outage_is_rejected(tmp_path, monkeypatch):
    output, payload = _run_influencer(tmp_path, monkeypatch, {
        'trump': 'failed',
        'musk': 'failed',
        'serenity': 'failed',
    })

    assert payload['items'] == []
    with pytest.raises(AssertionError, match='influencer: all sources failed'):
        validate_sidecars.validate_influencer(output)


def test_influencer_retains_only_fresh_items_with_original_timestamp(
        tmp_path, monkeypatch):
    fresh = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    previous = {
        'items': [
            {'author': 'Trump', 'text': 'fresh statement', 'published': fresh},
            {'author': 'Musk', 'text': 'stale statement', 'published': stale},
        ],
    }
    output, payload = _run_influencer(
        tmp_path, monkeypatch,
        {'trump': 'failed', 'musk': 'failed', 'serenity': 'failed'},
        previous=previous)

    assert [(item['text'], item['published']) for item in payload['items']] == [
        ('fresh statement', fresh),
    ]
    assert payload['items'][0]['retained_from_previous'] is True
    validate_sidecars.validate_influencer(output)


def _news_portfolio(path):
    path.write_text(json.dumps({
        'portfolios': {
            'us_stocks': {'holdings': [{'ticker': 'AAPL', 'shares': 1}]},
        },
    }), encoding='utf-8')


def test_news_producer_writes_explicit_quiet_artifact(tmp_path, monkeypatch):
    _news_portfolio(tmp_path / 'portfolio.json')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        gh_action_news_digest, 'fetch_news',
        lambda _tickers, since_days=2: (
            {'AAPL': []},
            {'AAPL': {
                'finnhub': 'failed',
                'google_news': 'success_empty',
            }},
        ))
    monkeypatch.setattr(
        gh_action_news_digest, 'chat',
        lambda **kwargs: pytest.fail('quiet news run must not call the LLM'))

    gh_action_news_digest.main()

    output = tmp_path / 'assets/data/us_news_digest.json'
    payload = json.loads(output.read_text(encoding='utf-8'))
    assert payload['no_material_news'] is True
    assert payload['digest_markdown'] == ''
    validate_sidecars.validate_news_digest(
        output,
        now=datetime.fromisoformat(payload['generated_at']).replace(
            tzinfo=timezone.utc) + timedelta(hours=1))


def test_news_producer_total_source_outage_fails_without_writing(
        tmp_path, monkeypatch):
    _news_portfolio(tmp_path / 'portfolio.json')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        gh_action_news_digest, 'fetch_news',
        lambda _tickers, since_days=2: (
            {'AAPL': []},
            {'AAPL': {
                'finnhub': 'failed',
                'google_news': 'failed',
            }},
        ))

    with pytest.raises(RuntimeError, match='news: all sources failed'):
        gh_action_news_digest.main()

    assert not (tmp_path / 'assets/data/us_news_digest.json').exists()
