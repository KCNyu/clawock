"""Focused producer tests for quiet runs versus genuine source outages."""
from __future__ import annotations

import json

import pytest

from scripts.data import fetch_sentiment
from scripts.data import validate_sidecars


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
    monkeypatch.setattr(fetch_sentiment, 'OUT_FILE', str(output))
    monkeypatch.setattr(fetch_sentiment, 'load_tickers', lambda: [{
        'ticker': 'AAPL', 'name': 'Apple', 'region': 'us_stocks',
    }])
    monkeypatch.setattr(fetch_sentiment.requests, 'get', get)
    monkeypatch.setattr(fetch_sentiment.time, 'sleep', lambda _seconds: None)
    fetch_sentiment.main()
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
