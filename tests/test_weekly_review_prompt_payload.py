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
    # these are exactly the keys the old slice silently dropped. On real data
    # dropping `plans` alone clears the budget, so decision_metrics survives —
    # it is LAST in the sacrifice order (#991), not exempt from it.
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


def test_what_gets_dropped_is_decided_by_purpose_not_by_byte_count():
    """#991: the drop used to take the largest section first. On 2026-W30 data
    that takes plans (83,809 chars) and then decision_metrics (32,380) ahead of
    snapshots (19,368) — question 2's distilled per-strategy win/loss sacrificed
    to keep the raw daily book composition, purely on byte count. The order is
    OMITTABLE_SECTIONS', so plans goes first even when it is the smallest of the
    three, and decision_metrics only after snapshots was not enough."""
    # Book composition survives _slim_snapshot, so the bulk has to live in the
    # holdings the projection keeps — a `note` blob would be slimmed away and
    # leave nothing to drop.
    holdings = [{'ticker': f'T{i:02d}', 'name': 'n' * 60, 'current_value': 1.0,
                 'pnl_percent': 1.0, 'today_change_pct': 1.0} for i in range(30)]
    bundle = {
        'week': '2026-W40',
        'window': '2026-10-05 -> 2026-10-12',
        'bundle_evidence': {'plan_days': 5, 'nav_points': []},
        # plans is deliberately the SMALLEST omittable section: under the old
        # largest-first rule it would have survived while the other two went.
        'plans': [{'date': '2026-10-05', 'data': {'decisions': [], 'n': 'p' * 500}}],
        'decision_episodes': [],
        'decision_metrics': {'per_strategy': {f's{i}': 'y' * 3000 for i in range(4)}},
        'snapshots': [{'portfolios': {'us_stocks': {'holdings': holdings}}}
                      for _ in range(6)],
        'current_risk': {'combined': {'beta': 1.1}},
        'input_warnings': [],
    }

    payload = weekly.build_prompt_payload(bundle, budget=20_000)

    dropped = [row['section'] for row in payload['_omitted']]
    assert dropped == ['plans', 'snapshots'], dropped
    assert 'decision_metrics' in payload, (
        'question 2 lost its distilled input to a byte-count decision')
    for key in ('bundle_evidence', 'decision_episodes', 'current_risk',
                'input_warnings'):
        assert key in payload
    assert len(_compact(payload)) <= 20_000


def test_decision_metrics_is_the_last_thing_sacrificed_not_the_first():
    """When even plans + snapshots is not enough, decision_metrics may still go
    — the budget has to stay enforceable — but only at the end of the order."""
    bundle = {
        'week': '2026-W41',
        'window': '2026-10-12 -> 2026-10-19',
        'bundle_evidence': {'plan_days': 5, 'nav_points': []},
        'plans': [{'date': '2026-10-12', 'data': {'decisions': [], 'n': 'p' * 500}}],
        'decision_episodes': [],
        'decision_metrics': {'per_strategy': {f's{i}': 'y' * 3000 for i in range(4)}},
        'snapshots': [{'portfolios': {}, 'note': 'z' * 3000} for _ in range(6)],
        'current_risk': {'combined': {'beta': 1.1}},
        'input_warnings': [],
    }

    payload = weekly.build_prompt_payload(bundle, budget=2_000)

    assert [row['section'] for row in payload['_omitted']] == [
        'plans', 'snapshots', 'decision_metrics']
    assert weekly.OMITTABLE_SECTIONS == ('plans', 'snapshots', 'decision_metrics')
    # The never-dropped set survives even at a budget nothing else fits in.
    for key in ('bundle_evidence', 'decision_episodes', 'current_risk',
                'input_warnings'):
        assert key in payload
