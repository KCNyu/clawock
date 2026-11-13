"""Semantic section-label coverage for the daily brief postflight."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
from clawock.harness import brief_postflight


CHINESE_LOCALIZED_BRIEF = """\
# 盘前摘要

HHI 集中度已复核；USDHKD 汇率已复核。

## 第一层
四个分析师角度。

## 第二层
多空辩论。

## 第三层
三个风险声音。

### 裁决
最终动作。

## 同行扫描
板块相对强弱。

## 信心
动作信心校准。

## 下一交易时段
下一时段可执行计划。
"""


def _missing_section_issues(issues):
    return [issue for issue in issues if '缺段标记' in issue]


def test_fully_chinese_localized_brief_has_no_missing_sections(tmp_path):
    path = tmp_path / 'pre-open.md'
    path.write_text(CHINESE_LOCALIZED_BRIEF, encoding='utf-8')

    issues = brief_postflight.validate_markdown(path)

    assert _missing_section_issues(issues) == []


def test_genuinely_omitted_section_still_raises_same_missing_issue(tmp_path):
    path = tmp_path / 'pre-open.md'
    path.write_text(
        CHINESE_LOCALIZED_BRIEF.replace('## 第二层\n多空辩论。\n\n', ''),
        encoding='utf-8',
    )

    issues = brief_postflight.validate_markdown(path)

    # The concept key is the section's current name (2026-09-06 regrouped the
    # report into four parts); `## 第二层` stays an accepted alias, which is why
    # the localized fixture above still validates.
    assert _missing_section_issues(issues) == ['pre-open.md 缺段标记 "多空对辩"']
    # Keep today's warn/fail threshold semantics: one non-critical issue is a warn;
    # five such issues still fail. The section omission itself remains surfaced.
    assert brief_postflight.categorize(issues) == 'warn'


def test_harness_action_boundary_is_fail_closed():
    assert brief_postflight.categorize([
        "plan.json harness: decision[0] ABC action outside harness allowed_actions"
    ]) == "fail"


def test_placeholder_prose_in_the_shipped_brief_fails_like_the_other_harnesses(tmp_path):
    # `brief_render` puts judgment.portfolio_assessment verbatim into pre-open.md
    # and into the WeChat card's ▎核心结论, so a placeholder left in the model's
    # judgment ships unless this file is checked — the report and intraday
    # harnesses have policed the same phrases since #541.
    path = tmp_path / 'pre-open.md'
    path.write_text(
        CHINESE_LOCALIZED_BRIEF.replace('最终动作。', '最终动作 TODO,数据待获取。'),
        encoding='utf-8',
    )

    issues = brief_postflight.validate_markdown(path)

    assert [i for i in issues if '敷衍词' in i] == [
        'pre-open.md含敷衍词 "数据待获取"',
        'pre-open.md含敷衍词 "TODO"',
    ]
    assert brief_postflight.categorize(issues) == 'fail'


def test_clean_brief_keeps_passing_the_placeholder_gate(tmp_path):
    path = tmp_path / 'pre-open.md'
    path.write_text(CHINESE_LOCALIZED_BRIEF, encoding='utf-8')

    assert [i for i in brief_postflight.validate_markdown(path) if '敷衍词' in i] == []


def test_naming_a_section_in_a_sentence_does_not_satisfy_it(tmp_path):
    # #2261: 「本报告不含大盘速读、社交舆情」 passed the bare-substring gate.
    context = {'macro': {'age_hours': 2, 'vix': 18.0},
               'sentiment': {'age_hours': 2, 'tickers': ['ACME']}}
    path = tmp_path / 'pre-open.md'

    path.write_text(CHINESE_LOCALIZED_BRIEF + '\n本报告不含大盘速读、社交舆情速读两段。\n',
                    encoding='utf-8')
    dodged = brief_postflight.validate_markdown(path, context)
    assert any('大盘速读' in issue for issue in dodged)
    assert any('社交舆情' in issue for issue in dodged)

    path.write_text(CHINESE_LOCALIZED_BRIEF + '\n### 大盘速读\n\nVIX 18。\n\n### 社交舆情\n\n平静。\n',
                    encoding='utf-8')
    written = brief_postflight.validate_markdown(path, context)
    assert not any('大盘速读' in issue or '社交舆情' in issue for issue in written)


def test_a_watch_level_from_another_ticker_is_critical():
    """#3447: SPCX's 120.39 in `spch_prior_20d_low` at a 7.97 quote."""
    plan = {'watch_levels': {
        'spch_prior_20d_low': 120.39,
        'spcx_prior_20d_low': 120.39,
        'hstech_breakdown': 3912,
        'hk_leg_force_derisk_hkd': -80000,
        'spch_breakdown_pct': -4,
    }}
    packet = {'tickers': {
        'SPCH': {'facts': {'current_price': 7.97}},
        'SPCX': {'facts': {'current_price': 139.94}},
    }}
    issues = brief_postflight._watch_level_scale_issues(plan, packet)
    assert len(issues) == 1
    assert 'spch_prior_20d_low' in issues[0] and '15.1 倍' in issues[0]
    assert 'critical' in issues[0]
    assert 'plan.json watch_levels' in brief_postflight.CRITICAL_KEYWORDS


def test_a_plausible_watch_level_is_not_flagged():
    plan = {'watch_levels': {
        'spch_prior_20d_low': 5.93,      # the real SPCH 20d low
        'spch_breakdown': 7.0,           # 1.14x from 7.97
        'spch_target': 79.0,             # 9.9x: below the 10x gate
    }}
    packet = {'tickers': {'SPCH': {'facts': {'current_price': 7.97}}}}
    assert brief_postflight._watch_level_scale_issues(plan, packet) == []
