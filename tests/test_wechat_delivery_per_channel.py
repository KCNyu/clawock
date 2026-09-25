"""WeChat and Telegram are independent delivery targets, judged separately.

2026-09-17 08:03 HKT: the 盘前深度简报 postflight's WeChat send failed
(`sendMessage ret=-2 errmsg=prepare failed`) while its Telegram co-send landed.
The marker said so exactly:

    brief-sent-2026-09-17.json  {"sent_ok": false, "tg_ok": true, ...}

but two readers folded the channels together:

  * `already_delivered` answered "WeChat OR Telegram", so every later
    `clawock brief postflight` run skipped the send and reported
    `wechat_sent: true` — a WeChat success that was really Telegram's;
  * brief_watchdog at 08:33 saw `tg_ok` and logged "postflight cosend already
    delivered Telegram today — no backstop". WeChat was never retried and
    nothing told kcn it had missed.

The report and intraday postflights share `already_delivered`, and their
watchdogs share the Telegram-only verdict, so the same slot shape was silent
there too. Pinned here:

  A. a Telegram-only marker is NOT a WeChat delivery (all three postflights);
  B. the re-send owes WeChat alone — Telegram already has it, no second copy;
  C. the watchdog retries WeChat exactly once for THIS slot's confirmed failure,
     and alerts on Telegram when the retry fails too;
  D. none of that reaches past the slot: an ambiguous (missing/stale/other-day)
     marker keeps the 2026-07-09 no-WeChat-resend rule.
"""
import json
from datetime import datetime, timedelta

import pytest

from clawock.harness import _watchdog_common as common

# The marker 2026-09-17's brief actually left behind (ts rewritten per test).
INCIDENT = {
    'sent_ok': False, 'tg_ok': True,
    'first_line': '📊 盘前深度简报｜2026-09-17 08:03 HKT  (USDHKD=7.8449)',
    'out': 'OutboundDeliveryError: sendMessage ret=-2 errmsg=prepare failed',
}


@pytest.fixture(autouse=True)
def _watchdog_log(isolated_watchdog_log):
    return isolated_watchdog_log


def _events(log_path):
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines()]


def _now_ms(minutes_ago=0):
    return int((datetime.now() - timedelta(minutes=minutes_ago)).timestamp() * 1000)


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False))
    return path


# ── A. the idempotency guard ─────────────────────────────────────────────────

def test_telegram_only_marker_is_not_a_wechat_delivery(tmp_path):
    marker = _write(tmp_path / 'brief-sent-2026-09-17.json', {'ts': _now_ms(), **INCIDENT})

    assert common.delivered_channels(marker) == (False, True)
    assert common.already_delivered(marker) is False, (
        'Telegram landing must not stop the WeChat re-send — this is the '
        '2026-09-17 brief that never reached WeChat')


def test_wechat_success_still_blocks_the_resend(tmp_path):
    """The 2026-07-11 retry-storm guard is unchanged for a real WeChat delivery."""
    marker = _write(tmp_path / 'm.json', {'ts': _now_ms(), 'sent_ok': True, 'tg_ok': False})
    assert common.already_delivered(marker) is True


def test_a_landed_watchdog_backstop_counts_as_wechat_delivered(tmp_path):
    marker = _write(tmp_path / 'm.json', {'ts': _now_ms(), **INCIDENT,
                                          'wechat_backstop': {'ok': True}})
    assert common.delivered_channels(marker) == (True, True)
    assert common.already_delivered(marker) is True


def test_intraday_window_still_bounds_both_channels(tmp_path):
    marker = _write(tmp_path / 'intraday-sent-hk.json',
                    {'ts': _now_ms(minutes_ago=25), 'sent_ok': True, 'tg_ok': True})
    assert common.delivered_channels(marker, within_ms=20 * 60 * 1000) == (False, False)


SLOT_1000 = '2026-09-18T10:00:00+08:00'
SLOT_1030 = '2026-09-18T10:30:00+08:00'


