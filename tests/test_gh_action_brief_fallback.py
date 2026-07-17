import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import gh_action_brief_fallback as fallback  # noqa: E402


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
