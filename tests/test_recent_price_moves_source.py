"""The priced-in signal must come from canonical bars, not snapshot vintage.

Regression guard for #963: `_recent_price_moves` used to string together
`current_price` from the last few memory/snapshots/*.json files. bars.py
documents that field as fetch vintage rather than session identity — across 15
snapshots 00100's current_price was the previous close 7 times, that day's
close 3, an intraday print 5 — while SKILL.md makes the price-in judgement a
required step built on exactly this number. The move now reads session-dated
closes from memory/bars, and a ticker the store does not cover gets no move at
all instead of a fabricated one.
"""
from __future__ import annotations

import json

from clawock.harness import brief_preflight


def _write_bars(ws, ticker, closes_by_date):
    doc = {
        'schema_version': 1,
        'ticker': ticker,
        'leg': 'HK',
        'bars': {d: {'open': c, 'high': c, 'low': c, 'close': c}
                 for d, c in closes_by_date.items()},
    }
    path = ws / 'memory' / 'bars' / f'{ticker}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding='utf-8')


def _write_snapshot(ws, date, holdings_prices):
    snap = {'portfolios': {
        leg: {'holdings': [{'ticker': tk, 'current_price': px}]
              for tk, px in prices.items()}
        for leg, prices in (('hk_stocks', holdings_prices),
                            ('us_stocks', {}))
    }}
    path = ws / 'memory' / 'snapshots' / f'{date}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap), encoding='utf-8')


def test_move_computes_from_bar_closes_not_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    bars = {'2026-08-17': 100.0, '2026-08-18': 102.0, '2026-08-19': 101.0,
            '2026-08-20': 104.0, '2026-08-21': 103.0, '2026-08-24': 110.0}
    _write_bars(tmp_path, '00100', bars)
    # Snapshot current_price values disagree with the bars on purpose: under
    # the old source these numbers decided the answer.
    for i, (date, px) in enumerate([('2026-08-18', 90.0), ('2026-08-19', 91.0),
                                    ('2026-08-20', 92.0), ('2026-08-21', 93.0),
                                    ('2026-08-24', 94.0)]):
        _write_snapshot(tmp_path, date, {'00100': px})

    moves = brief_preflight._recent_price_moves(['00100'])

    assert moves == {'00100': {'px_pct': 10.0, 'n_sessions': 5}}


def test_lookback_window_is_the_last_n_closed_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    bars = {'2026-08-10': 50.0, '2026-08-11': 51.0, '2026-08-12': 52.0,
            '2026-08-13': 53.0, '2026-08-14': 54.0, '2026-08-17': 55.0,
            '2026-08-18': 56.0, '2026-08-19': 70.0}
    _write_bars(tmp_path, '07226', bars)

    moves = brief_preflight._recent_price_moves(['07226'], lookback_sessions=5)

    # window = last 6 closes (52..70) -> +34.6% over 5 sessions; the early
    # bars (50/51) stay out of the window.
    assert moves['07226'] == {'px_pct': round((70.0 / 52.0 - 1) * 100, 1),
                              'n_sessions': 5}


def test_ticker_without_bars_gets_no_move_even_when_snapshots_have_it(
        tmp_path, monkeypatch):
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    for i, px in enumerate([10.0, 11.0, 12.0]):
        _write_snapshot(tmp_path, f'2026-08-2{i}', {'NEWNAME': px})

    moves = brief_preflight._recent_price_moves(['NEWNAME'])

    assert moves == {}


def test_thin_or_corrupt_bar_docs_are_skipped_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    _write_bars(tmp_path, '00001', {'2026-08-20': 7.0})  # single session
    bad = tmp_path / 'memory' / 'bars' / '00002.json'
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text('{not json', encoding='utf-8')
    empty = tmp_path / 'memory' / 'bars' / '00003.json'
    empty.write_text(json.dumps({'ticker': '00003', 'bars': {}}),
                     encoding='utf-8')

    moves = brief_preflight._recent_price_moves(['00001', '00002', '00003'])

    assert moves == {}
