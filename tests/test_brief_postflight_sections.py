"""Semantic section-label coverage for the daily brief postflight."""

import sys
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
