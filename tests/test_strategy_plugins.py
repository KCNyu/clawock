"""Strategy plugins: the kernel's composition rules and the optimiser's gate."""
from __future__ import annotations

import json
import random
import types
from pathlib import Path

import pytest

from clawock.decision import signals
from clawock.costs import CostModel
from clawock.plugin_host import live
from clawock.strategies import registry
from clawock.strategies.plugins import quant_factors, rsi
from clawock.strategy_lab import lab, ledger
from clawock.plugin_host.kernel import ACTIVE, PENDING, Kernel, KernelError
from clawock.strategy_lab.plugins import (
    adjusted_bars, ledger_bars, registered_costs, walkforward)

ROOT = Path(__file__).resolve().parents[1]


def plugin(name, apply, inject=()):
    return types.SimpleNamespace(name=name, inject=inject, apply=apply)


def provider(service, value):
    return plugin(f'{service}-provider', lambda ctx, config: ctx.provide(service, value))


def test_a_plugin_waits_for_its_services_and_stops_when_one_is_withdrawn():
    kernel = Kernel()
    seen = []

    def apply(ctx, config):
        seen.append(ctx.get('bars'))
        ctx.effect(lambda: (lambda: seen.append('stopped')), 'watch')

    consumer = kernel.plugin(plugin('consumer', apply, inject=('bars',)))
    assert consumer.state == PENDING and consumer.missing == ['bars'] and seen == []

    source = kernel.plugin(provider('bars', 'tape'))
    assert consumer.state == ACTIVE and seen == ['tape']

    source.dispose()
    assert consumer.state == PENDING and seen == ['tape', 'stopped']
    assert kernel.services() == {}

    kernel.plugin(provider('bars', 'tape-2'))
    assert seen == ['tape', 'stopped', 'tape-2']


def test_unmounting_undoes_every_registration_in_reverse():
    kernel = Kernel()
    log = []

    def apply(ctx, config):
        for step in ('a', 'b', 'c'):
            ctx.effect(lambda step=step: (log.append(f'+{step}'),
                                          lambda: log.append(f'-{step}'))[1], step)

    fiber = kernel.plugin(plugin('p', apply))
    assert fiber.effects == ['a', 'b', 'c']
    fiber.dispose()
    assert log == ['+a', '+b', '+c', '-c', '-b', '-a']
    assert kernel.fibers == []


def test_a_plugin_that_fails_to_start_leaves_nothing_mounted():
    kernel = Kernel()

    def apply(ctx, config):
        ctx.provide('bars', 'tape')
        raise RuntimeError('bad config')

    with pytest.raises(RuntimeError):
        kernel.plugin(plugin('broken', apply))
    assert kernel.services() == {} and kernel.fibers == []


def test_undeclared_and_duplicate_services_are_refused():
    kernel = Kernel()
    kernel.plugin(provider('bars', 'tape'))
    with pytest.raises(KernelError, match='without declaring'):
        kernel.plugin(plugin('sneaky', lambda ctx, config: ctx.get('bars')))
    with pytest.raises(KernelError, match='already provided'):
        kernel.plugin(provider('bars', 'other'))
    assert kernel.get('bars') == 'tape'


def test_a_config_update_replaces_the_registered_strategy():
    kernel = Kernel()
    kernel.plugin(registry)
    kernel.plugin(quant_factors)
    fiber = kernel.plugin(rsi, {'params': {'period': 14}})
    strategies = kernel.get('strategies')
    assert strategies.get('rsi').params == {'period': 14, 'direction': 'reversion'}

    fiber.update({'params': {'period': 9, 'direction': 'momentum'}})
    assert strategies.get('rsi').params == {'period': 9, 'direction': 'momentum'}

    fiber.dispose()
    assert strategies.names() == []


