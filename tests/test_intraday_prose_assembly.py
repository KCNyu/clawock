"""Mode 7 after the data block stopped going through the model.

The 2026-07-28 00:30 US slot delivered its holdings table correctly and still
raised `🔴 Validation FAILED`: the model had retyped the RKLX row with one extra
space in the 浮$ cell, `check_raw_tables_verbatim` is a strict substring match,
and the whole ▎我的看法 段 was dropped in favour of the bare data block. Mode 6
removed that round trip on 2026-07-24; these tests pin the same contract for
Mode 7:

  * intraday_postflight assembles raw_wechat_block + prose itself, so table
    whitespace is no longer something the model can get wrong
  * the model echoes `context_id`; prose written against a superseded context is
    refused rather than married to fresh numbers
  * the content rules read the model's prose, never the prepended block — a
    block that names the movers must not satisfy the anomaly rule for prose that
    does not

Every test drives real functions; nothing asserts on prompt text.
"""

from __future__ import annotations

import importlib
import sys
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / 'src' / 'clawock' / 'harness'

# The real 2026-07-28 00:30 block, trimmed to the rows that matter.
BLOCK = ('🇺🇸 美股盯盘 | 07/27 12:30 ET\n\n'
         '📊 市值 $2,403 | 浮盈 $-2,098 (-46.6%) | 今日 +$7\n\n'
         '| 代码  |    股 |   成本 |   现价 |   今日 |    浮% |     浮$ |\n'
         '|:------|------:|-------:|-------:|-------:|-------:|--------:|\n'
         '| CRCL  |     2 |  87.00 |  64.13 |  +2.8% | -26.3% |     -46 |\n'
         '| RKLX  |    10 |  49.69 |  17.07 |  +4.6% | -65.6% |    -326 |')

# What the model actually produced that slot: same numbers, one extra space.
MANGLED_ROW = '| RKLX  |    10 |  49.69 |  17.07 |  +4.6% | -65.6% |     -326 |'

PROSE = ('▎我的看法\n'
         'SKHY 存储链 risk-off 未止，杠杆放大伤口；RKLX 反弹到区间顶部不是加仓信号，'
         '继续按计划减。CRCL 跌破 MA50 后先观察，不追。\n')


def _load(name):
    return importlib.import_module(f'clawock.harness.{name}')


@pytest.fixture
def pf():
    return _load('intraday_postflight')


def _ctx(**over):
    ctx = {
        'status': 'ok', 'market': 'us', 'date': '2026-07-28', 'time': '00:30',
        'raw_wechat_block': BLOCK,
        'signal_count': {'watch': 2, 'stop': 3, 'trim': 0},
        'anomalies': [{'ticker': 'SKHY', 'move_pct': -9.0, 'severity': 'high'}],
        'should_alert': True,
        'context_id': 'abc123def456',
    }
    ctx.update(over)
    return ctx


# ── assembly: the table is no longer the model's to get wrong ────────────────

def test_assembled_message_takes_the_table_from_the_context(pf):
    """The incident in one assertion: prose alone goes in, the context's exact
    table comes out."""
    msg = pf.assemble_message(_ctx(), PROSE)

    for line in BLOCK.splitlines():
        assert line in msg, f'assembled message dropped a context line: {line!r}'
    assert msg.startswith('🇺🇸 美股盯盘 | 07/27 12:30 ET')
    assert '▎我的看法' in msg
    # The mangled row can only appear if the model's copy leaked through.
    assert MANGLED_ROW not in msg


def test_the_same_slot_that_failed_on_a_space_now_passes(pf):
    """The 2026-07-28 00:30 incident, both ways round.

    Legacy: the model retypes the table, pads RKLX's 浮$ cell one space wider,
    and the strict substring match escalates to `fail` — which ships the data
    block alone and drops the analysis. Prose: the model never types the row, so
    the identical slot delivers the identical numbers AND the prose.
    """
    legacy_text = BLOCK.replace(
        '| RKLX  |    10 |  49.69 |  17.07 |  +4.6% | -65.6% |    -326 |',
        MANGLED_ROW) + '\n\n' + PROSE
    legacy_issues = pf.validate(legacy_text, _ctx())

    assert [i for i in legacy_issues if 'verbatim' in i], legacy_issues
    assert pf.categorize(legacy_issues) == 'fail'

    body = pf.assemble_message(_ctx(), PROSE)
    prose_issues = pf.validate(body, _ctx(), prose_only=True, model_text=PROSE)

    assert pf.categorize(prose_issues) == 'pass', prose_issues
    assert PROSE.strip() in body


