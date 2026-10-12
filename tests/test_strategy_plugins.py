"""Strategy plugins: the kernel's composition rules and the optimiser's gate."""
from __future__ import annotations

import json
import random
import types
from types import SimpleNamespace
from pathlib import Path

import pytest

from clawock.decision import signals
from clawock.costs import CostModel
from clawock.plugin_host import live
from clawock.strategies import registry
from clawock.strategies.plugins import quant_factors, rsi
from clawock.strategy_lab import boundaries, lab, ledger
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
    published = signals.compute_signals(
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


def test_a_sample_too_short_to_measure_selection_is_refused_not_waved_through(monkeypatch):
    # The short tape needs a lower session bar than a row is allowed to set.
    monkeypatch.setitem(walkforward.FLOOR, 'min_oos_sessions', 10)
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


NET = {'id': 'net-of-cost', 'rationale': 'after costs', 'effect': 'live',
       'gate': {'oos_net_excess_ci95_lower_gt': 0.0}}


def test_a_live_alternate_can_object_and_cannot_set_the_verdict_or_grant_permission():
    free = optimise(Tape(persistence=0.6), gate_alternates=[NET])
    assert free['status'] == 'candidate'
    assert free['live_review'] == {
        'alternates': ['net-of-cost'], 'objections': [], 'cleared': True}

    # The same edge, charged more than it earns: the registered gate reads a
    # gross IC and still passes; the live alternate objects.
    costly = optimise(Tape(persistence=0.6), costs=flat_costs(5000.0), gate_alternates=[NET])
    assert costly['status'] == 'candidate' and costly['refused_because'] == []
    assert costly['live_review'] == {
        'alternates': ['net-of-cost'], 'objections': ['net-of-cost'], 'cleared': False}
    [alternate] = costly['alternate_gates']
    assert alternate['binding'] is False and alternate['effect'] == 'live'
    assert costly['live_permission'] is False and free['live_permission'] is False


def test_nothing_clears_what_the_registered_gate_refuses():
    drop = {'id': 'statistics-only', 'rationale': 'raw store',
            'gate': {'corporate_actions_adjusted': False}}
    raw = optimise(Tape(persistence=0.6, adjusted=False), gate_alternates=[drop, NET])
    assert [a['would_pass'] for a in raw['alternate_gates']] == [True, False]
    assert raw['alternate_gates'][0]['effect'] == 'record'
    assert raw['status'] == 'refused'
    assert raw['live_review'] == {
        'alternates': ['net-of-cost'], 'objections': ['net-of-cost'], 'cleared': False}


@pytest.mark.parametrize('gate, loosened', [
    ({'corporate_actions_adjusted': False}, 'corporate_actions_adjusted'),
    ({'pbo_lt': 0.9}, 'pbo_lt'),
    ({'min_oos_sessions': 10}, 'min_oos_sessions'),
    ({'oos_ic_ci95_lower_gt': -0.1}, 'oos_ic_ci95_lower_gt'),
])
def test_an_alternate_with_live_effect_may_only_add_or_tighten_a_check(gate, loosened):
    row = {'id': 'a', 'rationale': 'r', 'effect': 'live', 'gate': gate}
    with pytest.raises(ValueError, match=f'has live effect and loosens .*{loosened}'):
        optimise(Tape(persistence=0.0), gate_alternates=[row])
    # The same thresholds are a legitimate thing to keep on record.
    optimise(Tape(persistence=0.0), gate_alternates=[dict(row, effect='record')])
    with pytest.raises(ValueError, match='effect must be one of'):
        optimise(Tape(persistence=0.0), gate_alternates=[dict(row, gate={}, effect='binding')])
    tighter = {'pbo_lt': 0.2, 'min_oos_sessions': 80, 'oos_net_excess_ci95_lower_gt': 0.0}
    optimise(Tape(persistence=0.0), gate_alternates=[dict(row, gate=tighter)])


def _lab(tape, **settings):
    kernel = Kernel()
    kernel.plugin(provider('costs', flat_costs(0.0)))
    kernel.plugin(walkforward, {'bootstrap_samples': 300, 'gate_alternates': [NET], **settings})
    kernel.plugin(plugin('trend', trend, inject=('strategies',)))
    kernel.plugin(provider('bars', tape))
    kernel.plugin(registry)
    return kernel


def test_the_scheduled_run_records_registers_once_and_scores_only_later_sessions(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ledger, 'ledger_path', lambda: tmp_path / 'lab' / 'ledger.jsonl')
    monkeypatch.setattr(ledger, 'registrations_path', lambda: tmp_path / 'lab' / 'registrations.jsonl')

    assert lab.record(_lab(Tape(persistence=0.6, sessions=200))) == 0
    [registered] = ledger.registrations()
    assert registered['strategy'] == 'trend' and registered['params']['sign'] == 1
    assert registered['after_session'] == 'd0199' and registered['live_permission'] is False
    assert registered['cleared_by'] == {'gate': 'registered', 'live_alternates': ['net-of-cost']}
    [first] = ledger.load()
    assert first['live_review']['cleared'] is True and first['prospective'] == []
    assert 'registered' in capsys.readouterr().out

    # The same tape, 40 sessions on: the registration is not repeated, and its
    # parameters are scored on the sessions after d0199 only.
    assert lab.record(_lab(Tape(persistence=0.6, sessions=240))) == 0
    assert len(ledger.registrations()) == 1
    [trial] = ledger.load()[-1]['prospective']
    assert trial['params'] == registered['params'] and trial['after_session'] == 'd0199'
    # Signal sessions d0200..d0233: the last six have no closed forward return.
    assert trial['sessions'] == 34 and trial['mean_ic'] > 0
    [entry] = ledger.statistics(ledger.load())['strategies'].values()
    assert entry['cleared'] == 2 and entry['objections'] == {}

    # Noise is recorded and registers nothing.
    monkeypatch.setattr(ledger, 'registrations_path', lambda: tmp_path / 'lab' / 'none.jsonl')
    assert lab.record(_lab(Tape(persistence=0.0))) == 0
    assert ledger.registrations() == [] and ledger.load()[-1]['status'] == 'refused'


def test_one_strategy_failing_does_not_stop_the_scheduled_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ledger, 'ledger_path', lambda: tmp_path / 'ledger.jsonl')
    monkeypatch.setattr(ledger, 'registrations_path', lambda: tmp_path / 'registrations.jsonl')
    kernel = _lab(Tape(persistence=0.6))

    def broken(ctx, config):
        spec = registry.StrategySpec(name='broken', params={'n': 1}, space={'n': [2]},
                                     score=lambda bars, params: None)
        ctx.effect(lambda: ctx.get('strategies').register(spec), 'strategy(broken)')
    kernel.plugin(plugin('broken', broken, inject=('strategies',)))
    assert lab.record(kernel) == 1
    assert 'broken: not recorded' in capsys.readouterr().err
    assert [row['strategy'] for row in ledger.load()] == ['trend']


