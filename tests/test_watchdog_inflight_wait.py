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

    assert slept == [30, 30, 10] and waited == 90


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
