"""Pre-breakout proposals stay sized, falsifiable and settle on canonical OHLC."""
import copy
import json
from pathlib import Path

import pytest

from clawock.decision import entry, ledger, packet, preposition
from clawock.harness.brief_preflight import proposal_universe

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / 'config/preposition-policy.json').read_text())


def context():
    return {
        'date': '2026-07-21', 'generation_id': 'experiment-test',
        'portfolio': {'portfolios': {'us_stocks': {'cash_usd': 10000, 'holdings': [
            {'ticker': 'SPCH', 'shares': 100, 'cost_basis': 100, 'current_price': 95,
             'current_value': 9500}]}}},
        'preposition_policy': POLICY,
        'preposition_inputs': {'SPCH': {'status': 'fresh', 'row_as_of': '2026-07-20',
                                      'close': 95, 'atr14_pct': 3, 'prior_20d_high': 110}},
        'open_decisions': {'open_add_tickers': []},
    }


def decision(p):
    row = p['tickers']['SPCH']
    setup = next(s for s in row['technical']['setups'] if s['setup_id'] == preposition.SETUP_ID)
    return ledger.legacy_action_to_decision({
        'ticker': 'SPCH', 'leg': 'US', 'strategy_id': 'core_position',
        'action': 'add_only_on_trigger', 'driven_by': 'technical', 'confidence': .4,
        'condition': {'type': 'price_below', 'price': setup['entry_price'], 'valid_for_sessions': 1},
        'size': {'shares': row['execution']['max_add_shares']},
        'technical_setup_id': setup['setup_id'], 'technical_campaign_id': setup['campaign_id'],
        'tranche_number': setup['next_tranche_number'], 'invalidation_price': setup['invalidation_price'],
        'hypothesis': 'Weakness can recover; crossing invalidation refutes this entry.',
        'method': 'User-authorized prospective preposition; no established timing edge.',
    }, p['date'])


def test_unknown_thesis_leveraged_entry_is_sized_and_settles(monkeypatch):
    p = packet.compile_packet(context())
    d = decision(p)
    assert d['size']['shares'] == 10
    assert d['invalidation_price'] >= 82
    ledger.assign_episode_ids([d])
    assert not ledger.validate_decision(d)
    assert not packet.validate_plan_constraints({'decisions': [d]}, p)
    days = ['2026-07-21', '2026-07-22', '2026-07-23', '2026-07-24', '2026-07-27', '2026-07-28']
    bars = {day: {'open': 94, 'high': 99+i, 'low': 93, 'close': 96+i} for i, day in enumerate(days)}
    monkeypatch.setattr(ledger, 'load_ticker_bars', lambda ticker: bars)
    monkeypatch.setattr(ledger, 'leg_sessions', lambda leg: days)
    monkeypatch.setattr(ledger, 'is_session', lambda leg, day: day in days)
    ledger.settle_decisions([d], now_date='2026-07-29')
    assert d['evaluation']['benefit_t1_pct'] is not None
    assert d['evaluation']['benefit_t5_pct'] is not None


@pytest.mark.parametrize('mutation', ['stop', 'size', 'duplicate', 'setup', 'hypothesis'])
def test_experiment_cannot_bypass_its_terms(mutation):
    p = packet.compile_packet(context())
    d = decision(p)
    plan = {'decisions': [d]}
    if mutation == 'stop': d['invalidation_price'] = 10
    if mutation == 'size': d['size']['shares'] = 100
    if mutation == 'duplicate': plan['decisions'].append(copy.deepcopy(d))
    if mutation == 'setup': d['technical_setup_id'] = None
    if mutation == 'hypothesis': d['hypothesis'] = None
    assert packet.validate_plan_constraints(plan, p)


def test_exhaustion_stale_bars_damaged_thesis_and_open_order():
    c = context()
    s = packet.compile_packet(c)['tickers']['SPCH']['technical']['setups'][-1]
    c['technical_setup_usage'] = {'SPCH': {s['campaign_id']: 2}}
    assert not packet.compile_packet(c)['tickers']['SPCH']['execution']['preposition_authorized']
    c = context()
    c['preposition_inputs']['SPCH']['status'] = 'stale'
    assert not packet.compile_packet(c)['tickers']['SPCH']['execution']['preposition_authorized']
    c = context()
    c['thesis_registry'] = {'theses': {'SPCH': {'state': 'damaged'}}}
    assert not packet.compile_packet(c)['tickers']['SPCH']['execution']['preposition_authorized']
    c = context()
    c['open_decisions']['open_add_tickers'] = ['SPCH']
    p = packet.compile_packet(c)
    assert 'add_only_on_trigger' not in p['tickers']['SPCH']['constraints']['open_actions']


@pytest.mark.parametrize('kind', ['hard_stop', 'regime'])
def test_retained_risk_obligations_block_the_experiment(kind):
    c = context()
    risk = {'ticker': 'SPCH', 'type': 'regime_delever', 'required_reduction': {
        'kind': 'full_leveraged_position', 'minimum_shares': 100, 'target_tickers': ['SPCH']}}
    c['risk_guardrail'] = {'hard_stop_watch' if kind == 'hard_stop' else 'breaches': [risk]}
    p = packet.compile_packet(c)
    assert 'add_only_on_trigger' not in p['tickers']['SPCH']['constraints']['open_actions']
    assert packet.validate_plan_constraints({'decisions': [decision(p)]}, p)