def test_the_brief_runs_the_lab_after_delivery_and_never_fails_on_it(monkeypatch, capsys):
    from clawock.harness import brief_postflight
    assert brief_postflight.record_strategy_lab() is False  # disabled for the suite

    monkeypatch.delenv('CLAWOCK_STRATEGY_LAB_RECORD_DISABLED')
    seen = []

    def run(command, **kwargs):
        seen.append((command[1:], kwargs['timeout']))
        return SimpleNamespace(returncode=0, stdout='rsi: candidate\n', stderr='')
    monkeypatch.setattr(brief_postflight.subprocess, 'run', run)
    assert brief_postflight.record_strategy_lab() is True
    assert seen == [(['-m', 'clawock', 'strategy-lab', 'record'], 300)]
    assert 'strategy lab: rsi: candidate' in capsys.readouterr().out

    def hang(command, **kwargs):
        raise brief_postflight.subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(brief_postflight.subprocess, 'run', hang)
    assert brief_postflight.record_strategy_lab() is False
    monkeypatch.setattr(brief_postflight.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout='', stderr='boom'))
    assert brief_postflight.record_strategy_lab() is False
    assert 'strategy lab exited 1: boom' in capsys.readouterr().err


def test_the_old_import_paths_are_views_of_the_mounted_plugins(monkeypatch):
    import importlib
    for path, service in [
            ('clawock.decision.add_policy', 'add_policy'),
            ('clawock.decision.add_alpha', 'add_alpha'),
            ('clawock.decision.left_side', 'left_side'),
            ('clawock.decision.add_side', 'add_side'),
            ('clawock.decision.preposition', 'preposition'),
            ('clawock.decision.intraday_policy', 'intraday_policy'),
            ('clawock.market_data.bar_signals', 'bar_signals'),
            ('clawock.evaluation.signal_panel', 'signal_panel')]:
        facade, mounted = importlib.import_module(path), live.service(service)
        assert mounted.__name__.endswith(f'.plugins.{service}')
        public = [name for name, value in vars(mounted).items()
                  if isinstance(value, types.FunctionType) and not name.startswith('_')]
        assert public and all(getattr(facade, name) is getattr(mounted, name) for name in public)
        with pytest.raises(AttributeError):
            facade.not_a_name_the_plugin_has
    # Setting through the old path sets the plugin's global, and is undone there.
    from clawock.decision import add_policy
    mounted = live.service('add_policy')
    monkeypatch.setattr(add_policy, 'TARGET_MAX_PCT', 60.0)
    assert mounted.TARGET_MAX_PCT == 60.0
    monkeypatch.undo()
    assert mounted.TARGET_MAX_PCT == 100.0


