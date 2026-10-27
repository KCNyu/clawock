"""A slot whose every attempt died before preflight still gets its data block.

2026-10-26 US: the 23:00 and 23:30 attempts failed in ~10s (both MiniMax hops at
the Token Plan cap, Luna at its Codex limit), so neither slot wrote a context.
The watchdog found only the 22:30 context, recorded `stale_context_rejected` and
sent nothing; kcn got no card for an hour. report_watchdog already rebuilt the
context itself in that case (#3162/#3171); the intraday watchdog now does too.
"""
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

HKT = ZoneInfo('Asia/Hong_Kong')
JOB = '美股盘中盯盘'
SLOT = '2026-10-26T23:00:00+08:00'
PRIOR_SLOT = '2026-10-26T22:30:00+08:00'
BLOCK = '🇺🇸 美股盯盘 · 10/26 23:23\n| 今日 USD | 市值 |'


def _ms(hour, minute, second=0):
    return int(datetime(2026, 10, 26, hour, minute, second, tzinfo=HKT).timestamp() * 1000)


def _failed(hour, minute):
    return {'status': 'error', 'runAtMs': _ms(hour, minute), 'ts': _ms(hour, minute, 10),
            'sessionId': f's-{hour}{minute}', 'summary': ''}


PRIOR_OK = {'status': 'ok', 'runAtMs': _ms(22, 33), 'ts': _ms(22, 37),
            'sessionId': 's-2233', 'summary': ''}


def _context(slot, block=BLOCK, **extra):
    return json.dumps({'heartbeat': {'job': JOB, 'slot': slot}, 'raw_wechat_block': block,
                       'generated_at': '2026-10-26T23:23:30', **extra}, ensure_ascii=False)


def _wire(monkeypatch, tmp_path, runs, written=None):
    from clawock.harness import intraday_watchdog as wd

    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True)
    ctx_path = tmp / 'intraday-context-us-latest.json'
    ctx_path.write_text(_context(PRIOR_SLOT, block='🇺🇸 22:30 block'))
    events, sent, built, beats = [], [], [], []

    def build(market):
        built.append(market)
        if written is not None:
            ctx_path.write_text(written)
        return True, ''

    now = datetime(2026, 10, 26, 23, 23, 2, tzinfo=HKT)
    monkeypatch.setattr(wd, 'WS', tmp_path)
    monkeypatch.setattr(wd, 'watchdog_target', lambda market: (now, JOB, SLOT))
    monkeypatch.setattr(wd, 'find_job_id', lambda name: 'us-stock-monitor-001')
    monkeypatch.setattr(wd, 'today_runs', lambda job_id: runs)
    monkeypatch.setattr(wd, 'log', events.append)
    monkeypatch.setattr(wd, 'build_context', build)
    monkeypatch.setattr(wd, 'telegram_target', lambda: 'tg')
    monkeypatch.setattr(wd, 'send_telegram',
                        lambda target, body, dry: (sent.append(body), (True, 'ok'))[1])
    monkeypatch.setattr(wd.cron_heartbeat, 'record',
                        lambda *a, **k: beats.append(k.get('watchdog_state')))
    monkeypatch.setattr(sys, 'argv', ['intraday_watchdog.py', '--job-name', JOB,
                                      '--market', 'us', '--inflight-wait-s', '0'])
    return wd, events, sent, built, beats


def test_the_2026_10_26_23_00_slot_gets_the_deterministic_block(tmp_path, monkeypatch):
    runs = [PRIOR_OK, _failed(23, 3), _failed(23, 4), _failed(23, 6)]
    wd, events, sent, built, beats = _wire(
        monkeypatch, tmp_path, runs, written=_context(SLOT))

    assert wd.main() == 0
    assert built == ['us']
    assert len(sent) == 1 and '确定性兜底' in sent[0] and '美股盯盘 · 10/26 23:23' in sent[0]
    assert '22:30 block' not in sent[0]
    assert events[-1]['action'] == 'deterministic-fallback'
    assert events[-1]['attempts'] == 3 and events[-1]['rebuilt_context'] is True
    assert beats == ['deterministic_fallback']
    assert (tmp_path / 'memory' / '.tmp' / 'watchdog-intraday-us-20261026-2300.done').exists()

    assert wd.main() == 0
    assert len(sent) == 1 and len(built) == 1, 'the dedupe flag holds the slot'


@pytest.mark.parametrize('runs', [
    [_failed(23, 3), {**_failed(23, 8), 'status': 'ok'}],
    [_failed(23, 3), {**_failed(23, 8), 'status': None}],
])
def test_a_slot_with_a_non_error_attempt_keeps_the_stale_rejection(tmp_path, monkeypatch, runs):
    wd, events, sent, built, beats = _wire(monkeypatch, tmp_path, runs)

    assert wd.main() == 0
    assert built == [] and sent == []
    assert events[-1]['action'] == 'stale-backstop-rejected'
    assert beats == ['stale_context_rejected']


def test_an_earlier_slots_failures_do_not_rebuild_this_one(tmp_path, monkeypatch):
    """Only this slot's attempts count: a failed 22:30 does not make 23:00 dead."""
    from clawock.harness import intraday_watchdog as wd
    assert not wd.chain_exhausted(
        wd.runs_for_slot([_failed(22, 33), PRIOR_OK], 'us', JOB, SLOT))


def test_a_preflight_that_writes_no_block_sends_nothing(tmp_path, monkeypatch):
    runs = [_failed(23, 3)]
    wd, events, sent, built, beats = _wire(
        monkeypatch, tmp_path, runs, written=_context(SLOT, block=''))

    assert wd.main() == 0
    assert built == ['us'] and sent == []
    assert events[-1]['action'] == 'skip' and 'produced no block' in events[-1]['reason']


def test_a_rebuilt_holiday_sentinel_reads_as_closed(tmp_path, monkeypatch):
    runs = [_failed(23, 3)]
    sentinel = json.dumps({'status': 'market_closed', 'reason': 'holiday',
                           'heartbeat': {'job': JOB, 'slot': SLOT}})
    wd, events, sent, built, beats = _wire(monkeypatch, tmp_path, runs, written=sentinel)

    assert wd.main() == 0
    assert built == ['us'] and sent == []
    assert events[-1]['closed_reason'] == 'holiday'


def test_report_watchdog_still_shares_the_rule():
    from clawock.harness import _watchdog_common, report_watchdog
    assert report_watchdog.chain_exhausted is _watchdog_common.chain_exhausted