# ── the block must not answer the content rules on the model's behalf ────────

def test_anomaly_rule_reads_the_prose_not_the_prepended_block(pf):
    """SKHY is named in the block's own table. Prose that never mentions it must
    still fail the should_alert rule — otherwise the check is decorative."""
    silent = '▎我的看法\n' + '大盘窄幅震荡，持仓按既定纪律执行，今天没有需要改的动作。' * 2
    ctx = _ctx(raw_wechat_block=BLOCK + '\n| SKHY  |     1 | 169.19 | 140.72 |')

    issues = pf.validate(pf.assemble_message(ctx, silent), ctx,
                         prose_only=True, model_text=silent)

    assert [i for i in issues if 'should_alert' in i], issues


def test_length_limit_measures_the_delivered_body(pf):
    """Length is a property of what WeChat receives, so it — unlike the content
    rules — is measured on the assembled message."""
    hard = pf.REPORT_CHAR_LIMITS['hard']
    prose = '▎我的看法\n' + 'x' * (hard - 100)
    body = pf.assemble_message(_ctx(), prose)

    issues = pf.validate(body, _ctx(), prose_only=True, model_text=prose)

    assert [i for i in issues if str(hard) in i], issues
    assert len(body) > len(prose)


# ── generation gate ─────────────────────────────────────────────────────────

@pytest.fixture
def sent(pf, tmp_path, monkeypatch):
    """Capture what would go to WeChat/Telegram instead of sending it."""
    box = {'messages': []}
    monkeypatch.setattr(pf, 'TMP', tmp_path)
    monkeypatch.setattr(pf, 'WS', tmp_path)
    monkeypatch.setattr(pf, 'resolve_wechat_target', lambda m: ('weixin', 'kcn', 'acct'))
    monkeypatch.setattr(pf, 'cosend_telegram', lambda *a, **k: (True, 'ok'))

    def _send(channel, to, account, message, dry_run=False):
        box['messages'].append(message)
        return True, 'ok'

    monkeypatch.setattr(pf, 'send_wechat', _send)
    return box


@pytest.fixture
def run_main(pf, sent, monkeypatch, tmp_path):
    """Drive the real main(). Helper-only tests do not guard the wiring — the
    2026-07-23 input_error fix needed the same lesson (a perfect
    read_report_text() still went green while main() ignored its error)."""
    monkeypatch.setattr(pf.trading_calendar, 'closed_reason', lambda m: None)
    monkeypatch.setattr(pf.cron_heartbeat, 'record', lambda *a, **k: None)
    monkeypatch.setattr(pf, 'publish_data_plane', lambda market: ('published', True))

    def run(prose, *, context_id, ctx=None):
        (tmp_path / 'intraday-context-us-latest.json').write_text(
            json.dumps(ctx or _ctx(), ensure_ascii=False))
        body = tmp_path / 'intraday-prose-us.md'
        body.write_text(prose)
        argv = ['intraday_postflight.py', '--market', 'us', '--text-file', str(body)]
        if context_id:
            argv += ['--context-id', context_id]
        monkeypatch.setattr(sys, 'argv', argv)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = pf.main()
        return rc, json.loads(buf.getvalue())

    return run


def test_main_delivers_block_plus_prose_on_the_happy_path(run_main, sent):
    rc, out = run_main(PROSE, context_id='abc123def456')

    assert rc == 0 and out['status'] == 'pass' and out['mode'] == 'prose'
    body = sent['messages'][0]
    assert body.startswith('🇺🇸 美股盯盘 | 07/27 12:30 ET')
    assert '▎我的看法' in body
    for line in BLOCK.splitlines():
        assert line in body