def test_intraday_marker_from_the_previous_slot_is_not_this_slot(tmp_path):
    """#1555: the 10:00 slot landed late (10:18); the 10:30 slot's postflight
    at 10:35 finds its marker 17min old — inside the window, but not a retry."""
    marker = _write(tmp_path / 'intraday-sent-hk.json',
                    {'ts': _now_ms(minutes_ago=17), 'sent_ok': True, 'tg_ok': True,
                     'slot': SLOT_1000})
    window = 20 * 60 * 1000
    assert common.delivered_channels(marker, within_ms=window, slot=SLOT_1030) == (False, False)
    assert common.already_delivered(marker, within_ms=window, slot=SLOT_1030) is False
    # A real retry of the same slot is still suppressed …
    assert common.already_delivered(marker, within_ms=window, slot=SLOT_1000) is True
    # … and a marker or caller without a slot keeps the window-only rule.
    assert common.already_delivered(marker, within_ms=window) is True
    legacy = _write(tmp_path / 'legacy.json',
                    {'ts': _now_ms(minutes_ago=17), 'sent_ok': True, 'tg_ok': True})
    assert common.already_delivered(legacy, within_ms=window, slot=SLOT_1030) is True


def test_intraday_postflight_sends_the_next_slot_after_a_late_one(tmp_path, monkeypatch):
    """intraday_postflight.main end-to-end at the send, external I/O stubbed."""
    from clawock.harness import intraday_postflight as postflight

    ctx = {'status': 'ok', 'date': '2026-09-18', 'context_id': 'c1030',
           'raw_wechat_block': '📈 港股盘中 10:30\nblock',
           'heartbeat': {'job': '盘中盯盘', 'slot': SLOT_1030}}
    monkeypatch.setattr(postflight, 'TMP', tmp_path)
    marker = postflight.delivery_receipts.receipt_path(tmp_path, 'intraday', market='hk')
    _write(marker, {'ts': _now_ms(minutes_ago=17), 'sent_ok': True, 'tg_ok': True,
                    'job': '盘中盯盘', 'slot': SLOT_1000, 'context_id': 'c1000'})
    sends = []
    stubs = {
        'load_context': lambda market: (ctx, None),
        'read_report_text': lambda market, text_file: ('prose', None),
        'assemble_message': lambda c, text: 'body',
        'validate': lambda *a, **kw: [],
        'normalize_intraday_insights': lambda path, **_kwargs: True,
        'publish_data_plane': lambda market: ('current', False),
        'send_per_policy': lambda *a, **kw: (sends.append(a[1]), (True, 'ok', True))[1],
    }
    for name, value in stubs.items():
        monkeypatch.setattr(postflight, name, value)
    monkeypatch.setattr(postflight.trading_calendar, 'closed_reason', lambda market: None)
    monkeypatch.setattr(postflight.cron_heartbeat, 'record', lambda *a, **kw: None)
    monkeypatch.setattr(postflight.cron_heartbeat, 'unpushed_commits', lambda: 0)
    monkeypatch.setattr(postflight.intraday_delta, 'persist_delivered_state',
                        lambda *a, **kw: None)

    postflight.main(['--market', 'hk', '--context-id', 'c1030', '--text-file', 'unused'])

    assert sends == ['body'], 'the 10:30 slot was swallowed by the 10:00 receipt'
    assert json.loads(marker.read_text())['slot'] == SLOT_1030


# ── B. the re-send owes WeChat alone ─────────────────────────────────────────

def test_send_per_policy_skips_telegram_already_delivered():
    sent = {'wechat': 0, 'telegram': 0}

    def wechat(*_a, **_kw):
        sent['wechat'] += 1
        return True, 'ok'

    def telegram(*_a, **_kw):
        sent['telegram'] += 1
        return True, 'ok'

    ok, _out, tg_ok = common.send_per_policy(
        'brief', 'card', tag='brief', wechat=wechat, telegram=telegram,
        resolve=lambda: ('openclaw-weixin', 'kcn', 'acct'), telegram_done=True)

    assert (ok, tg_ok) == (True, True)
    assert sent == {'wechat': 1, 'telegram': 0}


