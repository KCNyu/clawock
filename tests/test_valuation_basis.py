"""Basis is attached before normalization, and never means quote freshness."""
from clawock.portfolio import valuation, guardrail
from clawock.harness import brief_render
from clawock.publish import dashboard


def test_mixed_book_sources_zero_and_missing_marks():
    rows = [
        {"ticker": "QUOTE", "shares": 1, "current_value": 100, "data_source": "fixture",
         "day_session_date": "2026-10-30"},
        {"ticker": "COST", "shares": 2, "cost_basis": 50, "current_value": None},
        {"ticker": "MISSING", "shares": 1},
        {"ticker": "ZERO", "shares": 1, "cost_basis": 50, "current_value": 0},
        {"ticker": "CLOSED", "shares": 0, "cost_basis": 50},
    ]
    result = valuation.summary(rows)
    assert result["cost_carried_pct"] == 50
    assert result["cost_count"] == result["unavailable_count"] == 1
    assert [r["kind"] for r in result["rows"]] == ["quote", "cost", "unavailable", "quote"]
    assert result["rows"][0]["session"] == "2026-10-30"
    assert result["rows"][1]["source"] is None
    conc = guardrail.compute_concentration(rows)
    assert conc["valuation"] == result and conc["leg_total"] == 200
    context = {"concentration": {"us": conc}}
    for render in (brief_render.concentration_section, brief_render.risk_section):
        text = render(context)
        assert "成本结转 1 只" in text and "50%" in text and "无法估值 1 只" in text
        assert "fixture" in text and "2026-10-30" in text and "混合/不完整" in text
    trimmed = dashboard.trim_holding(rows[1], "USD")
    assert trimmed["current_value"] == 100
    assert trimmed["valuation_basis"]["kind"] == "cost"


def test_no_denominator_and_numeric_strings():
    assert valuation.summary([{"ticker": "MISSING", "shares": 1}])["cost_carried_pct"] is None
    assert valuation.basis({"shares": "2", "cost_basis": "5"})["kind"] == "cost"
    assert valuation.basis({"shares": 1, "current_value": "0"})["kind"] == "quote"
