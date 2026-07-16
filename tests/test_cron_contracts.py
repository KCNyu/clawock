import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))
sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))

import cron_contract
import cron_heartbeat
import sync_us_cron_dst

SPEC = importlib.util.spec_from_file_location(
    'cron_health_check', ROOT / 'scripts' / 'data' / 'cron_health_check.py'
)
cron_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cron_health)


def contract():
    return cron_contract.load_contract(ROOT / 'config' / 'cron-schedules.json')


def test_tracked_cron_contract_has_all_live_jobs():
    data = contract()
    jobs = data['jobs']
    names = {job['name'] for job in jobs}

    assert data['schema_version'] == 2
    assert len(jobs) == 11
    assert len(names) == 11
    assert {
        '盘前深度简报',
        '港股开盘报告',
        '港股午盘报告',
        '港股午后快报',
        '港股收盘报告',
        '盘中盯盘',
        '美股开盘报告',
        '美股盘中盯盘',
        '美股盘中盯盘-overnight',
        '美股收盘报告',
        'Memory Dreaming Promotion',
    } == names
    assert all(job.get('enabled', True) for job in jobs)
    assert sum(bool(job.get('watchdog')) for job in jobs) == 10


def test_us_schedules_follow_new_york_dst_without_moving_dreaming_window():
    data = contract()
    jobs = {job['name']: job for job in data['jobs']}
    july = datetime(2026, 7, 16, 0, tzinfo=timezone.utc)
    january = datetime(2026, 1, 16, 0, tzinfo=timezone.utc)

    assert cron_contract.us_season(july) == 'daylight'
    assert cron_contract.us_season(january) == 'standard'
    assert cron_contract.effective_schedule(jobs['美股开盘报告'], july)['expr'] == '30 21 * * 1-5'
    assert cron_contract.effective_schedule(jobs['美股开盘报告'], january)['expr'] == '30 22 * * 1-5'
    assert cron_contract.effective_schedule(jobs['美股收盘报告'], july)['expr'] == '0 4 * * 2-6'
    assert cron_contract.effective_schedule(jobs['美股收盘报告'], january)['expr'] == '0 5 * * 2-6'
    assert cron_contract.effective_schedule(jobs['美股盘中盯盘'], january)['expr'] == '*/30 23 * * 1-5'
    # 03:00 remains reserved for Memory Dreaming even in standard time.
    assert jobs['美股盘中盯盘-overnight']['schedule']['expr'] == '*/30 0-2 * * 2-6'


def test_us_season_changes_at_real_2026_transition_instants():
    assert cron_contract.us_season(
        datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)
    ) == 'standard'
    assert cron_contract.us_season(
        datetime(2026, 3, 8, 7, 1, tzinfo=timezone.utc)
    ) == 'daylight'
    assert cron_contract.us_season(
        datetime(2026, 11, 1, 5, 59, tzinfo=timezone.utc)
    ) == 'daylight'
    assert cron_contract.us_season(
        datetime(2026, 11, 1, 6, 1, tzinfo=timezone.utc)
    ) == 'standard'
    transition = cron_contract.next_us_dst_transition(
        datetime(2026, 1, 16, 0, tzinfo=timezone.utc)
    )
    assert transition.astimezone(ZoneInfo('America/New_York')).date().isoformat() == '2026-03-08'


def test_parse_cron_slots_uses_job_timezone_and_dow():
    # Monday 2026-07-13 16:30 UTC == Tuesday 00:30 HKT.
    now = datetime(2026, 7, 13, 16, 30, tzinfo=timezone.utc)
    slots = cron_health.parse_cron_slots(
        '*/30 0-2 * * 2-6', 'Asia/Shanghai', now
    )
    assert slots == [
        '00:00', '00:30', '01:00', '01:30', '02:00', '02:30'
    ]


def test_payload_semantic_contract_detects_deprecated_or_missing_rules():
    data = contract()
    expected = next(j for j in data['jobs'] if j['name'] == '美股开盘报告')
    profile = data['payload_profiles']['report']
    vars_ = expected['payload_vars']
    message = '\n'.join(s.format(**vars_) for s in profile['required_substrings'])
    live = {
        'payload': {'kind': 'agentTurn', 'model': profile['model'], 'message': message},
        'delivery': {'mode': 'none'},
    }
    assert cron_contract.payload_errors(data, expected, live) == []
    live['payload']['message'] = message.replace('唯一微信路径', '唯一发送路径')
    errors = cron_contract.payload_errors(data, expected, live)
    assert any('missing' in error and '唯一微信路径' in error for error in errors)
    assert any('deprecated' in error and '唯一发送路径' in error for error in errors)


def _crontab_from_contract(data, at):
    rows = []
    for index, job in enumerate(data['jobs']):
        # Mirror validate_watchdogs: a job may declare a primary `watchdog` plus
        # optional `extra_watchdogs` (盘前深度简报 has a second 09:05 miss-detector
        # pass). Synthesising only the primary made this fixture claim the extra pass
        # was missing from crontab.
        for watchdog in [job.get('watchdog')] + list(job.get('extra_watchdogs') or []):
            if not watchdog:
                continue
            expr = cron_contract.effective_schedule(watchdog, at)['expr']
            tokens = ' '.join(watchdog['command_contains'])
            rows.append(f'{expr} run-{index} {tokens}')
    sync = data['dst_sync']
    rows.append(
        f"{cron_contract.effective_schedule(sync, at)['expr']} "
        + ' '.join(sync['command_contains'])
    )
    return '\n'.join(rows) + '\n'


