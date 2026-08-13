"""The report path after the data block stopped going through the model.

Follow-up to tests/test_report_context_path.py (the 2026-07-24 transitional fix).
That one made a misread context loud; this one makes it unreachable:

  * report_postflight assembles title + raw_wechat_block + prose itself, so the
    delivered numbers come from the context file at send time
  * the model echoes `context_id`; prose written against a superseded context is
    refused rather than silently married to fresh numbers
  * delivery is fail-closed — a rejected report ships the data block alone, and
    may be superseded exactly once by a report that validates

Every test drives real functions; nothing asserts on prompt text.
"""

from __future__ import annotations

import importlib
import sys
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / 'src' / 'clawock' / 'harness'

FRESH_BLOCK = ('🇺🇸 美股盯盘 | 07/23 16:00 ET\n\n'
               '📊 市值 $2,508 | 浮盈 $-1,993\n\n'
               '| 代码  |    股 |\n|:------|------:|\n| CRCL  |     2 |')
STALE_BLOCK = '🇺🇸 美股盯盘 | 07/22 16:02 ET\n\n📊 市值 $2,495 | 浮盈 $-2,007'
PROSE = ('▎情绪面\nCRCL 今日 -5.5%，稳定币板块只有它在跌。\n\n'
         '▎技术面\n跌破 $65，下一支撑 $60。\n\n'
         '▎操作建议\nSPCH 减仓至 1/3。\n')


def _load(name):
    return importlib.import_module(f'clawock.harness.{name}')


@pytest.fixture
def pf():
    return _load('report_postflight')


@pytest.fixture
def pre():
    return _load('report_preflight')


def _ctx(**over):
    ctx = {
        'status': 'ok', 'market': 'us', 'phase': 'close', 'date': '2026-07-24',
        'title': '🌙 美股收盘日报｜2026-07-24',
        'raw_wechat_block': FRESH_BLOCK,
        'commit_msg': 'portfolio: 美股收盘价格更新',
        'signal_count': {'watch': 1, 'stop': 4, 'trim': 0},
        'anomalies': [{'ticker': 'CRCL', 'move_pct': -5.5, 'reason': '跳空/异动'}],
        'index_direction': None, 'peer_scan': {},
        'needs_risk_section': False,
        'context_id': 'abc123def456',
    }
    ctx.update(over)
    return ctx


# ── assembly: the numbers can no longer come from the model ─────────────────

def test_assembled_message_uses_the_context_block_not_the_model_text(pf):
    """The incident in one assertion: even if the model's prose quotes 07/22
    numbers, what ships is the context's 07/23 block."""
    msg = pf.assemble_message(_ctx(), f'{STALE_BLOCK}\n\n{PROSE}')

    assert msg.startswith('🌙 美股收盘日报｜2026-07-24')
    assert FRESH_BLOCK in msg
    assert msg.index(FRESH_BLOCK) < msg.index('▎情绪面')


def test_verbatim_and_table_rules_are_skipped_in_prose_mode(pf):
    """The model no longer copies the block, so asserting it copied correctly
    would just be the harness checking its own string concatenation."""
    ctx = _ctx()
    assembled = pf.assemble_message(ctx, PROSE)

    assert pf.validate(assembled, ctx, prose_only=True, model_text=PROSE) == []
    # the same prose WITHOUT the block still fails the legacy rules
    legacy_issues = pf.validate(PROSE, ctx, prose_only=False)
    assert any('verbatim' in i for i in legacy_issues)


def test_prose_mode_still_judges_what_the_model_actually_wrote(pf):
    ctx = _ctx(needs_risk_section=True)
    thin = '▎情绪面\n数据待获取\n'
    issues = pf.validate(pf.assemble_message(ctx, thin), ctx, prose_only=True, model_text=thin)

    assert any('缺段标记 "▎技术面"' in i for i in issues)
    assert any('▎风险提示' in i for i in issues)
    assert any('敷衍词' in i for i in issues)
    assert pf.categorize(issues) == 'fail'


