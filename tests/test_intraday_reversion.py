"""Causal execution, costs and authority boundaries of the intraday research lane."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

from clawock.costs import CostModel
from clawock.decision.intraday_reversion import replay
from clawock.strategy_lab.lab import load_rows, mount, main
from clawock.strategy_lab.plugins.registered_costs import Costs
from clawock.strategies.plugins.intraday_reversion import Reversion

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def service():
    return Reversion(Costs(CostModel.load(ROOT / 'config/cost-model.json')), {})


@pytest.fixture
def packet():
    start = datetime.fromisoformat('2026-10-16T09:35:00-04:00')
    bars = []
    for i in range(78):
        price = 100 + (0.2 if i % 2 else -0.2)
        bars.append({'end': (start + timedelta(minutes=5*i)).isoformat(),
                     'open': price, 'high': price + 0.1, 'low': price - 0.1, 'close': price})
    bars[20].update(open=100, high=102.1, low=99.9, close=102)
    bars[21].update(open=102, high=102.2, low=99.9, close=100)
    return {'market': 'us', 'ticker': 'TEST', 'session': '2026-10-16',
            'research_allowed': True, 'forbid_reduce_advice': False,
            'shares': 10, 'base_shares': 100, 'lot_size': 1, 'bars': bars}


def test_net_round_trip_is_next_open_with_waiver_and_regulatory_fees(service, packet):
    original = deepcopy(packet)
    report = service.replay(packet)
    trade = report['trades'][0]
    assert trade['sell_price'] == 102
    assert trade['signal_at'] == packet['bars'][20]['end']
    assert trade['entry_bar_end'] == packet['bars'][21]['end']
    assert trade['sell_cost']['commission'] == 0
    assert trade['buy_cost']['commission'] == 0
    assert trade['net_pnl'] == pytest.approx(19.566)
    assert report['live_permission'] is False
    assert report['cost_model']['minimum_commission_applied'] is True
    assert original == packet


def test_gap_back_to_mean_cannot_fill_at_signal_close(service, packet):
    packet['bars'][21].update(open=100, high=100.2, low=99.9, close=100)
    assert service.replay(packet)['status'] == 'no_trade'


def test_both_touches_stop_first_and_gap_stop(service, packet):
    packet['bars'][21]['high'] = 105
    trade = service.replay(packet)['trades'][0]
    assert trade['exit_reason'] == 'stop'
    assert trade['buy_price'] == 104
    packet['bars'][21].update(high=102.2, low=101.9, close=102)
    packet['bars'][22].update(open=105, high=106, low=99, close=100)
    trade = service.replay(packet)['trades'][0]
    assert trade['exit_reason'] == 'gap_stop'
    assert trade['buy_price'] == 105
    assert trade['net_pnl'] < -30


def test_session_close_buyback_and_future_does_not_change_entry(service, packet):
    for bar in packet['bars'][21:]:
        bar.update(open=102, high=103, low=101, close=102)
    trade = service.replay(packet)['trades'][0]
    assert trade['exit_reason'] == 'session_close'
    assert trade['net_pnl'] < 0
    assert trade['sell_price'] == 102
    assert trade['target'] == 100


@pytest.mark.parametrize('field,value', [('research_allowed', False), ('forbid_reduce_advice', True), ('forbid_reduce_advice', None)])
def test_policy_refusal(service, packet, field, value):
    packet[field] = value
    report = service.replay(packet)
    assert report['status'] == 'refused'
    assert report['trades'] == []
    assert report['live_permission'] is False


def test_hk_taxes_and_no_obsolete_ccass_floor(service, packet):
    packet['market'] = 'hk'
    start = datetime.fromisoformat('2026-10-16T09:35:00+08:00')
    times = [start + timedelta(minutes=5*i) for i in range(30)]
    times += [datetime.fromisoformat('2026-10-16T13:05:00+08:00') + timedelta(minutes=5*i) for i in range(36)]
    packet['bars'] = packet['bars'][:66]
    for bar, stamp in zip(packet['bars'], times):
        bar['end'] = stamp.isoformat()
    assert service.replay(packet)['trades'][0]['sell_cost']['regulatory']['ccass'] == 0.04
    packet.update(shares=100, base_shares=1000)
    trade = service.replay(packet)['trades'][0]
    assert trade['sell_cost']['commission'] == 0
    assert trade['buy_cost']['commission'] == 0
    assert trade['net_pnl'] == pytest.approx(164.29)


@pytest.mark.parametrize('damage', ['gap', 'duplicate', 'short', 'wrong_date', 'nan', 'bool', 'ohlc'])
def test_invalid_inputs_never_trade(service, packet, damage):
    if damage == 'gap':
        packet['bars'].pop(30)
    elif damage == 'duplicate':
        packet['bars'][30] = packet['bars'][29]
    elif damage == 'short':
        packet['bars'].pop()
    elif damage == 'wrong_date':
        packet['session'] = '2026-10-15'
    else:
        packet['bars'][30]['high'] = {'nan': float('nan'), 'bool': True, 'ohlc': 1}[damage]
    try:
        result = service.replay(packet)
    except ValueError:
        return
    assert result['status'] == 'refused'
    assert result['trades'] == []


def test_size_gate(service, packet):
    packet['shares'] = 11
    assert service.replay(packet)['reason'] == 'lot_or_base_fraction'
    packet.update(shares=10, lot_size=3)
    assert service.replay(packet)['reason'] == 'lot_or_base_fraction'


def test_composition_facade_and_cli(packet, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr('clawock.costs.CONFIG', ROOT / 'config/cost-model.json')
    config = ROOT / 'config/strategy-plugins.json'
    doc = json.loads(config.read_text())
    assert not any(r['id'] == 'intraday-reversion' for r in doc['live'])
    kernel = mount(load_rows(config))
    try:
        assert replay(kernel, packet)['status'] == 'replayed'
        assert 'intraday-reversion' not in kernel.get('strategies').names()
    finally:
        kernel.dispose()
    source = tmp_path / 'session.json'
    source.write_text(json.dumps(packet))
    assert main(['--config', str(config), 'intraday-replay', str(source)]) == 0
    assert json.loads(capsys.readouterr().out)['live_permission'] is False


def test_facade_obeys_replaced_service(packet):
    class Kernel:
        def get(self, name):
            assert name == 'intraday_reversion'
            return self

        def replay(self, value):
            assert value is packet
            return 'replacement'
    assert replay(Kernel(), packet) == 'replacement'


@pytest.mark.parametrize('config', [{'window': True}, {'window': 1}, {'deviations': float('inf')}, {'cost_multiple': 0.5}, {'max_base_fraction': 2}, {'live_permission': True}])
def test_bad_config(service, config):
    with pytest.raises(ValueError):
        Reversion(service.costs, config)


def test_cost_multiple_blocks_tiny_ticket_with_explicit_minimum(service, packet):
    packet.update(market='hk', shares=1, base_shares=100)
    # US timestamps are invalid HK input, so use the original US session to
    # isolate the cost gate with an explicit high-cost model instead.
    packet['market'] = 'us'
    from dataclasses import replace
    model = replace(service.costs.model, account_commission={},
                    assumed_minimum_commission={'us': 2})
    assert Reversion(Costs(model), {}).replay(packet)['status'] == 'no_trade'
