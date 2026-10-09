"""Shared bad-tick, refresh and consumer-session contracts (#2798–#2802)."""
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawock.decision import regime, setups, signals
from clawock.harness import artifacts, brief_preflight, deadline
from clawock.market_data import peer_quotes, tencent_daily


def bars():
    return [{'date': (date(2026, 8, 1) + timedelta(days=i)).isoformat(),
             'open': 100 + i, 'close': 100 + i, 'high': 101 + i, 'low': 99 + i}
            for i in range(45)]


@pytest.mark.parametrize('bad', [None, 'bad', 0, '0.00', -1, float('nan'), float('inf')])
def test_shared_price_policy_preserves_valid_rows_and_peer_return(monkeypatch, bad):
    rows = [[f'2026-10-0{i+1}', 10, c, 12, 9]
            for i, c in enumerate([10, 10.2, 10.1, bad, 10.7, 11, 11.2])]
    monkeypatch.setattr(peer_quotes.requests, 'get', lambda *a, **k: SimpleNamespace(
        json=lambda: {'data': {'hkTEST': {'qfqday': rows}}}))
    result = {}
    peer_quotes._apply_pct_5d(result, 'hkTEST')
    assert result == {'pct_5d': 12.0}
    assert [b['close'] for b in signals._parse_bars(rows)] == [
        c for _, c in tencent_daily.parse_daily_closes(rows)]


@pytest.mark.parametrize('where', [20, 35, 44])
@pytest.mark.parametrize('bad', [0, -1, float('nan'), float('inf')])
def test_quant_direct_calls_and_refresh_share_bad_tick_policy(where, bad):
    raw = bars()
    raw[where]['close'] = bad
    clean = raw[:where] + raw[where+1:]
    assert signals.compute_signals(raw) == signals.compute_signals(clean)
    detail = {'label': 'TEST', 'code': 'usTEST', 'region': 'US',
              'source_holdings': ['TEST'], 'is_leveraged_etf': False}
    rows = signals.refresh_rows({}, [detail], run_date=date(2026, 9, 15),
                                expected_sessions={'US': date(2026, 9, 14)},
                                fetcher=lambda _: raw)
    assert rows['TEST']['close'] == clean[-1]['close']
    assert rows['TEST']['row_as_of'] == clean[-1]['date']
    assert rows['TEST']['status'] == ('stale' if where == 44 else 'fresh')


def test_quant_no_usable_bars_publishes_missing_row():
    raw = bars()
    for b in raw:
        b['close'] = 0
    assert signals.compute_signals(raw) is None
    assert signals.compute_short_history_signals(raw) is None
    detail = {'label': 'TEST', 'code': 'usTEST', 'region': 'US',
              'source_holdings': ['TEST'], 'is_leveraged_etf': False}
    rows = signals.refresh_rows({}, [detail], fetcher=lambda _: raw)
    assert rows['TEST']['status'] == 'missing'
    assert regime.compute([0, -1, float('nan'), float('inf')]) == (None, None)


@pytest.mark.parametrize('node,file,empty', [
    ('regime_node', 'lev_regime.json', None),
    ('quant_node', 'quant_signals.json', {}),
    ('quant_review_node', 'quant_signal_review.json', {}),
    ('t0_node', 't0_setups.json', {}),
    ('t0_review_node', 't0_setup_review.json', {}),
    ('portfolio_risk_node', 'risk.json', {}),
    ('cross_factor_node', 'cross_sectional_factor.json', {}),
    ('peer_residual_node', 'peer_residual.json', {}),
])
@pytest.mark.parametrize('failure', ['exit', 'timeout', 'no_write'])
def test_artifact_nodes_do_not_consume_recovery_files(tmp_path, monkeypatch, node, file, empty, failure):
    path = tmp_path / 'assets/data' / file
    path.parent.mkdir(parents=True)
    original = json.dumps({'tier': 'amber', 'lev_cap_mult': .5, 'as_of': '2026-10-07'})
    path.write_text(original)
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)

    def run(cmd, **kw):
        assert kw['check'] is True
        if failure == 'exit':
            raise subprocess.CalledProcessError(1, cmd, stderr='fixture error')
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(cmd, kw['timeout'])
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(artifacts.subprocess, 'run', run)
    args = ({'portfolios': {}},) if node in {'cross_factor_node', 'peer_residual_node'} else ()
    assert getattr(brief_preflight, node)(*args) == (empty, [])
    assert path.read_text() == original


@pytest.mark.parametrize('as_of,accepted', [('2026-10-08', True), ('2026-10-07', False), (None, False)])
def test_regime_rewrite_also_requires_latest_completed_session(tmp_path, monkeypatch, as_of, accepted):
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    monkeypatch.setattr(brief_preflight.trading_calendar, 'latest_completed_session',
                        lambda _: date(2026, 10, 8))
    payload = {'as_of': as_of, 'tier': 'amber', 'lev_cap_mult': .5}
    monkeypatch.setattr(brief_preflight, 'refresh_json', lambda *a, **k: payload)
    assert brief_preflight.regime_node() == (payload if accepted else None, [])