def test_content_rules_run_on_prose_not_the_prepended_block(pf):
    """2026-07-24 review, blocking #1: the assembled body starts with the data
    table, which contains the anomaly ticker (CRCL) and could contain
    section-looking tokens. A prose that mentions NO mover must still fail —
    validating the body would let the table answer for the model."""
    ctx = _ctx()  # anomalies = [CRCL]
    prose = ('▎情绪面\n大盘今天很平静，没什么可说的。\n\n'
             '▎技术面\n指数横盘。\n\n▎操作建议\n继续持有。\n')
    assert 'CRCL' not in prose
    assembled = pf.assemble_message(ctx, prose)
    assert 'CRCL' in assembled  # the table carries it

    issues = pf.validate(assembled, ctx, prose_only=True, model_text=prose)
    assert any('异动票' in i and 'CRCL' in i for i in issues)
    # and the bug: validating the assembled body would MISS it
    assert not any('异动票' in i for i in pf.validate(assembled, ctx, prose_only=True))


def test_length_is_measured_on_the_assembled_message(pf):
    """The ceiling has always meant the delivered message. Measuring prose alone
    would silently loosen it by the length of the harness-owned block."""
    soft = pf.CHAR_LIMITS['soft']
    ctx = _ctx()
    # prose sized to sit just UNDER the ceiling on its own, so the only way to
    # trip the rule is to count the block the harness prepends
    prose = PROSE + '填' * (soft - 10 - len(PROSE))
    assembled = pf.assemble_message(ctx, prose)
    assert len(prose) < soft < len(assembled)

    assert [i for i in pf.validate(prose, ctx, prose_only=True, model_text=prose)
            if '报告长度' in i] == []
    assert [i for i in pf.validate(assembled, ctx, prose_only=True, model_text=prose)
            if '报告长度' in i] == [f'报告长度 {len(assembled)} 字 > {soft} 软上限 (warn)']


# ── generation binding ─────────────────────────────────────────────────────

def test_context_id_is_per_generation(pre):
    """The id pins prose to THIS preflight output. Two runs differ (raw_wechat_block
    carries the fetch minute, and generated_at differs), and any change to the data
    the model reasons about also differs — so a mismatch always means "prose was
    written against a superseded context", which is what postflight rejects."""
    base = {k: v for k, v in _ctx().items() if k != 'context_id'}
    run_a = pre.compute_context_id({**base, 'generated_at': '2026-07-24T04:00:33'})
    run_b = pre.compute_context_id({**base, 'generated_at': '2026-07-24T04:06:11'})
    moved = pre.compute_context_id({**base, 'raw_wechat_block': STALE_BLOCK,
                                    'generated_at': '2026-07-24T04:00:33'})

    assert run_a != run_b            # a re-run is a new generation
    assert run_a != moved            # changed data is a new generation
    # deterministic: same dict in, same id out (no dict-ordering / float wobble)
    assert run_a == pre.compute_context_id({**base, 'generated_at': '2026-07-24T04:00:33'})


def test_peer_scan_is_trimmed_at_the_source_not_in_a_second_view(pre):
    """peer_scan bulk is what provoked `| tail -80` on 2026-07-24. It is cut in
    the context itself so stdout and the file stay the same JSON — an abridged
    print of a fat file would be one more thing to drift."""
    peers = {'RKLX': {
        'theme': 'RKLB 2x leveraged', 'self_pct_1d': 0.51,
        'divergence_signal': 'MU +3.2% vs self +0.1%',
        'listed_peers': [{'ticker': f'P{i}', 'name': 'x' * 40, 'rel': 'y' * 40,
                          'pct_1d': i, 'pct_5d': i} for i in range(9)],
        'auto_peers': [{'ticker': f'A{i}', 'name': 'auto',
                        'label': '同行业·自动', 'pct_1d': i, 'pct_5d': i}
                       for i in range(7)],
        'private_peers': ['a' * 50] * 6,
        'key_news_keywords': ['k' * 20] * 8,
    }}
    trimmed = pre.trim_peer_scan(peers)

    # the fields a 4-6 line briefing actually cites survive
    assert trimmed['RKLX']['divergence_signal'] == 'MU +3.2% vs self +0.1%'
    assert trimmed['RKLX']['theme'] == 'RKLB 2x leveraged'
    lines = trimmed['RKLX']['listed_peers']
    assert len(lines) == 5 and lines[0].startswith('P0 ')
    assert '+0.00% (5d +0.00%)' in lines[0]        # both moves stay quotable
    auto_lines = trimmed['RKLX']['auto_peers']
    assert len(auto_lines) == 3
    assert auto_lines[0].startswith('同行业·自动｜A0 auto ')
    # the long tail does not
    assert 'private_peers' not in trimmed['RKLX']
    assert all(isinstance(ln, str) for ln in lines)  # flat: 1 line per peer, not 6
    assert len(json.dumps(trimmed, ensure_ascii=False)) < len(json.dumps(peers, ensure_ascii=False)) / 4


