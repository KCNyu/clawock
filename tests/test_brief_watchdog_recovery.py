"""The final local rerun has an outcome owner independent of alert dedupe."""
import json
from datetime import datetime

import pytest

from clawock.harness import brief_watchdog as watchdog

TODAY = '2026-10-19'


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, 'WS', tmp_path)
    now = datetime(2026, 10, 19, 9, 50, tzinfo=watchdog.HKT)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(watchdog, 'datetime', Clock)
    start = int(now.replace(hour=9, minute=5).timestamp() * 1000)
    state = watchdog.load_missing_state(TODAY)
    state.update(rerun_inflight=True, notification_succeeded=True,
                 fallback_dispatch_attempted=True, local_rerun_after_ms=start)
    watchdog.write_missing_state(TODAY, state)
    (tmp_path / 'memory/.tmp' / f'watchdog-brief-missing-{TODAY}.done').write_text('alerted')
    job = {'state': {'lastRunAtMs': start + 1000, 'lastStatus': 'error'}}
    monkeypatch.setattr(watchdog, '_safe_brief_cron_job_state', lambda: job)
    monkeypatch.setattr(watchdog, 'telegram_target', lambda: 'target')
    messages, dispatches = [], []
    monkeypatch.setattr(watchdog, 'send_telegram',
                        lambda _, msg, dry: (messages.append(msg) or True, 'sent'))
    monkeypatch.setattr(watchdog, 'log', lambda event: None)

    def dispatch(dry):
        if not dry:
            assert watchdog.load_missing_state(TODAY)['recovery_dispatch_attempted']
        dispatches.append(dry)
        return True, 'queued'

    monkeypatch.setattr(watchdog, 'dispatch_brief_fallback', dispatch)
    monkeypatch.setattr(watchdog, 'await_brief_fallback_outcome',
                        lambda *a, **k: ('success', 'confirmed workflow receipt'))
    return tmp_path, job, messages, dispatches, start


def test_ended_local_rerun_dispatches_and_reports_despite_alert_flag(recovery):
    _, _, messages, dispatches, _ = recovery
    assert watchdog.check_local_recovery(TODAY) == 0
    assert dispatches == [False] and 'off-host 兜底已完成' in messages[0]
    watchdog.check_local_recovery(TODAY)
    assert len(dispatches) == len(messages) == 1


@pytest.mark.parametrize('evidence', ['running', 'old', 'unknown'])
def test_no_second_writer_without_selected_run_ending(recovery, evidence):
    _, job, messages, dispatches, start = recovery
    if evidence == 'running':
        job['state']['runningAtMs'] = start
    elif evidence == 'old':
        job['state']['lastRunAtMs'] = start - 1000
    else:
        job.clear()
    watchdog.check_local_recovery(TODAY)
    assert not dispatches and '未确认' in messages[0]


def test_produced_brief_reports_delivery_evidence_without_dispatch(recovery):
    root, _, messages, dispatches, _ = recovery
    (root / 'memory' / f'{TODAY}-pre-open.md').write_text('# brief')
    (root / 'memory' / f'{TODAY}-plan.json').write_text(json.dumps(
        {'decisions': [{'action': 'hold_and_watch'}]}))
    watchdog.check_local_recovery(TODAY)
    assert not dispatches
    assert '已生成产物' in messages[0] and '微信送达：未确认' in messages[0]


def test_dry_run_leaves_recovery_state_unchanged(recovery):
    path = watchdog.missing_state_path(TODAY)
    before = path.read_bytes()
    watchdog.check_local_recovery(TODAY, dry_run=True)
    assert path.read_bytes() == before


def test_notification_retry_does_not_redispatch(recovery, monkeypatch):
    _, _, messages, dispatches, _ = recovery
    monkeypatch.setattr(watchdog, 'send_telegram', lambda *a: (False, 'timeout'))
    watchdog.check_local_recovery(TODAY)
    monkeypatch.setattr(watchdog, 'send_telegram', lambda _, msg, dry: (messages.append(msg) or True, 'sent'))
    watchdog.check_local_recovery(TODAY)
    assert len(dispatches) == 1 and 'off-host 兜底已完成' in messages[0]


def test_recovery_schedule_leaves_a_full_local_turn_before_offhost_cutoff():
    from clawock.scheduling import load_contract
    contract = load_contract()
    brief = next(j for j in contract['jobs'] if j['payload_profile'] == 'brief')
    extras = brief['extra_watchdogs']
    minutes = {}
    for spec in extras:
        minute, hour, *_ = spec['schedule']['expr'].split()
        minutes[spec['command'].split()[1]] = int(hour) * 60 + int(minute)
    assert minutes['--check-recovery'] >= (minutes['--check-missing']
                                          + contract['payload_profiles']['brief']['timeout_seconds'] / 60)
    assert minutes['--check-recovery'] < 10 * 60
