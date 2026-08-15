"""Per-slot bars cache (#613): the three collectors must share one fetch.

Before #613 each collector fetched the same code independently (3x per slot,
~540 requests/day for a 10-name book). The cache is scoped to one preflight
slot: main() clears it, and distinct codes still fetch separately.
"""
from clawock.harness import intraday_preflight as P


def test_fetch_bars_cached_fetches_once_per_code(monkeypatch):
    calls = {'n': 0}

    def fake_fetch(code, cnt=400):
        calls['n'] += 1
        return [{'date': '2026-08-14', 'close': 10, 'high': 11, 'low': 9}]

    monkeypatch.setattr(P.quant_signals, 'fetch_bars', fake_fetch)
    P._BARS_CACHE.clear()

    first = P._fetch_bars_cached('x', 400)
    second = P._fetch_bars_cached('x', 400)
    assert first is second
    assert calls['n'] == 1

    P._fetch_bars_cached('y', 400)
    assert calls['n'] == 2  # a distinct code fetches its own bars


def test_cache_scope_is_one_slot(monkeypatch):
    """Clearing the cache (what main() does at slot start) forces a refetch."""
    calls = {'n': 0}

    def fake_fetch(code, cnt=400):
        calls['n'] += 1
        return []

    monkeypatch.setattr(P.quant_signals, 'fetch_bars', fake_fetch)
    P._BARS_CACHE.clear()

    P._fetch_bars_cached('x', 400)
    P._BARS_CACHE.clear()
    P._fetch_bars_cached('x', 400)
    assert calls['n'] == 2
