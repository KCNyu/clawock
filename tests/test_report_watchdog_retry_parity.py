"""report_watchdog delivery evidence must survive an openclaw cron retry.

2026-08-03: 港股开盘报告 and 港股午后快报 each errored only in post-turn summary
generation (MiniMax response-header timeout), openclaw auto-retried, the retry's
preflight rewrote the context file with a fresh per-invocation `context_id`, and
its postflight correctly declined to re-send. The watchdog then compared the
marker's id against the retry's id, read "never delivered", and pushed kcn a
duplicate deterministic fallback for a report already sitting in his Telegram.

The opposite failure must stay caught: 2026-07-24 delivered 07/22 numbers behind
a fresh-looking marker and no backstop ever fired. Both invariants are pinned
here — a fix for either one that breaks the other fails this file.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))

SENT_AT = datetime(2026, 8, 3, 13, 31, 24)
NOW_MS = int(datetime(2026, 8, 3, 13, 42).timestamp() * 1000)
TITLE = '🌤 港股午后快报｜2026-08-03 13:30'
BLOCK_FIRST = '🇭🇰 港股盯盘 | 08/03 13:30 HKT'


def _marker(context_id, generated_at, **extra):
    return {
        'ts': int(SENT_AT.timestamp() * 1000),
        'tg_ok': True,
        'first_line': TITLE,
        'context_id': context_id,
        'context_generated_at': generated_at.isoformat(),
        **extra,
    }


def test_retry_regenerated_context_still_counts_as_delivered():
    from clawock_kcnyu.harness import report_watchdog as watchdog

    # The retry's preflight rebuilt the context 2m35s after the delivered one.
    marker = _marker('af4310c68bbf', datetime(2026, 8, 3, 13, 30, 24))
    retry_ctx_at = datetime(2026, 8, 3, 13, 32, 59)

    delivered, judge = watchdog.slot_delivered(
        marker, 'e3d82a1c096e', BLOCK_FIRST, NOW_MS,
        ctx_generated_at=retry_ctx_at.isoformat())

    assert delivered is True
    assert judge == 'regenerated-context'


def test_stale_body_behind_a_fresh_marker_still_gets_a_backstop():
    from clawock_kcnyu.harness import report_watchdog as watchdog

    # 2026-07-24 shape: the marker was written today, but the report it sent was
    # built from a context two days old. That must remain a miss.
    marker = _marker('af4310c68bbf', SENT_AT - timedelta(days=2))

    delivered, judge = watchdog.slot_delivered(
        marker, 'e3d82a1c096e', BLOCK_FIRST, NOW_MS,
        ctx_generated_at=SENT_AT.isoformat())

    assert delivered is False
    assert judge == 'regenerated-context'


def test_context_older_than_the_delivered_one_is_not_a_retry():
    from clawock_kcnyu.harness import report_watchdog as watchdog

    # A retry always regenerates FORWARD. A context materially older than the
    # delivered generation means the watchdog is reading someone else's file,
    # not a retry, so the delivery is not proven for what is on disk now.
    marker = _marker('af4310c68bbf', SENT_AT)

    delivered, _ = watchdog.slot_delivered(
        marker, 'e3d82a1c096e', BLOCK_FIRST, NOW_MS,
        ctx_generated_at=(SENT_AT - timedelta(minutes=20)).isoformat())

    assert delivered is False


def test_postflight_records_the_source_context_timestamp(tmp_path, monkeypatch):
    """Without this field on the marker the window above can never engage."""
    from clawock_kcnyu.harness import report_postflight as postflight

    monkeypatch.setattr(postflight, 'TMP', tmp_path)
    monkeypatch.setattr(postflight, 'resolve_wechat_target',
                        lambda market: ('wechat', 'kcn', 'acct'))
    monkeypatch.setattr(postflight, 'send_wechat',
                        lambda *a, **kw: (True, 'sent'))
    monkeypatch.setattr(postflight, 'cosend_telegram',
                        lambda *a, **kw: (True, 'sent'))

    postflight.deliver_wechat('hk', 'pm', '2026-08-03', '', f'{TITLE}\nbody',
                              context_id='af4310c68bbf',
                              context_generated_at='2026-08-03T13:30:24.100000')

    marker = json.loads((tmp_path / 'report-sent-hk-pm-2026-08-03.json').read_text())
    assert marker['context_generated_at'] == '2026-08-03T13:30:24.100000'
    assert marker['context_id'] == 'af4310c68bbf'
