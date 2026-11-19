"""The one in-flight wait both session watchdogs hold a slot open with.

report_watchdog (#988) and intraday_watchdog (#1532) each carried this loop;
it is `_watchdog_common.wait_out_inflight` now. The driven tests in
`test_{report,intraday}_watchdog_inflight.py` prove each watchdog reaches the
right verdict through it. These pin the loop's own contract, which those
cannot see: it re-reads the slot after every poll and stops the moment the
attempt has finished, and it never waits past its budget.
"""
from datetime import datetime, timedelta, timezone

import pytest

HKT = timezone(timedelta(hours=8))
CONTEXT = {'generated_at': '2026-08-11T00:07:14'}
BEFORE = {'ts': int(datetime(2026, 8, 11, 0, 3, 30, tzinfo=HKT).timestamp() * 1000)}
AFTER = {'ts': int(datetime(2026, 8, 11, 0, 11, 49, tzinfo=HKT).timestamp() * 1000)}


from clawock.harness import _watchdog_common as common


@pytest.fixture
def logged(monkeypatch):
    lines = []
    monkeypatch.setattr(common, 'log', lines.append)
    return lines


def test_the_wait_ends_as_soon_as_a_poll_shows_the_attempt_finished(logged):
    slept, polls = [], []

    def refresh(context, last):
        polls.append(last)
        return context, AFTER

    context, last, waited = common.wait_out_inflight(
        CONTEXT, BEFORE, refresh=refresh, budget_s=600, poll_s=30,
        tag='us-close', sleep=slept.append)

    assert (slept, polls, waited) == ([30], [BEFORE], 30)
    assert last is AFTER, 'the verdict must be judged on the run the wait found'


def test_the_wait_never_runs_past_its_budget(logged):
    slept = []

    _, _, waited = common.wait_out_inflight(
        CONTEXT, BEFORE, refresh=lambda c, r: (c, r), budget_s=70, poll_s=30,
        tag='us-close', sleep=slept.append)

    assert slept == [30, 30, 10] and waited == 70


def test_a_finished_slot_never_sleeps(logged):
    def refresh(*_):
        raise AssertionError('nothing to re-read when nothing is in flight')

    _, _, waited = common.wait_out_inflight(
        CONTEXT, AFTER, refresh=refresh, budget_s=600, poll_s=30,
        tag='us-close', sleep=lambda _s: pytest.fail('slept'))

    assert waited == 0 and logged == []


def test_each_watchdog_keeps_its_own_log_fields(logged):
    slot = {'expected_job': '盘中盯盘', 'expected_slot': '2026-08-11T10:00:00+08:00'}

    common.wait_out_inflight(
        CONTEXT, BEFORE, refresh=lambda c, r: (c, AFTER), budget_s=600, poll_s=30,
        tag='intraday-hk', lead=slot, trail={'run_at': 1}, sleep=lambda _s: None)
    common.log_after_wait(CONTEXT, AFTER, waited=30, budget_s=600,
                          tag='intraday-hk', run_at=1, lead=slot)

    waiting, verdict = logged
    assert waiting['action'] == 'wait-inflight'
    assert waiting['expected_slot'] == slot['expected_slot'] and waiting['run_at'] == 1
    assert verdict['action'] == 'attempt-finished'
    assert verdict['expected_job'] == slot['expected_job'] and verdict['waited_s'] == 30


