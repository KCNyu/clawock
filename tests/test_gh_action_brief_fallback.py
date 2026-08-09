import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

from clawock_kcnyu.automation import brief_fallback as fallback  # noqa: E402


def _context():
    return {
        "date": "2026-07-17",
        "portfolio": {
            "portfolios": {
                "hk_stocks": {
                    "holdings": [{"ticker": "00100", "shares": 100}],
                    "cash": 1234,
                },
                "us_stocks": {
                    "holdings": [{"ticker": "MSFT", "shares": 2}],
                    "cash": 567,
                },
            }
        },
    }


def test_oversize_context_keeps_required_sections_whole():
    context = _context()
    original_portfolio = json.loads(json.dumps(context["portfolio"]))
    context["news"] = {"items": [{"text": "N" * 20_000}]}
    context["sentiment"] = {"analysis": "S" * 20_000}

    prepared = fallback.prepare_context(context, cap=2_500)
    parsed = json.loads(prepared["serialized"])

    assert prepared["complete"] is True
    assert len(prepared["serialized"]) <= 2_500
    assert parsed["portfolio"] == original_portfolio
    assert parsed["portfolio"]["portfolios"]["hk_stocks"] == (
        original_portfolio["portfolios"]["hk_stocks"])
    assert parsed["portfolio"]["portfolios"]["us_stocks"] == (
        original_portfolio["portfolios"]["us_stocks"])
    assert prepared["manifest"]["portfolio"]["status"] == "included"
    assert prepared["manifest"]["hk_stocks"]["status"] == "included"
    assert prepared["manifest"]["us_stocks"]["status"] == "included"
    assert prepared["manifest"]["news"]["status"] in {"trimmed", "omitted"}


def test_missing_required_section_produces_zero_actions_and_explicit_brief():
    context = _context()
    del context["portfolio"]["portfolios"]["us_stocks"]

    prepared = fallback.prepare_context(context, cap=2_500)
    markdown, plan = fallback.fail_closed_artifacts("2026-07-17", prepared)

    assert prepared["complete"] is False
    assert prepared["manifest"]["us_stocks"]["status"] == "missing"
    assert plan["decisions"] == []
    assert plan["data_complete"] is False
    assert "数据不完整，本次不生成交易动作" in markdown
    assert "us_stocks" in markdown


import pytest


@pytest.mark.parametrize('fence', ['```json', '```JSON', '``` json', '```\tjson'])
def test_split_brief_and_plan_tolerates_fence_case_and_spacing(fence):
    """2026-07 audit: pinning the exact lowercase ```json discarded a valid plan
    the moment the model shifted case/spacing, killing the last brief-recovery."""
    out = f'# 盘前简报\n正文……\n\n{fence}\n{{"decisions": [], "as_of": "x"}}\n```\n'
    md, plan = fallback.split_brief_and_plan(out)
    assert json.loads(plan) == {'decisions': [], 'as_of': 'x'}
    assert '盘前简报' in md and '```' not in md


def test_split_brief_and_plan_uses_last_fence_not_first():
    """Markdown may itself contain a ```json example; the plan is the LAST fence."""
    out = ('示例：```json\n{"example": true}\n```\n正文\n\n'
           '```json\n{"decisions": [1], "as_of": "real"}\n```')
    _, plan = fallback.split_brief_and_plan(out)
    assert json.loads(plan) == {'decisions': [1], 'as_of': 'real'}


def test_split_brief_and_plan_recovers_a_bare_trailing_plan():
    out = '# 简报\n正文 {行内 brace 不是 plan}\n\n{"decisions": [], "as_of": "bare"}'
    _, plan = fallback.split_brief_and_plan(out)
    assert json.loads(plan)['as_of'] == 'bare'


def test_split_brief_and_plan_returns_empty_object_when_no_json():
    _, plan = fallback.split_brief_and_plan('# 简报\n只有正文，没有计划。')
    assert plan == '{}'


def test_split_recovers_bare_plan_after_an_earlier_fenced_example():
    """2026-07 review: an earlier ```json example must not steal the plan when the
    real plan is a bare trailing object — the LAST valid object wins."""
    out = ('示例：\n```json\n{"example": 1}\n```\n正文\n\n'
           '{"decisions": [], "as_of": "real"}')
    _, plan = fallback.split_brief_and_plan(out)
    assert json.loads(plan)['as_of'] == 'real'


def test_split_survives_unbalanced_brace_in_prose():
    """An unmatched { in Markdown must not poison extraction of a valid trailing plan."""
    out = '正文 { 未闭合花括号\n\n```json\n{"decisions": [], "as_of": "d"}\n```'
    _, plan = fallback.split_brief_and_plan(out)
    assert json.loads(plan)['as_of'] == 'd'


def test_split_is_string_aware_for_braces_inside_json_values():
    out = '```json\n{"note": "a } b {", "as_of": "e"}\n```'
    _, plan = fallback.split_brief_and_plan(out)
    assert json.loads(plan) == {'note': 'a } b {', 'as_of': 'e'}
