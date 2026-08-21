"""An unreadable cron contract must not silence the brief watchdog (#775).

`_brief_job_names` is the only place in the running system that touches the
schedule contract on a watchdog's behalf, and it sat behind a bare
`except Exception: return set()`. Empty means `brief_cron_job()` returns None,
which switches off the re-run and retry-budget limbs entirely — the exact
"discovery gate that quietly discovers nothing" this repository keeps having to
re-learn. It still degrades rather than crashing a cron slot; it just has to say
so.

The exception path is the whole point here: #768 was a fallback handler that had
been dead since the day it was written, because nothing ever executed it. This
test executes it.
"""
from clawock.harness import _watchdog_common


def test_unreadable_contract_is_logged_not_swallowed(monkeypatch):
    written = []
    monkeypatch.setattr(_watchdog_common, 'log', written.append)

    def explode():
        raise FileNotFoundError('cron contract not found: /root/config/cron-schedules.json')

    monkeypatch.setattr('clawock.scheduling.load_contract', explode)

    assert _watchdog_common._brief_job_names() == set()

    assert len(written) == 1, 'contract failure left no trace at all'
    event = written[0]
    assert event['action'] == 'contract-unreadable'
    assert 'FileNotFoundError' in event['error']
    assert event['effect'], 'the trace must say what stopped working, not just that it failed'


def test_a_readable_contract_logs_nothing(monkeypatch):
    """The trace is for the failure, not a per-slot heartbeat."""
    written = []
    monkeypatch.setattr(_watchdog_common, 'log', written.append)

    names = _watchdog_common._brief_job_names()

    assert names, 'the tracked contract still has to name the daily deep brief'
    assert written == []
