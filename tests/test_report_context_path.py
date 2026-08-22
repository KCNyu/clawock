"""Regression tests for the 2026-07-24 美股收盘报告 stale-context incident.

What happened: the cron payload named the preflight output as
``report-context-us-close-{date}.json``. The agent resolved ``{date}`` to the
*market close* date (07/23) instead of the *run* date (07/24), yesterday's
leftover file sat at exactly that name, so a day-old portfolio was written into
the report and pushed to WeChat. Postflight's verbatim check caught it and
skipped the commit, but it sends on every status — so the stale body went out,
the retry with fresh data was blocked by the idempotency marker, and the
watchdog never backstopped because the marker recorded the *expected* first line
rather than the one actually sent.

Three defences, one test each:
  1. preflight prints the absolute path as its final stdout line
  2. preflight deletes this market+phase's contexts from other dates
  3. postflight's marker records the first line of the body it really sent
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / 'src' / 'clawock' / 'harness'


def _load(name):
    """Import the package-owned report lifecycle module."""
    return importlib.import_module(f'clawock.harness.{name}')


@pytest.fixture(autouse=True)
def _ledger(isolated_workflow_ledger):
    """Every test here drives a real postflight, which records a workflow stage.
    Without this they all append to the checkout's own ledger (#816)."""


@pytest.fixture
def preflight():
    return _load('report_preflight')


@pytest.fixture
def postflight():
    return _load('report_postflight')


@pytest.fixture
def tmp_context_dir(tmp_path, monkeypatch, preflight):
    monkeypatch.setattr(preflight, 'TMP', tmp_path)
    return tmp_path


# ── 2. stale-context cleanup ────────────────────────────────────────────────

def test_drop_stale_contexts_removes_other_dates_only(preflight, tmp_context_dir):
    """The exact file the agent misread (yesterday's us/close) must be gone,
    and nothing else may be touched."""
    names = [
        'report-context-us-close-2026-07-22.json',      # stale — the footgun
        'report-context-us-close-2026-07-23.json',      # stale — what was misread
        'report-context-us-close-2026-07-24.json',      # today — keep
        'report-context-us-open-2026-07-23.json',       # other phase — keep
        'report-context-hk-close-2026-07-23.json',      # other market — keep
        'report-sent-us-close-2026-07-23.json',         # stale send marker — drop
        'report-sent-us-close-2026-07-24.json',         # today's marker — keep
        'report-upgrade-us-close-2026-07-23.claim',     # stale upgrade claim — drop
        'report-upgrade-us-close-2026-07-24.claim',     # today's claim — keep
        'report-sent-us-open-2026-07-23.json',          # other phase marker — keep
        'report-upgrade-us-open-2026-07-23.claim',      # other phase claim — keep
        'report-sent-hk-close-2026-07-23.json',         # other market marker — keep
    ]
    for name in names:
        (tmp_context_dir / name).write_text('{}')

    dropped = preflight.drop_stale_contexts('us', 'close', '2026-07-24')

    assert sorted(dropped) == [
        'report-context-us-close-2026-07-22.json',
        'report-context-us-close-2026-07-23.json',
        'report-sent-us-close-2026-07-23.json',
        'report-upgrade-us-close-2026-07-23.claim',
    ]
    survivors = sorted(p.name for p in tmp_context_dir.iterdir())
    assert survivors == [
        'report-context-hk-close-2026-07-23.json',
        'report-context-us-close-2026-07-24.json',
        'report-context-us-open-2026-07-23.json',
        'report-sent-hk-close-2026-07-23.json',
        'report-sent-us-close-2026-07-24.json',
        'report-sent-us-open-2026-07-23.json',
        'report-upgrade-us-close-2026-07-24.claim',
        'report-upgrade-us-open-2026-07-23.claim',
    ]


def test_drop_stale_contexts_is_noop_without_leftovers(preflight, tmp_context_dir):
    (tmp_context_dir / 'report-context-us-close-2026-07-24.json').write_text('{}')
    assert preflight.drop_stale_contexts('us', 'close', '2026-07-24') == []
    assert (tmp_context_dir / 'report-context-us-close-2026-07-24.json').exists()


# ── 1. the path is announced, and survives `| tail -N` ──────────────────────

