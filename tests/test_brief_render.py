"""The harness owns the brief's layout; the model owns only the thoughts.

Before this, the model wrote `{date}-pre-open.md` itself — every heading, table
and ornament — so the report's shape was re-decided each morning and the
deliberation leaked into the tables. These tests pin the split: the same inputs
must produce the same document, model text lands in slots rather than deciding
them, and no string reaching a table can add a column to it.
"""
import json

import pytest

from clawock.harness import brief_render as render
from clawock.harness.validation import check_md_table_column_consistency


CONTEXT = {
    "date": "2026-08-31",
    "book_totals": {"hk_pnl_hkd": -39811.24, "us_pnl_usd": -1239.66,
                    "usd_base_total": -6317.88, "hkd_base_total": -49529.68},
    "fx": {"rate": 7.8396, "source": "Frankfurter", "fetched_at": "2026-08-31T00:00:44Z"},
    "concentration": {
        "hk": {"hhi": 0.406, "top2_pct": 85.8, "verdict": "🔴 危险集中", "leg_total": 65465.0},
        "us": {"hhi": 0.67, "top2_pct": 86.5, "verdict": "🔴 危险集中", "leg_total": 3366.0},
    },
    "risk_discipline": {"open_count": 7, "unacknowledged_count": 7, "oldest_open_days": 47},
    "risk_guardrail": {
        "hard_stop_watch": [{"ticker": "07226", "severity": "critical",
                             "detail": "07226 浮亏 -25.7% ≤ 硬止损线 -18%",
                             "breach_id": "risk-4ab"}],
        "breaches": [], "directive": "四条硬闸必须各出一个动作。",
    },
    "breakeven_math": {"rows": [{"ticker": "07226", "pnl_pct": -25.7,
                                 "breakeven_need_pct": 34.7,
                                 "chop_drag_pct_per_month": 0.41,
                                 "underlying_need_2x_6m_pct": 17.5}],
                       "note": "直线涨→2x 回本更快。"},
    "portfolio": {"portfolios": {
        "hk_stocks": {"holdings": [{"ticker": "07226", "name": "XL二南方恒科", "shares": 6200,
                                    "cost_basis": 4.36, "current_price": 3.24,
                                    "today_change_pct": -0.8, "pnl_percent": -25.74,
                                    "pnl_abs": -6964.0, "data_source": "Tencent"}],
                      "total_pnl": -6964.0, "total_pnl_percent": -25.74,
                      "today_total_change": -160.0, "cash_hkd": 17597},
        "us_stocks": {"holdings": [], "total_pnl": 0, "cash_usd": 264.28},
    }},
    "quant_signals": {"rows": {"HSTECH": {"rsi14": 42.5, "tag": "趋势OFF",
                                          "dist_ma200_pct": -10.1, "status": "fresh",
                                          "source_holdings": ["07226"]}}},
    "retrospective": {"prior_plan_date": "2026-08-28", "decisions": []},
    "peer_scan": {"07226": {"theme": "HK 科技指数 2x", "self_pct_1d": -0.8,
                            "listed_peers": [{"ticker": "00700", "name": "腾讯控股",
                                              "pct_1d": 1.65}]}},
    "macro": {"as_of": "2026-08-30T23:56Z", "age_hours": 0.1,
              "vix": {"price": 14.43, "change_pct": -0.55},
              "hstech": {"price": 4605.15, "change_pct": -0.33}},
    "sentiment": {"tickers": [{"ticker": "07226", "reddit_mentions_7d": 0,
                               "news_top": [{"title": "Hang Seng Tech | Southbound buys"}]}]},
    "influencer": {"counts": {"total": 0}},
    "decision_metrics": {"window_days": 30, "settled_episodes": 16, "raw_decisions": 186,
                         "brier": 0.2595,
                         "by_driver": {"risk_rule": {"n_episodes": 5, "avg_benefit_pct": 1.2,
                                                     "cluster_ci95": [0.37, 0.96],
                                                     "edge_significant": True}}},
    "issues": [],
}

PLAN = {"decisions": [
    {"ticker": "07226", "action": "cut", "strategy_id": "risk_rebalance",
     "driven_by": "risk_rule", "confidence": 0.92,
     "size": {"shares": 6200},
     "rationale": "硬止损 7d breach，2x→1x 同因子换仓 | 敞口保留",
     "debate": {"frames": ["technical_breakdown", "relative_strength"]}},
    {"ticker": "00100", "action": "hold_and_watch", "strategy_id": "core_position",
     "driven_by": "sentiment", "confidence": 0.55, "rationale": "利好已在价。"},
], "watch_levels": {"hstech_breakdown": 4500}}


