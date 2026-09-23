"""The 敷衍词 gate that brief, report and intraday all share.

`敷衍词` is critical in all three postflights, so a placeholder the gate misses
is delivered as a normal card. Two ways it used to miss: the model wrote the
placeholder in lower case (#1771), and intraday carried its own shorter copy of
the table (#1776).
"""

from __future__ import annotations

import pytest

from clawock.harness import intraday_postflight, report
from clawock.harness.validation import validate_forbidden_phrases


@pytest.mark.parametrize('prose', [
    '后市待定，TODO 稍后补充',
    '后市待定，todo 稍后补充',
    '细节 tbd',
    '仓位 Tbd，明早再看',
])
def test_a_placeholder_is_caught_in_any_case(prose):
    assert validate_forbidden_phrases(prose, report.FORBIDDEN_PHRASES) != []


def test_a_lowercase_phrase_inside_an_ordinary_word_is_not_a_placeholder():
    assert validate_forbidden_phrases('Mastodon 社区讨论升温', report.FORBIDDEN_PHRASES) == []


@pytest.mark.parametrize('phrase', report.FORBIDDEN_PHRASES)
def test_intraday_refuses_every_placeholder_report_refuses(phrase):
    prose = (f'▎我的看法\n恒指夜期波动加剧席位分歧明显加大，相关环节{phrase}，'
             '待明日开盘确认方向后再做判断，暂维持观察仓位不动并控制回撤。')
    issues = intraday_postflight.validate(prose, {}, prose)
    assert f'报告含敷衍词 "{phrase}"' in issues
    assert intraday_postflight.categorize(issues) == 'fail', issues