def test_report_rerun_after_wechat_failure_resends_wechat_only(tmp_path, monkeypatch):
    """report_postflight end-to-end at the send: marker in, marker out."""
    from clawock.harness import report_postflight as postflight

    sent = {'wechat': 0, 'telegram': 0}
    monkeypatch.setattr(postflight, 'TMP', tmp_path)
    monkeypatch.setattr(postflight, 'resolve_wechat_target',
                        lambda market: ('openclaw-weixin', 'kcn', 'acct'))
    monkeypatch.setattr(postflight, 'send_wechat',
                        lambda *a, **kw: (sent.__setitem__('wechat', sent['wechat'] + 1),
                                          (True, 'sent'))[1])
    monkeypatch.setattr(postflight, 'cosend_telegram',
                        lambda *a, **kw: (sent.__setitem__('telegram', sent['telegram'] + 1),
                                          (True, 'sent'))[1])
    marker = _write(tmp_path / 'report-sent-hk-open-2026-09-17.json',
                    {'ts': _now_ms(), **INCIDENT})
    assert postflight.already_delivered(marker) is False
    _, telegram_done = postflight.delivered_channels(marker)

    postflight.deliver_wechat('hk', 'open', '2026-09-17', '', 'title\nbody',
                              telegram_done=telegram_done)

    assert sent == {'wechat': 1, 'telegram': 0}
    rewritten = json.loads(marker.read_text())
    assert (rewritten['sent_ok'], rewritten['tg_ok']) == (True, True)


# ── C. the watchdog WeChat backstop ──────────────────────────────────────────

def _senders(wechat_ok=True):
    calls = {'wechat': [], 'telegram': []}

    def wechat(channel, to, account, message, dry_run=False):
        calls['wechat'].append(message)
        return (True, 'sent') if wechat_ok else (False, 'ret=-2 errmsg=prepare failed')

    def telegram(target, message, dry_run):
        calls['telegram'].append(message)
        return True, 'sent'

    return calls, dict(wechat=wechat, telegram=telegram,
                       resolve=lambda *a: ('openclaw-weixin', 'kcn', 'acct'))


def test_backstop_retries_wechat_once_and_records_it(tmp_path, isolated_watchdog_log):
    marker_path = _write(tmp_path / 'brief-sent-2026-09-17.json', {'ts': _now_ms(), **INCIDENT})
    flag = tmp_path / 'watchdog-brief-wechat-2026-09-17.done'
    calls, senders = _senders(wechat_ok=True)

    marker = json.loads(marker_path.read_text())
    assert common.wechat_backstop('brief', 'brief', 'card', marker, marker_path,
                                  flag, False, **senders) is True
    # a second pass (or a second watchdog) must not double it
    assert common.wechat_backstop('brief', 'brief', 'card', marker, marker_path,
                                  flag, False, **senders) is None

    assert calls == {'wechat': ['card'], 'telegram': []}
    rewritten = json.loads(marker_path.read_text())
    assert rewritten['sent_ok'] is False, "the postflight's own result stays countable"
    assert rewritten['wechat_backstop']['ok'] is True
    assert common.already_delivered(marker_path) is True
    assert [e['action'] for e in _events(isolated_watchdog_log)][0] == 'wechat-backstop'


def test_failed_backstop_alerts_kcn_on_telegram(tmp_path, isolated_watchdog_log):
    marker_path = _write(tmp_path / 'brief-sent-2026-09-17.json', {'ts': _now_ms(), **INCIDENT})
    calls, senders = _senders(wechat_ok=False)

    assert common.wechat_backstop('brief', 'brief', 'card', json.loads(marker_path.read_text()),
                                  marker_path, tmp_path / 'flag', False, **senders) is False

    assert len(calls['wechat']) == 1
    assert len(calls['telegram']) == 1 and '微信未送达' in calls['telegram'][0]
    assert 'prepare failed' in calls['telegram'][0]
    assert json.loads(marker_path.read_text())['wechat_backstop']['ok'] is False
    assert any(e['action'] == 'wechat-miss-alert' for e in _events(isolated_watchdog_log))


