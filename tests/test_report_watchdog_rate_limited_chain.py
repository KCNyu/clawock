"""A slot whose every attempt died on rate_limit never ran preflight (2026-10-22).

The watchdog used to read the missing context as "cron likely never ran" and
skip; the report reached kcn 49 minutes late, when a model came back. The data
block needs no model, so the watchdog now runs the slot's preflight itself and
sends the labelled deterministic fallback to Telegram.
"""
import json
import sys
from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))
LIMITED = {'status': 'error', 'errorReason': 'rate_limit', 'runAtMs': 1, 'sessionId': 's', 'summary': ''}


def _wire(monkeypatch, tmp_path, runs, block='📊 港股开盘 · 恒指 25,000'):
    from clawock.harness import report_watchdog as watchdog

    today = datetime.now(HKT).strftime('%Y-%m-%d')
    ctx_dir = tmp_path / 'memory' / '.tmp'
    ctx_dir.mkdir(parents=True)
    events, sent, built = [], [], []

    def build(market, phase):
        built.append((market, phase))
        if block is not None:
            (ctx_dir / f'report-context-{market}-{phase}-{today}.json').write_text(
                json.dumps({'status': 'ok', 'raw_wechat_block': block}, ensure_ascii=False))
        return True, ''

    monkeypatch.setattr(watchdog, 'WS', tmp_path)
    monkeypatch.setattr(watchdog, 'find_job_id', lambda name: 'job-hk')
    monkeypatch.setattr(watchdog, 'today_runs', lambda job_id: runs)
    monkeypatch.setattr(watchdog, 'log', events.append)
    monkeypatch.setattr(watchdog, 'build_context', build)
    monkeypatch.setattr(watchdog, 'telegram_target', lambda: 'tg')
    monkeypatch.setattr(watchdog, 'send_telegram',
                        lambda target, body, dry: (sent.append(body), (True, 'ok'))[1])
    monkeypatch.setattr(sys, 'argv', ['report_watchdog.py', '--market', 'hk', '--phase', 'open',
                                      '--job-name', '港股开盘报告'])
    return watchdog, events, sent, built


def test_a_rate_limited_chain_gets_the_deterministic_block(tmp_path, monkeypatch):
    watchdog, events, sent, built = _wire(monkeypatch, tmp_path, [dict(LIMITED)] * 8)

    assert watchdog.main() == 0
    assert built == [('hk', 'open')]
    assert len(sent) == 1 and '确定性兜底' in sent[0] and '恒指 25,000' in sent[0]
    assert events[-1]['action'] == 'deterministic-fallback' and events[-1]['attempts'] == 8
    assert list((tmp_path / 'memory' / '.tmp').glob('watchdog-hk-open-*.done')), (
        'the slot is marked handled so the next pass does not send it again')


def test_other_failures_before_preflight_keep_the_old_skip(tmp_path, monkeypatch):
    runs = [dict(LIMITED), {**LIMITED, 'errorReason': 'timeout'}]
    watchdog, events, sent, built = _wire(monkeypatch, tmp_path, runs)

    assert watchdog.main() == 0
    assert built == [] and sent == []
    assert 'cron likely never ran' in events[-1]['reason']


def test_a_preflight_that_writes_no_block_sends_nothing(tmp_path, monkeypatch):
    watchdog, events, sent, built = _wire(monkeypatch, tmp_path, [dict(LIMITED)], block=None)

    assert watchdog.main() == 0
    assert built == [('hk', 'open')] and sent == []
    assert events[-1]['action'] == 'skip' and 'produced no block' in events[-1]['reason']
