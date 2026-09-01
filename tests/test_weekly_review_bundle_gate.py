"""Deterministic input sufficiency tests for the weekly review producer."""
from __future__ import annotations

import json
from datetime import date

import pytest

from clawock.automation import weekly_review as weekly


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


def test_week_nav_change_is_computed_not_asked_for(tmp_path, monkeypatch):
    """#1266: the prompt asked the model to subtract week-open from week-close.

    The subtraction is deterministic and nothing downstream re-checks the
    number the model typed, so the harness does it once and the prompt quotes
    it. FX differs across the two days on purpose: the HK leg must be converted
    at each day's own rate, which is exactly the step a model gets wrong.
    """
    monkeypatch.chdir(tmp_path)
    _stub_decisions(monkeypatch)
    _write_json(tmp_path / 'memory/2026-07-20-plan.json', _plan('2026-07-20', fx=7.80))
    _write_json(tmp_path / 'memory/2026-07-24-plan.json', _plan(
        '2026-07-24', fx=7.84, decisions=[{'action': 'hold'}]))
    _write_json(tmp_path / 'memory/snapshots/2026-07-20.json', _snapshot())
    end = _snapshot()
    end['portfolios']['us_stocks']['total_current_value'] = 900.0
    _write_json(tmp_path / 'memory/snapshots/2026-07-24.json', end)
    _write_json(tmp_path / 'assets/data/risk.json', {'combined': {'beta': 1.2}})

    evidence = weekly.validate_bundle(weekly.aggregate_week(today=date(2026, 7, 26)))
    change = evidence['nav_change']
    start, finish = evidence['nav_points'][0], evidence['nav_points'][-1]

    assert change['start_date'] == '2026-07-20' and change['end_date'] == '2026-07-24'
    assert change['change_usd'] == round(
        finish['total_nav_usd'] - start['total_nav_usd'], 2)
    # The US leg lost 100 USD of value; the HK leg only moved because its rate did.
    assert change['legs']['us_usd']['change'] == -100.0
    assert change['legs']['hk_hkd']['change'] == 0.0
    # NAV, not P&L — the label has to survive, a reader who takes it for P&L
    # mis-reads any week with a deposit in it.
    assert 'capital flows' in change['basis']

    prompt = weekly.build_user_prompt(weekly.build_prompt_payload(
        weekly.aggregate_week(today=date(2026, 7, 26))))
    assert 'nav_change' in prompt


def test_week_nav_change_is_none_rather_than_a_zero_week():
    assert weekly.week_nav_change([]) is None
    assert weekly.week_nav_change([{'date': 'x', 'total_nav_usd': 1.0}]) is None
    assert weekly.week_nav_change(
        [{'date': 'a', 'total_nav_usd': None}, {'date': 'b', 'total_nav_usd': 2.0}]
    ) is None


def test_weekly_nav_uses_boundary_and_nearest_fx_when_interior_fx_missing(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _stub_decisions(monkeypatch)
    _write_json(tmp_path / 'memory/2026-07-20-plan.json',
                _plan('2026-07-20', fx=7.80))
    _write_json(tmp_path / 'memory/2026-07-22-plan.json',
                _plan('2026-07-22', fx=None,
                      decisions=[{'action': 'hold'}]))
    _write_json(tmp_path / 'memory/2026-07-24-plan.json',
                _plan('2026-07-24', fx=7.84))
    for day in ('2026-07-20', '2026-07-22', '2026-07-24'):
        _write_json(tmp_path / f'memory/snapshots/{day}.json', _snapshot())
    _write_json(tmp_path / 'assets/data/risk.json',
                {'combined': {'beta': 1.2}})

    bundle = weekly.aggregate_week(today=date(2026, 7, 28))
    evidence = weekly.validate_bundle(bundle)

    assert [point['date'] for point in evidence['nav_points']] == [
        '2026-07-20', '2026-07-22', '2026-07-24',
    ]
    assert [point['fx_rate_usdhkd'] for point in evidence['nav_points']] == [
        7.80, 7.80, 7.84,
    ]


def test_weekly_nav_still_fails_when_no_valid_fx_exists(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _stub_decisions(monkeypatch)
    for day in ('2026-07-22', '2026-07-24'):
        _write_json(tmp_path / f'memory/{day}-plan.json',
                    _plan(day, fx=None, decisions=[{'action': 'hold'}]))
        _write_json(tmp_path / f'memory/snapshots/{day}.json', _snapshot())
    _write_json(tmp_path / 'assets/data/risk.json',
                {'combined': {'beta': 1.2}})

    bundle = weekly.aggregate_week(today=date(2026, 7, 28))

    with pytest.raises(RuntimeError, match='start/end NAV from two dated snapshots'):
        weekly.validate_bundle(bundle)


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