def test_rsi_plugin_is_the_published_rsi_and_rejects_a_bad_row():
    rnd = random.Random(3)
    closes = [100.0]
    for _ in range(60):
        closes.append(closes[-1] * (1 + rnd.gauss(0, 0.02)))
    bars = [{'close': close} for close in closes]
    published = signals.legacy_compute_signals(
        [{'open': c, 'high': c, 'low': c, 'close': c} for c in closes])['rsi14']
    kernel = Kernel()
    kernel.plugin(registry)
    kernel.plugin(quant_factors)
    kernel.plugin(rsi)
    score = kernel.get('strategies').get('rsi').score
    assert score(bars, {'period': 14, 'direction': 'momentum'}) == published - 50
    assert score(bars, {'period': 14, 'direction': 'reversion'}) == 50 - published
    assert score(bars[:10], {'period': 14, 'direction': 'momentum'}) is None

    kernel = Kernel()
    kernel.plugin(registry)
    kernel.plugin(quant_factors)
    with pytest.raises(ValueError, match='period'):
        kernel.plugin(rsi, {'space': {'period': [1, 14]}})
    assert kernel.get('strategies').names() == []


class Tape:
    """A bars service over generated closes. `persistence` plants momentum."""

    def __init__(self, *, persistence, sessions=200, tickers=12, adjusted=True, seed=7):
        rnd = random.Random(seed)
        self._series, self._adjusted = {}, adjusted
        self._digest = f'tape-{persistence}-{sessions}-{tickers}-{adjusted}-{seed}'
        for t in range(tickers):
            close, previous, rows = 100.0, 0.0, []
            for day in range(sessions):
                previous = persistence * previous + rnd.gauss(0, 0.02)
                close *= 1 + previous
                rows.append({'date': f'd{day:04d}', 'close': close})
            self._series[f'T{t:02d}'] = rows

    def tickers(self):
        return sorted(self._series)

    def series(self, ticker):
        return self._series[ticker]

    def leg(self, ticker):
        return 'US'

    def describe(self):
        return {'source': 'generated', 'adjustment': 'qfq' if self._adjusted else 'raw',
                'corporate_actions_adjusted': self._adjusted, 'digest': self._digest}


def trend(ctx, config):
    """A toy strategy: the last `lookback` sessions' return, signed."""
    def score(bars, params):
        if len(bars) <= params['lookback']:
            return None
        return params['sign'] * (bars[-1]['close'] / bars[-1 - params['lookback']]['close'] - 1)

    spec = registry.StrategySpec(
        name='trend', params={'lookback': 3, 'sign': -1},
        space={'lookback': [1, 2, 3], 'sign': [-1, 1]}, score=score)
    ctx.effect(lambda: ctx.get('strategies').register(spec), 'strategy(trend)')


def flat_costs(bps):
    return registered_costs.Costs(CostModel(
        assumed_commission_bps={'us': bps}, spread_source='off'))


def optimise(tape, costs=None, **settings):
    kernel = Kernel()
    kernel.plugin(provider('costs', costs or flat_costs(0.0)))
    # Mounted before anything it depends on, on purpose.
    kernel.plugin(walkforward, {'bootstrap_samples': 300, **settings})
    kernel.plugin(plugin('trend', trend, inject=('strategies',)))
    kernel.plugin(provider('bars', tape))
    kernel.plugin(registry)
    return kernel.get('optimizer').run('trend')


def test_a_planted_edge_becomes_a_candidate_and_still_carries_no_permission():
    report = optimise(Tape(persistence=0.6))
    assert report['status'] == 'candidate' and report['refused_because'] == []
    assert report['selected_params']['sign'] == 1
    assert report['walk_forward']['oos_lift_ci95'][0] > 0
    assert report['live_permission'] is False


def test_noise_is_refused():
    report = optimise(Tape(persistence=0.0))
    assert report['status'] == 'refused'
    assert 'oos_ic_ci95_lower_gt' in report['refused_because']
    assert report['live_permission'] is False


def test_the_same_edge_on_unadjusted_bars_is_refused():
    report = optimise(Tape(persistence=0.6, adjusted=False))
    assert report['refused_because'] == ['corporate_actions_adjusted']


