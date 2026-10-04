from clawock.harness import _watchdog_common as common
from clawock.providers.openclaw import CronRead


def test_run_source_survives_the_common_wrapper(monkeypatch):
    monkeypatch.setattr(common._openclaw, 'read_runs', lambda *a: CronRead([], 'empty'))
    assert common.today_runs('job') == []
    assert common.LAST_RUNS_SOURCE == 'empty'


def test_unreadable_evidence_is_named_and_recorded(monkeypatch):
    from clawock.automation import workflow_outcomes
    events, notes = [], []
    monkeypatch.setattr(common, 'log', events.append)
    monkeypatch.setattr(workflow_outcomes, 'note_degradation', lambda *a, **kw: notes.append((a, kw)))
    for source in ('fossil', 'empty'):
        assert common.cron_evidence_unreadable(source, tag='hk-close')
    assert len(notes) == 2 and all(e['action'] == 'scheduler-unreadable' for e in events)
    assert not common.cron_evidence_unreadable('sqlite', tag='hk-close')
    common.cron_evidence_unreadable('empty', tag='hk-close', dry_run=True)
    assert len(notes) == 2


def test_report_watchdog_does_not_claim_no_run_when_scheduler_is_unreadable(monkeypatch):
    import sys
    from clawock.harness import report_watchdog
    monkeypatch.setattr(common._openclaw, 'read_jobs', lambda *a: CronRead([], 'empty'))
    events = []
    monkeypatch.setattr(common, 'log', events.append)
    monkeypatch.setattr(report_watchdog, 'log', events.append)
    monkeypatch.setattr(sys, 'argv', ['watchdog', '--market', 'hk', '--phase', 'mid',
                                    '--job-name', 'job', '--dry-run'])
    assert report_watchdog.main() == 0
    assert events[-1]['action'] == 'scheduler-unreadable'
    assert not any('job not found' in e.get('reason', '') for e in events)
