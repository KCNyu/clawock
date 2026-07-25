import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


HKT = ZoneInfo('Asia/Hong_Kong')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))
sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))


def _ms(at):
    return int(at.timestamp() * 1000)


def _run(at, **extra):
    return {'runAtMs': _ms(at), 'sessionId': f'session-{at:%H%M}', **extra}


def test_watchdog_target_owns_the_slot_ten_minutes_earlier():
    import intraday_watchdog as watchdog

    now = datetime(2026, 7, 25, 0, 10, tzinfo=HKT)
    wall, job, slot = watchdog.watchdog_target('us', now)

    assert wall == now
    assert job == '美股盘中盯盘-overnight'
    assert slot == '2026-07-25T00:00:00+08:00'


def test_hk_watchdog_runs_after_the_observed_long_turn_window():
    contract = json.loads((ROOT / 'config' / 'cron-schedules.json').read_text())
    job = next(item for item in contract['jobs'] if item['name'] == '盘中盯盘')

    assert job['watchdog']['schedule'] == {
        'kind': 'cron',
        'expr': '10,40 10-11,14-15 * * 1-5',
        'tz': 'Asia/Hong_Kong',
    }


def test_run_for_slot_rejects_the_latest_completed_prior_slot():
    import intraday_watchdog as watchdog

    prior = _run(datetime(2026, 7, 24, 10, 0, tzinfo=HKT))
    expected = _run(datetime(2026, 7, 24, 10, 30, tzinfo=HKT))
    runs = [prior, expected]

    assert watchdog.run_for_slot(
        runs, 'hk', '盘中盯盘', '2026-07-24T10:30:00+08:00') is expected
    assert watchdog.run_for_slot(
        [prior], 'hk', '盘中盯盘', '2026-07-24T10:30:00+08:00') is None


def test_context_and_delivery_marker_must_match_the_exact_slot(tmp_path):
    import intraday_watchdog as watchdog

    current_slot = '2026-07-24T10:30:00+08:00'
    path = tmp_path / 'context.json'
    path.write_text(json.dumps({
        'heartbeat': {'job': '盘中盯盘', 'slot': '2026-07-24T10:00:00+08:00'},
        'raw_wechat_block': 'old block',
    }))
    marker = {
        'ts': 1_000_000, 'tg_ok': True, 'first_line': 'same heading',
        'job': '盘中盯盘', 'slot': '2026-07-24T10:00:00+08:00',
    }

    assert watchdog.context_for_slot(path, '盘中盯盘', current_slot) is None
    assert not watchdog.marker_covers_slot(
        marker, '盘中盯盘', current_slot, 'same heading', 1_000_100)


def test_postflight_delivery_marker_carries_preflight_slot_identity():
    import intraday_postflight as postflight

    marker = postflight.delivery_marker_payload(
        {
            'heartbeat': {
                'job': '盘中盯盘',
                'slot': '2026-07-24T10:30:00+08:00',
            },
        },
        ts=1_000_000,
        sent_ok=True,
        tg_ok=True,
        first_line='current block',
        market='hk',
        out='ok',
    )

    assert marker['job'] == '盘中盯盘'
    assert marker['slot'] == '2026-07-24T10:30:00+08:00'


def test_main_does_not_assess_a_prior_completed_run(
        tmp_path, monkeypatch):
    import intraday_watchdog as watchdog

    now = datetime(2026, 7, 24, 10, 40, tzinfo=HKT)
    prior = _run(
        datetime(2026, 7, 24, 10, 0, tzinfo=HKT),
        summary='shared heading',
        delivery={'messageToolSentTo': ['telegram']},
    )
    sent = []
    recorded = []
    events = []

    monkeypatch.setattr(watchdog, 'WS', tmp_path)
    monkeypatch.setattr(watchdog, 'watchdog_target',
                        lambda market: (now, '盘中盯盘',
                                        '2026-07-24T10:30:00+08:00'))
    monkeypatch.setattr(watchdog, 'find_job_id', lambda name: 'job-hk')
    monkeypatch.setattr(watchdog, 'today_runs', lambda job_id: [prior])
    monkeypatch.setattr(watchdog, 'send_telegram',
                        lambda *args: sent.append(args) or (True, 'ok'))
    monkeypatch.setattr(watchdog.cron_heartbeat, 'record',
                        lambda *args, **kwargs: recorded.append((args, kwargs)))
    monkeypatch.setattr(watchdog, 'log', events.append)
    monkeypatch.setattr(
        sys, 'argv',
        ['intraday_watchdog.py', '--job-name', '盘中盯盘', '--market', 'hk'],
    )

    assert watchdog.main() == 0
    assert sent == []
    assert recorded == []
    assert events[-1]['reason'] == 'expected slot has no completed run'
    assert events[-1]['expected_slot'] == '2026-07-24T10:30:00+08:00'


def test_main_rejects_mismatched_context_and_uses_wall_clock_for_heartbeat(
        tmp_path, monkeypatch):
    import intraday_watchdog as watchdog

    now = datetime(2026, 7, 24, 10, 40, tzinfo=HKT)
    run = _run(datetime(2026, 7, 24, 10, 30, tzinfo=HKT))
    context_dir = tmp_path / 'memory' / '.tmp'
    context_dir.mkdir(parents=True)
    (context_dir / 'intraday-context-hk-latest.json').write_text(json.dumps({
        'heartbeat': {'job': '盘中盯盘', 'slot': '2026-07-24T10:00:00+08:00'},
        'raw_wechat_block': 'old block',
    }))
    recorded = []

    monkeypatch.setattr(watchdog, 'WS', tmp_path)
    monkeypatch.setattr(watchdog, 'watchdog_target',
                        lambda market: (now, '盘中盯盘',
                                        '2026-07-24T10:30:00+08:00'))
    monkeypatch.setattr(watchdog, 'find_job_id', lambda name: 'job-hk')
    monkeypatch.setattr(watchdog, 'today_runs', lambda job_id: [run])
    monkeypatch.setattr(watchdog.cron_heartbeat, 'record',
                        lambda *args, **kwargs: recorded.append((args, kwargs)))
    monkeypatch.setattr(watchdog, 'log', lambda event: None)
    monkeypatch.setattr(
        sys, 'argv',
        ['intraday_watchdog.py', '--job-name', '盘中盯盘', '--market', 'hk'],
    )

    assert watchdog.main() == 0
    assert recorded == [(
        ('hk', 'watchdog_rejected'),
        {
            'at': now,
            'job_name': '盘中盯盘',
            'slot': '2026-07-24T10:30:00+08:00',
            'watchdog_state': 'stale_context_rejected',
            'telegram_sent': False,
        },
    )]