def test_market_closed_run_announces_context_path_as_final_line(
    preflight, tmp_context_dir, monkeypatch, capsys
):
    """Drives the real main() through its holiday branch: the agent's own
    `| tail -80` is why the JSON's `date` field was lost, so the guarantee under
    test is positional — `context_path:` must be the LAST stdout line."""
    monkeypatch.setattr(preflight, '_market_closed_reason', lambda m, p: '周末休市')
    monkeypatch.setattr(sys, 'argv',
                        ['report_preflight.py', '--market', 'us', '--phase', 'close'])
    stale = tmp_context_dir / 'report-context-us-close-2026-07-23.json'
    stale.write_text('{"stale": true}')

    assert preflight.main() == 0

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-1].startswith('context_path: ')
    announced = Path(lines[-1].split('context_path: ', 1)[1])
    assert announced.is_absolute()
    assert announced.exists()
    assert json.loads(announced.read_text())['status'] == 'market_closed'
    # …and the holiday branch cleans up too, or the next run inherits the footgun
    assert not stale.exists()


def test_preflight_failure_run_also_announces_context_path(
    preflight, tmp_context_dir, monkeypatch, capsys
):
    """The failure branch writes a context that postflight will read, so it owes
    the same announcement — an unannounced path is what forces a guess."""
    monkeypatch.setattr(preflight, '_market_closed_reason', lambda m, p: None)
    monkeypatch.setattr(preflight, 'run_analyze', lambda market: (1, '', 'boom'))
    monkeypatch.setattr(sys, 'argv',
                        ['report_preflight.py', '--market', 'us', '--phase', 'close'])

    assert preflight.main() == 1

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-1].startswith('context_path: ')
    assert json.loads(
        Path(lines[-1].split('context_path: ', 1)[1]).read_text()
    )['status'] == 'preflight_failed'


# ── 3. the send marker records what was actually sent ──────────────────────

def _capture_marker(postflight, tmp_path, monkeypatch, *, text, prefix=''):
    monkeypatch.setattr(postflight, 'TMP', tmp_path)
    monkeypatch.setattr(postflight, 'resolve_wechat_target',
                        lambda market: ('weixin', 'kcn', 'acct'))
    monkeypatch.setattr(postflight, 'send_wechat',
                        lambda *a, **k: (True, 'sent'))
    monkeypatch.setattr(postflight, 'cosend_telegram',
                        lambda *a, **k: (True, 'sent'))
    postflight.deliver_wechat('us', 'close', '2026-07-24', prefix, text)
    return json.loads((tmp_path / 'report-sent-us-close-2026-07-24.json').read_text())


FRESH_FIRST = '🇺🇸 美股盯盘 | 07/23 16:00 ET'
STALE_FIRST = '🇺🇸 美股盯盘 | 07/22 16:02 ET'


def test_marker_records_first_line_of_the_body_actually_sent(
    postflight, tmp_path, monkeypatch
):
    marker = _capture_marker(
        postflight, tmp_path, monkeypatch,
        text=f'{FRESH_FIRST}\n\n📊 市值 $2,508\n')
    assert marker['first_line'] == FRESH_FIRST
    assert marker['sent_ok'] is True and marker['tg_ok'] is True


def test_marker_exposes_a_stale_body_so_the_watchdog_can_backstop(
    postflight, tmp_path, monkeypatch
):
    """The incident itself: a body built from yesterday's context, sent behind a
    🔴 banner. The marker must carry the STALE line — recording the fresh line
    the context expected made the watchdog's mismatch check tautological, so no
    backstop ever fired and kcn's WeChat kept the wrong numbers."""
    marker = _capture_marker(
        postflight, tmp_path, monkeypatch,
        prefix='🔴 Validation FAILED (2 issues), 报告仍发布但未 commit:\n- ...\n\n',
        text=f'{STALE_FIRST}\n\n📊 市值 $2,495\n')

    assert marker['first_line'] == STALE_FIRST
    # what report_watchdog computes from the fresh context, and its `matches` test
    assert marker['first_line'].strip() != FRESH_FIRST.strip()


def test_marker_first_line_ignores_the_validation_banner(
    postflight, tmp_path, monkeypatch
):
    """`wechat_prefix` leads the delivered message but is not part of the report;
    keying on the prefixed message would make every warn/fail run look stale."""
    marker = _capture_marker(
        postflight, tmp_path, monkeypatch,
        prefix='⚠️ Validation warnings (1): 报告长度 2409 字 > 2000 软上限 (warn)\n\n',
        text=f'{FRESH_FIRST}\n\n📊 市值 $2,508\n')
    assert marker['first_line'] == FRESH_FIRST


def test_marker_survives_an_empty_body_without_crashing(
    postflight, tmp_path, monkeypatch
):
    """main() gates on MIN_REPORT_CHARS before delivery, but deliver_wechat must
    not be the thing that raises if that gate ever moves."""
    marker = _capture_marker(postflight, tmp_path, monkeypatch, text='   \n')
    assert marker['first_line'] == ''