def test_main_sends_only_the_deterministic_receipt_for_an_unchanged_slot(
    run_main, sent, tmp_path
):
    receipt = "🇺🇸 美股盯盘 | 08/13 13:30 ET\n✓ 本轮无新的加仓/减仓条件；5/5 行情已刷新。"
    ctx = _ctx(
        raw_wechat_block=receipt,
        delivery_mode="unchanged_receipt",
        should_alert=False,
        semantic_state={"session": "us:2026-08-13", "breaches": []},
    )

    rc, out = run_main(PROSE, context_id="abc123def456", ctx=ctx)

    assert rc == 0
    assert sent["messages"] == [receipt]
    persisted = json.loads((
        tmp_path / "memory" / ".tmp" / "intraday-delivered-state-us.json"
    ).read_text())
    assert persisted["state"] == ctx["semantic_state"]


def test_unchanged_receipt_needs_no_dummy_prose_file(pf, sent, monkeypatch, tmp_path):
    receipt = "🇺🇸 美股盯盘 | 08/13 13:30 ET\n✓ 本轮无新的加仓/减仓条件；5/5 行情已刷新。"
    ctx = _ctx(
        raw_wechat_block=receipt, delivery_mode="unchanged_receipt",
        should_alert=False, semantic_state={"session": "us:2026-08-13"},
    )
    (tmp_path / "intraday-context-us-latest.json").write_text(json.dumps(ctx))
    monkeypatch.setattr(pf, "TMP", tmp_path)
    monkeypatch.setattr(pf, "WS", tmp_path)
    monkeypatch.setattr(pf.trading_calendar, "closed_reason", lambda _m: None)
    monkeypatch.setattr(pf.cron_heartbeat, "record", lambda *a, **k: None)
    monkeypatch.setattr(pf, "publish_data_plane", lambda _m: ("current", False))
    monkeypatch.setattr(sys, "argv", [
        "intraday_postflight.py", "--market", "us", "--context-id", ctx["context_id"],
    ])
    output = io.StringIO()

    with redirect_stdout(output):
        rc = pf.main()

    assert rc == 0
    assert sent["messages"] == [receipt]


def test_receipt_ignores_irrelevant_context_id_mismatch(
    pf, sent, monkeypatch, tmp_path
):
    receipt = "🇺🇸 美股盯盘 | 08/13 13:30 ET\n✓ 本轮无新的条件。"
    ctx = _ctx(
        raw_wechat_block=receipt, delivery_mode="unchanged_receipt",
        should_alert=False, semantic_state={"session": "us:2026-08-13"},
    )
    (tmp_path / "intraday-context-us-latest.json").write_text(json.dumps(ctx))
    monkeypatch.setattr(pf.trading_calendar, "closed_reason", lambda _m: None)
    monkeypatch.setattr(pf.cron_heartbeat, "record", lambda *a, **k: None)
    monkeypatch.setattr(pf, "publish_data_plane", lambda _m: ("current", False))
    monkeypatch.setattr(sys, "argv", [
        "intraday_postflight.py", "--market", "us", "--context-id", "OLD",
    ])

    with redirect_stdout(io.StringIO()):
        assert pf.main() == 0

    assert sent["messages"] == [receipt]


def test_unchanged_receipt_does_not_refresh_an_old_dashboard_narrative(
    pf, sent, monkeypatch, tmp_path
):
    receipt = "🇺🇸 美股盯盘 | 08/13 13:30 ET\n✓ 本轮无新的加仓/减仓条件。"
    ctx = _ctx(
        date="2026-07-28", raw_wechat_block=receipt,
        delivery_mode="unchanged_receipt", should_alert=False,
        semantic_state={"session": "us:2026-07-28"},
    )
    (tmp_path / "intraday-context-us-latest.json").write_text(json.dumps(ctx))
    sidecar = tmp_path / "intraday-insights-2026-07-28.json"
    old = {"generated_at": "2026-07-28T10:00:00Z", "status_banner": "old", "movers": {}}
    sidecar.write_text(json.dumps(old))
    monkeypatch.setattr(pf, "TMP", tmp_path)
    monkeypatch.setattr(pf, "WS", tmp_path)
    monkeypatch.setattr(pf.trading_calendar, "closed_reason", lambda _m: None)
    monkeypatch.setattr(pf.cron_heartbeat, "record", lambda *a, **k: None)
    monkeypatch.setattr(pf, "publish_data_plane", lambda _m: ("current", False))
    monkeypatch.setattr(sys, "argv", [
        "intraday_postflight.py", "--market", "us", "--context-id", ctx["context_id"],
    ])

    with redirect_stdout(io.StringIO()):
        assert pf.main() == 0

    assert json.loads(sidecar.read_text()) == old