# ── the boundaries of the evolution chain ───────────────────────────────────

@pytest.mark.parametrize('gate, lowered', [
    ({'corporate_actions_adjusted': False}, 'corporate_actions_adjusted'),
    ({'pbo_lt': 0.6}, 'pbo_lt'),
    ({'min_oos_sessions': 59}, 'min_oos_sessions'),
    ({'oos_ic_ci95_lower_gt': -0.01}, 'oos_ic_ci95_lower_gt'),
    ({'oos_lift_ci95_lower_gt': -0.01}, 'oos_lift_ci95_lower_gt'),
])
def test_a_row_may_tighten_the_registered_gate_and_never_lower_it(gate, lowered):
    with pytest.raises(ValueError, match=f'asks less than the floor on .*{lowered}'):
        optimise(Tape(persistence=0.0), gate=gate)
    optimise(Tape(persistence=0.0), gate={'pbo_lt': 0.3, 'min_oos_sessions': 90,
                                          'oos_net_excess_ci95_lower_gt': 0.0})


def _candidate():
    return optimise(Tape(persistence=0.6), gate_alternates=[NET])


def _set(path, value):
    def change(report):
        target = report
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change


@pytest.mark.parametrize('tamper, said', [
    (_set(['live_permission'], True), 'live_permission is True'),
    (_set(['status'], 'approved'), "status 'approved'"),
    (_set(['gate', 0, 'passed'], False), "not the registered gate's verdict"),
    (_set(['alternate_gates', 0, 'binding'], True), 'is marked binding'),
    (_set(['alternate_gates', 0, 'would_pass'], False), 'live_review.objections is not'),
    (_set(['sample', 'bars', 'corporate_actions_adjusted'], False), 'do not say they are adjusted'),
])
def test_a_proposal_that_claims_more_than_the_gate_concluded_is_not_recorded(
        tamper, said, tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, 'ledger_path', lambda: tmp_path / 'ledger.jsonl')
    monkeypatch.setattr(ledger, 'registrations_path', lambda: tmp_path / 'registrations.jsonl')
    report = _candidate()
    assert boundaries.proposal_violations(report) == []
    tamper(report)
    with pytest.raises(boundaries.BoundaryError, match=said):
        ledger.append(report)
    with pytest.raises(boundaries.BoundaryError):
        ledger.register(report)
    assert ledger.load() == [] and ledger.registrations() == []


def test_a_refused_proposal_cannot_be_registered_by_marking_it_cleared(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, 'registrations_path', lambda: tmp_path / 'registrations.jsonl')
    report = optimise(Tape(persistence=0.0), gate_alternates=[NET])
    assert report['status'] == 'refused' and ledger.register(report) is None
    report['live_review']['cleared'] = True
    with pytest.raises(boundaries.BoundaryError, match='live_review.cleared is not'):
        ledger.register(report)
    assert ledger.registrations() == []


def test_the_ledger_is_read_back_against_the_boundaries(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ledger, 'ledger_path', lambda: tmp_path / 'ledger.jsonl')
    monkeypatch.setattr(ledger, 'registrations_path', lambda: tmp_path / 'registrations.jsonl')
    assert lab.record(_lab(Tape(persistence=0.6, sessions=200))) == 0
    assert lab.record(_lab(Tape(persistence=0.6, sessions=240))) == 0
    assert boundaries.verify(ledger.load(), ledger.registrations()) == []
    assert lab.main(['verify']) == 0
    assert '2 ledger rows, 1 registrations: within the boundaries' in capsys.readouterr().out
    [trial] = ledger.load()[-1]['prospective']
    assert trial['first_session'] == 'd0200' > trial['after_session']

    # Rows that reached the files some other way are found on the next read.
    rows, [registration] = ledger.load(), ledger.registrations()
    forged = [dict(rows[0], live_permission=True),
              dict(rows[0], status='candidate', refused_because=['pbo_lt']),
              dict(rows[1], prospective=[dict(trial, first_session='d0199')])]
    stray = dict(registration, input_digest='0' * 16, live_permission=True)
    found = boundaries.verify(forged, [stray])
    assert [line.split(': ', 1)[1] for line in found] == [
        'live_permission is not false',
        'status disagrees with refused_because',
        'prospective score counts a session not after d0199',
        'live_permission is not false',
        'no cleared ledger row with its input digest']
    with (tmp_path / 'registrations.jsonl').open('a') as handle:
        handle.write(json.dumps(stray) + '\n')
    assert lab.main(['verify']) == 1