def test_an_alternate_gate_is_recorded_beside_the_verdict_and_never_sets_it():
    drop_adjustment = {'id': 'statistics-only', 'rationale': 'raw store',
                       'gate': {'corporate_actions_adjusted': False}}
    report = optimise(Tape(persistence=0.6, adjusted=False),
                      gate_alternates=[drop_adjustment])
    [alternate] = report['alternate_gates']
    assert alternate['would_pass'] is True and alternate['binding'] is False
    assert alternate['agrees_with_registered'] is False
    # The alternate inherits every registered check it does not override.
    assert alternate['gate']['pbo_lt'] == 0.5
    assert report['status'] == 'refused' and report['live_permission'] is False
    assert report['refused_because'] == ['corporate_actions_adjusted']

    stricter = {'id': 'long-sample', 'rationale': 'want a year',
                'gate': {'min_oos_sessions': 250}}
    report = optimise(Tape(persistence=0.6), gate_alternates=[stricter])
    assert report['status'] == 'candidate'
    assert report['alternate_gates'][0]['would_refuse_because'] == ['min_oos_sessions']


@pytest.mark.parametrize('settings, message', [
    ({'gate': {'pbo_below': 0.4}}, 'unknown gate check'),
    ({'gate_alternates': [{'id': 'a', 'rationale': 'r', 'gate': {'pbo': 0.4}}]},
     'unknown gate check'),
    ({'gate_alternates': [{'id': 'a', 'gate': {}}]}, 'needs a rationale'),
    ({'gate_alternates': [{'id': 'a', 'rationale': 'r'}, {'id': 'a', 'rationale': 'r'}]},
     'unique id'),
])
def test_a_gate_row_that_does_not_say_what_it_means_is_refused_at_mount(settings, message):
    with pytest.raises(ValueError, match=message):
        optimise(Tape(persistence=0.0, sessions=5), **settings)


def test_a_sample_too_short_to_measure_selection_is_refused_not_waved_through():
    report = optimise(Tape(persistence=0.6, sessions=45), min_train_sessions=10,
                      test_sessions=10, pbo_groups=20,
                      gate={'min_oos_sessions': 10})
    assert report['pbo']['pbo'] is None
    assert 'pbo_lt' in report['refused_because']


def test_refits_only_use_sessions_whose_forward_return_had_closed():
    sessions = [f'd{i:03d}' for i in range(40)]
    # Config 0 leads until d013, then config 1 takes over hard. The first refit
    # happens before d016, when only d000..d009 had a realised forward return:
    # it must still pick config 0. Reading up to d015 would pick config 1.
    matrix = [[1.0, 0.0] if i < 14 else [0.0, 10.0] for i in range(40)]
    walk = walkforward.walk_forward(
        sessions, matrix, 0, min_train=10, test_len=6, embargo=6)
    assert [fold['train_sessions'] for fold in walk['folds']] == [10, 16, 22, 28]
    assert [fold['chosen'] for fold in walk['folds']] == [0, 1, 1, 1]
    assert walk['days'][0] == 'd016' and len(walk['days']) == 24


def test_shipped_rows_mount_with_nothing_left_waiting(tmp_path, capsys):
    kernel = lab.mount(lab.load_rows(ROOT / lab.CONFIG))
    assert [fiber.missing for fiber in kernel.fibers] == [[], [], [], [], [], []]
    spec = kernel.get('strategies').get('rsi')
    assert spec.params in walkforward.configurations(spec.space)
    kernel.dispose()

    rows = [row for row in lab.load_rows(ROOT / lab.CONFIG) if row['id'] != 'bars']
    config = tmp_path / 'rows.json'
    config.write_text(json.dumps({'schema_version': 1, 'plugins': rows}))
    with pytest.raises(SystemExit) as stopped:
        lab.main(['--config', str(config), 'optimize', 'rsi'])
    assert stopped.value.code == 2
    assert "waiting plugins: {'walkforward-optimizer': ['bars']}" in capsys.readouterr().err


def test_ledger_bars_reads_the_store_and_reports_it_as_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_bars.bar_store, 'BARS_DIR', tmp_path)
    for ticker in ('AAA', 'BBB'):
        (tmp_path / f'{ticker}.json').write_text(json.dumps({
            'ticker': ticker, 'adjustment': 'raw', 'bars': {
                '2026-01-06': {'open': 1, 'high': 2, 'low': 1, 'close': 2.0},
                '2026-01-05': {'open': 1, 'high': 2, 'low': 1, 'close': 1.5},
                '2026-01-07': {'open': 1, 'high': 2, 'low': 1, 'close': 0},
            }}))
    kernel = Kernel()
    kernel.plugin(ledger_bars, {'tickers': ['AAA']})
    bars = kernel.get('bars')
    assert bars.tickers() == ['AAA']
    assert [(bar['date'], bar['close']) for bar in bars.series('AAA')] == [
        ('2026-01-05', 1.5), ('2026-01-06', 2.0)]
    assert bars.describe()['corporate_actions_adjusted'] is False