@pytest.mark.parametrize('mode', ['intraday', 'report'])
def test_manual_context_after_finished_cron_does_not_wait(monkeypatch, logged, mode):
    from clawock.providers.openclaw import CronRead
    job = '盘中盯盘' if mode == 'intraday' else '港股开盘报告'
    context = {**CONTEXT, 'market': 'hk'}
    if mode == 'intraday':
        context['heartbeat'] = {'job': job, 'slot': '2026-08-11T00:00:00+08:00'}
    else:
        context['phase'] = 'open'
    monkeypatch.setattr(common._openclaw, 'read_jobs', lambda *_: CronRead([
        {'name': job, 'state': {'lastRunAtMs': BEFORE['ts'], 'lastStatus': 'ok'}}], 'sqlite'))
    _, _, waited = common.wait_out_inflight(
        context, BEFORE, refresh=lambda c, r: (c, r), budget_s=600, poll_s=30,
        tag=mode, sleep=lambda _: pytest.fail('completed manual context consumed budget'))
    assert waited == 0
    # Completion of collection must not release a still-running scheduled agent.
    monkeypatch.setattr(common._openclaw, 'read_jobs', lambda *_: CronRead([
        {'name': job, 'state': {'runningAtMs': BEFORE['ts']}}], 'sqlite'))
    assert common.attempt_still_running(context, BEFORE)
    monkeypatch.setattr(common._openclaw, 'read_jobs', lambda *_: CronRead([], 'empty'))
    assert common.attempt_still_running(context, BEFORE)


def test_next_intraday_slot_does_not_hold_previous_slot_open(monkeypatch):
    from clawock.providers.openclaw import CronRead
    context = {**CONTEXT, 'market': 'hk',
               'heartbeat': {'job': '盘中盯盘', 'slot': '2026-08-11T00:00:00+08:00'}}
    next_run = int(datetime(2026, 8, 11, 0, 33, tzinfo=HKT).timestamp() * 1000)
    monkeypatch.setattr(common._openclaw, 'read_jobs', lambda *_: CronRead([
        {'name': '盘中盯盘', 'state': {'runningAtMs': next_run}}], 'sqlite'))
    assert not common.attempt_still_running(context, BEFORE)


@pytest.mark.parametrize("launch_delay", [0, 65])
def test_queued_retry_extends_the_wait_and_refreshes_the_run(monkeypatch, logged, launch_delay):
    from clawock.providers.openclaw import CronRead

    job_name = '美股开盘报告'
    first_start = datetime(2026, 11, 18, 22, 33, tzinfo=HKT)
    finished = first_start + timedelta(seconds=1741)
    announced = finished + timedelta(seconds=30)
    retry_start = announced + timedelta(seconds=launch_delay)
    completed = retry_start + timedelta(seconds=214)
    clock = [first_start + timedelta(minutes=20)]
    failed = {
        'status': 'error', 'runAtMs': first_start.timestamp() * 1000,
        'ts': finished.timestamp() * 1000, 'nextRunAtMs': announced.timestamp() * 1000,
    }
    ok = {'status': 'ok', 'runAtMs': retry_start.timestamp() * 1000,
          'ts': completed.timestamp() * 1000}

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz)

    def read_jobs(_source):
        state = {'lastRunAtMs': first_start.timestamp() * 1000}
        if finished <= clock[0] < retry_start:
            state['nextRunAtMs'] = failed['nextRunAtMs']
        elif clock[0] < completed:
            start = retry_start if clock[0] >= retry_start else first_start
            state['runningAtMs'] = start.timestamp() * 1000
        return CronRead([{
            'name': job_name, 'state': state, 'payload': {'timeoutSeconds': 1740},
            'schedule': {'kind': 'cron', 'expr': '33 22 * * 1-5', 'tz': 'Asia/Hong_Kong'},
        }], 'sqlite')

    def sleep(seconds):
        clock[0] += timedelta(seconds=seconds)

    def refresh(context, last):
        if clock[0] >= completed:
            return context, ok
        return context, failed if clock[0] >= finished else last

    monkeypatch.setattr(common, 'datetime', FakeDateTime)
    monkeypatch.setattr(common._openclaw, 'read_jobs', read_jobs)
    context = {'generated_at': first_start.isoformat()}
    _, last, waited = common.wait_out_inflight(
        context, common.UNFINISHED_RUN, refresh=refresh, budget_s=600, poll_s=30,
        tag='us-open', job_name=job_name, sleep=sleep,
    )
    assert last is ok and completed <= clock[0] < completed + timedelta(seconds=30)
    assert any(row['reason'] == 'scheduler has a retry for this slot' for row in logged)