def test_main_replaces_model_authored_future_sidecar_time(
    run_main, sent, tmp_path
):
    """The 2026-08-11 trajectory wrote local 10:02 with a UTC offset (+8h).
    Postflight must persist the prose but never that model-authored clock."""
    path = tmp_path / 'intraday-insights-2026-08-11.json'
    future = '2026-08-11T10:02:00+00:00'
    path.write_text(json.dumps({
        'generated_at': future,
        'status_banner': 'low 12% 区间底，先观察',
        'movers': {'02208': '无明确个股催化，观望'},
        'model_metadata': 'must not survive',
    }, ensure_ascii=False))

    rc, out = run_main(
        PROSE, context_id='abc123def456',
        ctx=_ctx(date='2026-08-11', generated_at='2026-08-11T10:01:59'),
    )

    persisted = json.loads(path.read_text())
    assert rc == 0 and out['insights_sidecar'] is True
    assert persisted['generated_at'] != future
    assert persisted['generated_at'].endswith('Z')
    assert set(persisted) == {'generated_at', 'status_banner', 'movers'}
    assert persisted['status_banner'] == 'low 12% 区间底，先观察'
    assert '▎我的看法' in sent['messages'][0]


def test_malformed_sidecar_never_suppresses_delivery(run_main, sent, tmp_path):
    path = tmp_path / 'intraday-insights-2026-08-11.json'
    path.write_text('{"status_banner":')

    rc, out = run_main(
        PROSE, context_id='abc123def456', ctx=_ctx(date='2026-08-11'))

    assert rc == 0 and out['status'] == 'pass'
    assert out['insights_sidecar'] is False
    assert '▎我的看法' in sent['messages'][0]


def test_publish_failure_is_loud_after_report_delivery(
    run_main, sent, pf, monkeypatch
):
    """A delivered report cannot turn a frozen public dashboard green."""
    monkeypatch.setattr(
        pf, 'publish_data_plane', lambda market: ('publish_failed', False)
    )

    rc, out = run_main(PROSE, context_id='abc123def456')

    assert rc == 2
    assert out['status'] == 'pass'
    assert out['data_plane_status'] == 'publish_failed'
    assert out['heartbeat']['state'] == 'publish_failed'
    assert '▎我的看法' in sent['messages'][0]


def test_main_refuses_to_marry_stale_prose_to_fresh_numbers(run_main, sent):
    """The model wrote against a context that has since been regenerated. Ship
    the data block alone rather than a check-in that looks clean and is not."""
    rc, out = run_main(PROSE, context_id='OLDGENERATION')

    assert rc == 2 and out['status'] == 'fail'
    assert any('context_id 不匹配' in i for i in out['issues'])
    assert out['data_plane_status'] == 'published'
    assert out['dashboard_published'] is True
    assert out['heartbeat']['state'] == 'completed'
    body = sent['messages'][0]
    assert BLOCK.splitlines()[0] in body and '▎我的看法' not in body


def test_failed_full_delta_delivery_does_not_advance_semantic_cursor(
    run_main, sent, tmp_path
):
    ctx = _ctx(semantic_state={"session": "us:2026-08-13", "setups": ["new"]})
    cursor = tmp_path / 'memory' / '.tmp' / 'intraday-delivered-state-us.json'
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text(json.dumps({"state": {"session": "us:2026-08-13"}}))

    rc, out = run_main(PROSE, context_id='OLDGENERATION', ctx=ctx)

    assert rc == 2 and out['status'] == 'fail'
    assert sent['messages']
    assert json.loads(cursor.read_text()) == {
        "state": {"session": "us:2026-08-13"},
    }


def test_preflight_stamps_a_per_generation_context_id():
    """Two preflight runs of the same slot produce different ids, so prose can
    always be pinned to the generation it described."""
    common = _load('_harness_common')

    a = common.compute_context_id({'raw_wechat_block': BLOCK, 'time': '00:30'})
    b = common.compute_context_id({'raw_wechat_block': BLOCK, 'time': '01:00'})

    assert a != b
    assert a == common.compute_context_id({'raw_wechat_block': BLOCK, 'time': '00:30'})
    assert len(a) == 12