def test_peer_line_survives_a_missing_move(pre):
    """peer feeds drop pct_5d often enough that a format crash here would take
    the whole report down for a cosmetic field."""
    assert pre._peer_line({'ticker': 'MU', 'name': '美光', 'pct_1d': 3.2}) == \
        'MU 美光 +3.20% (5d n/a)'
    assert pre._peer_line({'ticker': 'MU'}) == 'MU n/a (5d n/a)'


# ── fail-closed delivery + the single upgrade ──────────────────────────────

@pytest.fixture
def sent(pf, tmp_path, monkeypatch):
    """Capture what deliver_wechat would publish, without any network."""
    box = {}
    monkeypatch.setattr(pf, 'TMP', tmp_path)
    monkeypatch.setattr(pf, 'resolve_wechat_target', lambda m: ('weixin', 'kcn', 'a'))
    monkeypatch.setattr(pf, 'cosend_telegram', lambda *a, **k: (True, 'ok'))

    def _send(channel, to, account, message, dry_run):
        box.setdefault('messages', []).append(message)
        return True, 'sent'

    monkeypatch.setattr(pf, 'send_wechat', _send)
    box['tmp'] = tmp_path
    return box


def test_failed_report_delivers_the_data_block_without_the_rejected_prose(pf, sent):
    ctx = _ctx()
    pf.deliver_wechat('us', 'close', '2026-07-24',
                      '🔴 Validation FAILED (1 issues), 仅发布数据块、未 commit:\n- x\n\n',
                      pf.assemble_message(ctx, ''), delivery_state='failed')

    body = sent['messages'][0]
    assert FRESH_BLOCK in body
    assert '▎情绪面' not in body
    marker = json.loads((sent['tmp'] / 'report-sent-us-close-2026-07-24.json').read_text())
    assert marker['delivery_state'] == 'failed'


def test_upgrade_is_claimed_exactly_once(pf, sent):
    assert pf.claim_upgrade('us', 'close', '2026-07-24') is True
    assert pf.claim_upgrade('us', 'close', '2026-07-24') is False
    assert pf.claim_upgrade('us', 'close', '2026-07-24') is False


# ── the failure surface --text-file introduces ─────────────────────────────

def test_stale_prose_file_is_refused_because_context_id_cannot_see_it(pf, tmp_path):
    """The model passes the CURRENT context_id on the command line while the file
    still holds the previous slot's prose — generation binding is blind to this,
    so the file's own mtime has to be the gate (PR #22's intraday lesson)."""
    import os
    stale = tmp_path / 'report-prose-us-close.md'
    stale.write_text(PROSE)
    old = datetime_minus_minutes(pf.PROSE_MAX_AGE_MIN + 5)
    os.utime(stale, (old, old))

    text, err = pf.read_prose_text('us', 'close', str(stale))
    assert text == '' and '分钟未更新' in err

    fresh = tmp_path / 'fresh.md'
    fresh.write_text(PROSE)
    assert pf.read_prose_text('us', 'close', str(fresh)) == (PROSE, None)


def datetime_minus_minutes(minutes):
    import time
    return time.time() - minutes * 60