def test_positive_information_can_enter_without_a_dip_and_negative_cannot():
    row = context()['preposition_inputs']['SPCH'] | {'prior_20d_high': 96}
    args = dict(ticker='SPCH', leg='US', usage={}, leveraged=True, cost_basis=100)
    assert preposition.setup(row, {}, POLICY, **args) is None
    assert preposition.setup(row, {'usable_for_decisions': True, 'sizing_tilt': 'positive'}, POLICY, **args)
    assert preposition.setup(row | {'prior_20d_high': 110},
                             {'usable_for_decisions': True, 'sizing_tilt': 'negative'}, POLICY, **args) is None


def test_entry_gate_to_discovery_proposal_end_to_end(tmp_path):
    gates = tmp_path / 'memory/entry-gates'
    gates.mkdir(parents=True)
    doc = json.loads((ROOT / 'tests/fixtures/entry-gates/ustest-2026-07-20.json').read_text())
    ticker = doc['ticker']
    (gates / 'gate.json').write_text(json.dumps(doc))
    bars = tmp_path / 'memory/bars'
    bars.mkdir()
    (bars / f'{ticker}.json').write_text(json.dumps({'ticker': ticker, 'leg': 'US',
        'bars': {'2026-07-20': {'close': 100}}}))
    c = context()
    c['proposal_universe'] = proposal_universe({}, bars_dir=bars, today=c['date'])
    c['stock_discovery'] = {'candidates': [{'ticker': ticker}, {'ticker': 'MISSING'}]}
    p = packet.compile_packet(c)
    row = p['proposal_universe'][ticker]
    assert row['constraints']['authorization'] == 'entry_gate_cleared'
    d = ledger.legacy_action_to_decision({'ticker': ticker, 'strategy_id': 'core_position',
        'action': 'add_only_on_trigger', 'condition': {'type': 'price_below', 'price': 100},
        'size': {'shares': 1}, 'confidence': .4, 'driven_by': 'technical',
        'hypothesis': 'Falsifiable research thesis', 'invalidation_price': 90}, c['date'])
    ledger.assign_episode_ids([d])
    assert not ledger.validate_decision(d)
    assert not packet.validate_plan_constraints({'decisions': [d]}, p)
    assert p['stock_discovery']['candidates'][1]['proposal_availability']['status'] == 'unavailable'
    assert not entry.proposal_authorizations(tmp_path, today='2026-08-01')[ticker]['cleared']
    doc['assessed_at'] = '2026-07-21T08:00:00+00:00'
    doc['checks'][0]['verdict'] = 'unknown'
    (gates / 'newer.json').write_text(json.dumps(doc))
    assert not entry.proposal_authorizations(tmp_path, today='2026-07-21')[ticker]['cleared']


def test_own_archive_freshness_and_positive_overlay_size(tmp_path):
    from datetime import datetime, timezone, timedelta
    bars = tmp_path / 'memory/bars'
    bars.mkdir(parents=True)
    end = datetime(2026, 7, 20, tzinfo=timezone.utc)
    rows = {(end - timedelta(days=i)).date().isoformat():
            {'open': 94, 'high': 100, 'low': 92, 'close': 95} for i in range(35)}
    (bars / 'SPCH.json').write_text(json.dumps({'bars': rows}))
    at = datetime(2026, 7, 21, 0, tzinfo=timezone.utc)
    result = preposition.measurements(tmp_path, context()['portfolio'], at=at)
    assert result['SPCH']['status'] == 'fresh'
    result = preposition.measurements(tmp_path, context()['portfolio'],
                                     at=datetime(2026, 7, 23, 0, tzinfo=timezone.utc))
    assert result['SPCH']['status'] == 'unavailable'
    c = context()
    p = packet.compile_packet(c)
    row = p['tickers']['SPCH']
    sized = packet._execution_view(c['portfolio']['portfolios']['us_stocks']['holdings'][0],
        'US', 9500, 10000, row['technical'], row['thesis'], True,
        authority_tier=preposition.TIER, overlay={'sizing_multiplier': 1.2})
    assert sized['max_add_shares'] == 12


def test_corrupt_latest_bar_is_not_silently_replaced_by_an_older_signal(tmp_path):
    from datetime import datetime, timezone, timedelta
    bars = tmp_path / 'memory/bars'
    bars.mkdir(parents=True)
    end = datetime(2026, 7, 20, tzinfo=timezone.utc)
    rows = {(end - timedelta(days=i)).date().isoformat():
            {'open': 94, 'high': 100, 'low': 92, 'close': 95} for i in range(35)}
    rows['2026-07-20']['close'] = None
    (bars / 'SPCH.json').write_text(json.dumps({'bars': rows}))
    result = preposition.measurements(tmp_path, context()['portfolio'],
                                     at=datetime(2026, 7, 21, 0, tzinfo=timezone.utc))
    assert result['SPCH']['reason'] == 'suspect_own_instrument_bars'