def test_retry_cannot_claim_the_next_regular_slot(monkeypatch):
    from clawock.harness import intraday_watchdog
    from clawock.providers.openclaw import CronRead

    job_name = '美股盘中盯盘-overnight'
    job = {'name': job_name, 'id': 'overnight', 'schedule': {
        'kind': 'cron', 'expr': '3,33 0-2 * * 2-6', 'tz': 'Asia/Hong_Kong',
    }}
    slot = datetime(2026, 11, 17, 2, tzinfo=HKT)
    ms = lambda at: int(at.timestamp() * 1000)  # noqa: E731
    retry_at = slot + timedelta(minutes=32, seconds=31)
    initial = {'runAtMs': ms(slot + timedelta(minutes=3)),
               'status': 'error', 'ts': ms(slot + timedelta(minutes=32, seconds=1)),
               'nextRunAtMs': ms(retry_at)}
    retry = {'runAtMs': ms(retry_at), 'status': 'ok'}
    regular_at = slot + timedelta(minutes=33)
    regular = {'runAtMs': ms(regular_at), 'status': 'ok'}
    assert intraday_watchdog.run_for_slot(
        [initial, retry, regular], 'us', job_name, slot.isoformat(), job=job,
    ) is retry
    assert intraday_watchdog.run_for_slot(
        [initial, retry, regular], 'us', job_name, (slot + timedelta(minutes=30)).isoformat(), job=job,
    ) is regular
    assert common.scheduled_retry_at(job, {**initial, 'nextRunAtMs': ms(regular_at)}) is None

    monkeypatch.setattr(common, 'live_cron_job', lambda _name: {
        **job, 'state': {'runningAtMs': ms(retry_at)},
    })
    monkeypatch.setattr(common._openclaw, 'read_runs', lambda *_: CronRead([initial], 'sqlite'))
    preflight_at = slot + timedelta(minutes=33, seconds=10)
    assert common.active_intraday_slot('us', job_name, preflight_at) == (job_name, slot.isoformat())


def test_delayed_overnight_retry_chain_keeps_the_last_scheduled_slot(monkeypatch):
    job_name = "美股盘中盯盘-overnight"
    job = {"name": job_name, "id": "overnight", "payload": {"timeoutSeconds": 1740},
           "schedule": {"kind": "cron", "expr": "3,33 0-2 * * 2-6", "tz": "Asia/Hong_Kong"}}
    slot = datetime(2026, 11, 19, 2, 30, tzinfo=HKT)

    def ms(hour, minute, second):
        return int(slot.replace(hour=hour, minute=minute, second=second).timestamp() * 1000)

    first = {"runAtMs": ms(2, 33, 0), "ts": ms(3, 2, 1), "status": "error",
             "nextRunAtMs": ms(3, 2, 31)}
    second = {"runAtMs": ms(3, 3, 6), "ts": ms(3, 32, 7), "status": "error",
              "nextRunAtMs": ms(3, 33, 7)}
    third = {"runAtMs": ms(3, 33, 7), "status": "ok"}
    assert [owner for _, owner in common.intraday_run_slots([first, second, third], "us", job)] == [
        (job_name, slot.isoformat())] * 3

    class DuringRetry(datetime):
        @classmethod
        def now(cls, tz=None):
            return slot.replace(hour=3, minute=4).astimezone(tz)

    monkeypatch.setattr(common, 'datetime', DuringRetry)
    monkeypatch.setattr(common, 'live_cron_job', lambda _: {
        **job, 'state': {'runningAtMs': second['runAtMs']}})
    assert common._attempt_state({}, first, job_name=job_name) == (
        True, second["runAtMs"] / 1000 + 1740)
