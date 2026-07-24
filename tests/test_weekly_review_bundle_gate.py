"""Deterministic input sufficiency tests for the weekly review producer."""
from __future__ import annotations

import json
from datetime import date

import pytest

from scripts.data import gh_action_weekly_review as weekly


def _plan(day, fx=7.8, decisions=None):
    return {
        'date': day,
        'fx_rate_usdhkd': fx,
        'decisions': [] if decisions is None else decisions,
    }


def _snapshot():
    return {
        'portfolios': {
            'us_stocks': {
                'total_current_value': 1000.0,
                'cash_usd': 100.0,
            },
            'hk_stocks': {
                'total_current_value': 7800.0,
                'cash_hkd': 780.0,
            },
        },
    }


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def _stub_decisions(monkeypatch):
    monkeypatch.setattr(weekly.decision_v2, 'load_decisions', lambda: [])
    monkeypatch.setattr(
        weekly.decision_v2, 'episode_representatives',
        lambda _decisions, _horizon: [])
    monkeypatch.setattr(
        weekly.decision_v2, 'compute_metrics',
        lambda _decisions: {'total': 0})


def test_real_committed_weekly_bundle_passes():
    bundle = weekly.aggregate_week(today=date(2026, 7, 24))

    evidence = weekly.validate_bundle(bundle)

    assert evidence['plan_days'] >= 1
    assert len(evidence['nav_points']) >= 2
    serialized = json.dumps(bundle, ensure_ascii=False)
    assert serialized.index('"bundle_evidence"') < serialized.index('"snapshots"')


def test_weekly_bundle_with_valid_minimum_inputs_passes(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _stub_decisions(monkeypatch)
    _write_json(tmp_path / 'memory/2026-07-20-plan.json',
                _plan('2026-07-20', decisions=[{'action': 'hold'}]))
    _write_json(tmp_path / 'memory/2026-07-24-plan.json',
                _plan('2026-07-24'))
    _write_json(tmp_path / 'memory/snapshots/2026-07-20.json', _snapshot())
    _write_json(tmp_path / 'memory/snapshots/2026-07-24.json', _snapshot())
    _write_json(tmp_path / 'assets/data/risk.json', {'combined': {'beta': 1.2}})

    bundle = weekly.aggregate_week(today=date(2026, 7, 26))
    evidence = weekly.validate_bundle(bundle)

    assert evidence['plan_days'] == 2
    assert evidence['plan_decisions'] == 1
    assert [point['date'] for point in evidence['nav_points']] == [
        '2026-07-20', '2026-07-24',
    ]


def test_weekly_malformed_snapshot_names_missing_nav_before_llm(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _stub_decisions(monkeypatch)
    _write_json(tmp_path / 'memory/2026-07-20-plan.json',
                _plan('2026-07-20', decisions=[{'action': 'hold'}]))
    _write_json(tmp_path / 'memory/2026-07-24-plan.json',
                _plan('2026-07-24'))
    _write_json(tmp_path / 'memory/snapshots/2026-07-20.json', _snapshot())
    malformed = tmp_path / 'memory/snapshots/2026-07-24.json'
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_text('{', encoding='utf-8')
    _write_json(tmp_path / 'assets/data/risk.json', {'combined': {'beta': 1.2}})
    bundle = weekly.aggregate_week(today=date(2026, 7, 26))
    monkeypatch.setattr(weekly, 'aggregate_week', lambda: bundle)
    monkeypatch.setattr(
        weekly, 'chat',
        lambda **kwargs: pytest.fail('thin bundle must not call the LLM'))

    with pytest.raises(RuntimeError) as exc_info:
        weekly.main()

    message = str(exc_info.value)
    assert 'start/end NAV from two dated snapshots' in message
    assert 'memory/snapshots/2026-07-24.json' in message
