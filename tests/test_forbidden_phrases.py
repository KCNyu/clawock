"""The 敷衍词 gate that brief, report and intraday all share.

`敷衍词` is critical in all three postflights, so a placeholder the gate misses
is delivered as a normal card. Two ways it used to miss: the model wrote the
placeholder in lower case (#1771), and intraday carried its own shorter copy of
the table (#1776). The table lives in `validation`, the layer all three entries
share; each entry is checked here by what it refuses, not by where it imports.
"""

from __future__ import annotations

import pytest

from clawock.harness import brief_postflight, intraday_postflight, report
from clawock.harness.validation import FORBIDDEN_PHRASES, validate_forbidden_phrases


@pytest.mark.parametrize('prose', [
    '后市待定，TODO 稍后补充',
    '后市待定，todo 稍后补充',
    '细节 tbd',
    '仓位 Tbd，明早再看',
])
def test_a_placeholder_is_caught_in_any_case(prose):
    assert validate_forbidden_phrases(prose, FORBIDDEN_PHRASES) != []


def test_a_lowercase_phrase_inside_an_ordinary_word_is_not_a_placeholder():
    assert validate_forbidden_phrases('Mastodon 社区讨论升温', FORBIDDEN_PHRASES) == []


@pytest.mark.parametrize('token', [
    'TODO123', 'TODO_123', 'TBD-456', 'TBD:789', 'TODO.123', 'TODO_abc',
])
def test_numbered_references_are_not_standalone_placeholders(token):
    assert validate_forbidden_phrases(f'跟踪 {token} 的进度', FORBIDDEN_PHRASES) == []


def test_a_placeholder_with_sentence_punctuation_is_still_caught():
    assert validate_forbidden_phrases('TODO: 稍后补充', FORBIDDEN_PHRASES)


@pytest.mark.parametrize('phrase', FORBIDDEN_PHRASES)
def test_intraday_refuses_every_placeholder_report_refuses(phrase):
    prose = (f'▎我的看法\n恒指夜期波动加剧席位分歧明显加大，相关环节{phrase}，'
             '待明日开盘确认方向后再做判断，暂维持观察仓位不动并控制回撤。')
    issues = intraday_postflight.validate(prose, {}, prose)
    assert f'报告含敷衍词 "{phrase}"' in issues
    assert intraday_postflight.categorize(issues) == 'fail', issues


@pytest.mark.parametrize('phrase', FORBIDDEN_PHRASES)
def test_report_refuses_every_placeholder(phrase):
    prose = f'▎情绪面\n分歧加大，相关环节{phrase}。\n▎技术面\n—\n▎操作建议\n观望'
    issues = report.validate(prose, {'market': 'hk'}, prose)
    assert f'报告含敷衍词 "{phrase}"' in issues
    assert report.categorize(issues) == 'fail', issues


@pytest.mark.parametrize('phrase', FORBIDDEN_PHRASES)
def test_brief_refuses_every_placeholder(phrase, tmp_path):
    from test_brief_postflight_sections import CHINESE_LOCALIZED_BRIEF

    path = tmp_path / 'pre-open.md'
    path.write_text(CHINESE_LOCALIZED_BRIEF.replace('最终动作。', f'最终动作，{phrase}。'),
                    encoding='utf-8')
    issues = brief_postflight.validate_markdown(path)
    assert f'pre-open.md含敷衍词 "{phrase}"' in issues
    assert brief_postflight.categorize(issues) == 'fail', issues