def test_a_terse_but_valid_prose_under_50_chars_is_not_broken_pipe_rejected(run_main, sent):
    """2026-07-24 review: the 50-字 floor is a legacy full-report broken-pipe guard.
    A valid three-section prose can sit under it; read_prose_text already rejects
    empty/missing/stale files, so the floor must not apply to prose."""
    terse = '▎情绪面\n跌\n▎技术面\n弱\n▎操作建议\n等\n'
    assert len(terse.strip()) < 50
    rc, out = run_main(terse, context_id='abc123def456',
                       ctx=_ctx(anomalies=[]))  # no mover to require

    assert out['status'] == 'pass' and rc == 0
    assert sent['messages'][0].startswith('🌙 美股收盘日报')


@pytest.mark.parametrize('setup, marker', [
    ('missing', '不存在'),
    ('empty', '空输入'),
])
def test_broken_input_is_classified_apart_from_a_bad_report(pf, tmp_path, setup, marker):
    path = tmp_path / 'report-prose-us-close.md'
    if setup == 'empty':
        path.write_text('   \n')
    text, err = pf.read_prose_text('us', 'close', str(path))
    assert text == '' and marker in err


@pytest.fixture
def run_main(pf, sent, monkeypatch, tmp_path):
    """Drive the real main(). Helper-only tests would not have caught the
    2026-07-24 bug — the defect was in how main() sequenced send vs commit."""
    monkeypatch.setattr(pf.trading_calendar, 'phase_session', lambda m, p: 'x')
    monkeypatch.setattr(pf.trading_calendar, 'closed_reason', lambda m, session=None: None)
    monkeypatch.setattr(pf, 'maybe_commit',
                        lambda status, msg: (True, f'commit({status})'))

    def run(prose, *, context_id, ctx=None, age_minutes=0):
        (tmp_path / f'report-context-us-close-{pf.datetime.now():%Y-%m-%d}.json'
         ).write_text(json.dumps(ctx or _ctx(), ensure_ascii=False))
        body = tmp_path / 'body.md'
        body.write_text(prose)
        if age_minutes:
            import os
            old = datetime_minus_minutes(age_minutes)
            os.utime(body, (old, old))
        argv = ['report_postflight.py', '--market', 'us', '--phase', 'close',
                '--text-file', str(body)]
        if context_id:
            argv += ['--context-id', context_id]
        monkeypatch.setattr(sys, 'argv', argv)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = pf.main()
        return rc, json.loads(buf.getvalue())

    return run


def test_incident_replay_stale_prose_is_refused_not_married_to_fresh_numbers(
    run_main, sent
):
    """2026-07-24 exactly: the model wrote against a context that has since been
    replaced. The old code published it; the new code must refuse to assemble and
    ship the data block alone."""
    rc, out = run_main(f'{STALE_BLOCK}\n\n{PROSE}', context_id='OLDGENERATION')

    assert rc == 2 and out['status'] == 'fail'
    assert any('context_id 不匹配' in i for i in out['issues'])
    assert out['commit_ok'] is True
    assert out['data_plane_status'] == 'published'
    assert out['narrative_status'] == 'failed'
    body = sent['messages'][0]
    assert FRESH_BLOCK in body and '▎情绪面' not in body and STALE_BLOCK not in body


def test_happy_path_assembles_commits_and_records_delivered(run_main, sent):
    rc, out = run_main(PROSE, context_id='abc123def456')

    assert rc == 0 and out['status'] == 'pass' and out['mode'] == 'prose'
    assert out['commit_ok'] is True
    body = sent['messages'][0]
    assert body.startswith('🌙 美股收盘日报') and FRESH_BLOCK in body and '▎情绪面' in body