def _judgment(**overrides):
    narrative = {
        "regime_read": "两地趋势 OFF。", "bull": "最坏定价已吃掉大半。",
        "bear": "纪律未执行是最大风险。", "devils_advocate": "共识建立在单一来源上。",
        "attacked_consensus": "板块仍有 alpha", "risk_voice_first": "conservative",
        "aggressive": "留一半敞口。", "conservative": "硬闸今天必须执行。",
        "neutral": "硬闸执行，其余持有。", "sector_read": "板块内部分化。",
        "macro_read": "指数小幅向下。", "calibration_read": "risk_rule 是唯一 edge。",
        "next_session": ["09:30 确认成交"], "data_holes": ["财报日未确认"],
    }
    narrative.update(overrides.pop("narrative", {}))
    return {
        "schema_version": 3, "portfolio_assessment": "三条杠杆全破硬止损。",
        "portfolio_counterargument": "再写软执行等于纪律债加码。",
        "narrative": narrative,
        "ticker_judgments": [
            {"ticker": "07226", "verdict": "bearish", "confidence": 0.92,
             "disposition": "wait", "assessment": "杠杆放大下行。",
             "counterargument": "反弹会踏空。", "rationale": "硬闸优先。",
             "falsifier": "HSTECH 收复 200 线。", "next_evidence": "09:30 成交。",
             "fundamentals": "2x 杠杆 ETF，无基本面。", "cross_market": "跟随 HSTECH。",
             "sentiment_read": "无硬催化。", "peer_read": "弱于腾讯 2.45pp。"},
        ],
        **overrides,
    }


def test_the_report_is_rendered_in_one_fixed_order():
    body = render.render_brief(CONTEXT, _judgment(), PLAN, date="2026-08-31")

    order = ["# 盘前深度简报", "## Header", "### 集中度", "### 风险纪律",
             "### Breakeven math", "## ▎仓位明细", "## Retrospective", "## Tier 1",
             "## Tier 2", "## Tier 3", "### Judge", "## ▎同行扫描", "## ▎大盘速读",
             "## ▎社交舆情速读", "## Confidence", "## ▎Decision v2 校准",
             "## Next-Session Plan", "## ▎待补"]
    positions = [body.index(heading) for heading in order]
    assert positions == sorted(positions), (
        "section order is the harness's, and it must not depend on the judgment")


def test_the_same_inputs_render_the_same_bytes():
    """Determinism is the property the model could not offer."""
    first = render.render_brief(CONTEXT, _judgment(), PLAN, date="2026-08-31")
    second = render.render_brief(CONTEXT, _judgment(), PLAN, date="2026-08-31")

    assert first == second


def test_a_pipe_in_a_headline_or_rationale_cannot_add_a_column():
    """Neither source is judgment-gated: a feed headline and a plan rationale
    both arrive with whatever punctuation they have."""
    body = render.render_brief(CONTEXT, _judgment(), PLAN, date="2026-08-31")

    assert "Southbound buys" in body
    assert check_md_table_column_consistency(body) == []


def test_model_text_lands_in_the_slot_it_was_written_for():
    body = render.render_brief(CONTEXT, _judgment(), PLAN, date="2026-08-31")

    bull = body.index("最坏定价已吃掉大半。")
    bear = body.index("纪律未执行是最大风险。")
    assert body.index("## Tier 2") < bull < bear < body.index("## Tier 3")
    assert "板块仍有 alpha" in body


def test_the_first_risk_voice_is_the_one_the_judgment_named():
    body = render.render_brief(CONTEXT, _judgment(), PLAN, date="2026-08-31")
    tier3 = body[body.index("## Tier 3"):body.index("### Judge")]

    assert tier3.index("Conservative") < tier3.index("Aggressive"), (
        "the rotation is stated by the model and ordered by the harness")
    assert "今日首位表态" in tier3


def test_a_missing_narrative_field_reads_as_a_hole_not_as_None():
    judgment = _judgment(narrative={"macro_read": ""})
    body = render.render_brief(CONTEXT, judgment, PLAN, date="2026-08-31")

    assert "None" not in body
    macro = body[body.index("## ▎大盘速读"):body.index("## ▎社交舆情速读")]
    assert render.MISSING in macro


