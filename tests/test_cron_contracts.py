import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops' / 'host'))

from clawock_kcnyu import schedule as cron_contract
from clawock_kcnyu.automation import cron_heartbeat
import sync_us_cron_dst

SPEC = importlib.util.spec_from_file_location(
    'cron_health_check', ROOT / 'ops' / 'host' / 'cron_health_check.py'
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
    message = cron_contract.render_payload_message(data, expected)
    live = {
        'payload': {
            'kind': 'agentTurn',
            'model': profile['model'],
            'fallbacks': profile['fallbacks'],
            'thinking': profile['thinking'],
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
            rows.append(f"{expr} {watchdog['command']}")
    sync = data['dst_sync']
    rows.append(
        f"{cron_contract.effective_schedule(sync, at)['expr']} "
        + sync['command']
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


def test_contract_has_no_retired_host_command_migrations():
    data = contract()
    specs = [data['dst_sync']]
    for job in data['jobs']:
        specs.extend(job.get('system_watchdogs', []))
        specs.extend(job.get('extra_system_watchdogs', []))
    assert all('legacy_command_contains' not in spec for spec in specs)


def test_crontab_apply_preserves_every_unmanaged_line(monkeypatch):
    original = (
        '# managed and unrelated host jobs\n'
        '30 8 * * 1-5 old-watchdog\n'
        '0,20,40 * * * * /bin/bash /srv/publisher.sh\n'
    )
    captured = {}

    def fake_run(argv, **kwargs):
        captured['argv'] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')

    monkeypatch.setattr(sync_us_cron_dst.subprocess, 'run', fake_run)
    errors = sync_us_cron_dst.apply_crontab(original, [{
        'line_index': 1,
        'to': {
            'expr': '30 8 * * 1-5',
            'command': '/root/.local/bin/clawock-kcnyu-brief-watchdog',
        },
    }])

    assert errors == []
    assert captured['argv'] == ['crontab', '-']
    assert captured['input'] == (
        '# managed and unrelated host jobs\n'
        '30 8 * * 1-5 /root/.local/bin/clawock-kcnyu-brief-watchdog\n'
        '0,20,40 * * * * /bin/bash /srv/publisher.sh\n'
    )


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
    from clawock_kcnyu.harness import intraday_postflight

    assert intraday_postflight.categorize(
        ['报告长度 3501 字 > 3500 上限']
    ) == 'fail'
    assert intraday_postflight.categorize(
        ['报告长度 3100 字 > 3000 软上限 (warn)']
    ) == 'warn'


def test_length_ceiling_is_one_number_shared_by_the_live_payloads():
    """#334 removed the pre-write字数目标 and left a single repeat-loop ceiling.
    The boundaries themselves are asserted in test_report_length_ceiling.py;
    what belongs here is that the tracked contract — which live payloads are
    checked against — moved with the code, and that the retired numbers can
    never reappear in a live payload."""
    from clawock.harness import validation

    soft = validation.REPORT_CHAR_LIMITS['soft']
    hard = validation.REPORT_CHAR_LIMITS['hard']

    for profile in ('report', 'intraday'):
        required = contract()['payload_profiles'][profile]['required_substrings']
        forbidden = contract()['payload_profiles'][profile]['forbidden_substrings']
        assert f'>{soft} warn' in required and f'>{hard} fail' in required
        # a live payload still carrying a writing target is the drift to catch
        assert '目标 ≤ 2200 字' in forbidden
        assert '>3000 字 warn' in forbidden and '>3500 字 fail' in forbidden
        assert '>2000 字 warn' in forbidden and '>2500 字 fail' in forbidden


def test_intraday_empty_input_is_an_input_error_not_a_content_failure(monkeypatch):
    """2026-07-23 10:00 HK: postflight was called with no stdin at all. The empty
    read went straight into validate() and produced four "you wrote the report
    wrong" issues, hiding the real cause (missing plumbing). Empty input must be
    reported as its own class, and must never reach content validation."""
    import io
    from clawock_kcnyu.harness import intraday_postflight

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

    from clawock_kcnyu.harness import intraday_postflight

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

    from clawock_kcnyu.harness import intraday_postflight

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
    assert 'clawock intraday postflight --market {market} --context-id' in profile['required_substrings']
    assert 'verbatim' in profile['forbidden_substrings']
    assert '<<<' in profile['forbidden_substrings']
    assert 'trading_calendar.py' in profile['forbidden_substrings']
    assert 'market_closed' in profile['required_substrings']
    assert '所有脚本 exec 调用都显式设置 `timeout: 300`' in profile['required_substrings']
    assert any(
        '只用 `process` poll' in line and 'sleep/ps/ls/grep' in line
        for line in profile['required_substrings']
    )
    assert '同一条回复内并行发出两个 `write` 工具调用' in profile['required_substrings']
    exact_number_rule = (
        '数字必须原样照抄 context 的完整字面值；'
        '禁止四舍五入、取整或改写成“约/近”等近似数，找不到原值就省略'
    )
    assert exact_number_rule in profile['required_substrings']
    assert any(
        'postflight 返回 pass/warn 后直接输出' in line and '禁止再读、搜或重建' in line
        for line in profile['required_substrings']
    )
    assert profile['tools_allow'] is None
    assert profile['thinking'] == 'adaptive'
    # 300s is a per-exec bound. A 300s whole-turn timeout would kill normal
    # 4–6 minute check-ins before postflight can deliver them.
    assert 'timeout_seconds' not in profile

    data = contract()
    expected = {job['name']: job for job in data['jobs']}['盘中盯盘']
    message = cron_contract.render_payload_message(data, expected)
    assert exact_number_rule in message
    live = {
        'payload': {'message': message, 'kind': 'agentTurn',
                    'model': profile['model'], 'thinking': profile['thinking'],
                    'fallbacks': profile['fallbacks']},
        'delivery': {'mode': 'none'},
    }
    assert cron_contract.payload_errors(data, expected, live) == []

    live['payload']['message'] = message + '\nintraday_postflight.py --market hk <<< "{报告}"'
    assert cron_contract.payload_errors(data, expected, live) != []


def test_strategy_crons_pin_minimax_m3_adaptive_reasoning():
    """M3 exposes only off/adaptive; high is a budgeted M2.x level.

    Adaptive is M3's reasoning-enabled mode, not a context or output reduction.
    Keeping the supported value explicit prevents every live run from silently
    rewriting the tracked contract while emitting an unsupported-level warning.
    """
    profiles = contract()['payload_profiles']
    assert {
        name: profiles[name].get('thinking')
        for name in ('report', 'intraday', 'brief')
    } == {
        'report': 'adaptive',
        'intraday': 'adaptive',
        'brief': 'adaptive',
    }


def test_strategy_cron_provider_order_is_fixed_policy():
    profiles = contract()['payload_profiles']

    # This concrete order is policy. Reordering it requires a deliberate human
    # decision; do not make this expectation follow the contract dynamically.
    assert {
        name: {
            'model': profiles[name].get('model'),
            'fallbacks': profiles[name].get('fallbacks'),
            'model_candidates': profiles[name].get('model_candidates'),
        }
        for name in ('report', 'intraday', 'brief')
    } == {
        'report': {
            'model': 'minimax/MiniMax-M3',
            'fallbacks': ['minimax-2/MiniMax-M3'],
            'model_candidates': [
                'minimax/MiniMax-M3',
                'minimax-2/MiniMax-M3',
                'openai/gpt-5.6-sol',
                'anthropic/claude-sonnet-4-6',
            ],
        },
        'intraday': {
            'model': 'minimax/MiniMax-M3',
            'fallbacks': ['minimax-2/MiniMax-M3'],
            'model_candidates': [
                'minimax/MiniMax-M3',
                'minimax-2/MiniMax-M3',
                'openai/gpt-5.6-sol',
                'anthropic/claude-sonnet-4-6',
            ],
        },
        'brief': {
            'model': 'minimax/MiniMax-M3',
            'fallbacks': ['minimax-2/MiniMax-M3'],
            'model_candidates': [
                'minimax/MiniMax-M3',
                'minimax-2/MiniMax-M3',
                'openai/gpt-5.6-sol',
                'anthropic/claude-sonnet-4-6',
            ],
        },
    }


def test_strategy_crons_require_skill_body_read_in_first_tool_batch():
    """The skills system prompt is a catalog, not the SKILL.md body.

    Saying "follow this skill" is therefore insufficient: a model can go
    straight to preflight and never receive the strategy rules.  Pin an
    explicit read in the first parallel tool batch so loading the real body
    does not add another model round trip.
    """
    data = contract()
    jobs = {job['name']: job for job in data['jobs']}

    report = cron_contract.render_payload_message(data, jobs['美股开盘报告'])
    assert (
        '并行调用 `read` 读取 '
        '`/root/.openclaw/workspace/skills/us-stock-analysis/SKILL.md` '
        '与 Step 1 preflight'
    ) in report

    intraday = cron_contract.render_payload_message(data, jobs['美股盘中盯盘'])
    assert (
        '并行调用 `read` 读取 '
        '`/root/.openclaw/workspace/skills/us-stock-analysis/SKILL.md` '
        '与 Step 1 preflight'
    ) in intraday

    brief = cron_contract.render_payload_message(data, jobs['盘前深度简报'])
    assert (
        '并行调用 `read` 读取 '
        '`/root/.openclaw/workspace/skills/daily-deep-brief/SKILL.md` '
        '与下方 Step 0 的两个休市闸命令'
    ) in brief

    assert all(
        'skills catalog 只有索引，不含 SKILL.md 正文' in message
        for message in (report, intraday, brief)
    )


def test_brief_repair_uses_whole_file_write_instead_of_brittle_edit():
    data = contract()
    profile = data['payload_profiles']['brief']
    brief = next(job for job in data['jobs'] if job['name'] == '盘前深度简报')
    message = cron_contract.render_payload_message(data, brief)
    rule = (
        '首次生成和 postflight 修复 Step 4 产物都只用 `write` 完整覆盖；'
        '禁止 `edit` 精确文本替换'
    )

    assert rule in profile['required_substrings']
    assert rule in message
    assert '一次已恢复的 `edit` 工具错误仍会把整个 cron 记成 error' in message


def test_brief_uses_the_installed_calendar_command():
    data = contract()
    profile = data['payload_profiles']['brief']
    brief = next(job for job in data['jobs'] if job['name'] == '盘前深度简报')
    message = cron_contract.render_payload_message(data, brief)

    for market in ('hk', 'us'):
        command = f'/root/.local/bin/clawock calendar {market}'
        assert command in profile['required_substrings']
        assert command in message
    assert 'trading_calendar.py' in profile['forbidden_substrings']
    assert 'trading_calendar.py' not in message


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
    message = cron_contract.render_payload_message(data, expected)
    live = {
        'payload': {'message': message, 'kind': 'agentTurn',
                    'model': profile['model'], 'thinking': profile['thinking'],
                    'fallbacks': profile['fallbacks']},
        'delivery': {'mode': 'none'},
        'trigger': {'script': 'json({ fire: false });', 'once': False},
    }
    assert cron_contract.payload_errors(data, expected, live) == [
        'unexpected condition trigger'
    ]


def test_intraday_payload_rejects_stale_restricted_tool_override():
    data = contract()
    expected = {job['name']: job for job in data['jobs']}['盘中盯盘']
    profile = data['payload_profiles']['intraday']
    message = cron_contract.render_payload_message(data, expected)
    live = {
        'payload': {
            'message': message,
            'kind': profile['payload_kind'],
            'model': profile['model'],
            'fallbacks': profile['fallbacks'],
            'thinking': profile['thinking'],
            'toolsAllow': ['exec', 'process', 'read', 'write'],
        },
        'delivery': {'mode': profile['delivery_mode']},
    }
    errors = cron_contract.payload_errors(data, expected, live)
    assert errors == [
        "payload.toolsAllow expected unrestricted tools, "
        "got ['exec', 'process', 'read', 'write']"
    ]


def test_every_twenty_minutes_timeline_label_is_not_every_hour():
    timeline_spec = importlib.util.spec_from_file_location(
        'cron_timeline', ROOT / 'ops' / 'host' / 'cron_timeline.py'
    )
    timeline = importlib.util.module_from_spec(timeline_spec)
    timeline_spec.loader.exec_module(timeline)

    mins, hours, _ = timeline.parse_cron('*/20 * * * *')
    assert timeline.time_label(mins, hours) == '每20分钟'


def _brief_live_payload(data, *, timeout=1800):
    """A live 盘前深度简报 job that satisfies every other clause of its profile."""
    expected = next(j for j in data['jobs'] if j['name'] == '盘前深度简报')
    profile = data['payload_profiles']['brief']
    message = cron_contract.render_payload_message(data, expected)
    live = {
        'payload': {
            'kind': profile['payload_kind'],
            'model': profile['model'],
            'fallbacks': profile['fallbacks'],
            'thinking': profile['thinking'],
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