def test_costs_come_off_the_excess_and_only_an_alternate_gate_reads_them():
    free = optimise(Tape(persistence=0.6))['net_of_cost']
    assert free['oos_mean_net_excess'] == free['oos_mean_gross_excess'] > 0

    net_gate = {'id': 'net-of-cost', 'rationale': 'must survive trading',
                'gate': {'oos_net_excess_ci95_lower_gt': 0.0}}
    cheap = optimise(Tape(persistence=0.6), flat_costs(1.0), gate_alternates=[net_gate])
    net = cheap['net_of_cost']
    assert 0 < net['oos_mean_net_excess'] < net['oos_mean_gross_excess']
    assert 0 < net['mean_turnover_per_tranche'] <= 1
    assert cheap['alternate_gates'][0]['would_pass'] is True

    # Costs no edge survives: the registered gate does not read them, so the
    # verdict stands, and the alternate that does read them says no.
    dear = optimise(Tape(persistence=0.6), flat_costs(5000.0), gate_alternates=[net_gate])
    assert dear['net_of_cost']['oos_mean_net_excess'] < 0
    assert dear['status'] == 'candidate'
    assert [check['check'] for check in dear['gate']] == [
        'min_oos_sessions', 'oos_ic_ci95_lower_gt', 'oos_lift_ci95_lower_gt',
        'pbo_lt', 'corporate_actions_adjusted']
    assert dear['alternate_gates'][0]['would_refuse_because'] == [
        'oos_net_excess_ci95_lower_gt']
    assert dear['alternate_gates'][0]['binding'] is False


def test_a_tranche_pays_for_the_names_it_replaces():
    def cell(order):
        return [(ticker, 4.0 - rank, 0.01 * (4 - rank)) for rank, ticker in enumerate(order)]

    # One configuration, horizon 1. Session 0 holds A,B; session 1 keeps them;
    # session 2 swaps B for C.
    cells = [[cell('ABCD')], [cell('ABCD')], [cell('ACBD')]]
    out = walkforward.net_excess(cells, [0, 0, 0], [0, 1, 2], horizon=1,
                                 side_bps=lambda ticker: 10.0)
    assert out['turnover'] == [1.0, 0.0, 0.5]
    costs = [round(g - n, 6) for g, n in zip(out['gross'], out['net'])]
    # Full entry at 10 bps; nothing; one of two names sold and one bought.
    assert costs == [0.001, 0.0, 0.001]


def test_registered_costs_are_the_cost_model_per_side():
    costs = registered_costs.Costs(CostModel.load(ROOT / 'config' / 'cost-model.json'))
    assert costs.side_bps('HK') == 3.0 + 12.0 * 0.5
    assert costs.side_bps('us') == 1.0 + 4.0 * 0.5
    assert registered_costs.Costs(CostModel.free()).side_bps('hk') == 0.0


def _store(tmp_path, monkeypatch, docs):
    monkeypatch.setattr(adjusted_bars.bar_store, 'BARS_DIR', tmp_path)
    for ticker, doc in docs.items():
        (tmp_path / f'{ticker}.json').write_text(json.dumps({'ticker': ticker, **doc}))


def _bar(day, close):
    return {'date': day, 'open': close, 'high': close, 'low': close, 'close': close}


