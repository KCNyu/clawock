"""News-digest prompt payload: whole-ticker inclusion, declared omissions.

Regression guard for #959: the prompt embedded `json.dumps(raw)[:25000]`, which
on busy days cut mid-string (malformed JSON tail) and silently dropped whole
tickers from a digest that was still expected to cover them.
"""
from __future__ import annotations

import json

from clawock.automation.news_digest import build_news_payload


def _news_item(seed):
    return {
        'headline': f'headline {seed} ' + 'w' * 180,
        'summary': 'summary ' + 's' * 380,
        'datetime': 1756000000 + seed,
        'source': 'Example Wire',
        'origin': 'finnhub',
        'url': f'https://example.com/{seed}',
    }


def _raw(tickers):
    return {ticker: [_news_item(i) for i in range(len(tickers))]
            for i, ticker in enumerate(tickers)}


def _fixed_size_raw(tickers):
    """Three items per ticker whatever the universe size — `_raw` scales items
    with the ticker count, which starves a 300-ticker budget test of any
    ticker small enough to include."""
    return {ticker: [_news_item(i) for i in range(3)] for ticker in tickers}


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def test_under_budget_every_ticker_rides_and_nothing_is_declared():
    raw = _raw(['PLTR', 'HOOD', 'MSFT'])

    payload = build_news_payload(raw, budget=25_000)

    assert set(payload) == {'PLTR', 'HOOD', 'MSFT'}
    assert payload == raw
    assert json.loads(_compact(payload)) == payload


def test_over_budget_tickers_are_included_or_skipped_whole():
    tickers = [f'T{i:02d}' for i in range(20)]
    raw = _raw(tickers)

    budget = 5000
    payload = build_news_payload(raw, budget=budget)
    serialized = _compact(payload)

    assert json.loads(serialized) == payload
    assert len(serialized) <= budget

    skipped = payload.get('_omitted_tickers')
    assert isinstance(skipped, list) and skipped, 'omissions must be declared'
    included = [t for t in tickers if t in payload]
    assert set(included) & set(skipped) == set()
    assert sorted(included + skipped) == sorted(tickers)
    # Included tickers ride with their items byte-for-byte intact.
    for ticker in included:
        assert payload[ticker] == raw[ticker]
    # Inclusion follows input order: no later ticker jumps an earlier skip.
    first_skip = min(tickers.index(t) for t in skipped)
    last_include = max((tickers.index(t) for t in included), default=-1)
    assert last_include < first_skip


def test_the_omission_manifest_cannot_push_the_payload_back_over_budget():
    """#989: the manifest rides inside the payload, so reserving only the empty
    list under-counted it. 300 oversized tickers serialized to 26,602 chars
    against a 25,000 budget — the word "budget" only means something if it is
    an upper bound."""
    tickers = [f'T{i:03d}' for i in range(300)]
    raw = _fixed_size_raw(tickers)

    budget = 25_000
    payload = build_news_payload(raw, budget=budget)
    serialized = _compact(payload)

    assert json.loads(serialized) == payload
    assert len(serialized) <= budget
    # Still whole-ticker, still declared, still input-ordered after the demotion.
    skipped = payload['_omitted_tickers']
    included = [t for t in tickers if t in payload]
    assert included, 'the budget is big enough for some tickers'
    assert sorted(included + skipped) == sorted(tickers)
    for ticker in included:
        assert payload[ticker] == raw[ticker]
    assert max(tickers.index(t) for t in included) < min(
        tickers.index(t) for t in skipped)


def test_a_manifest_bigger_than_the_budget_is_kept_whole_not_sliced():
    """The one honest overrun: when naming what was dropped costs more than the
    budget itself, the manifest still ships intact — a sliced manifest would be
    a payload that lies about what is missing."""
    tickers = [f'T{i:03d}' for i in range(300)]

    payload = build_news_payload(_fixed_size_raw(tickers), budget=500)

    assert [t for t in tickers if t in payload] == []
    assert payload['_omitted_tickers'] == tickers
    assert json.loads(_compact(payload)) == payload