def test_failed_narrative_still_commits_the_money_file_and_nothing_ignored(pf, monkeypatch):
    """A rejected narrative must not cost the deterministic half of the run.

    It used to stage the dashboard outputs alongside `portfolio.json`. Since #314
    those are gitignored, and `git add` on an ignored path FAILS — which would
    have aborted this commit and taken the money file with it. The rebuild still
    happens; only the staging is gone.
    """
    calls = []
    monkeypatch.setattr(pf, 'rebuild_dashboard', lambda: (True, 'ok'))
    monkeypatch.setattr(pf, 'snapshot_date_for_now', lambda: None)
    monkeypatch.setattr(pf, 'push_with_rebase_retry', lambda: (True, 'ok'))

    def fake_git(*args):
        calls.append(args)
        return True, 'ok'

    monkeypatch.setattr(pf, '_git', fake_git)

    ok, message = pf.maybe_commit('fail', 'portfolio: refresh')

    assert ok is True and message == 'committed + pushed'
    assert calls[0] == (
        'add', 'portfolio.json', 'logs/dashboard_build_status.json',
    )
    assert calls[1] == (
        'commit', '-m', 'portfolio: refresh (data only; prose rejected)', '--',
        'portfolio.json', 'logs/dashboard_build_status.json',
    )


def test_a_failed_slot_can_be_superseded_once_then_locks(run_main, sent, pf):
    """Fail-closed is only acceptable if the corrected report can still land."""
    def pf_min_chars():
        return pf.MIN_REPORT_CHARS

    bad = '▎情绪面\n' + '数据待获取，等待数据回补后再补充解读。' * 3 + '\n'
    assert len(bad) > pf_min_chars()
    rc1, out1 = run_main(bad, context_id='abc123def456')
    # banner names the offending phrase; the BODY must stop at the data block
    assert out1['status'] == 'fail'
    assert sent['messages'][0].endswith(FRESH_BLOCK.strip())

    rc2, out2 = run_main(PROSE, context_id='abc123def456')
    assert out2['status'] == 'pass' and out2['wechat_sent'] is True
    assert len(sent['messages']) == 2 and '▎情绪面' in sent['messages'][1]

    # a third run must NOT send again — one upgrade, then the lock holds
    rc3, out3 = run_main(PROSE, context_id='abc123def456')
    assert out3['status'] == 'pass' and len(sent['messages']) == 2


def test_main_refuses_to_publish_a_stale_prose_file(run_main, sent, pf, tmp_path):
    """A helper-only test does not guard main(): with read_prose_text returning an
    error but main() ignoring it, everything else still passes. Drive the whole
    entry point and assert NOTHING was sent."""
    import os
    rc, out = run_main(PROSE, context_id='abc123def456',
                       age_minutes=pf.PROSE_MAX_AGE_MIN + 5)

    assert rc == 2 and out['status'] == 'input_error'
    assert out['wechat_sent'] is False and out['commit_ok'] is False


@pytest.mark.parametrize('ctx, why', [
    ({'status': 'preflight_failed', 'market': 'us', 'phase': 'close',
      'error': 'analyze_us_stocks.py rc=1'}, 'preflight_failed sentinel'),
    ({'status': 'ok', 'market': 'us', 'phase': 'close', 'title': 't',
      'commit_msg': 'm', 'context_id': 'abc123def456', 'raw_wechat_block': ''},
     'ok status but empty data block'),
])
def test_main_rejects_an_unusable_context_without_sending_or_crashing(
    run_main, sent, ctx, why
):
    """2026-07-24 review, blocking #2: preflight writes a blockless sentinel on a
    fetch failure. Assembling against it sent a banner-only message and then
    crashed on ctx['commit_msg']. It must be rejected before any send/commit."""
    rc, out = run_main(PROSE, context_id='abc123def456', ctx=ctx)

    assert rc == 2, why
    assert out['status'] == 'preflight_error'
    assert out['wechat_sent'] is False and out['commit_ok'] is False
    assert 'messages' not in sent  # nothing delivered


