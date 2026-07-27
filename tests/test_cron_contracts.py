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
        'payload': {
            'kind': 'agentTurn',
            'model': profile['model'],
            'fallbacks': profile['model_candidates'][1:],
            'message': message,
        },
        'delivery': {'mode': 'none'},
    }
    assert cron_contract.payload_errors(data, expected, live) == []
    live['payload']['message'] = message.replace('唯一微信路径', '唯一发送路径')
    errors = cron_contract.payload_errors(data, expected, live)
    assert any('missing' in error and '唯一微信路径' in error for error in errors)
    assert any('deprecated' in error and '唯一发送路径' in error for error in errors)


def test_model_rotation_rejects_duplicates_unknown_models_and_skipped_order():
    data = contract()
    expected = next(j for j in data['jobs'] if j['name'] == '美股开盘报告')
    profile = data['payload_profiles']['report']
    message = '\n'.join(
        s.format(**expected['payload_vars']) for s in profile['required_substrings']
    )
    live = {
        'payload': {
            'kind': 'agentTurn',
            'model': profile['model_candidates'][0],
            'fallbacks': [profile['model_candidates'][0], 'dead/example'],
            'message': message,
        },
        'delivery': {'mode': 'none'},
    }
    errors = cron_contract.payload_errors(data, expected, live)
    assert any('duplicates' in error for error in errors)
    assert any('unknown models' in error for error in errors)

    live['payload']['fallbacks'] = [profile['model_candidates'][2]]
    errors = cron_contract.payload_errors(data, expected, live)
    assert any('fixed prefix' in error for error in errors)


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


def test_delta_no_change_heartbeat_counts_as_healthy():
    hkt = ZoneInfo('Asia/Hong_Kong')
    at = datetime(2026, 7, 16, 10, 35, tzinfo=hkt)
    ledger = {
        'schema_version': 1,
        'monitoring_started_at': '2026-07-16T09:00:00+08:00',
        'events': [{
            'job': '盘中盯盘',
            'market': 'hk',
            'slot': '2026-07-16T10:30:00+08:00',
            'state': 'no_change',
            'reasoning_invoked': False,
        }],
    }

    coverage = cron_health.heartbeat_coverage(
        '盘中盯盘', ['10:30'], 'Asia/Shanghai',
        at.astimezone(timezone.utc), ledger,
    )

    assert coverage['healthy'] == ['10:30']
    assert coverage['missing'] == []


def test_record_keeps_existing_monitoring_epoch_for_valid_empty_ledger(tmp_path, monkeypatch):
    # A ledger that exists on disk with a real (earlier) monitoring epoch but no
    # live events must NOT be re-anchored to the first later slot — doing so would
    # erase evidence that the earlier slots were missed.
    local = tmp_path / 'local.json'
    public = tmp_path / 'public.json'
    local.write_text(json.dumps({
        'schema_version': cron_heartbeat.SCHEMA_VERSION,
        'monitoring_started_at': '2026-07-16T09:00:00+08:00',
        'updated_at': '2026-07-16T09:00:00+08:00',
        'events': [],
    }))
    monkeypatch.setattr(cron_heartbeat, 'LOCAL_PATH', local)
    monkeypatch.setattr(cron_heartbeat, 'PUBLIC_PATH', public)
    hkt = ZoneInfo('Asia/Hong_Kong')
    at = datetime(2026, 7, 16, 10, 4, tzinfo=hkt)
    cron_heartbeat.record('hk', 'started', at=at)
    ledger = json.loads(local.read_text())
    assert ledger['monitoring_started_at'] == '2026-07-16T09:00:00+08:00'


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
        ['报告长度 3501 字 > 3500 上限']
    ) == 'fail'
    assert intraday_postflight.categorize(
        ['报告长度 3100 字 > 3000 软上限 (warn)']
    ) == 'warn'


def test_length_thresholds_are_the_relaxed_3000_3500_pair():
    """2026-07-23: every tier was raised by 1000 字 (target 1200→2200, warn
    2000→3000, fail 2500→3500). categorize() alone can't catch a threshold
    regression — it only reads the issue *string* — so assert the boundaries
    through the real validate() of both postflights, and keep the tracked cron
    contract pinned to the same numbers (live payloads are checked against it)."""
    import intraday_postflight
    import report_postflight

    body = '▎我的看法\n' + '判' * 200 + '\n'

    def intraday_len(n):
        text = body + '填' * (n - len(body))
        assert len(text) == n
        return [i for i in intraday_postflight.validate(text, {}) if '报告长度' in i]

    assert intraday_len(3000) == []
    assert intraday_len(3001) == ['报告长度 3001 字 > 3000 软上限 (warn)']
    assert intraday_len(3500) == ['报告长度 3500 字 > 3000 软上限 (warn)']
    assert intraday_len(3501) == ['报告长度 3501 字 > 3500 上限']
    assert intraday_postflight.categorize(['报告长度 3501 字 > 3500 上限']) == 'fail'

    for market in ('hk', 'us'):
        def report_len(n, market=market):
            text = '填' * n
            return [i for i in report_postflight.validate(text, {'market': market})
                    if '报告长度' in i]

        assert report_len(3000) == []
        assert report_len(3001) == ['报告长度 3001 字 > 3000 软上限 (warn)']
        assert report_len(3500) == ['报告长度 3500 字 > 3000 软上限 (warn)']
        assert report_len(3501) == ['报告长度 3501 字 > 3500 上限']
        assert report_postflight.categorize(['报告长度 3501 字 > 3500 上限']) == 'fail'

    for profile in ('report', 'intraday'):
        required = contract()['payload_profiles'][profile]['required_substrings']
        forbidden = contract()['payload_profiles'][profile]['forbidden_substrings']
        assert '>3000 字 warn' in required and '>3500 字 fail' in required
        assert '目标 ≤ 2200 字' in required
        # the pre-relaxation numbers must not survive in a live payload
        assert '>2000 字 warn' in forbidden and '>2500 字 fail' in forbidden