def test_a_repeated_wechat_miss_alerts_once_a_day_per_tag(tmp_path, isolated_watchdog_log):
    """2026-09-25: ret=-2 on every intraday slot put a 微信未送达 alert on
    Telegram after every card. Later misses the same day are logged, not sent."""
    calls, senders = _senders(wechat_ok=False)
    for slot in ('1000', '1030', '1100'):
        marker_path = _write(tmp_path / f'intraday-sent-hk-{slot}.json', {'ts': _now_ms(), **INCIDENT})
        common.wechat_backstop('intraday', 'intraday-hk', 'card',
                               json.loads(marker_path.read_text()), marker_path,
                               tmp_path / f'watchdog-intraday-hk-{slot}-wechat.done',
                               False, **senders)
    assert len(calls['wechat']) == 3, 'each slot still gets its one WeChat retry'
    assert len(calls['telegram']) == 1
    actions = [e['action'] for e in _events(isolated_watchdog_log)]
    assert actions.count('wechat-miss-alert-suppressed') == 2
    # another tag keeps its own first alert
    marker_path = _write(tmp_path / 'report-sent.json', {'ts': _now_ms(), **INCIDENT})
    common.wechat_backstop('report', 'report-hk-mid', 'card', json.loads(marker_path.read_text()),
                           marker_path, tmp_path / 'watchdog-report.done', False, **senders)
    assert len(calls['telegram']) == 2


@pytest.mark.parametrize('marker', [
    None,
    {'sent_ok': True, 'tg_ok': True},
    {'tg_ok': True},                       # no WeChat verdict recorded: ambiguous
    {**INCIDENT, 'wechat_backstop': {'ok': True}},
])
def test_backstop_only_acts_on_a_recorded_wechat_failure(tmp_path, marker):
    calls, senders = _senders()
    assert common.wechat_backstop('brief', 'brief', 'card', marker, tmp_path / 'm.json',
                                  tmp_path / 'flag', False, **senders) is None
    assert calls == {'wechat': [], 'telegram': []}


def test_dry_run_sends_nothing_real_and_leaves_no_trace(tmp_path):
    marker_path = _write(tmp_path / 'm.json', {'ts': _now_ms(), **INCIDENT})
    before = marker_path.read_text()
    _calls, senders = _senders()
    common.wechat_backstop('brief', 'brief', 'card', INCIDENT, marker_path,
                           tmp_path / 'flag', True, **senders)
    assert not (tmp_path / 'flag').exists()
    assert marker_path.read_text() == before


# ── The 2026-09-17 incident through brief_watchdog.main ─────────────────────

def _wire_brief_watchdog(monkeypatch, tmp_path, wechat_ok=True):
    from clawock.harness import brief_watchdog as watchdog

    today = watchdog.trading_calendar.hkt_today().isoformat()
    calls = {'wechat': [], 'telegram': []}
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    monkeypatch.setattr(watchdog, 'WS', tmp_path)
    monkeypatch.setattr(watchdog.trading_calendar, 'closed_reason', lambda *a, **kw: None)
    monkeypatch.setattr(watchdog, 'build_brief_card', lambda _today: '📊 盘前深度简报 card')
    monkeypatch.setattr(watchdog, 'resolve_wechat_target',
                        lambda *a: ('openclaw-weixin', 'kcn', 'acct'))
    monkeypatch.setattr(watchdog, 'send_wechat',
                        lambda c, t, a, message, dry_run=False: (
                            calls['wechat'].append(message),
                            (True, 'sent') if wechat_ok else (False, 'ret=-2'))[1])
    monkeypatch.setattr(watchdog, 'send_telegram',
                        lambda target, message, dry_run: (
                            calls['telegram'].append(message), (True, 'sent'))[1])
    monkeypatch.setattr('sys.argv', ['brief_watchdog.py'])
    brief = tmp_path / 'memory' / f'{today}-pre-open.md'
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text('# brief')
    return watchdog, today, calls


