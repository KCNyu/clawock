import json

import pytest

from clawock.decision import ledger
from clawock.decision.book import pnl_totals, validate_plan_book
from clawock.harness import brief_card, brief_postflight


def _plan():
    return {
        'date': '2026-09-30', 'schema_version': 2, 'fx_rate_usdhkd': 7.846,
        'book': {'hk_leg_hkd': -50801.64, 'us_leg_usd': -999.56,
                 'usd_total_pnl': -999.56, 'hkd_total_pnl': -50801.64},
        'decisions': [],
    }


def test_raw_plan_rejects_missing_leg_in_total_and_nonsense_amounts():
    plan = _plan()
    errors = ledger.validate_plan(plan)
    assert any('book totals mismatch: usd_total_pnl' in e for e in errors)
    plan['book'].update(usd_total_pnl=999999, hk_leg_hkd=0, us_leg_usd=0)
    assert validate_plan_book(plan)


def test_normalization_repairs_only_totals_and_is_idempotent(tmp_path):
    plan = _plan()
    result = ledger.normalize_authored_plan(plan, tmp_path / 'absent-ledger.jsonl')
    assert result['book']['usd_total_pnl'] == -7474.41
    assert result['book']['hkd_total_pnl'] == -58644.19
    assert result['book']['hk_leg_hkd'] == -50801.64
    assert plan['book']['usd_total_pnl'] == -999.56  # caller's input unchanged
    assert not validate_plan_book(result)
    assert ledger.normalize_authored_plan(result, tmp_path / 'absent-ledger.jsonl') == result


@pytest.mark.parametrize('rate', [None, 0, -1, True, float('nan'), float('inf'), '7.846'])
def test_invalid_exchange_rate_is_not_normalized_or_printed(rate):
    plan = _plan()
    plan['fx_rate_usdhkd'] = rate
    assert validate_plan_book(plan)[0].startswith('book inputs invalid')
    with pytest.raises(ValueError):
        pnl_totals(-50801.64, -999.56, rate)
    assert not brief_postflight._normalization_owned_plan_error('book inputs invalid')
    assert brief_postflight.categorize(['plan.json authored: book inputs invalid']) == 'fail'


def test_historical_fallback_recomputes_total_without_rewriting_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_card, 'WS', tmp_path)
    path = tmp_path / 'memory' / '2026-09-30-plan.json'
    path.parent.mkdir()
    path.write_text(json.dumps(_plan()))
    before = path.read_bytes()
    card = brief_card.build_brief_card('2026-09-30', decision_packet={})
    assert 'Book: USD$-7474.41' in card
    assert 'HK leg -50801.64HKD' in card
    assert path.read_bytes() == before
    plan = _plan()
    plan['fx_rate_usdhkd'] = 0
    path.write_text(json.dumps(plan))
    card = brief_card.build_brief_card('2026-09-30', decision_packet={})
    assert '金额未核验' in card and 'USD$-999.56' not in card


def test_postflight_recognizes_only_derived_totals_as_owned_errors():
    assert brief_postflight._normalization_owned_plan_error('book totals mismatch: usd_total_pnl must equal -7474.41')
    assert not brief_postflight._normalization_owned_plan_error('book inputs invalid: finite legs required')


def test_postflight_binds_book_to_generation_inputs(tmp_path):
    plan = _plan()
    plan['decisions'] = [{
        'ticker': 'AAA', 'strategy_id': 'risk_rebalance', 'action': 'cut',
        'condition': {'type': 'manual', 'price': None, 'description': 'risk rule'},
        'size': {'shares': 1, 'pct': None, 'note': ''},
        'confidence': .8, 'driven_by': 'risk_rule', 'regime': 'neutral',
        'rationale': 'reduce exposure',
    }]
    plan['book'].update(pnl_totals(-50801.64, -999.56, 7.846))
    plan['book']['hk_leg_hkd'] = 123
    path = tmp_path / '2026-09-30-plan.json'
    path.write_text(json.dumps(plan))
    errors = brief_postflight.normalize_plan_json(path, tmp_path / 'absent-ledger.jsonl',
        context={'book_totals': {'hk_pnl_hkd': -50801.64, 'us_pnl_usd': -999.56, 'fx_used': 7.846}})
    assert not errors
    normalized = json.loads(path.read_text())
    assert normalized['book']['usd_total_pnl'] == -7474.41
    assert not ledger.validate_plan(normalized, path)


def test_stored_history_exception_is_exact_and_cannot_hide_other_errors(tmp_path):
    from ops.ci.check_plan_schema import book_digest, validate_stored_plan
    plan = ledger.normalize_authored_plan(_plan(), tmp_path / 'empty-ledger.jsonl')
    # This test uses the independent author fixture to produce valid decisions.
    plan['decisions'] = ledger.normalize_authored_plan({**plan, 'decisions': [{
        'ticker': 'AAA', 'strategy_id': 'risk_rebalance', 'action': 'cut',
        'condition': {'type': 'manual', 'description': 'risk rule'},
        'size': {'shares': 1}, 'confidence': .8, 'driven_by': 'risk_rule',
        'regime': 'neutral', 'rationale': 'reduce exposure',
    }]}, tmp_path / 'empty-ledger.jsonl')['decisions']
    plan['book']['usd_total_pnl'] = -999.56
    name = '2026-09-30-plan.json'
    legacy = {name: book_digest(plan)}
    errors, retained = validate_stored_plan(plan, name, legacy)
    assert not errors and retained
    assert ledger.validate_plan(plan, name)  # Author gate remains strict.
    plan['book']['usd_total_pnl'] = 123
    assert validate_stored_plan(plan, name, legacy)[0]
    plan['book']['usd_total_pnl'] = -999.56
    assert validate_stored_plan(plan, '2026-10-01-plan.json', legacy)[0]
    plan['decisions'][0]['action'] = 'invalid-action'
    assert validate_stored_plan(plan, name, legacy)[0]