def test_intraday_empty_input_is_an_input_error_not_a_content_failure(monkeypatch):
    """2026-07-23 10:00 HK: postflight was called with no stdin at all. The empty
    read went straight into validate() and produced four "you wrote the report
    wrong" issues, hiding the real cause (missing plumbing). Empty input must be
    reported as its own class, and must never reach content validation."""
    import io
    import intraday_postflight

    monkeypatch.setattr(sys, 'stdin', io.StringIO(''))
    text, err = intraday_postflight.read_report_text('hk', None)
    assert text == ''
    assert '空输入' in err and '--text-file' in err

    monkeypatch.setattr(sys, 'stdin', io.StringIO('   \n\n  '))
    _, err_ws = intraday_postflight.read_report_text('hk', None)
    assert err_ws, 'whitespace-only input must be rejected too'


def test_intraday_stale_report_file_is_refused(tmp_path):
    """A forgotten Step 3 rewrite must not silently republish the previous slot's
    report — the failure mode --text-file would otherwise introduce."""
    import os

    import intraday_postflight

    report = tmp_path / 'intraday-report-hk.md'
    report.write_text('🇭🇰 港股盯盘 | 07/23 10:03 HKT\n▎我的看法\n' + 'x' * 80)

    text, err = intraday_postflight.read_report_text('hk', str(report))
    assert err is None and text, 'a freshly written report must pass'

    stale = (datetime.now().timestamp()
             - (intraday_postflight.REPORT_MAX_AGE_MIN + 5) * 60)
    os.utime(report, (stale, stale))
    _, err_stale = intraday_postflight.read_report_text('hk', str(report))
    assert err_stale and '旧报告' in err_stale

    _, err_missing = intraday_postflight.read_report_text('hk', str(tmp_path / 'nope.md'))
    assert err_missing and '不存在' in err_missing


def test_intraday_main_stops_on_empty_input_and_blames_the_context_slot(monkeypatch, capsys):
    """End-to-end on main(): empty input must exit 2 without ever reaching content
    validation or delivery, and the failure must be stamped on the slot the
    preflight context was built for. A run that starts at 10:00 but hits empty
    input at 10:31 would otherwise record a phantom 10:30 failure while the
    successful retry marks 10:00 completed."""
    import io

    import intraday_postflight

    recorded = {}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(''))
    monkeypatch.setattr(sys, 'argv', ['intraday_postflight.py', '--market', 'hk'])
    monkeypatch.setattr(intraday_postflight.trading_calendar, 'closed_reason', lambda m: None)
    monkeypatch.setattr(intraday_postflight, 'load_context', lambda m: (
        {'heartbeat': {'job': '盘中盯盘', 'slot': '2026-07-23T10:00:00+08:00'}}, None))
    monkeypatch.setattr(intraday_postflight.cron_heartbeat, 'record',
                        lambda *a, **kw: recorded.update(args=a, kwargs=kw))

    def _never(*a, **kw):
        raise AssertionError('empty input must not reach content validation/delivery')

    monkeypatch.setattr(intraday_postflight, 'validate', _never)
    monkeypatch.setattr(intraday_postflight, 'send_wechat', _never)

    assert intraday_postflight.main() == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload['status'] == 'input_error'
    assert payload['n_chars'] == 0
    assert payload['wechat_sent'] is None and payload['dashboard_published'] is False

    assert recorded['args'] == ('hk', 'postflight_failed')
    assert recorded['kwargs']['slot'] == '2026-07-23T10:00:00+08:00'
    assert recorded['kwargs']['job_name'] == '盘中盯盘'
    assert recorded['kwargs']['failure_stage'] == 'input'


