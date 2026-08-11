"""Prose may quote the context. It may not compute.

On 2026-07-27 two reports passed every existing check while carrying numbers the
context never contained: a HK$1.5-2万 loss estimate for an exposure whose actual
-2% impact was about HK$1,000, and a "+0.3~-0.4%" range for two ETFs the context
put at +0.3% each (issue #120).

The gate's limits are asserted here as deliberately as its catches. It sees
magnitudes absent from the context; it cannot see a real number attached to the
wrong subject, and a test that pretended otherwise would be the more dangerous
kind of green.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


WS = Path(__file__).resolve().parents[1]
INSTANCE_SRC = str(WS / "instances" / "kcnyu" / "src")

# The 09:30 港股开盘报告 context, reduced to the fields prose quotes from.
CTX = {
    "raw_wechat_block": (
        "🇭🇰 港股盯盘 | 07/27 09:33 HKT\n"
        "  恒指 25,031 ▲0.27%  恒科 4,654 ▲0.52%\n"
        "📊 市值 HK$49,881 | 浮盈 -50,796 (-50.5%) | 今日 +314\n"
        "| 07226 | 6200 | 4.36 | 3.34 | +0.7% | -23.4% | -6,331 |\n"
        "| 03033 | 1000 | 5.14 | 4.56 | +0.3% | -11.3% |   -582 |"
    ),
    "peer_scan": {"03032": {"self_pct_1d": 0.35, "listed_peers": ["03033 +0.40%"]}},
    "plan_context": {"open": [{"ticker": "07226", "shares": 1000, "pct": 16.1}]},
}


@pytest.fixture(scope="module")
def hc():
    if INSTANCE_SRC not in sys.path:
        sys.path.insert(0, INSTANCE_SRC)
    return pytest.importorskip("clawock.harness.validation")


def test_the_shipped_loss_estimate_is_caught(hc):
    prose = "一旦恒科掉头 -2%，叠加 07226 杠杆放大效应日内可能再伤 1.5-2 万 HK$。"
    assert hc.check_numeric_claims(prose, CTX)


def test_the_shipped_impossible_range_is_caught(hc):
    prose = "03032 / 03033 两支恒科 ETF 同步 +0.3~-0.4%，跟踪误差正常。"
    issues = hc.check_numeric_claims(prose, CTX)
    assert issues and "区间自相矛盾" in issues[0]


def test_quoting_the_data_block_passes(hc):
    prose = "市值 HK$49,881、浮盈 -50,796，07226 持有 6200 股，03033 现价 4.56。"
    assert hc.check_numeric_claims(prose, CTX) == []


def test_quoting_the_plan_size_passes(hc):
    # plan_context is what the prose is supposed to quote a swap size from.
    assert hc.check_numeric_claims("07226 纪律 swap 1000 股仍挂着。", CTX) == []


def test_wan_notation_matches_the_same_number_in_the_context(hc):
    # 2 万 and 20,000 are the same claim. Without the magnitude conversion the
    # gate would flag every correctly-quoted round figure kcn's reports use.
    ctx = dict(CTX, plan_context={"open": [{"ticker": "07226", "shares": 20000}]})
    assert hc.check_numeric_claims("07226 共 2 万股。", ctx) == []
    assert hc.check_numeric_claims("敞口约 2 万 HK$。", ctx) == []


def test_percentages_outside_a_range_are_not_policed(hc):
    # "if HSTECH fell 2%" is a hypothesis, not a claim about today's data. Policing
    # bare percentages would flag every conditional sentence in every report.
    assert hc.check_numeric_claims("若恒科再跌 2%，杠杆仓位承压。", CTX) == []


def test_prices_without_a_unit_are_not_policed(hc):
    assert hc.check_numeric_claims("07226 若跌破 4.00 支撑位考虑减仓。", CTX) == []


def test_a_well_formed_range_still_requires_context_provenance(hc):
    issue = hc.check_numeric_claims("同业今日在 0.2~0.5% 之间。", CTX)
    assert issue and "context 里没有的数字" in issue[0]


def test_gate_emits_at_most_one_issue(hc):
    # Both postflights escalate to `fail` (not delivered) past a small issue count.
    # A chatty gate would turn a cosmetic problem into a missed report.
    prose = ("再伤 1.5-2 万 HK$，另计 999,999 股，还有 88,888 股，"
             "以及 77,777 股；区间 0.3~-0.4% 与 5~1%。")
    assert len(hc.check_numeric_claims(prose, CTX)) == 1


def _gate_issue(hc):
    return hc.check_numeric_claims("再伤 1.5-2 万 HK$。", CTX)[0]


@pytest.mark.parametrize("module_name", ["report_postflight", "intraday_postflight"])
def test_gate_cannot_turn_a_delivered_report_into_a_blocked_one(hc, module_name):
    """The severity property, asserted where it actually bites.

    The first version of this gate emitted a plain issue, which still counted
    toward `warn_max`. Two unrelated soft issues plus the gate categorised as
    `fail` — not delivered — while the same two without it were `warn`. An
    advisory line must never be able to cost kcn a report.
    """
    if INSTANCE_SRC not in sys.path:
        sys.path.insert(0, INSTANCE_SRC)
    post = importlib.import_module(f'clawock_kcnyu.harness.{module_name}')
    gate = _gate_issue(hc)
    soft = "报告长度 3200 字 > 3000 软上限 (warn)"
    thin = '"▎我的看法" 段仅 40 字，太敷衍'

    assert post.categorize([gate]) == "warn"
    for existing in ([soft], [soft, thin], [soft, thin, thin]):
        assert post.categorize(existing + [gate]) == post.categorize(existing), existing


def test_advisory_never_masks_a_real_failure(hc):
    if INSTANCE_SRC not in sys.path:
        sys.path.insert(0, INSTANCE_SRC)
    post = importlib.import_module('clawock_kcnyu.harness.intraday_postflight')
    # A critical issue must still fail with the advisory line alongside it.
    assert post.categorize(['缺段标记 "▎我的看法"', _gate_issue(hc)]) == "fail"
    # And a genuine over-budget pile must still fail.
    real = ["报告长度 3200 字 > 3000 软上限 (warn)", "段仅 40 字，太敷衍",
            "段仅 40 字，太敷衍", "报告长度 3200 字 > 3000 软上限 (warn)"]
    assert post.categorize(real + [_gate_issue(hc)]) == "fail"


def test_known_blind_spot_a_real_number_on_the_wrong_subject(hc):
    """The 10:05 slot's actual error, asserted as NOT caught.

    "07226 + 03033 各 1000 股" quotes a share count that exists — 03033 holds
    1000 — it is simply not 07226's. No numeral test can see that; the defence is
    plan_context (issue #119) plus the SKILL rule against restating position
    sizes. This test exists so nobody later reads the gate as covering it.
    """
    prose = "portfolio 仍挂着 07226 + 03033 各 1000 股。"
    assert hc.check_numeric_claims(prose, CTX) == []


@pytest.mark.parametrize("module_name", ["report_postflight", "intraday_postflight"])
def test_both_postflights_run_the_gate(module_name):
    if INSTANCE_SRC not in sys.path:
        sys.path.insert(0, INSTANCE_SRC)
    module = importlib.import_module(f'clawock_kcnyu.harness.{module_name}')
    prose = (
        "🇭🇰 港股盯盘 | 07/27 09:33 HKT\n▎我的看法\n"
        "恒指 25,031、恒科 4,654，07226 现价 3.34 是纪律 swap 标的，今日不追高；"
        "03033 现价 4.56 用来承接敞口，整体仓位不动，等成交回报再评估下一步。"
        "日内可能再伤 1.5-2 万 HK$。"
    )
    ctx = dict(CTX, needs_risk_section=False, should_alert=False, market="hk")
    issues = module.validate(prose, ctx) if module_name == "intraday_postflight" \
        else module.validate(prose, ctx, prose_only=True, model_text=prose)
    assert any("不许心算" in issue for issue in issues), issues


@pytest.mark.parametrize("skill", ["hk-stock-analysis", "us-stock-analysis"])
def test_skill_states_the_rule_the_gate_enforces(skill):
    # The gate is warn-only, so the prompt is the layer that actually prevents the
    # error. A skill that never states the rule leaves the gate as decoration.
    text = (WS / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "数字铁律" in text
    assert "check_numeric_claims" in text, "prompt does not name the check it faces"
    assert "不心算" in text or "不换算" in text


def test_price_levels_are_not_treated_as_book_amounts(hc):
    # Caught by the existing report-assembly suite: US technical prose writes
    # levels with the currency symbol. Flagging "$65" would make the gate noise on
    # every ordinary 技术面 line.
    assert hc.check_numeric_claims("跌破 $65，下一支撑 $60。", CTX) == []


def test_book_scale_amounts_are_still_checked(hc):
    assert hc.check_numeric_claims("日内可能再伤 HK$18,000。", CTX)


def test_a_numeric_ticker_followed_by_a_negative_percent_is_not_a_range(hc):
    """HK tickers are numeric, so the ASCII hyphen cannot be a range separator.

    Measured against 23 real sent reports: `07226 -3.5%` parsed as a range from
    07226 to 3.5 and was every single false positive the gate produced. The
    observed real defect used `~` ("+0.3~-0.4%"), which still trips.
    """
    ctx = dict(CTX, exact_unit_literals=["-3.5%", "-2.0%", "-2.04%", "2x", "-3.9%"])
    assert hc.check_numeric_claims("07226 -3.5% 领跌，03032 -2.0%。", ctx) == []
    assert hc.check_numeric_claims("恒科 -2.04% → 2x 的 07226 放大到 -3.9%。", ctx) == []
    assert hc.check_numeric_claims("两支 ETF 同步 +0.3~-0.4%。", CTX)


def test_a_backwards_range_is_still_caught(hc):
    assert hc.check_numeric_claims("波动在 5~1% 之间。", CTX)
    assert hc.check_numeric_claims("波动在 1~5% 之间。", CTX)


def test_market_units_require_unit_specific_context_provenance(hc):
    ctx = {
        "move_pct": -1.44,
        "divergence_signal": "gap +9.0pp",
        "instrument": "2x HSTECH",
        "rationale": "z+2.1σ EXTREME",
        # Same digits under another unit must not authorize a calculated multiple.
        "peer_pct": 2.3,
    }
    exact = "07226 -1.44%，跑输同业 9pp；产品 2× 杠杆，信号 2.1σ。"
    assert hc.check_numeric_claims(exact, ctx) == []

    issue = hc.check_numeric_claims("07226 -1.44%，杠杆放大约 2.3x。", ctx)
    assert len(issue) == 1
    assert "2.3x" in issue[0] and hc.ADVISORY_MARK in issue[0]


def test_absent_market_units_stay_one_advisory(hc):
    issue = hc.check_numeric_claims("今日 +8.8%，背离 7pp，放大 3x，偏离 4σ。", CTX)
    assert len(issue) == 1
    assert all(label in issue[0] for label in ("+8.8%", "7pp", "3x", "4σ"))