def test_legacy_failed_report_also_ships_the_data_block_only(run_main, sent):
    """Dual-stack: a legacy (no --context-id) run that fails validation must ALSO
    fall back to the data block, not deliver the model's rejected full text —
    this closes 07-24 on the legacy path during the migration window."""
    legacy_bad = f'{FRESH_BLOCK}\n\n▎情绪面\n数据待获取\n'  # missing 技术面/操作建议
    rc, out = run_main(legacy_bad, context_id=None)

    assert out['status'] == 'fail' and out['mode'] == 'legacy'
    body = sent['messages'][0]
    # ends at the data block ⇒ the model's rejected text is gone (数据待获取 still
    # appears once, in the banner, which is expected — it names the failure)
    assert body.endswith(FRESH_BLOCK.strip())
    assert '▎情绪面' not in body


# ── watchdog must not mistake prose mode for a dead run ────────────────────

@pytest.fixture
def wd():
    return _load('report_watchdog')


def _marker(**over):
    m = {'ts': 1_000_000, 'sent_ok': True, 'tg_ok': True,
         'first_line': '🌙 美股收盘日报｜2026-07-24', 'context_id': 'abc123def456'}
    m.update(over)
    return m


def _delivered(wd, *args, **kwargs):
    """slot_delivered returns (verdict, judge); these tests assert the verdict."""
    return wd.slot_delivered(*args, **kwargs)[0]


def test_watchdog_accepts_a_prose_slot_by_context_id(wd):
    """Prose bodies start with the TITLE, so the old first-line compare would call
    a healthy run a mismatch and mirror a duplicate to Telegram."""
    assert _delivered(wd, _marker(), 'abc123def456',
                             '🇺🇸 美股盯盘 | 07/23 16:00 ET', 1_000_100) is True


def test_watchdog_still_backstops_a_different_generation(wd):
    assert _delivered(wd, _marker(context_id='OTHERGEN'), 'abc123def456',
                             '🇺🇸 美股盯盘 | 07/23 16:00 ET', 1_000_100) is False


def test_watchdog_context_id_match_ignores_the_age_window(wd):
    """2026-07-24 review, non-blocking: both ids are per market+phase+date, so an
    exact match is proof of THIS slot regardless of marker age. A delayed watchdog
    must not re-mirror a confirmed delivery just because the marker is >2h old."""
    old = 1_000_000 + wd.MARKER_FRESH_MS + 1
    assert _delivered(wd, _marker(), 'abc123def456', 'x', old) is True


def test_watchdog_falls_back_to_first_line_for_legacy_markers(wd):
    legacy = _marker(first_line='🇺🇸 美股盯盘 | 07/23 16:00 ET')
    legacy.pop('context_id')
    assert _delivered(wd, legacy, None, '🇺🇸 美股盯盘 | 07/23 16:00 ET', 1_000_100) is True
    assert _delivered(wd, legacy, None, '🇺🇸 美股盯盘 | 07/22 16:02 ET', 1_000_100) is False
    # freshness still gates the FUZZY legacy path — an old first-line match could
    # belong to an earlier day
    old = 1_000_000 + wd.MARKER_FRESH_MS
    assert _delivered(wd, legacy, None, '🇺🇸 美股盯盘 | 07/23 16:00 ET', old) is False


def test_watchdog_ignores_an_undelivered_marker(wd):
    assert _delivered(wd, _marker(tg_ok=False), 'abc123def456', 'x', 1_000_100) is False
    assert _delivered(wd, None, 'abc123def456', 'x', 1_000_100) is False


# ── watchdog must not duplicate a healthy prose run ────────────────────────

@pytest.fixture
def wd():
    return _load('report_watchdog')


def test_watchdog_identifies_the_slot_by_context_id_not_first_line(wd):
    """Prose-mode bodies start with the TITLE, so the old first-line compare
    reports a false mismatch on every healthy run — and a 'mismatch' makes the
    watchdog mirror a duplicate to Telegram."""
    now = 1_700_000_000_000
    marker = {'ts': now - 60_000, 'tg_ok': True, 'context_id': 'abc123def456',
              'first_line': '🌙 美股收盘日报｜2026-07-24'}

    assert _delivered(wd, marker, 'abc123def456', FRESH_BLOCK.splitlines()[0], now)
    # a marker from a different generation is NOT this slot's
    assert not _delivered(wd, marker, 'NEWGENERATION', FRESH_BLOCK.splitlines()[0], now)


