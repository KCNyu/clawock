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


# ── #988: the wait replaces the defer, because this watchdog runs ONCE ───────
# `intraday_watchdog` may simply return when an attempt is in flight: crontab
# runs it at :10 and :40 all session, so "defer" means "the next pass looks
# again". report_watchdog is a single crontab line per slot — returning there IS
# the verdict, so a retry chain that never delivers used to leave kcn with no
# report AND no backstop, one `defer` line the only trace. These tests pin the
# replacement: hold the slot open, then judge on whatever the wait produced.

import json
import sys

import pytest


@pytest.fixture
def wd(isolated_workflow_ledger, isolated_watchdog_log):
    import importlib
    return importlib.import_module('clawock.harness.report_watchdog')


BLOCK = '🌙 美股收盘日报｜test\n数据块正文'


def _drive(wd, tmp_path, monkeypatch, *, script, marker_at_step=None):
    """Run main() with a scripted timeline.

    `script` is the list of run-record sets today_runs() returns on successive
    calls; every fake sleep advances one step. `marker_at_step` writes a
    delivered postflight marker when that step is reached.
    """
    from datetime import datetime

    monkeypatch.setattr(wd, 'WS', tmp_path)
    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True)
    now = datetime.now(wd.HKT)
    today = now.strftime('%Y-%m-%d')
    ctx = {'raw_wechat_block': BLOCK, 'context_id': 'ctx-under-test',
           'generated_at': now.replace(tzinfo=None).isoformat()}
    (tmp / f'report-context-us-close-{today}.json').write_text(
        json.dumps(ctx, ensure_ascii=False))

    step = {'i': 0}

    def fake_sleep(_seconds):
        step['i'] = min(step['i'] + 1, len(script) - 1)
        if marker_at_step is not None and step['i'] >= marker_at_step:
            (tmp / f'report-sent-us-close-{today}.json').write_text(json.dumps({
                'ts': int(now.timestamp() * 1000), 'sent_ok': True, 'tg_ok': True,
                'context_id': 'ctx-under-test', 'first_line': BLOCK.splitlines()[0]}))

    slept = []
    # Patch the stdlib module, not `wd.time`: these tests must be runnable
    # against the pre-#988 module too, which imports no `time` at all.
    import time as _time
    monkeypatch.setattr(_time, 'sleep',
                        lambda s: (slept.append(s), fake_sleep(s))[0])
    # Budget as a module constant rather than the CLI flag, for the same reason.
    monkeypatch.setattr(wd, 'INFLIGHT_WAIT_S', 90, raising=False)
    monkeypatch.setattr(wd, 'find_job_id', lambda name: 'jid')
    monkeypatch.setattr(wd, 'today_runs', lambda jid: script[step['i']])
    monkeypatch.setattr(wd, 'transcript_loop_score', lambda s: (0, {}))
    monkeypatch.setattr(wd, 'last_report_text', lambda s, first: f'{BLOCK}\n\n正文')
    sent = []
    monkeypatch.setattr(wd, 'send_telegram',
                        lambda target, msg, dry: (sent.append(msg), (True, 'ok'))[1])
    monkeypatch.setattr(sys, 'argv', [
        'report_watchdog.py', '--market', 'us', '--phase', 'close',
        '--job-name', '美股收盘报告'])
    assert wd.main() == 0
    return sent, slept


def _run(*, finished_ms, summary=BLOCK):
    return [{'runAtMs': finished_ms - 200_000, 'sessionId': 'sess',
             'summary': summary, 'ts': finished_ms}]


def test_the_backstop_still_fires_when_the_waited_out_attempt_delivered_nothing(
        wd, tmp_path, monkeypatch):
    """The hole #988 names: an attempt in flight at watchdog time finishes
    during the wait without delivering. Deferring returned 0 here — no report,
    no backstop. The wait must let the slot reach its verdict."""
    from datetime import datetime
    now_ms = int(datetime.now(wd.HKT).timestamp() * 1000)

    sent, slept = _drive(
        wd, tmp_path, monkeypatch,
        # step 0: newest FINISHED run predates the context → an attempt is live.
        # step 1: the retry finished (after the context) and delivered nothing.
        script=[_run(finished_ms=now_ms - 120_000), _run(finished_ms=now_ms + 5_000)])

    assert slept, 'the watchdog judged without ever waiting for the live attempt'
    assert sent, 'a slot that finished undelivered must still get its backstop'
    assert BLOCK.splitlines()[0] in sent[-1]


def test_an_attempt_that_lands_during_the_wait_is_not_doubled(
        wd, tmp_path, monkeypatch):
    """The 2026-08-11 duplicate this gate exists for: the live attempt succeeds
    while we wait, its postflight writes the marker, and the marker gate — which
    still runs after the wait — must recognise the delivery."""
    from datetime import datetime
    now_ms = int(datetime.now(wd.HKT).timestamp() * 1000)

    sent, slept = _drive(
        wd, tmp_path, monkeypatch,
        script=[_run(finished_ms=now_ms - 120_000), _run(finished_ms=now_ms + 5_000)],
        marker_at_step=1)

    assert slept, 'the watchdog did not wait for the live attempt'
    assert sent == [], 'mirrored a report the slot had already delivered'


def test_a_slot_still_in_flight_at_the_budget_is_judged_not_silently_dropped(
        wd, tmp_path, monkeypatch):
    """Budget exhausted with the attempt still live: the old code's answer was
    `return 0` forever. The rule is detect-but-never-silence — judge on the
    evidence that exists, with the marker gate still protecting against a
    duplicate."""
    from datetime import datetime
    now_ms = int(datetime.now(wd.HKT).timestamp() * 1000)
    stuck = _run(finished_ms=now_ms - 120_000)

    sent, slept = _drive(wd, tmp_path, monkeypatch, script=[stuck, stuck, stuck])

    assert len(slept) == 3, f'wait budget not honoured: {slept}'
    assert sent, 'a hung slot must still reach kcn on Telegram'


def test_a_normal_slot_never_sleeps(wd, tmp_path, monkeypatch):
    """No in-flight attempt ⇒ not one second of added latency on the ~75% of
    days that have no retry at all."""
    from datetime import datetime
    now_ms = int(datetime.now(wd.HKT).timestamp() * 1000)

    sent, slept = _drive(wd, tmp_path, monkeypatch,
                         script=[_run(finished_ms=now_ms + 5_000)])

    assert slept == []
    assert sent, 'an undelivered finished slot still gets the backstop'
