"""The timetable panel reports the ledger's verdict — it never forms its own."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from clawock.publish.cron_schedule import timetable

HKT = ZoneInfo('Asia/Hong_Kong')


def _contract(expr='3,33 10-11 * * 1-5', name='盘中盯盘', harness='intraday --hk'):
    return {'jobs': [{'name': name, 'harness': harness,
                      'schedule': {'expr': expr, 'tz': 'Asia/Shanghai'}}]}


def _record(slot, status, job='盘中盯盘'):
    return {'job': job, 'slot': slot, 'final_product': {'status': status}}


def _states(result, job=0):
    return [cell['state'] for cell in result['jobs'][job]['slots']]


def test_the_panel_prints_the_ledgers_verdict_not_its_own():
    at = datetime(2026, 9, 3, 12, 0, tzinfo=HKT)  # Thursday, after every slot
    result = timetable(_contract(), [
        _record('2026-09-03T10:03:00+08:00', 'success'),
        _record('2026-09-03T10:33:00+08:00', 'recovered'),
        _record('2026-09-03T11:03:00+08:00', 'degraded'),
        _record('2026-09-03T11:33:00+08:00', 'failed'),
    ], now=at)

    assert _states(result) == ['ok', 'recovered', 'degraded', 'failed']


def test_an_unmapped_ledger_status_shows_as_unknown_not_as_green():
    """A default of 'ok' would render a status nobody has looked at as healthy."""
    at = datetime(2026, 9, 3, 12, 0, tzinfo=HKT)
    result = timetable(_contract('3 10 * * 1-5'),
                       [_record('2026-09-03T10:03:00+08:00', 'brand-new-status')],
                       now=at)

    assert _states(result) == ['unknown']


def test_a_slot_is_upcoming_before_it_fires_and_running_inside_its_grace():
    # A record for some other job: the ledger has content, it just has nothing
    # for these slots yet.
    result = timetable(_contract(), [_record('2026-09-03T09:33:00+08:00', 'success',
                                             job='港股开盘报告')],
                       now=datetime(2026, 9, 3, 10, 10, tzinfo=HKT))

    # 10:03 fired 7 minutes ago (grace 20) — still running, not a miss yet.
    assert _states(result) == ['running', 'upcoming', 'upcoming', 'upcoming']


def test_a_slot_past_its_grace_with_nothing_on_it_is_missed():
    result = timetable(_contract(), [_record('2026-09-03T09:33:00+08:00', 'success',
                                             job='港股开盘报告')],
                       now=datetime(2026, 9, 3, 10, 30, tzinfo=HKT))

    assert _states(result)[0] == 'missed'


def test_records_snap_to_the_grid_so_a_schedule_move_is_not_nine_outages():
    """#1278 shifted nine jobs by three minutes. The records written that day
    carry the OLD slot, so an exact join would call the whole day missed."""
    at = datetime(2026, 9, 3, 12, 0, tzinfo=HKT)
    result = timetable(_contract(), [
        _record('2026-09-03T10:00:00+08:00', 'success'),   # old grid
        _record('2026-09-03T10:30:00+08:00', 'success'),
    ], now=at)

    assert _states(result)[:2] == ['ok', 'ok']


def test_snapping_never_lets_one_record_answer_for_two_slots():
    """The tolerance is capped at half the gap, so a single run cannot light up
    its neighbour — which would turn one delivered report into two green slots."""
    at = datetime(2026, 9, 3, 12, 0, tzinfo=HKT)
    result = timetable(_contract(), [
        _record('2026-09-03T10:03:00+08:00', 'success'),
    ], now=at)

    assert _states(result) == ['ok', 'missed', 'missed', 'missed']


def test_a_job_the_ledger_cannot_see_is_not_reported_as_an_outage():
    """Memory Dreaming runs no harness, so the ledger will never carry a record
    for it however well it ran. Red every day trains the reader to ignore the
    panel. The criterion is the contract's `harness` field, not absence from a
    windowed ledger — absence there also describes a job idle for a few days."""
    at = datetime(2026, 9, 3, 12, 0, tzinfo=HKT)
    contract = _contract('0 3 * * *', name='Memory Dreaming Promotion', harness='—')

    result = timetable(contract, [_record('2026-09-03T10:03:00+08:00', 'success')],
                       now=at)

    assert result['jobs'][0]['unmonitored'] is True
    assert _states(result) == ['unmonitored']


def test_an_empty_ledger_hides_the_panel_rather_than_reporting_red():
    """A day we cannot speak about is not a day when nothing ran. Painting every
    past slot red would blame the cron for a bookkeeping gap."""
    at = datetime(2026, 9, 3, 12, 0, tzinfo=HKT)

    assert timetable(_contract(), [], now=at)['jobs'] == []


def test_a_day_the_job_does_not_fire_produces_no_row():
    """Saturday: the cron dow excludes it, so there is nothing to report — an
    empty row of grey lights would read as 'something should have happened'."""
    saturday = datetime(2026, 9, 5, 12, 0, tzinfo=HKT)
    ledger = [_record('2026-09-05T09:33:00+08:00', 'success', job='港股开盘报告')]

    assert timetable(_contract(), ledger, now=saturday)['jobs'] == []