def test_watchdog_falls_back_to_the_legacy_first_line_when_no_context_id(wd):
    now = 1_700_000_000_000
    first = FRESH_BLOCK.splitlines()[0]
    legacy = {'ts': now - 60_000, 'tg_ok': True, 'first_line': first}

    assert _delivered(wd, legacy, None, first, now)
    assert not _delivered(wd, {**legacy, 'first_line': 'something else'}, None, first, now)
    assert not _delivered(wd, {**legacy, 'tg_ok': False}, None, first, now)
    assert not _delivered(wd, {**legacy, 'ts': 0}, None, first, now)


@pytest.fixture
def wd_main(wd, tmp_path, monkeypatch):
    """Drive report_watchdog.main() with the run/session lookups mocked out, so the
    reordered generation gate (transcript extracted BEFORE block_present) is under
    test — codex flagged it as covered only at the slot_delivered() helper level."""
    tmp = tmp_path / '.tmp'
    tmp.mkdir()
    monkeypatch.setattr(wd, 'WS', tmp_path)
    (tmp_path / 'memory').mkdir(exist_ok=True)
    monkeypatch.setattr(wd, 'WS', tmp_path, raising=True)
    # WS/memory/.tmp is where main() reads ctx + marker and writes the dedupe flag
    (tmp_path / 'memory' / '.tmp').mkdir(parents=True, exist_ok=True)

    sent = {}
    monkeypatch.setattr(wd, 'find_job_id', lambda name: 'jid')
    monkeypatch.setattr(wd, 'today_runs',
                        lambda jid: [{'runAtMs': 1, 'sessionId': 'sess', 'summary': SUMMARY[0]}])
    monkeypatch.setattr(wd, 'transcript_loop_score', lambda s: (0, {}))
    def _tg(target, msg, dry):
        sent.setdefault('msgs', []).append(msg)
        return True, 'sent'
    monkeypatch.setattr(wd, 'send_telegram', _tg)
    monkeypatch.setattr(wd, 'last_report_text', lambda s, first: TRANSCRIPT[0])

    ctx = _ctx()
    (tmp_path / 'memory' / '.tmp' / 'report-context-us-close-'
     f'{__import__("datetime").datetime.now(wd.HKT):%Y-%m-%d}.json'
     ).write_text(json.dumps(ctx, ensure_ascii=False))

    def run(*, summary, transcript):
        SUMMARY[0], TRANSCRIPT[0] = summary, transcript
        monkeypatch.setattr(sys, 'argv',
                            ['report_watchdog.py', '--market', 'us', '--phase', 'close',
                             '--job-name', '美股收盘报告'])
        wd.main()
        return sent

    return run


SUMMARY = ['']
TRANSCRIPT = [None]
FRESH_FIRST = FRESH_BLOCK.splitlines()[0]


def test_watchdog_mirrors_the_real_report_when_summary_truncated_it(wd_main):
    """Summary lacks the data block but the transcript holds the real report. The
    old gate (block_present = raw in summary) would fire the deterministic
    data-block fallback and drop the full report; the fix must mirror the real one."""
    real = f'{FRESH_BLOCK}\n\n▎情绪面\n完整报告正文……\n'
    sent = wd_main(summary='（summary truncated, no block）', transcript=real)

    assert sent['msgs'], 'watchdog sent nothing'
    body = sent['msgs'][-1]
    assert '▎情绪面\n完整报告正文' in body      # the real report, not the block-only fallback


def test_marker_state_defaults_to_delivered_for_pre_field_markers(pf, sent):
    """An old marker must not read as 'failed' — that would unlock a re-send of a
    report kcn already has, which is the 2026-06-03 duplicate class."""
    path = sent['tmp'] / 'report-sent-us-close-2026-07-24.json'
    path.write_text(json.dumps({'ts': 1, 'sent_ok': True, 'tg_ok': True,
                                'first_line': 'x'}))
    assert pf._marker_state(path) == 'delivered'
    assert pf._marker_state(sent['tmp'] / 'nope.json') is None