def test_intraday_payload_contract_bans_heredoc_and_requires_text_file():
    """The live cron payload and the SKILL are two sources of truth for the same
    command. Pin the plumbing in the tracked contract so they cannot drift apart
    again."""
    profile = contract()['payload_profiles']['intraday']
    assert '--text-file' in profile['required_substrings']
    assert 'intraday-prose-{market}.md' in profile['required_substrings']
    assert 'intraday_postflight.py --market {market} --context-id' in profile['required_substrings']
    assert 'verbatim' in profile['forbidden_substrings']
    assert '<<<' in profile['forbidden_substrings']

    vars_ = {'market': 'hk', 'skill': 'hk-stock-analysis'}
    data = contract()
    expected = {job['name']: job for job in data['jobs']}['盘中盯盘']
    message = '\n'.join(s.format(**vars_) for s in profile['required_substrings'])
    live = {
        'payload': {'message': message, 'kind': 'agentTurn',
                    'model': profile['model'], 'thinking': profile['thinking']},
        'delivery': {'mode': 'none'},
    }
    assert cron_contract.payload_errors(data, expected, live) == []

    live['payload']['message'] = message + '\nintraday_postflight.py --market hk <<< "{报告}"'
    assert cron_contract.payload_errors(data, expected, live) != []


def test_intraday_slots_are_unconditional_again():
    """Every Mode 7 slot runs the turn; no pre-model condition gate.

    The delta trigger (#46 / #61) skipped slots where nothing crossed a
    threshold. It saved model workload, but kcn's constraint is not cost — a
    silent slot is indistinguishable from a dead cron, and the whole point of
    the intraday cadence is being able to look at any slot. The contract now
    carries no trigger, and a live job that still has one is a drift error
    rather than the expected state.
    """
    data = contract()
    profile = data['payload_profiles']['intraday']
    assert 'trigger' not in profile
    assert not (ROOT / 'config' / 'cron-triggers').exists()

    expected = {job['name']: job for job in data['jobs']}['盘中盯盘']
    vars_ = {'market': 'hk', 'skill': 'hk-stock-analysis'}
    message = '\n'.join(s.format(**vars_) for s in profile['required_substrings'])
    live = {
        'payload': {'message': message, 'kind': 'agentTurn',
                    'model': profile['model'], 'thinking': profile['thinking']},
        'delivery': {'mode': 'none'},
        'trigger': {'script': 'json({ fire: false });', 'once': False},
    }
    assert cron_contract.payload_errors(data, expected, live) == [
        'unexpected condition trigger'
    ]


def test_every_twenty_minutes_timeline_label_is_not_every_hour():
    timeline_spec = importlib.util.spec_from_file_location(
        'cron_timeline', ROOT / 'scripts' / 'data' / 'cron_timeline.py'
    )
    timeline = importlib.util.module_from_spec(timeline_spec)
    timeline_spec.loader.exec_module(timeline)

    mins, hours, _ = timeline.parse_cron('*/20 * * * *')
    assert timeline.time_label(mins, hours) == '每20分钟'


def _brief_live_payload(data, *, timeout=1800):
    """A live 盘前深度简报 job that satisfies every other clause of its profile."""
    expected = next(j for j in data['jobs'] if j['name'] == '盘前深度简报')
    profile = data['payload_profiles']['brief']
    vars_ = expected.get('payload_vars') or {}
    message = '\n'.join(s.format(**vars_) for s in profile['required_substrings'])
    live = {
        'payload': {
            'kind': profile['payload_kind'],
            'model': profile['model'],
            'fallbacks': profile['model_candidates'][1:2],
            'message': message,
        },
        'delivery': {'mode': profile['delivery_mode']},
    }
    if timeout is not None:
        live['payload']['timeoutSeconds'] = timeout
    return expected, live


def test_brief_payload_must_declare_a_timeout():
    # Unbounded, this job ran 71/81/86 minutes on 2026-07-15/16/17 and was stopped
    # only by an unrelated gateway restart — each time still running minutes before
    # the 09:30 report's slot (issue #121).
    data = contract()
    expected, live = _brief_live_payload(data)
    assert cron_contract.payload_errors(data, expected, live) == []

    _, no_timeout = _brief_live_payload(data, timeout=None)
    errors = cron_contract.payload_errors(data, expected, no_timeout)
    assert any('timeoutSeconds' in error for error in errors), errors

    _, drifted = _brief_live_payload(data, timeout=5400)
    errors = cron_contract.payload_errors(data, expected, drifted)
    assert any('timeoutSeconds' in error for error in errors), errors


def test_brief_timeout_lands_before_the_next_cron_window():
    # 08:00 + timeout must finish clear of 港股开盘报告 at 09:30, or a slow brief
    # is still holding the agent when the next job is due.
    data = contract()
    timeout = data['payload_profiles']['brief']['timeout_seconds']
    brief = next(j for j in data['jobs'] if j['name'] == '盘前深度简报')
    nxt = next(j for j in data['jobs'] if j['name'] == '港股开盘报告')
    start_min = int(brief['schedule']['expr'].split()[1]) * 60
    next_min = (int(nxt['schedule']['expr'].split()[1]) * 60
                + int(nxt['schedule']['expr'].split()[0]))
    assert start_min + timeout / 60 <= next_min


def test_only_the_brief_profile_pins_a_timeout_for_now():
    # The reporting profiles have a 558s p100 and no evidence of harm; pinning them
    # here would assert a bound the live jobs do not have and red the gate.
    data = contract()
    pinned = [name for name, profile in data['payload_profiles'].items()
              if profile.get('timeout_seconds') is not None]
    assert pinned == ['brief']
