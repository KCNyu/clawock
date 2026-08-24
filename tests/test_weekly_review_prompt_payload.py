"""The weekly-review prompt payload must be whole, declared, and complete.

Regression guard for #959: the prompt used to embed `json.dumps(bundle)[:40000]`,
which on committed 2026-08 data kept 5.7% of a 702K-character bundle, cut the
string mid-JSON (malformed tail), and silently hid decision_metrics /
snapshots / current_risk / input_warnings — while question 3 of the same prompt
asks for the current risk numbers.
"""
from __future__ import annotations

import json
from datetime import date

from clawock.automation import weekly_review as weekly


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _oversized_bundle():
    filler = 'x' * 4000
    return {
        'week': '2026-W33',
        'window': '2026-08-17 -> 2026-08-24',
        'bundle_evidence': {'plan_days': 1, 'nav_points': [
            {'date': '2026-08-17', 'total_nav_usd': 1.0},
            {'date': '2026-08-24', 'total_nav_usd': 2.0},
        ]},
        'plans': [
            {'date': f'2026-08-{day:02d}', 'data': {'decisions': [], 'note': filler}}
            for day in range(17, 24)
        ],
        'decision_episodes': [],
        'decision_metrics': {'per_strategy': {f'strat_{i}': filler for i in range(40)}},
        'snapshots': [{'portfolios': {}, 'gold_dca': filler} for _ in range(7)],
        'current_risk': {'combined': {'beta': 1.2}},
        'input_warnings': [],
    }


def test_real_committed_week_payload_is_whole_and_complete():
    bundle = weekly.aggregate_week(today=date(2026, 7, 24))

    payload = weekly.build_prompt_payload(bundle)
    serialized = _compact(payload)

    # The payload must parse as one JSON value — no sliced mid-string tail.
    assert json.loads(serialized) == payload
    assert len(serialized) <= weekly.PROMPT_BUDGET_CHARS

    # Everything the four questions consume must actually reach the model;
    # these are exactly the keys the old slice silently dropped, and they are
    # never omittable no matter how heavy the week.
    for key in ('bundle_evidence', 'decision_metrics', 'current_risk',
                'input_warnings'):
        assert key in payload
    # Machine-owned provenance blobs never belonged in the prompt.
    assert 'signal_provenance' not in serialized
    # Any budget-driven omission must be whole-section and declared; nothing
    # outside OMITTABLE_SECTIONS may ever disappear.
    omitted = {row['section'] for row in payload.get('_omitted', [])}
    assert omitted <= set(weekly.OMITTABLE_SECTIONS)
    for section in omitted:
        assert section not in payload


def test_oversized_bundle_omits_whole_sections_and_declares_them():
    bundle = _oversized_bundle()

    payload = weekly.build_prompt_payload(bundle, budget=8000)
    serialized = _compact(payload)

    assert json.loads(serialized) == payload
    assert len(serialized) <= 8000

    omitted = {row['section'] for row in payload.get('_omitted', [])}
    assert omitted, 'an oversized bundle must declare what was dropped'
    for section in omitted:
        assert section not in payload
    # Sections the questions cannot do without are never omittable.
    assert 'current_risk' in payload
    assert 'bundle_evidence' in payload


def test_snapshot_slimming_keeps_attribution_fields_only():
    snapshot = {
        'last_updated': '2026-08-24T00:00:00',
        'portfolios': {
            'us_stocks': {
                'total_current_value': 1000.0,
                'total_pnl': -10.0,
                'today_total_change': -5.0,
                'cash_usd': 100.0,
                'holdings': [{
                    'ticker': 'PLTU',
                    'name': 'PLTR 2X',
                    'current_value': 900.0,
                    'pnl_percent': 12.5,
                    'today_change_pct': -1.0,
                    'volume': 987654,
                    'trades': [{'side': 'buy'}],
                    'day_high': 11.0,
                }],
            },
            'hk_stocks': {
                'total_current_value': 7800.0,
                'cash_hkd': 780.0,
                'holdings': [],
            },
        },
        'gold_dca': {'lots': ['irrelevant to the review questions']},
    }

    slim = weekly._slim_snapshot(snapshot)

    us = slim['portfolios']['us_stocks']
    assert us['total_current_value'] == 1000.0
    assert us['cash'] == 100.0
    holding = us['holdings'][0]
    assert holding['ticker'] == 'PLTU'
    assert holding['pnl_percent'] == 12.5
    serialized = _compact(slim)
    for noise in ('volume', 'trades', 'day_high', 'gold_dca'):
        assert noise not in serialized