def test_adjusted_bars_serve_adjusted_and_no_action_names_and_leave_out_the_unconfirmed(
        tmp_path, monkeypatch):
    settled = {'2026-01-05': _bar('2026-01-05', 100.0), '2026-01-06': _bar('2026-01-06', 51.0)}
    _store(tmp_path, monkeypatch, {
        'SPLIT': {'leg': 'US', 'tencent': 'usSPLIT.OQ', 'bars': settled},
        'FLAT': {'leg': 'HK', 'tencent': 'hk00001', 'bars': settled},
        'RAW': {'leg': 'US', 'tencent': 'usRAW.N', 'bars': settled},
        'QUIET': {'leg': 'US', 'tencent': 'usQUIET.N', 'bars': settled},
        'DOWN': {'leg': 'US', 'tencent': 'usDOWN.N', 'bars': settled},
        'GONE': {'leg': 'US', 'tencent': 'usGONE.N', 'retired': True, 'bars': settled},
    })

    def fetch(symbol, count):
        if symbol == 'usDOWN.N':
            raise OSError('reset')
        first = 50.0 if symbol == 'usSPLIT.OQ' else 100.0
        rows = [_bar('2026-01-05', first), _bar('2026-01-06', 51.0),
                # The session in progress: not in the settled store.
                _bar('2026-01-07', 52.0)]
        return rows, {'usRAW.N': 'unconfirmed',
                      'usQUIET.N': 'no_action_on_record'}.get(symbol, 'adjusted')

    bars = adjusted_bars.AdjustedBars(fetch=fetch)
    assert bars.tickers() == ['FLAT', 'QUIET', 'SPLIT']
    assert [bar['date'] for bar in bars.series('SPLIT')] == ['2026-01-05', '2026-01-06']
    assert bars.series('SPLIT')[0]['close'] == 50.0 and bars.leg('FLAT') == 'HK'
    described = bars.describe()
    assert described['corporate_actions_adjusted'] is True
    assert described['differs_from_raw'] == 1
    assert described['basis'] == {
        'adjusted': ['FLAT', 'SPLIT'], 'no_action_on_record': ['QUIET']}
    assert described['left_out'] == {
        'DOWN': 'fetch failed: OSError', 'GONE': 'retired or not in the settled store',
        'RAW': 'answered raw without an empty action record'}

    nothing = adjusted_bars.AdjustedBars(['RAW'], fetch=fetch).describe()
    assert nothing['corporate_actions_adjusted'] is False and nothing['tickers'] == 0


def test_the_ledger_counts_a_repeated_question_once(tmp_path, monkeypatch):
    path = tmp_path / 'strategy-lab' / 'ledger.jsonl'
    monkeypatch.setattr(ledger, 'ledger_path', lambda: path)
    drop = {'id': 'statistics-only', 'rationale': 'raw store',
            'gate': {'corporate_actions_adjusted': False}}
    raw = optimise(Tape(persistence=0.6, adjusted=False), gate_alternates=[drop])
    ledger.append(raw)
    ledger.append(raw)
    record = ledger.append(optimise(Tape(persistence=0.0), gate_alternates=[drop]))
    assert record['live_permission'] is False
    assert record['alternate_gates'][0]['binding'] is False

    [entry] = ledger.statistics(ledger.load()).pop('strategies').values()
    assert entry['runs'] == 3 and entry['distinct_inputs'] == 2
    assert entry['candidates'] == 0 and entry['candidate_rate'] == 0.0
    assert entry['refused_by_check']['corporate_actions_adjusted'] == 1
    assert entry['alternate_gates']['statistics-only'] == {
        'binding': False, 'judged': 2, 'would_pass': 1, 'disagrees_with_registered': 1}

    path.write_text(path.read_text() + '{"torn":\n')
    with pytest.raises(ValueError, match='unreadable ledger row'):
        ledger.load()


def test_the_live_composition_is_the_shipped_rows_and_refuses_a_broken_list(tmp_path):
    assert live.rows(ROOT / live.CONFIG) == [dict(row) for row in live.DEFAULT_ROWS]
    assert live.rows(tmp_path / 'absent.json') == [dict(row) for row in live.DEFAULT_ROWS]
    assert live.service('factors').describe() == {'sigma_target': 0.25}
    assert live.service('daily_bars').describe() == {'adjustment': 'qfq'}
    with pytest.raises(ValueError, match="no live row provides 'absent'"):
        live.service('absent')

    config = tmp_path / 'rows.json'
    config.write_text(json.dumps({'schema_version': 1, 'plugins': []}))
    assert live.rows(config) == [dict(row) for row in live.DEFAULT_ROWS]
    config.write_text(json.dumps({'live': [{'id': 'factors'}]}))
    with pytest.raises(ValueError, match='live must be a list of rows'):
        live.rows(config)
    with pytest.raises(ValueError, match='sigma_target'):
        Kernel().plugin(quant_factors, {'sigma_target': 0})
