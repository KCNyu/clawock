"""A slot whose every attempt died on rate_limit never ran preflight (2026-10-22).

The watchdog used to read the missing context as "cron likely never ran" and
skip; the report reached kcn 49 minutes late, when a model came back. The data
block needs no model, so the watchdog now runs the slot's preflight itself and
sends the labelled deterministic fallback to Telegram.
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

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


@pytest.mark.parametrize('runs', [
    [dict(LIMITED)] * 8 + [{**LIMITED, 'errorReason': None}],
    [{'status': 'error', 'runAtMs': 1}] * 8,
    [{**LIMITED, 'errorReason': 'timeout'}],
])
def test_failed_chains_without_context_recover(tmp_path, monkeypatch, runs):
    watchdog, events, sent, built = _wire(monkeypatch, tmp_path, runs)
    assert watchdog.main() == 0
    assert built == [('hk', 'open')] and len(sent) == 1
    assert '全部限流' not in sent[0]
    assert events[-1]['action'] == 'deterministic-fallback'
    assert watchdog.main() == 0
    assert len(sent) == 1 and len(built) == 1


@pytest.mark.parametrize('runs', [[], [dict(LIMITED), {'status': 'ok'}],
                                  [dict(LIMITED), {}], [{'status': 'running'}]])
def test_incomplete_or_successful_evidence_does_not_rebuild(tmp_path, monkeypatch, runs):
    watchdog, events, sent, built = _wire(monkeypatch, tmp_path, runs)
    assert watchdog.main() == 0
    assert built == [] and sent == []
    assert events[-1]['action'] == 'skip'


def test_existing_market_closed_context_does_not_rebuild(tmp_path, monkeypatch):
    watchdog, events, sent, built = _wire(monkeypatch, tmp_path, [dict(LIMITED)])
    today = datetime.now(HKT).strftime('%Y-%m-%d')
    (tmp_path / 'memory' / '.tmp' / f'report-context-hk-open-{today}.json').write_text(
        json.dumps({'status': 'market_closed', 'reason': 'holiday'}))
    assert watchdog.main() == 0
    assert built == [] and sent == []
    assert events[-1]['closed_reason'] == 'holiday'


def test_a_preflight_that_writes_no_block_sends_nothing(tmp_path, monkeypatch):
    watchdog, events, sent, built = _wire(monkeypatch, tmp_path, [dict(LIMITED)], block=None)

    assert watchdog.main() == 0
    assert built == [('hk', 'open')] and sent == []
    assert events[-1]['action'] == 'skip' and 'produced no block' in events[-1]['reason']


@pytest.mark.parametrize("state,day,expected", [
    ({}, "2026-11-25", True),
    ({"runningAtMs": 1}, "2026-11-25", False),
    ({}, "2026-11-28", False),
])
def test_empty_history_reports_only_an_idle_scheduled_trading_slot(
        tmp_path, monkeypatch, state, day, expected):
    from clawock.automation import workflow_outcomes

    watchdog, events, sent, built = _wire(monkeypatch, tmp_path, [])
    now = datetime.fromisoformat(f"{day}T09:50:00+08:00")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    notes = []
    monkeypatch.setattr(watchdog, "datetime", Clock)
    monkeypatch.setattr(watchdog, "hkt_today", lambda: now.date())
    monkeypatch.setattr(workflow_outcomes, "slot_for_job", lambda *a: f"{day}T09:30:00+08:00")
    monkeypatch.setattr(watchdog, "live_cron_job", lambda name: {
        "enabled": True, "schedule": {"kind": "cron", "expr": "30 9 * * 1-6", "tz": "Asia/Hong_Kong"},
        "state": state,
    })
    monkeypatch.setattr(workflow_outcomes, "note_degradation",
                        lambda ledger, kind, detail, **kw: notes.append((kind, detail)))

    assert watchdog.main() == 0
    assert sent == built == []
    assert bool(notes) is expected
    assert (events[-1]["action"] == "scheduled-slot-unobserved") is expected
    if expected:
        assert notes[0][0] == "scheduled_slot_unobserved" and day in notes[0][1]



def test_host_crontab_report_is_expected_even_with_openclaw_job_disabled(monkeypatch):
    from clawock.automation import workflow_outcomes
    from clawock.harness import _watchdog_common as common

    slot = datetime(2026, 11, 25, 13, 33, tzinfo=HKT)
    now = datetime(2026, 11, 25, 13, 53, tzinfo=HKT)
    events = []
    monkeypatch.setattr(workflow_outcomes, "note_degradation",
                        lambda *a, **kw: pytest.fail("dry-run wrote a degradation"))
    assert common.note_unobserved_slot(
        {"name": "港股午后快报", "enabled": False}, slot, now=now,
        tag="hk-pm", log_event=events.append, dry_run=True)
    assert events[-1]["action"] == "scheduled-slot-unobserved"
    assert not common.note_unobserved_slot(
        {"name": "港股开盘报告", "enabled": False}, slot, now=now,
        tag="hk-open", log_event=events.append, dry_run=True)
