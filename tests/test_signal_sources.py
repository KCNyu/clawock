"""Signal sources as plugin rows: what they declare, what they return, and how a broken row fails.

The recorded outputs in `fixtures/signal_sources/goldens.json` are the standing
check that a signal source still computes what it did. They were recorded from
bars and scan files copied out of the workspace on 2026-10-12, and they are
compared exactly, floats included. A deliberate change to a source's arithmetic
re-records them (`CLAWOCK_WRITE_GOLDENS=1`), and the diff of that file is then
the statement of what changed.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clawock.harness import brief_preflight
from clawock.plugin_host import declarations, live, rows
from clawock.plugin_host.kernel import Kernel, KernelError
from clawock.strategies.plugins import bar_signals, quant_factors, rsi, sentiment

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures' / 'signal_sources'
GOLDENS = FIXTURES / 'goldens.json'
BARS = json.loads((FIXTURES / 'bars.json').read_text())['series']
SOURCES = {'factors': quant_factors, 'bar-signals': bar_signals, 'rsi': rsi,
           'sentiment': sentiment}


# ── declarations ────────────────────────────────────────────────────────────

def test_every_shipped_signal_source_row_carries_a_complete_declaration():
    config = json.loads((ROOT / 'config' / 'strategy-plugins.json').read_text())
    flagged = {row['id'] for row in config['live'] + config['plugins']
               if row.get('signal_source')}
    assert flagged == set(SOURCES)
    assert {row['id'] for row in live.DEFAULT_ROWS if row.get('signal_source')} == \
        flagged - {'rsi'}
    for identifier, module in SOURCES.items():
        declaration = declarations.of(module)
        assert declaration['id'] == identifier
        assert declaration['missing']['serves_stale'] is False
    assert set(live.signal_sources()) == {'factors', 'bar-signals', 'sentiment'}


@pytest.mark.parametrize('damage, gap', [
    (lambda d: d['outputs'][0].pop('unit'), 'unit is missing'),
    (lambda d: d['outputs'][0].update(window=' '), 'window is missing'),
    (lambda d: d['outputs'][0].pop('missing'), 'missing is missing'),
    (lambda d: d['inputs'][0].pop('source'), 'source is missing'),
    (lambda d: d.update(family='vibes'), 'family must be one of'),
    (lambda d: d['missing'].update(policy='last_value'), 'missing.policy must be one of'),
    (lambda d: d['missing'].update(serves_stale=True), 'serves_stale must be False'),
    (lambda d: d.pop('missing'), 'missing must say'),
    (lambda d: d['outputs'].append(dict(d['outputs'][0])), 'outputs repeat'),
])
def test_a_declaration_that_leaves_a_reader_guessing_is_refused(damage, gap):
    declaration = copy.deepcopy(quant_factors.SIGNAL_SOURCE)
    damage(declaration)
    with pytest.raises(declarations.DeclarationError, match=gap):
        declarations.validate(declaration)


def test_a_row_that_claims_to_be_a_signal_source_needs_the_declaration(monkeypatch):
    import sys
    bare = types.ModuleType('bare_source')
    bare.apply = lambda ctx, config: ctx.provide('bare', object())
    monkeypatch.setitem(sys.modules, 'bare_source', bare)
    with pytest.raises(declarations.DeclarationError, match='has no SIGNAL_SOURCE'):
        rows.mount(Kernel(), {'module': 'bare_source', 'signal_source': True})
    kernel = Kernel()
    rows.mount(kernel, {'module': 'bare_source'})
    assert 'bare' in kernel.services()
    # A module that carries a declaration is checked even when the row does not ask.
    bare.SIGNAL_SOURCE = {'id': 'bare'}
    with pytest.raises(declarations.DeclarationError, match='summary is missing'):
        rows.mount(Kernel(), {'module': 'bare_source'})


def _cuts(series):
    return sorted({20, 25, 29, 30, 60, 130, 200, len(series)} & set(range(len(series) + 1)))


def test_the_factor_row_holds_exactly_the_declared_fields_and_its_nulls_are_the_declared_ones():
    declared = set(declarations.fields(quant_factors.SIGNAL_SOURCE))
    factors = live.service('factors')
    series = BARS['02208']
    assert set(factors.signals(series)) == declared
    assert set(factors.short_history(series[:25])) == declared
    # Below the stated minimum the whole reading is None, not a partial row.
    assert factors.signals(series[:29]) is None
    assert factors.short_history(series[:19]) is None
    young = factors.signals(series[:60])
    assert young['ma200'] is None and young['trend_on'] is None and young['mom_12_1'] is None
    assert young['ma50'] is not None and young['rsi14'] is not None
    assert '趋势未知' in young['tag']
    short = factors.short_history(series[:25])
    assert [short[key] for key in ('ma50', 'ma200', 'mom_1m', 'vol20_annualized',
                                   'vol_target_weight', 'pct_52w_range')] == [None] * 6


def test_the_estimator_row_holds_the_declared_fields_and_never_a_zero_for_undefined():
    declared = set(declarations.fields(bar_signals.SIGNAL_SOURCE))
    series = BARS['NVDA']
    full = bar_signals.bar_signal_row(series, len(series) - 1)
    assert set(full) == declared
    early = bar_signals.bar_signal_row(series, 10)
    # The two moments are left out of an early row, as declared; the rest are null.
    assert set(early) == declared - {'realised_skew', 'realised_kurtosis'}
    assert all(value is None for value in early.values())


def test_a_strategy_scores_null_without_enough_closes():
    score = rsi.scorer(live.service('factors'))
    params = {'period': 14, 'direction': 'reversion'}
    assert score(BARS['SPCH'][:14], params) is None
    value = score(BARS['SPCH'][:15], params)
    assert value is not None and -50 <= value <= 50
    assert score(BARS['SPCH'][:15], {'period': 14, 'direction': 'momentum'}) == -value


# ── the sentiment service ───────────────────────────────────────────────────

def _stamp(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _workspace(tmp_path, *, attention=None, statements=None):
    data = tmp_path / 'assets' / 'data'
    data.mkdir(parents=True, exist_ok=True)
    for name, payload in (('sentiment.json', attention), ('influencer_feed.json', statements)):
        if payload is None:
            continue
        (data / name).write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return tmp_path


def _scan(name, hours=1.2, **changes):
    payload = json.loads((FIXTURES / name).read_text())
    payload['generated_at'] = _stamp(hours)
    payload.update(changes)
    return payload


def _moves(tickers):
    return {ticker: {'px_pct': float(len(ticker)), 'n_sessions': 5} for ticker in tickers[:2]}


def test_the_sentiment_service_says_which_of_four_things_happened(tmp_path):
    service = live.service('sentiment')
    assert service.describe() == {'stale_after_hours': 36}
    assert service.attention(tmp_path, _moves)['status'] == 'missing'
    assert service.statements(tmp_path)['status'] == 'missing'

    _workspace(tmp_path, attention=_scan('sentiment.json'), statements=_scan('influencer_feed.json'))
    attention, statements = service.attention(tmp_path, _moves), service.statements(tmp_path)
    assert attention['status'] == statements['status'] == 'ok'
    assert attention['reading']['age_hours'] == statements['reading']['age_hours'] == 1.2
    assert attention['detail']['scanned'] == 9

    for payload in (_scan('sentiment.json', hours=37), _scan('sentiment.json', hours=-3),
                    _scan('sentiment.json', generated_at='yesterday'),
                    {key: value for key, value in _scan('sentiment.json').items()
                     if key != 'generated_at'}):
        _workspace(tmp_path, attention=payload)
        answer = service.attention(tmp_path, _moves)
        # Too old, from the future, or unstamped: nothing of it is served.
        assert (answer['status'], answer['reading']) == ('stale', {})

    _workspace(tmp_path, attention='{not json', statements='7')
    assert service.attention(tmp_path, _moves)['status'] == 'unreadable'
    broken = service.statements(tmp_path)
    assert (broken['status'], broken['reading']) == ('unreadable', {})
    assert broken['detail']['error'] == 'AttributeError'


def test_a_name_reddit_did_not_answer_for_is_kept_as_unknown_not_dropped_as_quiet(tmp_path):
    scan = _scan('sentiment.json')
    quiet = next(row for row in scan['tickers'] if row['ticker'] == '00100')
    quiet.update(reddit_mentions_7d=None, reddit_status='failed', google_news_en=[],
                 google_news_zh=[])
    _workspace(tmp_path, attention=scan)
    answer = live.service('sentiment').attention(tmp_path, _moves)
    row = next(row for row in answer['reading']['tickers'] if row['ticker'] == '00100')
    assert row['reddit_mentions_7d'] is None and row['reddit_status'] == 'failed'
    assert answer['detail']['unanswered'] == 1


def _both(tmp_path, monkeypatch, capsys, moves=_moves):
    """(new, legacy), each as (reading, issues, console)."""
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    monkeypatch.setattr(brief_preflight, '_recent_price_moves', moves)
    sent_path = tmp_path / 'assets' / 'data' / 'sentiment.json'
    out = []
    for attention, statements in (
            (brief_preflight._sentiment_reading, brief_preflight.load_influencer_feed),
            (brief_preflight._legacy_sentiment_reading,
             brief_preflight._legacy_load_influencer_feed)):
        issues = []
        capsys.readouterr()
        readings = (attention(sent_path, 36, issues), statements(issues))
        out.append((readings, issues, capsys.readouterr().out))
    return out


def _raises(tickers):
    raise RuntimeError('bars store unreadable')


CASES = {
    'the scans as committed': dict(attention=_scan('sentiment.json'),
                                   statements=_scan('influencer_feed.json')),
    'both absent': {},
    'both a day and a half old': dict(attention=_scan('sentiment.json', hours=36.5),
                                      statements=_scan('influencer_feed.json', hours=36.5)),
    'just inside the window': dict(attention=_scan('sentiment.json', hours=35.4),
                                   statements=_scan('influencer_feed.json', hours=35.4)),
    'stamped in the future': dict(attention=_scan('sentiment.json', hours=-2.5),
                                  statements=_scan('influencer_feed.json', hours=-2.5)),
    'unstamped': dict(attention={'tickers': [{'ticker': 'X', 'reddit_mentions_7d': 5}]},
                      statements={'counts': {'held_hits': 1}}),
    'not json': dict(attention='{', statements='nope'),
    'the wrong shape': dict(attention=[1, 2], statements={'generated_at': _stamp(1.2),
                                                           'held_hits': [3]}),
    'an empty scan': dict(attention={'generated_at': _stamp(1.2)},
                          statements={'generated_at': _stamp(1.2)}),
    'reddit silent on every name': dict(
        attention=_scan('sentiment.json', tickers=[
            {'ticker': 'A', 'reddit_mentions_7d': None, 'reddit_status': 'failed'},
            {'ticker': 'B', 'reddit_mentions_7d': 0, 'reddit_status': 'ok'},
            {'ticker': 'C', 'reddit_mentions_7d': 3, 'reddit_posts': [{'title': 't', 'url': 'u', 'x': 1}],
             'google_news_zh': [{'title': None}, {'title': '标题'}]}]),
        statements=_scan('influencer_feed.json', counts={})),
}


@pytest.mark.parametrize('case', sorted(CASES))
def test_the_brief_loaders_answer_as_the_code_they_replaced(case, tmp_path, monkeypatch, capsys):
    _workspace(tmp_path, **CASES[case])
    new, legacy = _both(tmp_path, monkeypatch, capsys)
    assert new == legacy


def test_a_failing_price_lookup_is_reported_the_same_way(tmp_path, monkeypatch, capsys):
    _workspace(tmp_path, attention=_scan('sentiment.json'))
    new, legacy = _both(tmp_path, monkeypatch, capsys, moves=_raises)
    assert new == legacy
    assert new[1] == ['sentiment load exception: RuntimeError', 'influencer feed missing']


# ── a row that fails ────────────────────────────────────────────────────────

def _live_file(tmp_path, monkeypatch, changed):
    config = json.loads((ROOT / 'config' / 'strategy-plugins.json').read_text())
    config['live'] = changed(config['live'])
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'strategy-plugins.json').write_text(json.dumps(config))
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))


def test_a_row_that_does_not_import_stops_its_own_readers_and_nobody_elses(tmp_path, monkeypatch):
    def changed(live_rows):
        return [dict(row, module='clawock.strategies.plugins.no_such_module')
                if row['id'] == 'sentiment' else row for row in live_rows]
    _live_file(tmp_path, monkeypatch, changed)
    assert live.service('factors').describe() == {'sigma_target': 0.25}
    assert live.service('add_policy') is not None
    with pytest.raises(ValueError) as refused:
        live.service('sentiment')
    assert "no live row provides 'sentiment'" in str(refused.value)
    assert "'sentiment': \"ModuleNotFoundError" in str(refused.value)
    states = {row['id']: row['state'] for row in live.health()}
    assert states.pop('sentiment') == 'failed' and set(states.values()) == {'mounted'}


def test_a_row_with_a_refused_config_takes_down_only_what_declared_it_needs_it(tmp_path, monkeypatch):
    import sys
    dependent = types.ModuleType('needs_factors')
    dependent.inject = ('factors',)
    dependent.apply = lambda ctx, config: ctx.provide('needs_factors', ctx.get('factors'))
    monkeypatch.setitem(sys.modules, 'needs_factors', dependent)

    def changed(live_rows):
        return [dict(row, config={'sigma_target': 0}) if row['id'] == 'factors' else row
                for row in live_rows] + [{'id': 'dependent', 'module': 'needs_factors'}]
    _live_file(tmp_path, monkeypatch, changed)
    health = {row['id']: row for row in live.health()}
    assert health['factors']['state'] == 'failed' and 'sigma_target' in health['factors']['error']
    assert health['dependent']['state'] == 'waiting'
    assert health['dependent']['waiting_for'] == ['factors']
    assert live.service('daily_bars').describe() == {'adjustment': 'qfq'}
    assert live.service('bar_signals') is not None
    with pytest.raises(ValueError, match="rows not mounted: .*'dependent': \"waiting for"):
        live.service('needs_factors')


# ── events ──────────────────────────────────────────────────────────────────

def test_a_plugin_emits_only_what_it_declares_and_a_stopped_listener_hears_nothing():
    heard = []
    listener = types.SimpleNamespace(
        name='listener', apply=lambda ctx, config: ctx.on('tick', lambda n: heard.append(n) or n * 2))
    speaker = types.SimpleNamespace(name='speaker', emits=('tick',), apply=lambda ctx, config: (
        ctx.provide('speak', lambda n: ctx.emit('tick', n)),
        ctx.provide('mumble', lambda: ctx.emit('tock'))))
    kernel = Kernel()
    fiber = kernel.plugin(listener)
    kernel.plugin(speaker)
    assert kernel.get('speak')(3) == [6] and heard == [3]
    assert fiber.effects == ['on(tick)']
    with pytest.raises(KernelError, match="emits 'tock' without declaring it"):
        kernel.get('mumble')()
    fiber.dispose()
    assert kernel.get('speak')(4) == [] and heard == [3]
    assert kernel.emit('tick', 5) == []


def test_a_listener_can_refuse_what_it_hears_and_the_emitter_sees_the_refusal():
    def refuse(payload):
        raise ValueError(f'not {payload}')
    kernel = Kernel()
    kernel.on('ask', lambda payload: 'fine')
    stop = kernel.on('ask', refuse)
    with pytest.raises(ValueError, match='not this'):
        kernel.emit('ask', 'this')
    stop()
    assert kernel.emit('ask', 'this') == ['fine']


# ── recorded outputs ────────────────────────────────────────────────────────

def _recorded(tmp_path):
    factors = live.service('factors')
    score = rsi.scorer(factors)
    out = {'factors': {}, 'bar_signals': {}, 'rsi': {}}
    for ticker, series in BARS.items():
        out['factors'][ticker] = {
            str(cut): {'signals': factors.signals(series[:cut]),
                       'short_history': factors.short_history(series[:cut])}
            for cut in _cuts(series)}
        out['bar_signals'][ticker] = {
            str(index): bar_signals.bar_signal_row(series, index)
            for index in sorted({10, 25, 70, len(series) - 1})}
        out['rsi'][ticker] = {
            f'{period}/{direction}/{cut}': score(series[:cut], {'period': period, 'direction': direction})
            for period in rsi.SPACE['period'] for direction in rsi.SPACE['direction']
            for cut in (15, 40, len(series))}
    _workspace(tmp_path, attention=_scan('sentiment.json'), statements=_scan('influencer_feed.json'))
    service = live.service('sentiment')
    readings = {'attention': service.attention(tmp_path, _moves)['reading'],
                'statements': service.statements(tmp_path)['reading']}
    for reading in readings.values():
        del reading['as_of']  # the stamp is set relative to now by the fixture
    out['sentiment'] = readings
    return json.loads(json.dumps(out, ensure_ascii=False))


def _naive_sum(values, start=0):
    """`sum` as Python 3.11 computes it: left to right, no compensation."""
    total = start
    for value in values:
        total += value
    return total


def _flat(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _flat(value, path + (key,))
    else:
        yield '/'.join(path), node


def _expected(naive: bool):
    """The recorded outputs for this interpreter's `sum`.

    Python 3.12 made `sum` of floats compensated. The factor row rounds moving
    averages to three places, and a sum that lands on a rounding boundary goes
    one way under 3.11 and the other from 3.12 on. The desk host runs 3.12 and
    CI runs 3.11, so both are recorded: `goldens.json` is the compensated sum,
    and `naive_sum` lists the cells that read differently without it.
    """
    document = json.loads(GOLDENS.read_text())
    expected = document['outputs']
    if naive:
        for pointer, value in document['naive_sum'].items():
            *parents, leaf = pointer.split('/')
            node = expected
            for key in parents:
                node = node[key]
            node[leaf] = value
    return expected


COMPENSATED = sys.version_info >= (3, 12)


def test_every_signal_source_still_computes_its_recorded_outputs(tmp_path, monkeypatch):
    recorded = _recorded(tmp_path)
    monkeypatch.setattr(quant_factors, 'sum', _naive_sum, raising=False)
    naive = _recorded(tmp_path)
    monkeypatch.undo()
    if os.environ.get('CLAWOCK_WRITE_GOLDENS') == '1':
        assert COMPENSATED, 'record on the interpreter the desk host runs (3.12 or later)'
        differs = {pointer: value for (pointer, value), (_, native)
                   in zip(_flat(naive), _flat(recorded)) if value != native}
        GOLDENS.write_text(json.dumps({'outputs': recorded, 'naive_sum': differs},
                                      ensure_ascii=False, indent=1, sort_keys=True) + '\n')
    for label, got, expected in (('this interpreter', recorded, _expected(not COMPENSATED)),
                                 ('left-to-right sum', naive, _expected(True))):
        for source in expected:
            for key in expected[source]:
                assert got[source][key] == expected[source][key], f'{label}: {source} {key} moved'
        assert got == expected, label


def test_the_two_summations_differ_only_in_the_last_place_of_a_rounded_average():
    document = json.loads(GOLDENS.read_text())
    assert document['naive_sum'], 'no cell depends on the summation: drop the second record'
    recorded = dict(_flat(document['outputs']))
    for pointer, value in document['naive_sum'].items():
        assert pointer.split('/')[0] == 'factors', pointer
        assert abs(value - recorded[pointer]) <= 0.0011, (pointer, value, recorded[pointer])
