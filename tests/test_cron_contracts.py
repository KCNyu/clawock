import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'cron_health_check', ROOT / 'scripts' / 'data' / 'cron_health_check.py'
)
cron_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cron_health)


def test_tracked_cron_contract_has_all_live_jobs():
    data = json.loads((ROOT / 'config' / 'cron-schedules.json').read_text())
    jobs = data['jobs']
    names = {job['name'] for job in jobs}

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


def test_hkt_cross_midnight_schedule_days_are_explicit():
    data = json.loads((ROOT / 'config' / 'cron-schedules.json').read_text())
    schedules = {job['name']: job['schedule'] for job in data['jobs']}

    assert schedules['美股盘中盯盘-overnight']['expr'] == '*/30 0-2 * * 2-6'
    assert schedules['美股收盘报告']['expr'] == '0 4 * * 2-6'
    assert schedules['美股盘中盯盘-overnight']['tz'] == 'Asia/Shanghai'
    assert schedules['美股收盘报告']['tz'] == 'Asia/Shanghai'


def test_parse_cron_slots_uses_job_timezone_and_dow():
    # Monday 2026-07-13 16:30 UTC == Tuesday 00:30 HKT.
    now = datetime(2026, 7, 13, 16, 30, tzinfo=timezone.utc)
    slots = cron_health.parse_cron_slots(
        '*/30 0-2 * * 2-6', 'Asia/Shanghai', now
    )
    assert slots == [
        '00:00', '00:30', '01:00', '01:30', '02:00', '02:30'
    ]


def test_intraday_hard_length_limit_is_a_failure():
    sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))
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
