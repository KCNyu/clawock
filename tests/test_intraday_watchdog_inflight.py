"""The watchdog must not judge a slot that has not finished running.

2026-08-11 00:00 US overnight. The slot burned three failed attempts before the
successful one started, so the work was still in flight when the watchdog ran:

    00:00:00  attempt 1  error   (86s)
    00:01:55  attempt 2  error   (34s)
    00:03:30  attempt 3  error  (104s)  → finished 00:05:14
    00:07:14  attempt 4  ok     (275s)  → finished 00:11:48
    00:10:44  watchdog sends the deterministic fallback ("未完成")
    00:10:45  postflight delivers the real report

kcn received both, one second apart.

openclaw writes a run record only with `action: "finished"`, so a running
attempt is invisible and `run_for_slot` returns the newest *completed* one —
attempt 3's error. The preflight context is the signal that was already on disk:
it is written when an attempt starts, so a context generated after the newest
finished run ended means a later attempt began and has not finished.

This is not the #458/#459 failure. That was marker/context identity on retries;
this is judging a slot that is still running.
"""
from datetime import datetime, timedelta, timezone

import pytest

HKT = timezone(timedelta(hours=8))


def _ms(hour, minute, second=0):
    return int(datetime(2026, 8, 11, hour, minute, second,
                        tzinfo=HKT).timestamp() * 1000)


def test_the_2026_08_11_timeline_is_deferred():
    """Verbatim from the incident: attempt 3 finished 00:05:14, attempt 4's
    preflight ran 00:07:27, watchdog at 00:10:44."""
    from clawock.harness.intraday_watchdog import attempt_still_running

    assert attempt_still_running(
        {'generated_at': '2026-08-11T00:07:27'},
        {'ts': _ms(0, 5, 14)})


def test_a_context_older_than_the_finished_run_is_not_in_flight():
    """The healthy shape: the run wrote its own context, then finished."""
    from clawock.harness.intraday_watchdog import attempt_still_running

    assert not attempt_still_running(
        {'generated_at': '2026-08-11T00:07:27'},
        {'ts': _ms(0, 11, 48)})


def test_a_dead_slot_is_not_deferred():
    """The direction that must not break. A slot whose run errored and where
    nothing started afterwards writes no newer context, so the backstop still
    fires — deferring unconditionally would silence every real miss."""
    from clawock.harness.intraday_watchdog import attempt_still_running

    assert not attempt_still_running(
        {'generated_at': '2026-08-11T00:00:13'},
        {'ts': _ms(0, 5, 14)})


@pytest.mark.parametrize('context, run', [
    ({}, {'ts': _ms(0, 5)}),
    ({'generated_at': None}, {'ts': _ms(0, 5)}),
    ({'generated_at': 'not-a-date'}, {'ts': _ms(0, 5)}),
    ({'generated_at': '2026-08-11T00:07:27'}, {}),
    ({'generated_at': '2026-08-11T00:07:27'}, {'ts': None}),
    (None, None),
])
def test_missing_or_broken_inputs_do_not_defer(context, run):
    """Unreadable inputs must fall through to the existing gates rather than
    silently suppressing the backstop — an unknown state is not evidence that
    something is running."""
    from clawock.harness.intraday_watchdog import attempt_still_running

    assert not attempt_still_running(context, run)


def test_a_naive_timestamp_is_read_as_local_not_utc():
    """Preflight writes `generated_at` without an offset. Reading it as UTC
    would shift it 8 hours and make every context look older than its run,
    disabling this gate entirely and silently."""
    from clawock.harness.intraday_watchdog import attempt_still_running

    # 00:07:27 HKT is 16:07 UTC the previous day; if parsed as UTC it would sort
    # before a run that finished at 00:05:14 HKT and the gate would not fire.
    assert attempt_still_running(
        {'generated_at': '2026-08-11T00:07:27'},
        {'ts': _ms(0, 5, 14)})


def test_the_gate_runs_before_the_slot_is_judged():
    """Placement is the substance: it has to sit above the loop, marker and
    generation gates, because each of those can send."""
    import inspect

    from clawock.harness import intraday_watchdog

    source = inspect.getsource(intraday_watchdog.main)
    defer = source.index('attempt_still_running(context, last)')
    for later in ("if looped:", "marker_covers_slot(", "delivered_clean"):
        assert defer < source.index(later), (
            f'the in-flight check must precede {later!r}, or the slot can still '
            'be judged while it is running')