def test_watchdog_contract_and_dst_change_plan_cover_both_schedulers():
    data = contract()
    july = datetime(2026, 7, 16, 0, tzinfo=timezone.utc)
    january = datetime(2026, 1, 16, 0, tzinfo=timezone.utc)
    july_crontab = _crontab_from_contract(data, july)
    assert cron_contract.validate_watchdogs(data, july_crontab, july) == []

    live = []
    for job in data['jobs']:
        live.append({
            'id': f"id-{len(live)}", 'name': job['name'],
            'enabled': job.get('enabled', True),
            'schedule': cron_contract.effective_schedule(job, july),
        })
    oc, watchdogs, errors = sync_us_cron_dst.desired_changes(
        data, live, july_crontab, january
    )
    assert errors == []
    assert {change['name'] for change in oc} == {
        '美股开盘报告', '美股收盘报告', '美股盘中盯盘'
    }
    assert {change['name'] for change in watchdogs} == {
        '美股开盘报告', '美股收盘报告', '美股盘中盯盘'
    }


def test_intraday_heartbeat_is_slot_keyed_published_and_health_checked(tmp_path, monkeypatch):
    local = tmp_path / 'local.json'
    public = tmp_path / 'public.json'
    monkeypatch.setattr(cron_heartbeat, 'LOCAL_PATH', local)
    monkeypatch.setattr(cron_heartbeat, 'PUBLIC_PATH', public)
    hkt = ZoneInfo('Asia/Hong_Kong')
    at = datetime(2026, 7, 16, 10, 4, tzinfo=hkt)

    started = cron_heartbeat.record('hk', 'started', at=at)
    cron_heartbeat.record(
        'hk', 'completed', at=at, job_name=started['job'], slot=started['slot'],
        postflight_status='pass', telegram_sent=True,
    )
    assert cron_heartbeat.publish() is True
    ledger = json.loads(public.read_text())
    coverage = cron_health.heartbeat_coverage(
        '盘中盯盘', ['10:00'], 'Asia/Shanghai', at.astimezone(timezone.utc), ledger
    )
    assert coverage == {
        'monitored': ['10:00'], 'healthy': ['10:00'], 'missing': [],
        'failed': [], 'pending': []
    }
    assert cron_heartbeat.publish() is False


def test_heartbeat_health_distinguishes_missing_and_failed_slots():
    hkt = ZoneInfo('Asia/Hong_Kong')
    now = datetime(2026, 7, 16, 12, 0, tzinfo=hkt)
    ledger = {
        'schema_version': 1,
        'monitoring_started_at': '2026-07-16T09:00:00+08:00',
        'events': [{
            'job': '盘中盯盘', 'market': 'hk',
            'slot': '2026-07-16T10:00:00+08:00', 'state': 'preflight_failed',
        }],
    }
    coverage = cron_health.heartbeat_coverage(
        '盘中盯盘', ['10:00', '10:30'], 'Asia/Shanghai',
        now.astimezone(timezone.utc), ledger,
    )
    assert coverage['healthy'] == []
    assert coverage['failed'] == ['10:00:preflight_failed']
    assert coverage['missing'] == ['10:30']


def test_heartbeat_health_graces_the_current_running_slot():
    hkt = ZoneInfo('Asia/Hong_Kong')
    now = datetime(2026, 7, 16, 10, 8, tzinfo=hkt)
    ledger = {
        'schema_version': 1,
        'monitoring_started_at': '2026-07-16T09:00:00+08:00',
        'events': [{
            'job': '盘中盯盘', 'market': 'hk',
            'slot': '2026-07-16T10:00:00+08:00', 'state': 'preflight_ok',
        }],
    }
    coverage = cron_health.heartbeat_coverage(
        '盘中盯盘', ['10:00'], 'Asia/Shanghai',
        now.astimezone(timezone.utc), ledger,
    )
    assert coverage['pending'] == ['10:00:preflight_ok']
    assert coverage['failed'] == []


def test_intraday_hard_length_limit_is_a_failure():
    import intraday_postflight

    assert intraday_postflight.categorize(
        ['报告长度 2501 字 > 2500 上限']
    ) == 'fail'
    assert intraday_postflight.categorize(
        ['报告长度 2100 字 > 2000 软上限 (warn)']
    ) == 'warn'


def test_every_twenty_minutes_timeline_label_is_not_every_hour():
    timeline_spec = importlib.util.spec_from_file_location(
        'cron_timeline', ROOT / 'scripts' / 'data' / 'cron_timeline.py'
    )
    timeline = importlib.util.module_from_spec(timeline_spec)
    timeline_spec.loader.exec_module(timeline)

    mins, hours, _ = timeline.parse_cron('*/20 * * * *')
    assert timeline.time_label(mins, hours) == '每20分钟'
