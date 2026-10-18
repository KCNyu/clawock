"""Synthetic causal checks, explicitly not empirical performance validation."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from clawock.costs import CostModel
from clawock.harness.intraday_research import snapshot, render
from clawock.sessions import is_trading_day
from clawock.strategy_lab.intraday_study import manifest, packets, path_metrics, run
from clawock.strategy_lab.lab import load_rows, mount
from clawock.strategies.plugins.intraday_reversion import Reversion
from clawock.strategies.plugins.intraday_vwap import VWAP
from clawock.strategies.plugins.intraday_breakout import Breakout
from clawock.strategy_lab.plugins.registered_costs import Costs

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def plan():
    return json.loads((ROOT/'config/intraday-research-manifest.json').read_text())


def session(day='2026-10-16'):
    start = datetime.fromisoformat(day+'T09:35:00-04:00')
    return {'market': 'us', 'ticker': 'SPY', 'session': day,
            'research_allowed': True, 'forbid_reduce_advice': False,
            'shares': 1, 'base_shares': 10, 'lot_size': 1,
            'execution': {'delay_bars': 0, 'participation': .01, 'cash_reserve': 2000},
            'bars': [{'end': (start+timedelta(minutes=5*i)).isoformat(),
                      'open': 100., 'high': 100.2, 'low': 99.8, 'close': 100.+(i%2)*.1,
                      'volume': 10000.} for i in range(78)]}


@pytest.fixture
def data(plan):
    rows = []
    day = date.fromisoformat(plan['start'])
    while day <= date.fromisoformat(plan['end']):
        if is_trading_day('us', day):
            rows.append(session(day.isoformat()))
        day += timedelta(days=1)
    return {'source': {'provider': 'synthetic unit fixture', 'url': 'test://fixture',
                      'research_use': True, 'derived_public_use': True, 'license_evidence': 'owned test fixture',
                      'retrieved_at': '2026-10-18T00:00:00+00:00', 'raw_sha256': 'fixture',
                      'price_basis': 'unadjusted', 'interval_minutes': 5, 'synthetic': True}, 'sessions': rows}


def test_manifest_gates(plan):
    assert manifest(plan) == plan
    for change in ({'live_permission': True}, {'train_sessions': 59}, {'unknown': 1},
                   {'max_participation': .1}, {'shares': True}, {'usd_hkd': float('nan')},
                   {'presentation_focus': 'buy now'}):
        with pytest.raises(ValueError):
            manifest({**plan, **change})


def test_provenance_and_missing_denominator(plan, data):
    data['source']['research_use'] = False
    with pytest.raises(ValueError, match='entitlement'):
        packets(data, plan)
    data['source']['research_use'] = True
    dropped = data['sessions'].pop(3)['session']
    days, rows = packets(data, plan)
    assert dropped in days and dropped not in rows
    data['sessions'].append(data['sessions'][0])
    with pytest.raises(ValueError, match='duplicate'):
        packets(data, plan)


def test_signal_causality_and_distinct_mechanisms():
    costs = Costs(CostModel.load(ROOT/'config/cost-model.json'))
    packet = session()
    bars = packet['bars']
    bars[20].update(close=103., high=104.)
    for cls in (Reversion, VWAP):
        service = cls(costs, {})
        target = service.target(bars, 20)
        assert target is not None
        changed = deepcopy(bars)
        changed[21].update(close=1000., volume=1e12)
        assert service.target(changed, 20) == target
    bars[20].update(close=98., low=97.)
    breakout = Breakout(costs, {})
    target = breakout.target(bars, 20)
    assert target < 98
    assert breakout.entry_valid(bars, 20, 98, target)
    assert not breakout.entry_valid(bars, 20, 104, target)
    assert not breakout.entry_valid(bars, 20, target-1, target)
    assert Reversion(costs, {}).target(bars, 20) is None


def test_failed_fill_is_not_a_skipped_winner():
    service = Reversion(Costs(CostModel.load(ROOT/'config/cost-model.json')), {})
    packet = session()
    packet['bars'][20].update(close=103., high=104.)
    packet['bars'][21].update(open=103., high=104., volume=0.)
    result = service.replay(packet)
    assert result['status'] == 'unresolved' and result['net_pnl'] is None
    packet['forbid_reduce_advice'] = True
    assert service.replay(packet)['status'] == 'refused'


def test_waiver_exhaustion_invalidates_full_net(plan):
    plan['monthly_opening_used_hkd'] = 499999
    result = {'status': 'replayed', 'net_pnl': 1, 'trades': [{'shares': 1,
              'sell_price': 100., 'buy_price': 98., 'sell_cost': {'total': .5}, 'buy_cost': {'total': .5}}]}
    row = path_metrics([('2026-10-16', result)], plan, 1000)
    assert not row['complete'] and row['net_increment'] is None
    assert 'commission_allowance_exhausted_unknown_tariff' in row['reasons']
    assert row['curve'][0]['cumulative_net'] is None


def test_full_fold_and_llm_binding(plan, data, monkeypatch):
    monkeypatch.setattr('clawock.costs.CONFIG', ROOT/'config/cost-model.json')
    kernel = mount(load_rows(ROOT/'config/strategy-plugins.json'))
    # Isolate orchestration from 15 full intraday scans per date; execution has
    # its own OHLC tests above and in test_intraday_reversion.
    def replay(self, packet):
        return {'status': 'no_trade', 'trades': [], 'net_pnl': 0., 'reason': 'fixture'}
    monkeypatch.setattr(Reversion, 'replay', replay)
    try:
        report = run(kernel, plan, data)
        assert report['validation'] == 'synthetic_test_only'
        assert report['live_permission'] is False
        assert report['oos_sessions'] >= 60
        assert all(f['train'][1] < f['test'][0] for f in report['folds'])
        assert 'llm' not in report['metrics'] and report['llm_errors']
        mutated = deepcopy(data)
        mutated['sessions'][-1]['bars'][-1]['close'] += .01
        assert run(kernel, plan, mutated)['requests'][0]['sha256'] == report['requests'][0]['sha256']
        mutated['sessions'][0]['bars'][0]['close'] += .01
        assert run(kernel, plan, mutated)['requests'][0]['sha256'] != report['requests'][0]['sha256']
        choices = {r['test_first']: {'request_sha256': r['sha256'], 'candidate': -1,
                   'author_model': 'test fixture', 'mechanism': 'hold', 'counterexample': 'trend',
                   'focus': 'validation'} for r in report['requests']}
        report = run(kernel, plan, data, choices)
        assert report['metrics']['llm']['net_increment'] == 0
        assert not report['llm_errors']
        choices[next(iter(choices))]['request_sha256'] = 'tampered'
        assert 'llm' not in run(kernel, plan, data, choices)['metrics']
    finally:
        kernel.dispose()


def test_card_fail_closed_and_research_label(tmp_path):
    (tmp_path/'config').mkdir()
    target = tmp_path/'config/intraday-research-status.json'
    report = json.loads((ROOT/'config/intraday-research-status.json').read_text())
    report.update(validation='blocked_data_rights')
    report['source'].update(research_use=False, derived_public_use=False)
    target.write_text(json.dumps(report))
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    ctx = snapshot(tmp_path, 'us', now=now)
    text = render(ctx)
    assert '非实盘指令' in text and '数据研究权限未核实' in text
    assert not ctx['metrics'] and '不是实时信号' in text
    assert snapshot(tmp_path, 'hk', now=now)['validation'] == 'missing'
    report['live_permission'] = True
    target.write_text(json.dumps(report))
    assert snapshot(tmp_path, 'us', now=now)['validation'] == 'invalid'


def test_public_card_uses_net_and_preserves_losses(tmp_path):
    (tmp_path/'config').mkdir()
    report = json.loads((ROOT/'config/intraday-research-status.json').read_text())
    report.update(validation='insufficient_or_failed', as_of='2026-10-16',
                  metrics={'base': {'net_increment': -5, 'max_session_close_drawdown': 7, 'costs': 4, 'trades': 2}})
    report['source'].update(research_use=True, derived_public_use=True)
    (tmp_path/'config/intraday-research-status.json').write_text(json.dumps(report))
    text = render(snapshot(tmp_path, 'us', now=datetime(2026, 10, 20, tzinfo=timezone.utc)))
    assert '净增量 -5.00 USD' in text and '回撤 7.00' in text
    assert '成本 4.00' in text and '样本或净验证未通过' in text


def test_adjusted_real_sample_refuses_without_inventing_metrics(plan, data, monkeypatch):
    monkeypatch.setattr('clawock.costs.CONFIG', ROOT/'config/cost-model.json')
    data['source'].update(price_basis='split_adjusted', synthetic=False)
    data['sessions'] = data['sessions'][:10]
    kernel = mount(load_rows(ROOT/'config/strategy-plugins.json'))
    try:
        report = run(kernel, plan, data)
        assert report['observed_sessions'] == 10
        assert report['oos_sessions'] == 0 and report['metrics'] == {}
        assert report['validation'] == 'insufficient_or_failed'
        assert len(report['blockers']) == 2
    finally:
        kernel.dispose()


def test_model_cli_exposes_only_next_unanswered_fold(tmp_path, monkeypatch, capsys):
    from clawock.strategy_lab.lab import main
    monkeypatch.setattr('clawock.costs.CONFIG', ROOT/'config/cost-model.json')
    fake = {'requests': [{'test_first': '2026-07-01'}, {'test_first': '2026-08-01'}],
            'llm_errors': [{'test_first': '2026-07-01'}, {'test_first': '2026-08-01'}]}
    monkeypatch.setattr('clawock.strategy_lab.intraday_study.run', lambda *a: fake)
    path = tmp_path/'input.json'
    path.write_text('{}')
    assert main(['--config', str(ROOT/'config/strategy-plugins.json'), 'intraday-study',
                 str(path), str(path), '--requests-only']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['request']['test_first'] == '2026-07-01'
    assert '2026-08-01' not in json.dumps(output)
