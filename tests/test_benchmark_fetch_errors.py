"""A fetch that could not run must not be spelled like a market with no sessions.

2026-09-07: `assets/data/benchmark.json` held SPY through 2026-09-02 while HSI
and HSTECH were current through 09-04. Polygon, queried directly that evening,
returned 09-03 and 09-04 — the data existed, the stored series just never
advanced. `fetch_polygon_daily` read `data.get("results") or []` off an
UNCHECKED response, so an HTTP 401 / 403 / 429 — whose body is
`{"status": "ERROR", "error": "..."}` with no `results` key — came back as an
empty list. `assign()` correctly retained the prior series (that contract is not
being changed), and the whole event's only trace was one stderr line.

Verified against the live API that evening: a bad key answers HTTP 401 with
`{"status": "ERROR", "error": "Unknown API Key"}`. No exception. No results.

The series is re-fetched as a 60-day window, so ONE success backfills every gap
— which is why a single unretried miss is worth this much machinery.
"""
import types

import pytest
import requests

from clawock.market_data import benchmarks


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f'{self.status_code} Client Error', response=self)

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    # `raising=False` so these tests still RUN against a build that has no retry
    # at all — the point of the suite is that the old shape fails on behaviour
    # (an HTTP error returning `[]` in silence), not on an AttributeError.
    monkeypatch.setattr(benchmarks, 'time',
                        types.SimpleNamespace(sleep=lambda _s: None),
                        raising=False)


def _polygon_bar(date_ms, close):
    return {'t': date_ms, 'c': close}


def test_an_http_error_is_reported_not_returned_as_emptiness(monkeypatch, capsys):
    monkeypatch.setattr(benchmarks.requests, 'get',
                        lambda *a, **kw: _Response(
                            401, {'status': 'ERROR', 'error': 'Unknown API Key'}))

    assert benchmarks.fetch_polygon_daily('SPY', 60, 'key') == []

    err = capsys.readouterr().err
    assert 'polygon SPY' in err and '401' in err


def test_a_200_with_status_error_is_also_a_failure(monkeypatch, capsys):
    """Polygon answers 200 with `status: ERROR` too. `results` being absent is
    only "no sessions" once the call is known to have succeeded."""
    monkeypatch.setattr(benchmarks.requests, 'get',
                        lambda *a, **kw: _Response(
                            200, {'status': 'ERROR', 'error': 'unknown ticker'}))

    assert benchmarks.fetch_polygon_daily('SPY', 60, 'key') == []
    assert 'unknown ticker' in capsys.readouterr().err


def test_a_genuinely_empty_window_is_not_reported_as_a_failure(monkeypatch, capsys):
    """The one case that really is "no data": a successful call, no bars."""
    monkeypatch.setattr(benchmarks.requests, 'get',
                        lambda *a, **kw: _Response(200, {'status': 'OK', 'results': []}))

    assert benchmarks.fetch_polygon_daily('SPY', 60, 'key') == []
    assert 'failed' not in capsys.readouterr().err


def test_a_transient_failure_is_retried_and_heals(monkeypatch):
    """One success backfills the whole 60-day window, so the retry is the
    difference between a healed series and a session stranded for a day."""
    calls = {'n': 0}

    def flaky(*a, **kw):
        calls['n'] += 1
        if calls['n'] == 1:
            raise requests.exceptions.ConnectionError('link dropped')
        return _Response(200, {'status': 'OK',
                               'results': [_polygon_bar(1_788_000_000_000, 700.5)]})

    monkeypatch.setattr(benchmarks.requests, 'get', flaky)

    rows = benchmarks.fetch_polygon_daily('SPY', 60, 'key')

    assert calls['n'] == 2
    assert [r['close'] for r in rows] == [700.5]


def test_a_rate_limit_is_retried(monkeypatch):
    calls = {'n': 0}

    def limited(*a, **kw):
        calls['n'] += 1
        if calls['n'] == 1:
            return _Response(429, {'status': 'ERROR', 'error': 'too many requests'})
        return _Response(200, {'status': 'OK', 'results': []})

    monkeypatch.setattr(benchmarks.requests, 'get', limited)

    benchmarks.fetch_polygon_daily('SPY', 60, 'key')

    assert calls['n'] == 2


def test_a_dead_credential_is_not_retried(monkeypatch):
    """Retrying a 401 is not resilience, it is two failures. It answers the same
    way forever; report it at once, while the reason is still in the log."""
    calls = {'n': 0}

    def unauthorized(*a, **kw):
        calls['n'] += 1
        return _Response(401, {'status': 'ERROR', 'error': 'Unknown API Key'})

    monkeypatch.setattr(benchmarks.requests, 'get', unauthorized)

    benchmarks.fetch_polygon_daily('SPY', 60, 'key')

    assert calls['n'] == 1


def test_a_missing_key_says_so(monkeypatch, capsys):
    """Silence here would be indistinguishable from a market with no sessions."""
    assert benchmarks.fetch_polygon_daily('SPY', 60, '') == []
    assert 'POLYGON_API_KEY' in capsys.readouterr().err


def test_the_hk_leg_has_the_same_guard(monkeypatch, capsys):
    """It was not the leg that broke — which is exactly why it needs the guard.
    A check that only exists where the failure already happened is the coverage
    bug this codebase keeps re-learning."""
    monkeypatch.setattr(benchmarks.requests, 'get',
                        lambda *a, **kw: _Response(503, {}))

    assert benchmarks.fetch_tencent_hk_daily('hkHSI', 60) == []
    assert 'tencent hkHSI' in capsys.readouterr().err


def test_a_failed_fetch_still_returns_a_list_so_the_prior_series_survives(monkeypatch):
    """`assign()` retains the prior series on an empty fetch (#fetcher-merge-not-
    overwrite). Raising out of here instead would turn a stale benchmark into a
    missing one — strictly worse."""
    monkeypatch.setattr(benchmarks.requests, 'get',
                        lambda *a, **kw: _Response(500, {}))

    assert benchmarks.fetch_polygon_daily('SPY', 60, 'key') == []
    assert benchmarks.fetch_tencent_hk_daily('hkHSI', 60) == []
