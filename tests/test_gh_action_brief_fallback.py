import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from clawock.automation import brief_fallback as fallback  # noqa: E402


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


def test_oversize_context_keeps_generation_metadata():
    context = _context()
    context["generation_id"] = "brief-20260717-082500"
    context["optional_blob"] = {"text": "X" * 20_000}

    prepared = fallback.prepare_context(context, cap=2_500)
    parsed = json.loads(prepared["serialized"])

    assert prepared["complete"] is True
    assert parsed["date"] == context["date"]
    assert parsed["generation_id"] == context["generation_id"]
    assert prepared["manifest"]["date"]["status"] == "included"
    assert prepared["manifest"]["generation_id"]["status"] == "included"
    assert prepared["manifest"]["optional_blob"]["status"] == "omitted"


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


REPLY = {'plan': {'decisions': [], 'as_of': 'real'}, 'judgment': {'note': 'a } b {'}}


@pytest.mark.parametrize('fence', ['```json', '```JSON', '``` json', '```\tjson'])
def test_the_reply_object_is_found_whatever_the_fence_looks_like(fence):
    """2026-07 audit: pinning the exact lowercase ```json discarded a valid plan
    the moment the model shifted case/spacing, killing the last brief-recovery."""
    out = f'好的，结果如下：\n\n{fence}\n{json.dumps(REPLY)}\n```\n'
    assert fallback.split_plan_and_judgment(out) == (REPLY['plan'], REPLY['judgment'])


def test_the_reply_object_is_the_last_one_not_an_earlier_example():
    """A preamble may itself contain a ```json example; the reply is the LAST object."""
    out = ('示例：```json\n{"plan": {"example": true}, "judgment": {}}\n```\n正文\n\n'
           + json.dumps(REPLY))
    assert fallback.split_plan_and_judgment(out)[0] == REPLY['plan']


def test_an_unbalanced_brace_in_the_preamble_does_not_poison_the_reply():
    out = '说明 { 未闭合花括号\n\n```json\n' + json.dumps(REPLY) + '\n```'
    plan, judgment = fallback.split_plan_and_judgment(out)
    # String-aware too: the braces inside the judgment text survive.
    assert plan == REPLY['plan'] and judgment['note'] == 'a } b {'


@pytest.mark.parametrize('out', [
    '# 简报\n只有正文，没有计划。',
    '```json\n{"decisions": [], "as_of": "plan only"}\n```',
    '```json\n{"plan": {"decisions": []}, "judgment": []}\n```',
])
def test_a_reply_that_is_not_plan_plus_judgment_is_refused(out):
    with pytest.raises(SystemExit):
        fallback.split_plan_and_judgment(out)
