"""Public preflights record unhandled collector exits outside the worker."""
from datetime import datetime, timezone
import signal
import sys

import pytest

from clawock.automation import workflow_outcomes as outcomes
from clawock.harness import deadline, intraday_preflight, report_preflight


@pytest.mark.parametrize('entry,args', [
    (intraday_preflight, ['--market', 'hk']),
    (report_preflight, ['--market', 'hk', '--phase', 'open']),
])
@pytest.mark.parametrize('exit_code', [1, -signal.SIGKILL])
def test_public_preflight_records_death(entry, args, exit_code, tmp_path, monkeypatch):
    monkeypatch.setattr(outcomes, 'slot_for_job', lambda job, at=None: (at or datetime.now(timezone.utc)).isoformat())
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    monkeypatch.setattr(entry, 'WS', tmp_path)
    monkeypatch.setattr(entry, 'TMP', tmp_path / 'memory' / '.tmp')
    monkeypatch.setattr(entry, 'slot_shipped', lambda *a, **kw: False)

    def worker(command, **kwargs):
        assert '_collect' in command[3]
        assert kwargs['env']['CLAWOCK_PREFLIGHT_STARTED_AT']
        return deadline.run_bounded_original(
            [sys.executable, '-c', f'import os,signal; os.kill(os.getpid(), {-exit_code})'
             if exit_code < 0 else 'raise TypeError("collector crash")'],
            timeout=5, cwd=tmp_path)

    monkeypatch.setattr(deadline, 'run_bounded_original', deadline.run_bounded, raising=False)
    monkeypatch.setattr(deadline, 'run_bounded', worker)
    assert entry.main(args) == exit_code
    row = outcomes.load_ledger()['records'][0]
    assert row['stages']['preflight']['reason'] == 'preflight_crashed'
    assert row['stages']['preflight']['return_code'] == exit_code
    assert row['final_product']['status'] == 'failed'


def test_supervisor_preserves_worker_terminal_and_shipped_slots(tmp_path, monkeypatch):
    monkeypatch.setattr(outcomes, 'slot_for_job', lambda job, at=None: (at or datetime.now(timezone.utc)).isoformat())
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    now = datetime.now(timezone.utc)
    slot = now.isoformat()

    def worker(*args, **kwargs):
        outcomes.record_stage('test', 'preflight', 'warning', slot=slot, reason='known warning')
        return 1

    monkeypatch.setattr(deadline, 'run_bounded', worker)
    deadline.supervise_preflight('clawock.harness.report_preflight', [], workspace=tmp_path,
                                 job='test', slot=slot, started=now, shipped=False)
    assert outcomes.load_ledger()['records'][0]['stages']['preflight']['reason'] == 'known warning'
    monkeypatch.setattr(deadline, 'run_bounded', lambda *a, **kw: -9)
    deadline.supervise_preflight('clawock.harness.report_preflight', [], workspace=tmp_path,
                                 job='test', slot=slot, started=now, shipped=True)
    assert outcomes.load_ledger()['records'][0]['stages']['preflight']['reason'] == 'known warning'
