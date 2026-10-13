"""Runtime failure isolation, row replacement, and explicit missing readings."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from clawock.plugin_host import live
from clawock.plugin_host.kernel import Kernel, PENDING
from clawock.strategies.plugins import morning_scans, sentiment
from clawock.strategy_lab import boundaries
from clawock.strategy_lab.plugins import row_edits, strategy_scores


def test_late_provider_survives_a_reader_that_fails_after_providing():
    kernel = Kernel()

    def broken(ctx, config):
        ctx.provide('partial', object())
        raise ValueError('reader config rejected')

    bad = kernel.plugin(SimpleNamespace(name='bad-reader', inject=('source',), apply=broken))
    downstream = kernel.plugin(SimpleNamespace(
        name='downstream', inject=('partial',),
        apply=lambda ctx, config: ctx.provide('dependent', object())))
    kernel.plugin(SimpleNamespace(name='source', apply=lambda ctx, config: ctx.provide('source', 42)))
    assert kernel.get('source') == 42
    assert kernel.services() == {'source': 'source'}
    assert bad.error == 'ValueError: reader config rejected'
    assert downstream.state == PENDING and downstream.missing == ['partial']
    kernel.dispose()
    assert kernel.services() == {}


def test_policy_consumers_follow_replaced_rows_and_fail_with_dependencies(tmp_path, monkeypatch):
    import sys
    from clawock.strategies.plugins import add_side
    policy = SimpleNamespace(name='custom-policy', apply=lambda ctx, config: ctx.provide(
        'add_policy', SimpleNamespace(size_cap_text=lambda p: 'custom sizing')))
    monkeypatch.setitem(sys.modules, 'audit_policy', policy)
    path = tmp_path / 'config' / 'strategy-plugins.json'
    path.parent.mkdir()
    rows = [dict(row, module='audit_policy') if row['id'] == 'add-policy' else row
            for row in live.DEFAULT_ROWS]
    path.write_text(json.dumps({'live': rows}))
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    # Replacing the row changes the internal caller as well as external readers.
    assert add_side._size_cap({}) == 'custom sizing'
    live.kernel().fibers[next(i for i, f in enumerate(live.kernel().fibers)
                             if f.name == 'custom-policy')].dispose()
    states = {row['id']: row for row in live.health()}
    assert states['add-side']['state'] == 'waiting'
    assert states['add-alpha']['state'] == 'waiting'
    assert states['preposition']['state'] == 'waiting'
    assert live.service('sentiment') is not None


@pytest.mark.parametrize('module', [sentiment, morning_scans])
def test_exact_scan_age_boundaries(module):
    service = module.Sentiment(36) if module is sentiment else module.Scans(36)
    assert not service.is_stale(36)
    assert service.is_stale(36 + 1 / 3600)
    assert not service.is_stale(-2)
    assert service.is_stale(-2 - 1 / 3600)
    assert service.is_stale(None)


@pytest.mark.parametrize('module', [sentiment, morning_scans, row_edits])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_thresholds_refuse_mount(module, value):
    key = 'min_prospective_sessions' if module is row_edits else 'stale_after_hours'
    with pytest.raises(ValueError):
        Kernel().plugin(module, {key: value})


def test_nonfinite_promotion_evidence_cannot_bypass_ledger_floor():
    record = {'strategy': 'x', 'to_params': {'p': 2}, 'from_params': {'p': 1},
              'after_session': '2026-01-01', 'live_permission': False, 'status': 'proposed',
              'evidence': {'sessions': float('nan'), 'ic_ci95': [.1, .2],
                           'first_session': '2026-01-02'}}
    registration = {'strategy': 'x', 'params': {'p': 2}, 'after_session': '2026-01-01'}
    with pytest.raises(boundaries.BoundaryError, match='under the floor'):
        boundaries.check_row_edit(record, [registration])


def test_statements_never_republish_retained_scores(tmp_path):
    path = tmp_path / sentiment.STATEMENTS_FILE
    path.parent.mkdir(parents=True)
    payload = {'generated_at': datetime.now(timezone.utc).isoformat(),
               'llm_filter_status': 'ok', 'held_hits': [
                   {'author': 'old', 'relevance': 80, 'retained_from_previous': True},
                   {'author': 'new', 'relevance': 70}]}
    path.write_text(json.dumps(payload))
    answer = sentiment.Sentiment(36).statements(tmp_path)
    assert [r['author'] for r in answer['reading']['held_hits']] == ['new']
    assert answer['reading']['degraded'] == ['retained prior statements omitted']
    payload['llm_filter_status'] = 'failed_kept_previous'
    path.write_text(json.dumps(payload))
    answer = sentiment.Sentiment(36).statements(tmp_path)
    assert answer['status'] == 'unreadable' and answer['reading'] == {}


def test_strategy_scores_no_store_is_unavailable(tmp_path):
    config = tmp_path / 'config' / 'strategy-plugins.json'
    config.parent.mkdir()
    config.write_text(json.dumps({'schema_version': 1, 'plugins': [
        {'module': 'clawock.strategies.registry'}]}))
    answer = strategy_scores.StrategyScores().read(tmp_path)
    assert answer['status'] == 'unavailable'
    assert 'no usable bar series' in answer['reason']


@pytest.mark.parametrize('value', [None, {}, 'bad'])
def test_present_invalid_live_config_never_uses_defaults(tmp_path, value):
    path = tmp_path / 'rows.json'
    path.write_text(json.dumps({'live': value}))
    with pytest.raises(ValueError, match='live must be a list'):
        live.rows(path)


def test_scores_stale_series_and_missing_names_are_explicit(tmp_path, monkeypatch):
    config = tmp_path / 'config' / 'strategy-plugins.json'
    config.parent.mkdir()
    config.write_text(json.dumps({'schema_version': 1, 'plugins': [
        {'module': 'clawock.strategies.registry'},
        {'module': 'clawock.strategies.plugins.quant_factors'},
        {'module': 'clawock.strategies.plugins.rsi'}]}))
    store = tmp_path / 'memory/bars'
    store.mkdir(parents=True)
    bars = {f'2026-09-{i:02d}': {'close': 100 + i} for i in range(1, 26)}
    (store / 'OLD.json').write_text(json.dumps({'bars': bars, 'leg': 'US'}))
    monkeypatch.setattr(strategy_scores, 'latest_completed_session',
                        lambda *a, **kw: SimpleNamespace(isoformat=lambda: '2026-10-12'))
    reading = strategy_scores.StrategyScores().read(tmp_path, ['OLD', 'ABSENT'])
    block = reading['strategies']['rsi']
    assert block['ranked'] == 0
    for row in block['rows'].values():
        assert row['score'] is None and row['rank'] is None and row['reason']
    assert block['measurement']['outputs'][0]['unit'].startswith('RSI points')


def test_zero_momentum_is_measured_zero_not_declared_missing():
    from clawock.strategies.plugins import quant_factors
    bars = [{'close': 10, 'open': 10, 'high': 11, 'low': 9} for _ in range(130)]
    reading = quant_factors.compute_signals(bars)
    assert [reading[key] for key in ('mom_1m', 'mom_3m', 'mom_6m')] == [0, 0, 0]
    assert all('measured zero' in row['missing'] for row in quant_factors.SIGNAL_SOURCE['outputs']
               if row['field'] in ('mom_1m', 'mom_3m', 'mom_6m'))


def test_a_service_registered_by_a_later_event_wakes_its_readers():
    kernel = Kernel()
    kernel.plugin(SimpleNamespace(name='waiting', inject=('late',),
                                  apply=lambda ctx, config: ctx.provide('answer', ctx.get('late'))))
    kernel.plugin(SimpleNamespace(name='event-source', apply=lambda ctx, config: ctx.on(
        'ready', lambda value: ctx.provide('late', value))))
    kernel.emit('ready', 42)
    assert kernel.get('answer') == 42
    kernel.dispose()
    assert kernel.services() == {}