@pytest.mark.parametrize('region,symbol,holding,expected', [
    ('hk', 'HSTECH', '07226', date(2026, 10, 8)),
    ('us', 'SPCX', 'SPCH', date(2026, 10, 9)),
])
@pytest.mark.parametrize('source,status,usable', [
    ('expected', 'fresh', True), ('old', 'fresh', False),
    ('future', 'fresh', False), ('expected', 'stale', False),
    (None, 'fresh', False), ('legacy', None, True),
])
def test_t0_atr_uses_signal_symbol_and_completed_market_session(
        tmp_path, monkeypatch, region, symbol, holding, expected, source, status, usable):
    p = tmp_path / 'portfolio.json'
    p.write_text(json.dumps({'portfolios': {'book': {'holdings': [{
        'ticker': holding, 'shares': 1, 'current_price': 11, 'prev_close': 10,
        'day_high': 12, 'day_low': 10, 'day_open': 10}]}}}))
    q = tmp_path / 'quant.json'
    day = (expected if source in {'expected', 'legacy'} else
           expected - timedelta(days=1) if source == 'old' else
           expected + timedelta(days=1) if source == 'future' else None)
    row = {'status': status, 'atr14_pct': 4, 'rsi14': 25}
    if source != 'legacy':
        row['row_as_of'] = day.isoformat() if day else None
    q.write_text(json.dumps({'as_of': expected.isoformat(), 'rows': {symbol: row}}))
    monkeypatch.setattr(setups, 'PORTFOLIO', p)
    monkeypatch.setattr(setups, 'QUANT', q)
    monkeypatch.setattr(setups.tc, 'in_session', lambda _: True)
    monkeypatch.setattr(setups.tc, 'latest_completed_session', lambda market: expected)
    monkeypatch.setattr(setups.tc, '_today_in_market', lambda _: expected + timedelta(days=1))
    result = setups.compute()['rows'][holding]
    assert result['atr14_pct'] == (4 if usable else None)
    assert result['range_used_atr'] == (5.0 if usable else None)
    assert result['quant_status'] == ('fresh' if usable else 'unavailable')
    assert result['quant_as_of'] == (day.isoformat() if day else None)


def test_preflight_timeout_replaces_success_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    monkeypatch.setattr(brief_preflight, 'TMP_DIR', tmp_path / 'memory/.tmp')
    monkeypatch.setenv('TODAY', '2026-10-09')
    path = tmp_path / 'memory/.tmp/brief-context-2026-10-09.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'date': '2026-10-09', 'decision_packet': {'old': True}}))
    def timeout(*args, **kw):
        assert kw['timeout'] == 600
        assert kw['env']['TODAY'] == '2026-10-09'
        raise subprocess.TimeoutExpired(args[0], kw['timeout'])
    monkeypatch.setattr(brief_preflight, 'run_bounded', timeout)
    monkeypatch.setattr(brief_preflight.workflow_outcomes, 'record_stage', lambda *a, **k: None)
    assert brief_preflight.main([]) == 1
    payload = json.loads(path.read_text())
    assert payload['status'] == 'preflight_timeout'
    assert 'decision_packet' not in payload
    assert (path.with_suffix('') / 'manifest.json').exists()


@pytest.mark.skipif(os.name != 'posix', reason='process-group supervision on POSIX')
def test_deadline_kills_nested_writer(tmp_path):
    pid_path = tmp_path / 'pid'
    code = ('import subprocess,sys,time; '
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
            f'open({str(pid_path)!r},"w").write(str(p.pid)); time.sleep(60)')
    with pytest.raises(subprocess.TimeoutExpired):
        deadline.run_bounded([sys.executable, '-c', code], timeout=.5, cwd=tmp_path)
    assert pid_path.exists()
    stat = Path('/proc') / pid_path.read_text() / 'stat'
    # A killed grandchild can briefly remain a zombie awaiting init's reap.
    if stat.exists():
        assert stat.read_text().split()[2] == 'Z'


def test_brief_contract_rejects_old_turn_that_cannot_hold_supervised_preflight(tmp_path):
    import shutil
    from clawock import scheduling
    root = Path(__file__).resolve().parents[1]
    config = tmp_path / 'config'
    config.mkdir()
    data = json.loads((root / 'config/cron-schedules.json').read_text())
    data['payload_profiles']['brief']['timeout_seconds'] = 1800
    path = config / 'cron-schedules.json'
    path.write_text(json.dumps(data))
    shutil.copytree(root / 'config/cron-payloads', config / 'cron-payloads')
    with pytest.raises(ValueError, match='pre-delivery reserve'):
        scheduling.load_contract(path, workspace=tmp_path)
