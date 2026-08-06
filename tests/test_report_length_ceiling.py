"""Length is a ceiling against repeat-loops, not a writing target (#334).

#214 handed the model an exact pre-write prose budget (assembled target 2,800
minus title and harness data block ≈ 1,200 chars) and every Mode 6 report was
then written under a compression instruction. kcn's 2026-08-06 call: take the
target away, let the model decide length, keep only a ceiling wide enough that
a real report never reaches it and a model stuck restating itself always does.

So what is worth pinning is no longer arithmetic — it is that the numbers exist
in exactly one place, that both report modes read that place, and that removing
the budget did not also remove the content the reports must carry.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))
import _harness_common as common  # noqa: F401
from clawock import validation  # noqa: E402
import intraday_postflight  # noqa: E402
import report_postflight as postflight  # noqa: E402


def test_every_mode_reads_one_definition_of_the_ceiling():
    # Mode 7 used to carry its own 3000/3500 literals, so the two modes could
    # drift apart with nothing to notice.
    assert postflight.CHAR_LIMITS is validation.REPORT_CHAR_LIMITS
    assert intraday_postflight.REPORT_CHAR_LIMITS is validation.REPORT_CHAR_LIMITS
    assert validation.REPORT_CHAR_LIMITS == {'soft': 5_000, 'hard': 6_000}


def test_a_repeat_loop_still_fails_closed():
    # The one thing the ceiling is for: a model restating itself blows past it,
    # and that is the only automatic signal we have for that failure.
    soft = validation.REPORT_CHAR_LIMITS['soft']
    hard = validation.REPORT_CHAR_LIMITS['hard']
    body = '▎我的看法\n' + '判' * 200 + '\n'

    def intraday_len(n):
        text = body + '填' * (n - len(body))
        return [i for i in intraday_postflight.validate(text, {}) if '报告长度' in i]

    assert intraday_len(hard) == [f'报告长度 {hard} 字 > {soft} 软上限 (warn)']
    assert intraday_len(hard + 1) == [f'报告长度 {hard + 1} 字 > {hard} 上限']
    assert intraday_postflight.categorize(
        [f'报告长度 {hard + 1} 字 > {hard} 上限']) == 'fail'

    for market in ('hk', 'us'):
        assert [i for i in postflight.validate('填' * (hard + 1), {'market': market})
                if '报告长度' in i] == [f'报告长度 {hard + 1} 字 > {hard} 上限']


def test_a_normal_length_report_is_no_longer_flagged():
    # 2,900 chars is roughly what the reports ran at under the old 2,800 target;
    # nothing at that size may produce a length issue any more.
    assert [i for i in postflight.validate('填' * 2_900, {'market': 'us'})
            if '报告长度' in i] == []


def test_removing_the_budget_did_not_remove_the_required_content():
    # The old budget paragraph was also where "do not compress peer detail"
    # lived (see clawock-peer-detail-preservation). Those requirements have to
    # survive the deletion on their own.
    for skill_name in ('us-stock-analysis', 'hk-stock-analysis'):
        text = (ROOT / 'skills' / skill_name / 'SKILL.md').read_text(
            encoding='utf-8')
        mode6 = text.split('### Mode 6', 1)[1].split('### Mode 5', 1)[0]
        assert 'prose_target_chars' not in mode6
        assert '目标 ≤2200' not in mode6 and '目标 ≤ 2200' not in mode6
        assert 'Top 5' in mode6 and '今日/5 日涨跌' in mode6
        for required in ('异动归因', '计划对账', '风险提示', '持仓', '归因'):
            assert required in mode6
