"""Prompt vocabulary leaking into what kcn reads on WeChat.

The samples are delivered text, not invented: 2026-09-14 HK mid/pm reports,
2026-09-09 HK intraday, and the 2026-09-09 brief card's 核心结论. The model
narrated in the prompt's words — packet, harness, preflight — which mean
nothing to the reader. The check is advisory: it must surface on the delivered
banner and must never turn a deliverable report into a data-block-only send.
"""
from __future__ import annotations

import importlib
import json

import pytest

from clawock.harness import report as report_core
from clawock.harness import validation as val


REPORT_LEAK = ('▎情绪面\n恒科 -1.5%，00100 -5.6% 跑输同业。\n\n▎技术面\n'
               '00100 跌破 280，200 是 packet 锁定的破位审议线。\n\n▎操作建议\n'
               '00100 / 02208 全部 hold_and_watch packet 锁定，今日无需动作。')
INTRADAY_LEAK = ('▎我的看法\n00100 +4.9% 异动，但 range_pos 91% 已被 harness 标 🔴「追高低质」，'
                 '窗口内无新公告，且无已知催化，暂无法归因，先不追，等回踩 20 日线再看。')
CARD_LEAK = ('Book 双 leg 都高 HHI 危险集中 (HK 0.43 / US 0.68), 9/9 preflight 仍 4 breach '
             '+ 2 hard stop, 主动 call 必须由 risk_rule 驱动。')
CLEAN = ('▎情绪面\n恒科 -1.5%，同业普跌。\n\n▎技术面\n00100 跌破 280，下一支撑 200。\n\n'
         '▎操作建议\n00100 风控规则只允许持有观察，今天不减；07226 cut 按计划执行。')


def _report_ctx():
    return {'title': '港股午盘', 'raw_wechat_block': '📊 市值 HK$64,804', 'anomalies': []}


def test_delivered_report_leak_is_flagged_once_and_stays_advisory():
    issues = report_core.validate(REPORT_LEAK, _report_ctx(), REPORT_LEAK)
    leaks = [i for i in issues if '管线术语' in i]
    assert len(leaks) == 1 and 'packet' in leaks[0]
    assert all(val.is_advisory(i) for i in leaks)
    # The same report without the leak categorises identically: the word alone
    # never costs kcn the analysis.
    rest = [i for i in issues if '管线术语' not in i]
    assert report_core.categorize(issues) in ('pass', 'warn')
    assert val.product_status(report_core.categorize(issues), val.split_advisory(issues)[0]) \
        == val.product_status(report_core.categorize(rest), val.split_advisory(rest)[0])


def test_leak_reaches_the_delivered_banner():
    _, advisories = val.split_advisory(report_core.validate(REPORT_LEAK, _report_ctx(), REPORT_LEAK))
    assert 'packet' in val.advisory_prefix(advisories)


def test_intraday_prose_leak_is_flagged():
    pf = importlib.import_module('clawock.harness.intraday_postflight')
    ctx = {'raw_wechat_block': '🇭🇰 港股盯盘', 'anomalies': [{'ticker': '00100'}],
           'should_alert': True}
    leaks = [i for i in pf.validate(INTRADAY_LEAK, ctx, INTRADAY_LEAK) if '管线术语' in i]
    assert leaks and 'harness' in leaks[0] and val.is_advisory(leaks[0])


def test_only_model_prose_is_checked_not_the_harness_block():
    """The data block is harness-owned; a pipeline word there is not the model's."""
    ctx = dict(_report_ctx(), raw_wechat_block='📊 preflight 快照 | 市值 HK$64,804')
    body = report_core.assemble_message(ctx, CLEAN)
    assert not [i for i in report_core.validate(body, ctx, CLEAN) if '管线术语' in i]


def test_brief_card_assessment_is_checked(tmp_path):
    pf = importlib.import_module('clawock.harness.brief_postflight')
    path = tmp_path / 'brief-judgment.json'
    path.write_text(json.dumps({'portfolio_assessment': CARD_LEAK}), encoding='utf-8')
    issues = pf._card_self_reference_issues(path)
    assert len(issues) == 1 and 'preflight' in issues[0] and val.is_advisory(issues[0])
    path.write_text(json.dumps({'portfolio_assessment': '今天仍有 4 条风控超限。'}), encoding='utf-8')
    assert pf._card_self_reference_issues(path) == []
    assert pf._card_self_reference_issues(tmp_path / 'missing.json') == []


@pytest.mark.parametrize('text', [
    CLEAN,
    # Trading vocabulary and field names kcn does read on the card stay quiet.
    '07226 cut 6200 股 (driven_by=risk_rule)，00100 hold_and_watch。',
    # Substrings of longer ASCII words are not the term.
    'packets of liquidity; harnessing the rebound; preflighted orders',
])
def test_ordinary_analysis_is_not_flagged(text):
    assert val.check_pipeline_self_reference(text) == []


def test_term_adjacent_to_cjk_is_still_caught():
    """`\\b` does not fire between an ASCII letter and a CJK character."""
    assert val.check_pipeline_self_reference('packet锁定')
    assert val.check_pipeline_self_reference('按Harness严令')
