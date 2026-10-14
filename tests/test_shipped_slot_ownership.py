"""A slot's outcome row belongs to the attempt that delivered it.

openclaw re-runs a whole turn (preflight included) after a post-turn error,
and a preflight can be re-run by hand later the same day; every such attempt
maps to the same slot. Each used to file its own outcome over the delivered
one because it wrote the ledger before, or without, reading the receipt:
#2961 (a report retry's input failure named the slot degraded) and #2960 (a
brief preflight re-run emptied the delivered slot's diagnostics). The rule
now lives in `_watchdog_common.slot_shipped`, asked by every preflight and
postflight before it can write; these pin it at each writer it covers. The
brief and report postflights' own cases sit beside their earlier tests
(`test_brief_projection_publication_gate`, `test_wechat_delivery_per_channel`).
"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime

import pytest

from clawock.automation import workflow_outcomes
from clawock.harness import brief_preflight, intraday_postflight, intraday_preflight
from clawock.harness import report_preflight

SLOT = '2026-10-14T10:30:00+08:00'
BRIEF_SLOT = '2026-10-14T08:03:00+08:00'


def _now_ms():
    return int(datetime.now().timestamp() * 1000)


def _receipt(path, **fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'ts': _now_ms(), 'sent_ok': True, 'tg_ok': True, **fields}))
    return path


@pytest.fixture
def heartbeats(monkeypatch):
    rows = []
    monkeypatch.setattr(intraday_postflight.cron_heartbeat, 'record',
                        lambda market, state, **kw: rows.append((state, kw.get('slot'))) or {})
    return rows


# ── the #2960 invariant, on a real ledger ────────────────────────────────────

def _delivered_brief_slot():
    """The 10-13 shape: preflight warned, the card shipped, the slot is degraded."""
    workflow_outcomes.record_stage(
        brief_preflight.BRIEF_JOB, 'preflight', 'warning', slot=BRIEF_SLOT,
        issue_count=2, context_generation_id='delivered-gen',
        context_path='memory/.tmp/brief-context-2026-10-14.json',
        model_context_bytes=1000, packet_read_ratios={'packet': 0.5},
        step_timings={'analyze_us': {'ok': True, 'wall_s': 1.0}})
    for stage in ('llm', 'postflight'):
        workflow_outcomes.record_stage(brief_preflight.BRIEF_JOB, stage, 'success',
                                       slot=BRIEF_SLOT, escalating_count=0)
    workflow_outcomes.record_primary_delivery(brief_preflight.BRIEF_JOB, slot=BRIEF_SLOT,
                                              wechat_ok=True, telegram_ok=True)


def _brief_row():
    return next(row for row in workflow_outcomes.load_ledger()['records']
                if row['job'] == brief_preflight.BRIEF_JOB and row['slot'] == BRIEF_SLOT)


def test_a_preflight_rerun_after_the_brief_shipped_leaves_its_preflight_stage(
        tmp_path, monkeypatch):
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    tmp = tmp_path / 'memory' / '.tmp'
    monkeypatch.setattr(brief_preflight, 'TMP_DIR', tmp)
    _delivered_brief_slot()
    before = _brief_row()
    assert before['final_product']['status'] == 'degraded'
    _receipt(tmp / 'brief-sent-2026-10-14.json')

    shipped = brief_preflight.slot_shipped(tmp, 'brief', date='2026-10-14')
    # Every outcome a re-run can reach: its start marker, a fresh clean
    # collection (which would turn the degraded slot into a success), a failure.
    brief_preflight._record_preflight(shipped, 'pending', slot=BRIEF_SLOT)
    brief_preflight._record_preflight(shipped, 'success', slot=BRIEF_SLOT, issue_count=0,
                                      context_generation_id='rerun-gen')
    brief_preflight._record_preflight(shipped, 'failed', slot=BRIEF_SLOT,
                                      reason='price_refresh_failed')

    after = _brief_row()
    assert shipped is True
    assert after['stages'] == before['stages']
    assert after['final_product'] == before['final_product']


def test_a_preflight_run_before_anything_shipped_still_files_its_outcome(
        tmp_path, monkeypatch):
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    tmp = tmp_path / 'memory' / '.tmp'
    # A Telegram-only receipt has not delivered the slot: WeChat is still owed.
    _receipt(tmp / 'brief-sent-2026-10-14.json', sent_ok=False)

    shipped = brief_preflight.slot_shipped(tmp, 'brief', date='2026-10-14')
    brief_preflight._record_preflight(shipped, 'pending', slot=BRIEF_SLOT)
    brief_preflight._record_preflight(shipped, 'warning', slot=BRIEF_SLOT, issue_count=1)

    assert shipped is False
    assert _brief_row()['stages']['preflight']['status'] == 'warning'


# ── brief preflight: the parent's timeout backstop ───────────────────────────

@pytest.mark.parametrize('shipped', [False, True])
def test_a_brief_preflight_timeout_files_only_when_nothing_shipped(
        tmp_path, monkeypatch, shipped):
    stages = []
    monkeypatch.setattr(brief_preflight, 'TMP_DIR', tmp_path)
    monkeypatch.setattr(brief_preflight.trading_calendar, 'hkt_today',
                        lambda: date(2026, 10, 14))
    monkeypatch.delenv('TODAY', raising=False)
    monkeypatch.setattr(brief_preflight.workflow_outcomes, 'record_stage',
                        lambda job, stage, status, **kw: stages.append((stage, status)))
    monkeypatch.setattr(brief_preflight.brief_context, 'write_run_bundle', lambda *a, **kw: None)

    def timeout(*_a, **_kw):
        raise subprocess.TimeoutExpired('collect', 600)
    monkeypatch.setattr(brief_preflight, 'run_bounded', timeout)
    if shipped:
        _receipt(tmp_path / 'brief-sent-2026-10-14.json')

    assert brief_preflight.main([]) == 1
    assert stages == ([] if shipped else [('preflight', 'failed')])


# ── report preflight ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('shipped', [False, True])
def test_a_report_preflight_failure_files_only_when_nothing_shipped(
        tmp_path, monkeypatch, shipped):
    stages = []
    monkeypatch.setattr(report_preflight, 'TMP', tmp_path)
    monkeypatch.setattr(report_preflight.trading_calendar, 'hkt_today',
                        lambda: date(2026, 10, 14))
    monkeypatch.setattr(report_preflight.workflow_outcomes, 'slot_for_job', lambda job: SLOT)
    monkeypatch.setattr(report_preflight.workflow_outcomes, 'record_stage',
                        lambda job, stage, status, **kw: stages.append((stage, status)))
    monkeypatch.setattr(report_preflight, '_market_closed_reason', lambda *a: None)
    monkeypatch.setattr(report_preflight, 'run_analyze', lambda market: (1, '', 'boom'))
    if shipped:
        _receipt(tmp_path / 'report-sent-hk-open-2026-10-14.json')

    assert report_preflight.main(['--market', 'hk', '--phase', 'open']) == 1
    assert stages == ([] if shipped else [('preflight', 'pending'), ('preflight', 'failed')])


# ── intraday preflight ───────────────────────────────────────────────────────

@pytest.mark.parametrize('shipped', [False, True])
def test_an_intraday_preflight_failure_files_only_when_nothing_shipped(
        tmp_path, monkeypatch, shipped):
    rows = []
    monkeypatch.setattr(intraday_preflight, 'TMP', tmp_path)
    monkeypatch.setattr(intraday_preflight.cron_heartbeat, 'slot_for',
                        lambda market, at=None: ('盘中盯盘', SLOT))
    monkeypatch.setattr(intraday_preflight.cron_heartbeat, 'record',
                        lambda market, state, **kw: rows.append(state)
                        or {'job': kw.get('job_name'), 'slot': kw.get('slot')})
    monkeypatch.setattr(intraday_preflight.trading_calendar, 'closed_reason',
                        lambda *a, **kw: None)
    monkeypatch.setattr(intraday_preflight.intraday_information, 'collect_live',
                        lambda *a, **kw: None)
    monkeypatch.setattr(intraday_preflight, 'run_analyze', lambda market: (1, '', 'boom'))
    if shipped:
        _receipt(tmp_path / 'intraday-sent-hk.json', slot=SLOT)

    assert intraday_preflight.main(['--market', 'hk']) == 1
    assert rows == ([] if shipped else ['started', 'preflight_failed'])


# ── intraday postflight ──────────────────────────────────────────────────────

def _intraday_ctx(monkeypatch, tmp_path, **ctx):
    ctx = {'heartbeat': {'job': '盘中盯盘', 'slot': SLOT}, 'context_id': 'c1', **ctx}
    monkeypatch.setattr(intraday_postflight, 'TMP', tmp_path)
    monkeypatch.setattr(intraday_postflight, 'load_context', lambda market: (ctx, None))
    return ctx


@pytest.mark.parametrize('shipped', [False, True])
def test_an_intraday_input_error_files_only_when_nothing_shipped(
        tmp_path, monkeypatch, heartbeats, shipped):
    _intraday_ctx(monkeypatch, tmp_path)
    if shipped:
        _receipt(tmp_path / 'intraday-sent-hk.json', slot=SLOT)

    code = intraday_postflight.input_error('hk', 'empty input')

    assert code == (0 if shipped else 2)
    assert heartbeats == ([] if shipped else [('postflight_failed', SLOT)])


def test_a_receipt_for_the_previous_slot_does_not_hide_this_slots_input_error(
        tmp_path, monkeypatch, heartbeats):
    _intraday_ctx(monkeypatch, tmp_path)
    _receipt(tmp_path / 'intraday-sent-hk.json', slot='2026-10-14T10:00:00+08:00')

    assert intraday_postflight.input_error('hk', 'empty input') == 2
    assert heartbeats == [('postflight_failed', SLOT)]


def test_a_no_change_retry_keeps_the_delivered_receipt(tmp_path, monkeypatch, heartbeats):
    """After the delivery persisted its cursor a retry reads as unchanged.

    Its quiet marker overwrote the delivery receipt with `sent_ok: null` and
    its heartbeat filed the delivered slot as `primary_delivery=not_required`.
    """
    _intraday_ctx(monkeypatch, tmp_path, delivery_mode='no_change')
    monkeypatch.setattr(intraday_postflight.trading_calendar, 'closed_reason',
                        lambda *a, **kw: None)
    monkeypatch.setattr(intraday_postflight, 'can_silence', lambda *a, **kw: True)
    monkeypatch.setattr(intraday_postflight, 'publish_data_plane',
                        lambda market: ('published', True))
    monkeypatch.setattr(intraday_postflight.intraday_delta, 'persist_delivered_state',
                        lambda *a: True)
    receipt = _receipt(tmp_path / 'intraday-sent-hk.json', slot=SLOT)
    before = receipt.read_text()

    code = intraday_postflight.main(['--market', 'hk', '--context-id', 'c1'])

    assert code == 0
    assert receipt.read_text() == before
    assert heartbeats == []


def test_a_no_change_slot_that_never_shipped_still_records_itself(
        tmp_path, monkeypatch, heartbeats):
    _intraday_ctx(monkeypatch, tmp_path, delivery_mode='no_change')
    monkeypatch.setattr(intraday_postflight.trading_calendar, 'closed_reason',
                        lambda *a, **kw: None)
    monkeypatch.setattr(intraday_postflight, 'can_silence', lambda *a, **kw: True)
    monkeypatch.setattr(intraday_postflight, 'publish_data_plane',
                        lambda market: ('published', True))
    monkeypatch.setattr(intraday_postflight.intraday_delta, 'persist_delivered_state',
                        lambda *a: True)
    monkeypatch.setattr(intraday_postflight, 'delivery_marker_payload',
                        lambda ctx, **kw: kw)

    assert intraday_postflight.main(['--market', 'hk', '--context-id', 'c1']) == 0
    assert heartbeats == [('no_change', SLOT)]
    assert json.loads((tmp_path / 'intraday-sent-hk.json').read_text())['sent_ok'] is None