def test_a_listener_may_refuse_a_registration_and_cannot_cause_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ledger, 'ledger_path', lambda: tmp_path / 'ledger.jsonl')
    monkeypatch.setattr(ledger, 'registrations_path', lambda: tmp_path / 'registrations.jsonl')
    heard = []

    def objector(ctx, config):
        ctx.on(lab.PROPOSAL, lambda report: heard.append(('proposal', report['status'])))

        def refuse(report):
            heard.append(('registration', report['strategy']))
            raise ValueError('one provider is not enough')
        ctx.on(lab.REGISTRATION, refuse)

    kernel = _lab(Tape(persistence=0.6))
    fiber = kernel.plugin(plugin('objector', objector))
    assert lab.record(kernel) == 1
    assert heard == [('proposal', 'candidate'), ('registration', 'trend')]
    # The proposal is on record; the registration it objected to is not.
    assert [row['status'] for row in ledger.load()] == ['candidate']
    assert ledger.registrations() == []
    assert 'not recorded (ValueError: one provider is not enough)' in capsys.readouterr().err

    # A listener that answers yes to everything changes nothing for noise.
    fiber.dispose()
    noise = _lab(Tape(persistence=0.0))
    noise.plugin(plugin('eager', lambda ctx, config: ctx.on(lab.PROPOSAL, lambda report: True)))
    assert lab.record(noise) == 0
    assert ledger.registrations() == [] and ledger.load()[-1]['status'] == 'refused'


def test_recording_a_candidate_changes_no_row_and_no_live_service(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, 'ledger_path', lambda: tmp_path / 'ledger.jsonl')
    monkeypatch.setattr(ledger, 'registrations_path', lambda: tmp_path / 'registrations.jsonl')
    config = ROOT / 'config' / 'strategy-plugins.json'
    before = config.read_bytes()
    closes = [100 + (i * 7) % 13 for i in range(60)]
    published = live.service('factors').rsi(closes, 14)
    kernel = _lab(Tape(persistence=0.6))
    assert lab.record(kernel) == 0
    [registered] = ledger.registrations()
    spec = kernel.get('strategies').get('trend')
    # The run selected other parameters and registered them; the strategy still
    # runs with the ones its row declares, and the live factor row is untouched.
    assert registered['params'] != spec.params == {'lookback': 3, 'sign': -1}
    assert config.read_bytes() == before
    assert live.service('factors').rsi(closes, 14) == published


class SplitTape(Tape):
    """A tape whose source says half its names rest on an empty action record."""

    def describe(self):
        names = self.tickers()
        return {**super().describe(),
                'basis': {'adjusted': names[:6], 'no_action_on_record': names[6:]}}


def test_a_candidate_says_whether_it_survives_without_the_single_source_names(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ledger, 'ledger_path', lambda: tmp_path / 'ledger.jsonl')
    monkeypatch.setattr(ledger, 'registrations_path', lambda: tmp_path / 'registrations.jsonl')
    assert optimise(Tape(persistence=0.6))['coverage_sensitivity'] is None
    kernel = _lab(SplitTape(persistence=0.6, tickers=12))
    report = kernel.get('optimizer').run('trend')
    narrow = report['coverage_sensitivity']
    assert narrow['tickers'] == 6 and narrow['left_out'] == [f'T{n:02d}' for n in range(6, 12)]
    assert narrow['verdict_survives'] is (narrow['status'] == report['status'])
    # It is written beside the verdict and decides nothing.
    assert report['status'] == 'candidate' and report['live_review']['cleared'] is True
    assert lab.record(kernel) == 0
    assert ledger.load()[-1]['coverage_sensitivity'] == narrow
    view = lab.evolution('trend', ledger.load(), ledger.registrations())
    assert view['live_permission'] is False and len(view['steps']) == 1
    assert view['steps'][0]['names_by_basis'] == {'adjusted': 6, 'no_action_on_record': 6}
    [trial] = view['registrations']
    assert trial['latest'] is None and trial['scored_runs'] == 0
    assert lab.main(['evolution', 'trend']) == 0
    assert 'adjusted names alone' in capsys.readouterr().out
