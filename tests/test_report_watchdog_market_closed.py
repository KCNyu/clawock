"""A holiday sentinel and a cron that never fired are the same shape on disk.

report_watchdog already makes the right CALL for both (skip, no backstop — a
blockless context has no report to mirror). What it used to get wrong is the
name: logging a holiday as "cron likely never ran" points the next diagnosis at
a phantom missing run. The 2026-09-07 Labor Day incident spent its first minutes
there before the log turned out to be describing a gate working correctly.
"""
import json
import sys
from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))


def _wire(monkeypatch, tmp_path, context):
    from clawock.harness import report_watchdog as watchdog

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    ctx_dir = tmp_path / 'memory' / '.tmp'
    ctx_dir.mkdir(parents=True)
    (ctx_dir / f'report-context-hk-open-{today}.json').write_text(
        json.dumps(context, ensure_ascii=False))

    events = []
    monkeypatch.setattr(watchdog, 'WS', tmp_path)
    monkeypatch.setattr(watchdog, 'find_job_id', lambda name: 'job-hk')
    monkeypatch.setattr(watchdog, 'today_runs',
                        lambda job_id: [{'runAtMs': 1, 'sessionId': 's', 'summary': ''}])
    monkeypatch.setattr(watchdog, 'log', events.append)
    monkeypatch.setattr(watchdog, 'send_telegram',
                        lambda *a: (_ for _ in ()).throw(
                            AssertionError('a blockless context must not send')))
    monkeypatch.setattr(sys, 'argv',
                        ['report_watchdog.py', '--market', 'hk', '--phase', 'open',
                         '--job-name', '港股开盘报告'])
    return watchdog, events


def test_a_holiday_sentinel_is_logged_as_a_holiday(tmp_path, monkeypatch):
    watchdog, events = _wire(monkeypatch, tmp_path, {
        'status': 'market_closed', 'market': 'hk', 'phase': 'open',
        'reason': '节假日休市', 'skip': True})

    assert watchdog.main() == 0
    assert events[-1]['action'] == 'skip'
    assert events[-1]['closed_reason'] == '节假日休市'
    assert 'never ran' not in events[-1]['reason']


def test_a_genuinely_absent_run_still_says_so(tmp_path, monkeypatch):
    watchdog, events = _wire(monkeypatch, tmp_path, {})

    assert watchdog.main() == 0
    assert events[-1]['action'] == 'skip'
    assert events[-1]['closed_reason'] is None
    assert 'cron likely never ran' in events[-1]['reason']
