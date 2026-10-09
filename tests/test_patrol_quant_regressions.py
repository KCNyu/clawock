"""Provider bad rows and failed refreshes must not masquerade as fresh quant."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from clawock.decision import regime, signals
from clawock.evaluation import us_leverage
from clawock.harness import brief_preflight


ROWS = [
    ['2026-10-04', '1.1', None, '2.0', '1.0'],
    ['2026-10-05', '1.1', 'bad', '2.0', '1.0'],
    ['2026-10-06', '1.1', '1.9', '2.0', '1.0'],
    None, {}, ['2026-10-07'],
]


def test_quant_and_evaluation_skip_bad_kline_rows(monkeypatch):
    monkeypatch.setattr(signals.requests, 'get', lambda *a, **k: SimpleNamespace(
        json=lambda: {'data': {'usTEST': {'qfqday': ROWS}}}))
    assert signals.fetch_bars('usTEST') == [
        {'date': '2026-10-06', 'open': 1.1, 'close': 1.9, 'high': 2.0, 'low': 1.0}]
    assert us_leverage.fetch('usTEST') == [('2026-10-06', 1.9)]


def test_regime_reads_string_shares_without_rewriting_ledger(tmp_path, monkeypatch):
    path = tmp_path / 'portfolio.json'
    holdings = [{'ticker': 'SPCH', 'shares': '300'},
                {'ticker': 'RKLX', 'shares': '0'},
                {'ticker': 'PLTU', 'shares': 'bad'},
                {'ticker': 'ROBN', 'shares': None}]
    original = json.dumps({'portfolios': {'book': {'holdings': holdings}}})
    path.write_text(original)
    monkeypatch.setattr(regime, 'PORTFOLIO', path)
    assert regime._held_us_lev_etfs() == ['SPCH']
    assert path.read_text() == original


@pytest.mark.parametrize('failure', ['exit', 'timeout'])
def test_quant_failure_omits_old_fresh_rows(tmp_path, monkeypatch, capsys, failure):
    path = tmp_path / 'assets/data/quant_signals.json'
    path.parent.mkdir(parents=True)
    original = json.dumps({'rows': {'TEST': {'status': 'fresh', 'tag': 'old'}}})
    path.write_text(original)
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)

    def run(cmd, **kwargs):
        assert kwargs['check'] is True
        if failure == 'exit':
            raise subprocess.CalledProcessError(1, cmd, stderr='fixture quant error')
        raise subprocess.TimeoutExpired(cmd, 120)

    monkeypatch.setattr(brief_preflight.subprocess, 'run', run)
    assert brief_preflight.quant_node() == ({}, [])
    output = capsys.readouterr().out
    assert 'compute failed' in output
    assert 'fresh symbols' not in output
    assert path.read_text() == original


def test_quant_success_consumes_current_rows(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'assets/data/quant_signals.json'
    path.parent.mkdir(parents=True)
    payload = {'rows': {'TEST': {'status': 'fresh', 'tag': 'current'}}}
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    def run(*a, **k):
        path.unlink()
        path.write_text(json.dumps(payload))
        return subprocess.CompletedProcess(a[0], 0)
    monkeypatch.setattr(brief_preflight.subprocess, 'run', run)
    assert brief_preflight.quant_node() == (payload, [])
    assert '1 fresh symbols' in capsys.readouterr().out
