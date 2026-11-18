"""The probe exercises the same request and payload checks as the producer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops' / 'ci'))
import smoke_reddit  # noqa: E402
from clawock.market_data import sentiment  # noqa: E402


def _response(code, data):
    class Response(requests.Response):
        def json(self):
            return data

    result = Response()
    result.status_code = code
    return result


@pytest.mark.parametrize('code, expected', [(403, 0), (429, 0), (404, 1), (502, 1)])
def test_probe_only_warns_for_block_and_throttle(monkeypatch, capsys, code, expected):
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: _response(code, {}))
    assert smoke_reddit.main() == expected
    assert ('::error::' if expected else '::warning::') in capsys.readouterr().out


@pytest.mark.parametrize('error', [requests.ConnectionError, requests.Timeout, TimeoutError])
def test_probe_warns_for_network_failures(monkeypatch, capsys, error):
    def get(*args, **kwargs):
        raise error()

    monkeypatch.setattr(requests, 'get', get)
    assert smoke_reddit.main() == 0
    assert '::warning::' in capsys.readouterr().out


@pytest.mark.parametrize('payload', [{}, {'data': []}, {'data': [{'subreddit': 'other'}]}])
def test_probe_fails_for_unusable_success_responses(monkeypatch, capsys, payload):
    monkeypatch.setattr(requests, 'get', lambda *args, **kwargs: _response(200, payload))
    assert smoke_reddit.main() == 1
    assert '::error::' in capsys.readouterr().out


def test_probe_exercises_all_production_communities():
    calls = []
    stamp = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()

    def get(url, *, params, **_kwargs):
        assert url == sentiment.REDDIT_INDEX
        assert params['limit'] == sentiment.REDDIT_LIMIT
        sub = params['subreddit']
        calls.append(sub)
        return _response(200, {'data': [
            {'subreddit': sub, 'created_utc': stamp, 'title': 'Stock question', 'id': 'abc'},
        ]})

    assert smoke_reddit.check(get=get) == ('reachable', len(sentiment.REDDIT_SUBREDDITS))
    assert calls == list(sentiment.REDDIT_SUBREDDITS)


def test_archive_rejects_a_stale_listing_and_excludes_deleted_titles():
    now = datetime.now(timezone.utc)
    row = {'subreddit': 'stocks', 'title': 'MSFT', 'id': 'abc'}
    recent = {**row, 'created_utc': (now - timedelta(hours=1)).timestamp()}
    old = {**row, 'created_utc': (now - timedelta(days=3)).timestamp()}
    with pytest.raises(ValueError, match='stale'):
        sentiment.fetch_reddit_community(
            'stocks', now=now, get=lambda *a, **k: _response(200, {'data': [old]}))

    entries, count = sentiment.fetch_reddit_community(
        'stocks', now=now, get=lambda *a, **k: _response(200, {'data': [
            recent, {**recent, 'id': 'def', 'author': '[deleted]'},
        ]}))
    assert count == 2
    assert [entry['url'] for entry in entries] == ['https://www.reddit.com/r/stocks/comments/abc/']


def test_archive_retries_an_index_timeout_once(monkeypatch):
    now = datetime.now(timezone.utc)
    post = {'subreddit': 'stocks', 'created_utc': now.timestamp(), 'title': 'MSFT', 'id': 'abc'}
    responses = iter([_response(422, {}), _response(200, {'data': [post]})])
    waits = []
    monkeypatch.setattr(sentiment.time, 'sleep', waits.append)

    def get(url, *, params, **_kwargs):
        assert params['after'] == (now - timedelta(days=7)).date().isoformat()
        return next(responses)

    entries, count = sentiment.fetch_reddit_community('stocks', now=now, get=get)
    assert count == len(entries) == 1
    assert len(waits) == 1
