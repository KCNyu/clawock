"""report_watchdog must not judge a slot that has not finished running.

The 2026-08-11 00:00 US incident taught intraday_watchdog this rule (attempts
00:00 / 00:01:55 / 00:03:30 errored, the fourth started 00:07:14, and the
watchdog sent the deterministic fallback at 00:10:44 one second before
postflight delivered the real report). Mode 6 runs the same retry machinery —
2026-08-03 港股开盘报告 / 港股午后快报 both auto-retried — so the same timeline
must defer here too. The opposite direction stays pinned as well: a genuinely
dead slot writes no newer context and still gets its backstop.
"""
from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))


def _ms(hour, minute, second=0):
    return int(datetime(2026, 8, 3, hour, minute, second,
                        tzinfo=HKT).timestamp() * 1000)


def test_a_retry_chain_still_running_is_deferred():
    """Mode-6 shape of the 08-11 timeline: attempt N errored 13:05:14, the
    retry's preflight rewrote the context at 13:07:27, watchdog due 13:45."""
    from clawock.harness.report_watchdog import attempt_still_running

    assert attempt_still_running(
        {'generated_at': '2026-08-03T13:07:27'},
        {'ts': _ms(13, 5, 14)})


def test_the_slots_own_context_is_not_in_flight():
    from clawock.harness.report_watchdog import attempt_still_running

    assert not attempt_still_running(
        {'generated_at': '2026-08-03T13:07:27'},
        {'ts': _ms(13, 11, 48)})


def test_a_dead_slot_is_not_deferred():
    """Nothing started after the error → real miss → backstop must fire."""
    from clawock.harness.report_watchdog import attempt_still_running

    assert not attempt_still_running(
        {'generated_at': '2026-08-03T13:00:13'},
        {'ts': _ms(13, 5, 14)})


def test_a_naive_timestamp_is_read_as_local_not_utc():
    """report_preflight writes generated_at without an offset; reading it as
    UTC would make every context look 8h older than its run and silently
    disable the gate."""
    from clawock.harness.report_watchdog import attempt_still_running

    assert attempt_still_running(
        {'generated_at': '2026-08-03T13:07:27'},
        {'ts': _ms(13, 5, 14)})


def test_the_gate_runs_before_any_branch_that_sends():
    """Placement is the substance: it has to precede the delivery-evidence
    judgment and both send branches (deterministic fallback + TG mirror),
    because each of those can send while the slot is still running."""
    import inspect

    from clawock.harness import report_watchdog

    source = inspect.getsource(report_watchdog.main)
    defer = source.index('attempt_still_running(ctx, last)')
    for later in ('slot_delivered(', "if not block_present or looped:",
                  "'循环'"):
        assert defer < source.index(later), (
            f'the in-flight check must precede {later!r}, or the slot can '
            'still be judged while it is running')