def test_brief_watchdog_retries_wechat_when_only_telegram_landed(
        tmp_path, monkeypatch, isolated_watchdog_log):
    """The exact 08:33 pass of 2026-09-17: WeChat failed, Telegram landed."""
    watchdog, today, calls = _wire_brief_watchdog(monkeypatch, tmp_path)
    tmp = tmp_path / 'memory' / '.tmp'
    _write(tmp / f'brief-sent-{today}.json', {'ts': _now_ms(minutes_ago=22), **INCIDENT})

    assert watchdog.main() == 0

    assert calls['wechat'] == ['📊 盘前深度简报 card'], 'WeChat must be retried'
    assert calls['telegram'] == [], 'Telegram already has the card — no mirror, no alert'
    actions = [e['action'] for e in _events(isolated_watchdog_log)]
    # WeChat retried first; the Telegram half still gets its own (unchanged) verdict
    assert actions == ['wechat-backstop', 'ok'], actions
    assert (tmp / f'watchdog-brief-wechat-{today}.done').exists()

    # the 09:05-ish re-run of the same pass does not send WeChat a second time
    assert watchdog.main() == 0
    assert len(calls['wechat']) == 1


def test_brief_watchdog_alerts_when_the_wechat_retry_fails(
        tmp_path, monkeypatch, isolated_watchdog_log):
    watchdog, today, calls = _wire_brief_watchdog(monkeypatch, tmp_path, wechat_ok=False)
    _write(tmp_path / 'memory' / '.tmp' / f'brief-sent-{today}.json',
           {'ts': _now_ms(minutes_ago=22), **INCIDENT})

    assert watchdog.main() == 0

    assert len(calls['wechat']) == 1
    assert len(calls['telegram']) == 1 and '微信未送达' in calls['telegram'][0]


@pytest.mark.parametrize('case', ['stale', 'other-day'])
def test_brief_watchdog_never_replays_an_old_marker(tmp_path, monkeypatch, case):
    """D: a stale marker, or a failed marker from an earlier day, is not this card."""
    watchdog, today, calls = _wire_brief_watchdog(monkeypatch, tmp_path)
    tmp = tmp_path / 'memory' / '.tmp'
    if case == 'stale':
        _write(tmp / f'brief-sent-{today}.json', {'ts': _now_ms(minutes_ago=90), **INCIDENT})
    else:
        yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()
        _write(tmp / f'brief-sent-{yesterday}.json', {'ts': _now_ms(minutes_ago=5), **INCIDENT})

    assert watchdog.main() == 0

    assert calls['wechat'] == [], 'only a fresh marker for today may trigger a WeChat retry'


# ── The same slot shape on report / intraday watchdogs ──────────────────────

def test_report_watchdog_identity_no_longer_requires_telegram():
    from clawock.harness import report_watchdog

    marker = {**INCIDENT, 'tg_ok': False, 'context_id': 'abc'}
    assert report_watchdog.slot_delivered(marker, 'abc', 'x', _now_ms())[0] is False
    assert report_watchdog.marker_matches_slot(marker, 'abc', 'x', _now_ms())[0] is True
    assert report_watchdog.marker_matches_slot(marker, 'other', 'x', _now_ms())[0] is False


def test_intraday_watchdog_identity_no_longer_requires_telegram():
    from clawock.harness import intraday_watchdog

    marker = {**INCIDENT, 'tg_ok': False, 'job': '盘中盯盘',
              'slot': '2026-09-17T10:30:00+08:00', 'context_id': 'abc'}
    args = ('盘中盯盘', '2026-09-17T10:30:00+08:00', 'x', _now_ms())
    assert intraday_watchdog.marker_covers_slot(marker, *args, ctx_id='abc') is False
    assert intraday_watchdog.marker_matches_slot(marker, *args, ctx_id='abc') is True
    assert intraday_watchdog.marker_matches_slot(
        marker, '盘中盯盘', '2026-09-17T11:00:00+08:00', 'x', _now_ms(), ctx_id='abc') is False
