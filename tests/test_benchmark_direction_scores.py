"""Same-window pairing, sell signs and episode denominators (#2854)."""
import copy

import pytest

from clawock.decision import ledger


def call(episode, benefit, *, action='hold_and_watch', start='2026-08-10', end='2026-08-11', leg='US'):
    return {'episode_id': episode, 'decision_id': f'{episode}-{start}',
            'plan_date': start, 'action': action, 'leg': leg,
            'execution': {'status': 'followed'},
            'evaluation': {'triggered': True, 'benefit_t1_pct': benefit,
                           'benefit_t5_pct': benefit, 'trigger_session': start,
                           'mark_t1_session': end, 'mark_t5_session': end,
                           'mark_horizon': 'open_of_session_to_close_of_next_session',
                           'reference_reason': 'first_tradable_price_after_publication',
                           'fill_reason': 'session_open'}}


def benchmark():
    return {'series': {'SPY': [
        {'date': '2026-08-10', 'open': 100, 'close': 90},
        {'date': '2026-08-11', 'open': 200, 'close': 95},
        {'date': '2026-08-12', 'open': 99, 'close': 220}],
        'HSI': [{'date': '2026-08-10', 'open': 100},
                {'date': '2026-08-11', 'close': 102}],
        'HSTECH': [{'date': '2026-08-10', 'open': 100},
                   {'date': '2026-08-11', 'close': 150}]}}


def test_pair_calls_before_episode_mean_and_disclose_partial_coverage():
    rows = [call('repeat', -3), call('repeat', 12, start='2026-08-11', end='2026-08-12'),
            call('repeat', 99, start='2026-01-01'), call('missing', 50, start='2026-01-01')]
    before = copy.deepcopy(rows)
    result = ledger.compute_backtest(rows, benchmark=benchmark())['horizons']['t1']['passive']
    assert result['excess_benefit_pct'] == 2  # mean(-3 - -5, 12 - 10), NOT first-window pairing
    assert result['benchmark_coverage_pct'] == 50
    assert result['benchmark_call_coverage_pct'] == 50
    assert result['benchmark_paired_calls'] == 2
    assert result['benchmark_excluded_calls'] == {'missing_benchmark_endpoints': 2}
    assert result['avg_benefit_pct'] == 43
    assert rows == before


def test_sells_reverse_the_index_sign_and_hk_always_uses_hsi():
    rows = [call('sell', 3, action='cut'), call('hk', 4, leg='HK')]
    result = ledger.compute_backtest(rows, benchmark=benchmark())['horizons']
    for horizon in ('t1', 't5'):
        assert result[horizon]['active']['excess_benefit_pct'] == -2
        assert result[horizon]['passive']['excess_benefit_pct'] == 2
        assert result[horizon]['followed']['excess_benefit_pct'] == 0
        assert result[horizon]['followed_active']['excess_benefit_pct'] == -2


@pytest.mark.parametrize('opening', [None, 0, -1, float('nan'), float('inf'), True])
def test_missing_or_invalid_opens_never_use_close_as_a_proxy(opening):
    bm = benchmark()
    bm['series']['SPY'][0]['open'] = opening
    result = ledger.compute_backtest([call('one', 3)], benchmark=bm)['horizons']['t1']['all']
    assert result['excess_benefit_pct'] is None
    assert result['benchmark_coverage_pct'] == 0


def test_intraday_fills_cannot_be_paired_to_daily_open_and_legacy_is_uncovered():
    intraday = call('intraday', 3, action='add')
    intraday['evaluation']['fill_reason'] = 'intraday_cross'
    legacy = call('legacy', 2)
    legacy['evaluation'].pop('mark_horizon')
    result = ledger.compute_backtest([intraday, legacy], benchmark=benchmark())['horizons']['t1']['all']
    assert result['excess_benefit_pct'] is None
    assert result['benchmark_excluded_calls'] == {'intraday_or_unknown_fill': 1, 'unknown_window': 1}


def test_empty_buckets_have_explicit_unavailable_fields():
    result = ledger.compute_backtest([], benchmark={})['horizons']['t1']
    for name in ('all', 'active', 'passive', 'followed', 'followed_active'):
        assert result[name]['excess_benefit_pct'] is None
        assert result[name]['benchmark_coverage_pct'] is None


def test_cli_reports_missing_and_present_coverage(monkeypatch, capsys):
    from clawock.decision import audit
    result = ledger.compute_backtest([call('one', 3)], benchmark=benchmark())
    monkeypatch.setattr(ledger, 'load_decisions', lambda: [])
    monkeypatch.setattr(ledger, 'compute_backtest', lambda rows: result)
    assert audit.main([]) == 0
    output = capsys.readouterr().out
    assert '相对 8.0pp' in output
    assert 'episode覆盖 100.0% (1/1)' in output
    assert 'call覆盖 100.0% (1/1)' in output
