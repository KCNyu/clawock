"""A ticker is mentioned when it stands as its own code, not inside another (#1557).

The postflight content rules asked `ticker in text`, so one code could vouch
for another. Both shapes are in the book's own pre-open prose: QQQ and TQQQ are
both holdings, and SPCH is written "SPCH 2xSPCX". An HK code can likewise sit
inside a longer digit run. The same prose also glues codes to numbers and CJK
("SPCH44.71%单名", "SPCH2x在趋势OFF", "ROBN/PLTU5日") — those must stay
mentions, or the fix trades a missed gap for a false alarm.

Every rule is driven through the real validator that owns it.
"""
from __future__ import annotations

import importlib

import pytest

from clawock.harness.validation import mentions_ticker


@pytest.mark.parametrize("text, ticker", [
    ("SPCH44.71%单名把US leg绑住", "SPCH"),        # memory/2026-07-15-pre-open.md
    ("SPCH2x在趋势OFF+波动过热", "SPCH"),           # memory/2026-07-08-pre-open.md
    ("ROBN/PLTU5日情绪仍正面", "PLTU"),              # memory/2026-07-08-pre-open.md
    ("SPCH260814P8000 是保护腿", "SPCH"),            # option code on the holding
    ("| TQQQ | wait |", "TQQQ"),
    ("00100.HK 破 365", "00100"),
    ("00100现价393", "00100"),
    ("减 00100，", "00100"),
])
def test_codes_glued_to_numbers_or_cjk_are_still_mentions(text, ticker):
    assert mentions_ticker(text, ticker)


@pytest.mark.parametrize("text, ticker", [
    ("| TQQQ | wait | 窗口内无一手公告", "QQQ"),    # memory/2026-09-18-pre-open.md
    ("SPCH 2xSPCX 航天杠杆 +4.27", "SPCX"),          # memory/2026-08-26-pre-open.md
    ("ROBN (2xHOOD) +8.43%", "HOOD"),
    ("成交 1500100 股", "00100"),
    ("", "SKHY"),
    ("SKHY", ""),
])
def test_a_code_inside_another_code_is_not_a_mention(text, ticker):
    assert not mentions_ticker(text, ticker)


# ── the five call sites ──────────────────────────────────────────────────────

TQQQ_ONLY = ('▎我的看法\n'
             'TQQQ 今天跟着纳指走，三倍杠杆放大了波动，纪律单继续挂着，'
             '其余持仓按 08:00 计划执行，不新增动作，等收盘再看一次。\n')


def _intraday_ctx(**over):
    ctx = {'status': 'ok', 'market': 'us', 'date': '2026-09-18', 'time': '00:30',
           'raw_wechat_block': '🇺🇸 美股盯盘 | QQQ -3.1%', 'context_id': 'x'}
    ctx.update(over)
    return ctx


def _intraday_issues(ctx, prose):
    pf = importlib.import_module('clawock.harness.intraday_postflight')
    return pf.validate(pf.assemble_message(ctx, prose), ctx, prose)


def test_intraday_anomaly_is_not_covered_by_a_longer_ticker():
    ctx = _intraday_ctx(should_alert=True,
                        anomalies=[{'ticker': 'QQQ', 'move_pct': -3.1}])
    issues = _intraday_issues(ctx, TQQQ_ONLY)
    assert [i for i in issues if '未提任何异动票' in i], issues


def test_intraday_trigger_and_add_side_rows_need_their_own_code():
    ctx = _intraday_ctx(
        plan_triggers=[{'ticker': 'QQQ', 'condition_price': 480.0}],
        add_side_reads={'rows': [{'ticker': 'QQQ', 'verdict': 'wait'}]})
    issues = _intraday_issues(ctx, TQQQ_ONLY)
    assert [i for i in issues if '计划触发线' in i], issues
    assert [i for i in issues if '加仓侧读数' in i], issues


def test_report_anomaly_is_not_covered_by_a_longer_ticker():
    report = importlib.import_module('clawock.harness.report')
    ctx = {'anomalies': [{'ticker': 'QQQ', 'move_pct': -3.1}]}
    issues = report.validate(TQQQ_ONLY, ctx, TQQQ_ONLY)
    assert [i for i in issues if '异动票' in i], issues


def test_brief_divergence_ticker_needs_its_own_mention(tmp_path):
    brief = importlib.import_module('clawock.harness.brief_postflight')
    md = tmp_path / 'pre-open.md'
    md.write_text('| SPCH 2xSPCX | 航天杠杆 | +4.27 |\nSPCH 跟随板块轮动。\n')
    context = {'peer_scan': {'SPCX': {'divergence_signal': True},
                             'SPCH': {'divergence_signal': True}}}
    flagged = [i for i in brief.validate_markdown(md, context) if 'divergence' in i]
    assert flagged and "['SPCX']" in flagged[0], flagged