def test_an_unknown_risk_voice_still_renders_three_named_voices():
    judgment = _judgment(narrative={"risk_voice_first": None})
    body = render.render_brief(CONTEXT, judgment, PLAN, date="2026-08-31")

    for voice in ("Aggressive", "Conservative", "Neutral"):
        assert voice in body


def test_the_judge_table_comes_from_the_plan_not_the_prose():
    """The plan is the validated boundary; the report must not restate it in the
    model's own words, or the two can disagree about what was decided."""
    body = render.render_brief(CONTEXT, _judgment(), PLAN, date="2026-08-31")
    judge = body[body.index("### Judge"):body.index("## ▎同行扫描")]

    assert "**cut**" in judge and "risk_rebalance" in judge
    assert "technical_breakdown + relative_strength" in judge
    assert "hold_and_watch" in judge


SECTOR_SCAN = {
    "sectors": [{
        "theme": "HK AI 大模型",
        "top_movers": [{"ticker": "09678", "name": "云知声", "pct": 22.0}],
        "self": [{"ticker": "00100", "pct": -4.51, "rank_text": "落后",
                  "attribution": "利好盘后才公布"}],
    }],
}


def test_the_sector_sweep_is_rendered_when_the_scan_exists():
    body = render.render_brief(CONTEXT, _judgment(), PLAN, date="2026-08-31",
                               sector_scan=SECTOR_SCAN)
    sector = body[body.index("## ▎板块全景"):body.index("## ▎大盘速读")]

    assert "09678" in sector and "落后" in sector
    assert "利好盘后才公布" in sector
    assert "板块内部分化。" in sector, "the model's read sits with the table"


def test_a_missing_sector_scan_still_publishes_the_read():
    """A day the search quota was spent still has to publish."""
    body = render.render_brief(CONTEXT, _judgment(), PLAN, date="2026-08-31")
    sector = body[body.index("## ▎板块全景"):body.index("## ▎大盘速读")]

    assert "板块内部分化。" in sector
    assert "|" not in sector, "no table when there is no scan"


def test_the_card_carries_the_actions_the_plan_holds():
    card = render.render_card(CONTEXT, _judgment(), PLAN, date="2026-08-31",
                              page_url="https://example.invalid/brief")

    assert "07226" in card and "6,200 股" in card
    assert "00100" in card and "hold_and_watch" in card
    assert card.rstrip().endswith("https://example.invalid/brief")


def test_a_non_numeric_level_is_printed_rather_than_raising():
    """Producer fields are occasionally text; the brief still has to go out."""
    plan = json.loads(json.dumps(PLAN))
    plan["watch_levels"] = {"next_nfp_date": "2026-09-04"}

    card = render.render_card(CONTEXT, _judgment(), plan, date="2026-08-31")

    assert "2026-09-04" in card


def test_rendering_from_a_workspace_writes_both_artifacts(tmp_path):
    tmp = tmp_path / "memory" / ".tmp"
    tmp.mkdir(parents=True)
    (tmp / "brief-context-2026-08-31.json").write_text(
        json.dumps(CONTEXT, ensure_ascii=False), encoding="utf-8")
    (tmp / "brief-judgment-2026-08-31.json").write_text(
        json.dumps(_judgment(), ensure_ascii=False), encoding="utf-8")
    (tmp_path / "memory" / "2026-08-31-plan.json").write_text(
        json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")

    issues, body = render.render_from_workspace(tmp_path, "2026-08-31")

    assert issues == []
    assert (tmp_path / "memory" / "2026-08-31-pre-open.md").read_text(
        encoding="utf-8") == body
    assert (tmp / "brief-card-2026-08-31.txt").exists()


def test_unreadable_inputs_report_instead_of_overwriting_the_report(tmp_path):
    """A renderer that cannot run must leave what is published alone."""
    (tmp_path / "memory").mkdir()
    existing = tmp_path / "memory" / "2026-08-31-pre-open.md"
    existing.write_text("previously published", encoding="utf-8")

    issues, body = render.render_from_workspace(tmp_path, "2026-08-31")

    assert body is None
    assert issues and "渲染跳过" in issues[0]
    assert existing.read_text(encoding="utf-8") == "previously published"
