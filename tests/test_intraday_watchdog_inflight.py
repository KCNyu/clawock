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


# ── #1532: wait instead of defer — the next pass owns the NEXT slot ──────────
# watchdog_target is wall clock minus ten minutes, so the 10:13 pass owns 10:00
# and the 10:43 pass owns 10:30. A `defer` at 10:13 was the 10:00 slot's only
# verdict: if the in-flight retry then died, that slot got no backstop at all.

import json
import sys

HK_SLOT = '2026-08-11T10:00:00+08:00'
BLOCK = '📊 盘中盯盘｜10:00\n数据块正文'


@pytest.fixture
def wd(isolated_workflow_ledger, isolated_watchdog_log):
    import importlib
    return importlib.import_module('clawock.harness.intraday_watchdog')


def _slot_run(finished_ms, summary='分析正文'):
    return [{'runAtMs': _ms(10, 3), 'sessionId': 'sess', 'status': 'error',
             'summary': summary, 'ts': finished_ms}]


def _drive(wd, tmp_path, monkeypatch, *, script, marker_at_step=None):
    """main() at 10:13 for the 10:00 slot; each fake sleep advances `script`."""
    from clawock.automation import delivery_receipts

    monkeypatch.setattr(wd, 'WS', tmp_path)
    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True)
    (tmp / 'intraday-context-hk-latest.json').write_text(json.dumps({
        'generated_at': '2026-08-11T10:08:00', 'status': 'ok',
        'context_id': 'ctx-1000', 'raw_wechat_block': BLOCK,
        'heartbeat': {'job': '盘中盯盘', 'slot': HK_SLOT}}, ensure_ascii=False))
    now = datetime(2026, 8, 11, 10, 13, tzinfo=HKT)
    step = {'i': 0}

    def fake_sleep(_seconds):
        slept.append(_seconds)
        step['i'] = min(step['i'] + 1, len(script) - 1)
        if marker_at_step is not None and step['i'] >= marker_at_step:
            delivery_receipts.receipt_path(tmp, 'intraday', market='hk').write_text(
                json.dumps({'ts': _ms(10, 14), 'sent_ok': True, 'tg_ok': True,
                            'job': '盘中盯盘', 'slot': HK_SLOT,
                            'context_id': 'ctx-1000',
                            'first_line': BLOCK.splitlines()[0]}))

    slept, sent = [], []
    import time as _time
    monkeypatch.setattr(_time, 'sleep', fake_sleep)
    monkeypatch.setattr(wd, 'INFLIGHT_WAIT_S', 90, raising=False)
    monkeypatch.setattr(wd, 'watchdog_target', lambda market: (now, '盘中盯盘', HK_SLOT))
    monkeypatch.setattr(wd, 'find_job_id', lambda name: 'jid')
    monkeypatch.setattr(wd, 'today_runs', lambda jid: script[step['i']])
    monkeypatch.setattr(wd, 'transcript_loop_score', lambda s: (0, {}))
    monkeypatch.setattr(wd, 'last_report_text', lambda s, first: None)
    monkeypatch.setattr(wd.cron_heartbeat, 'record', lambda *a, **k: None)
    monkeypatch.setattr(wd, 'send_telegram',
                        lambda target, msg, dry: (sent.append(msg), (True, 'ok'))[1])
    monkeypatch.setattr(sys, 'argv', [
        'intraday_watchdog.py', '--job-name', '盘中盯盘', '--market', 'hk'])
    assert wd.main() == 0
    return sent, slept


def test_a_retry_that_dies_after_the_watchdog_ran_still_gets_its_backstop(
        wd, tmp_path, monkeypatch):
    """The #1532 timeline: attempt 1 errored 10:06, the retry's preflight wrote
    the context 10:08, the watchdog ran 10:13, the retry died 10:18 undelivered."""
    sent, slept = _drive(wd, tmp_path, monkeypatch,
                         script=[_slot_run(_ms(10, 6)), _slot_run(_ms(10, 18))])

    assert slept, 'the watchdog judged without waiting for the live attempt'
    assert sent and BLOCK.splitlines()[0] in sent[-1], (
        'the slot finished undelivered and nobody backed it up')


def test_an_attempt_that_lands_during_the_wait_is_not_doubled(
        wd, tmp_path, monkeypatch):
    sent, slept = _drive(wd, tmp_path, monkeypatch,
                         script=[_slot_run(_ms(10, 6)), _slot_run(_ms(10, 14))],
                         marker_at_step=1)

    assert slept
    assert sent == [], 'mirrored a report the slot had already delivered'


def test_a_slot_still_in_flight_at_the_budget_is_judged(wd, tmp_path, monkeypatch):
    stuck = _slot_run(_ms(10, 6))
    sent, slept = _drive(wd, tmp_path, monkeypatch, script=[stuck, stuck, stuck])

    assert len(slept) == 3, f'wait budget not honoured: {slept}'
    assert sent, 'a hung slot must still reach kcn on Telegram'


def test_a_normal_slot_never_sleeps(wd, tmp_path, monkeypatch):
    sent, slept = _drive(wd, tmp_path, monkeypatch,
                         script=[_slot_run(_ms(10, 11))])

    assert slept == []
    assert sent, 'an undelivered finished slot still gets the backstop'
