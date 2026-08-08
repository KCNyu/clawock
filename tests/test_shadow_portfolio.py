import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import shadow_portfolio as shadow


DAY_1 = "2026-07-01"
DAY_2 = "2026-07-02"


def _holding(ticker, shares, *, lot_size=1):
    return {
        "ticker": ticker,
        "shares": shares,
        "lot_size": lot_size,
        "trades": [],
    }


def _portfolio(*, us_cash=0, us_holdings=(), hk_cash=0, hk_holdings=()):
    return {
        "portfolios": {
            "us_stocks": {
                "cash_usd": us_cash,
                "holdings": list(us_holdings),
            },
            "hk_stocks": {
                "cash_hkd": hk_cash,
                "holdings": list(hk_holdings),
            },
        }
    }


def _decision(
    decision_id,
    ticker,
    action,
    shares,
    *,
    leg="US",
    day=DAY_1,
    price=10,
    group=None,
):
    evaluation = {
        "triggered": True,
        "trigger_session": day,
    }
    if price is not None:
        evaluation.update({
            "execution_price": price,
            "fill_model": "daily_ohlc_trigger",
        })
    return {
        "decision_id": decision_id,
        "decision_group_id": group,
        "plan_date": day,
        "created_at": f"{day}T08:00:00+08:00",
        "leg": leg,
        "ticker": ticker,
        "action": action,
        "size": {"shares": shares},
        "evaluation": evaluation,
        "execution": {"status": "not_followed"},
    }


def _loaders(bars):
    def bar_loader(ticker, day):
        return (bars.get(ticker) or {}).get(day)

    def bar_map_loader(ticker):
        return bars.get(ticker) or {}

    return bar_loader, bar_map_loader


def _flat_bars(tickers, dates=(DAY_1, DAY_2), close=10):
    return {
        ticker: {day: {"close": close} for day in dates}
        for ticker in tickers
    }


def test_sell_is_capped_by_available_inventory():
    portfolio = _portfolio(us_holdings=[_holding("AAA", 5)])
    state = {"cash": 0.0, "inventory": {"AAA": 5}}
    decision = _decision("sell-too-many", "AAA", "cut", 9)
    fill = {"price": 10.0, "type": "ohlc_assumption", "model": "fixture"}

    result = shadow._execute_sell(state, decision, fill, portfolio)

    assert result["filled_shares"] == 5
    assert result["status"] == "partial_inventory_cap"
    assert state["inventory"]["AAA"] == 0
    assert all(qty >= 0 for qty in state["inventory"].values())


def test_buy_is_capped_by_affordable_cash():
    portfolio = _portfolio(us_cash=55, us_holdings=[_holding("AAA", 0)])
    state = {"cash": 55.0, "inventory": {}}
    decision = _decision("buy-too-many", "AAA", "add_on_breakout", 10)
    fill = {"price": 10.0, "type": "ohlc_assumption", "model": "fixture"}

    result = shadow._execute_buy(state, decision, fill, portfolio)

    assert result["filled_shares"] == 5
    assert result["status"] == "partial_cash_cap"
    assert state["cash"] == pytest.approx(5.0)
    assert state["cash"] >= 0


def test_swap_uses_only_sale_proceeds_and_derives_target_shares():
    portfolio = _portfolio(
        us_cash=1000,
        us_holdings=[_holding("AAA", 10), _holding("BBB", 0)],
    )
    state = {"cash": 1000.0, "inventory": {"AAA": 10}}
    sell = _decision("swap-sell", "AAA", "cut", 10, group="swap-1")
    buy = _decision(
        "swap-buy", "BBB", "add_on_breakout", 10, price=25, group="swap-1"
    )
    fills = {
        "swap-sell": {
            "price": 10.0,
            "type": "ohlc_assumption",
            "model": "fixture",
        },
        "swap-buy": {
            "price": 25.0,
            "type": "ohlc_assumption",
            "model": "fixture",
        },
    }

    legs = shadow._execute_swap_group(state, [sell, buy], fills, portfolio)

    assert [leg["filled_shares"] for leg in legs] == [10, 4]
    assert legs[1]["filled_shares"] != legs[0]["filled_shares"]
    assert state["cash"] == pytest.approx(1000.0)
    assert state["inventory"] == {"AAA": 0, "BBB": 4}


def test_paired_swap_is_serialized_as_one_group_not_two_successes():
    portfolio = _portfolio(
        us_cash=1000,
        us_holdings=[_holding("AAA", 10), _holding("BBB", 0)],
    )
    decisions = [
        _decision("swap-sell", "AAA", "cut", 10, group="swap-1"),
        _decision(
            "swap-buy", "BBB", "add_on_breakout", 10, price=25, group="swap-1"
        ),
    ]
    bars = _flat_bars(["AAA"], dates=(DAY_1,), close=10)
    bars["BBB"] = {DAY_1: {"close": 25}}
    bar_loader, bar_map_loader = _loaders(bars)

    result = shadow.simulate_leg(
        portfolio,
        decisions,
        "US",
        bar_loader=bar_loader,
        bar_map_loader=bar_map_loader,
        matched={},
    )

    assert result["counts"]["decision_groups"] == 1
    assert result["counts"]["paired_swap_groups"] == 1
    assert len(result["events"]) == 1
    assert result["events"][0]["kind"] == "paired_swap"
    assert len(result["events"][0]["legs"]) == 2


def test_build_keeps_usd_and_hkd_curves_separate_without_combination():
    portfolio = _portfolio(
        us_holdings=[_holding("AAA", 1)],
        hk_holdings=[_holding("HK1", 1, lot_size=1)],
    )
    decisions = [
        _decision("us-sell", "AAA", "cut", 1),
        _decision("hk-sell", "HK1", "cut", 1, leg="HK", price=20),
    ]
    bars = {
        "AAA": {DAY_1: {"close": 10}},
        "HK1": {DAY_1: {"close": 20}},
    }
    bar_loader, bar_map_loader = _loaders(bars)

    result = shadow.build_shadow_portfolio(
        portfolio,
        decisions,
        as_of="2026-07-02T00:00:00+08:00",
        bar_loader=bar_loader,
        bar_map_loader=bar_map_loader,
        matched={},
    )

    assert set(result["curves"]) == {"USD", "HKD"}
    assert set(result["cumulative_diff"]) == {"USD", "HKD"}
    assert result["fx_policy"]["combined_curve"] is False
    assert "combined" not in result["curves"]
    assert "combined" not in result["cumulative_diff"]


def test_buy_hold_uses_same_seed_and_only_canonical_close_marks():
    portfolio = _portfolio(
        us_cash=100,
        us_holdings=[_holding("AAA", 2), _holding("BBB", 0)],
    )
    decision = _decision("no-inventory", "BBB", "cut", 1)
    bars = {
        "AAA": {
            DAY_1: {"close": 11},
            DAY_2: {"close": 13},
        },
        "BBB": {
            DAY_1: {"close": 7},
            DAY_2: {"close": 8},
        },
    }
    bar_loader, bar_map_loader = _loaders(bars)

    result = shadow.simulate_leg(
        portfolio,
        [decision],
        "US",
        bar_loader=bar_loader,
        bar_map_loader=bar_map_loader,
        matched={},
    )

    assert result["initial"]["cash"] == 100
    assert result["initial"]["inventory"] == {"AAA": 2}
    assert [point["buy_and_hold"] for point in result["curve"]] == [122, 126]
    assert result["events"][0]["status"] == "skipped"


def test_mark_requires_exact_day_canonical_bar_for_every_holding():
    state = {"cash": 50.0, "inventory": {"AAA": 2, "BBB": 3}}
    bars = {"AAA": {DAY_1: {"close": 10}}}
    bar_loader, _ = _loaders(bars)

    value, missing = shadow._mark(state, DAY_1, bar_loader)

    assert value is None
    assert missing == ["BBB"]


def test_fill_counts_separate_real_assumed_fallback_and_skipped():
    portfolio = _portfolio(
        us_cash=100,
        us_holdings=[
            _holding("AAA", 2),
            _holding("BBB", 0),
            _holding("CCC", 0),
            _holding("DDD", 0),
        ],
    )
    decisions = [
        _decision("real-sell", "AAA", "cut", 1, day="2026-07-01"),
        _decision(
            "ohlc-buy", "BBB", "add_on_breakout", 1,
            day="2026-07-02", price=20,
        ),
        _decision(
            "close-buy", "CCC", "add_on_breakout", 1,
            day="2026-07-03", price=None,
        ),
        _decision("skip-sell", "DDD", "cut", 1, day="2026-07-04"),
    ]
    days = [f"2026-07-0{i}" for i in range(1, 5)]
    bars = {
        ticker: {
            day: {"close": close}
            for day in days
        }
        for ticker, close in {"AAA": 10, "BBB": 20, "CCC": 30, "DDD": 40}.items()
    }
    bar_loader, bar_map_loader = _loaders(bars)

    result = shadow.simulate_leg(
        portfolio,
        decisions,
        "US",
        bar_loader=bar_loader,
        bar_map_loader=bar_map_loader,
        matched={"real-sell": {"price": 9.5}},
    )
    counts = result["counts"]["fill_types"]

    assert counts == {
        "real_trade": 1,
        "ohlc_assumption": 1,
        "canonical_close_fallback": 1,
        "skipped": 1,
    }


def test_cumulative_diff_is_followed_minus_buy_hold_with_both_signs():
    portfolio = _portfolio(us_holdings=[_holding("AAA", 10)])
    decision = _decision("sell", "AAA", "cut", 10, price=10)

    def final_diff(day_2_close):
        bars = {
            "AAA": {
                DAY_1: {"close": 10},
                DAY_2: {"close": day_2_close},
            }
        }
        bar_loader, bar_map_loader = _loaders(bars)
        result = shadow.simulate_leg(
            deepcopy(portfolio),
            [deepcopy(decision)],
            "US",
            bar_loader=bar_loader,
            bar_map_loader=bar_map_loader,
            matched={},
        )
        return result["cumulative_diff"]

    assert final_diff(5) == 50
    assert final_diff(15) == -50


# ── attribution: the gap has to say *why*, not just *how much* ──────────────

def _leg(ticker, direction, shares, notional, *, driven_by="technical",
         execution_status="not_followed"):
    return {
        "ticker": ticker, "direction": direction, "filled_shares": shares,
        "notional": notional, "driven_by": driven_by,
        "execution_status": execution_status,
    }


def test_attribution_reproduces_the_published_gap_exactly():
    """The identity is the point: both books start from the same seed and only
    the followed book trades, so the gap IS the sum of the fills."""
    portfolio = _portfolio(us_cash=200, us_holdings=[_holding("AAA", 10)])
    decisions = [_decision("sell", "AAA", "cut", 10, price=10)]
    bars = {"AAA": {DAY_1: {"close": 10}, DAY_2: {"close": 5}}}
    bar_loader, bar_map_loader = _loaders(bars)

    result = shadow.simulate_leg(
        deepcopy(portfolio), decisions, "US",
        bar_loader=bar_loader, bar_map_loader=bar_map_loader, matched={})

    identity = result["attribution"]["identity"]
    assert identity["closes"] is True
    assert identity["residual"] == 0.0
    assert identity["sum_of_contributions"] == result["cumulative_diff"] == 50.0


def test_selling_before_a_fall_contributes_positively_and_a_buy_negatively():
    sold = shadow.attribute_fills(
        [{"legs": [_leg("AAA", "sell", 10, 100.0)]}], {"AAA": 5.0})
    bought = shadow.attribute_fills(
        [{"legs": [_leg("AAA", "buy", 10, 100.0)]}], {"AAA": 5.0})

    # Banked 100, gave up stock now worth 50.
    assert sold["total_contribution"] == 50.0
    # Paid 100 for stock now worth 50.
    assert bought["total_contribution"] == -50.0


def test_buckets_sum_to_the_total_on_every_dimension():
    events = [{"legs": [
        _leg("AAA", "sell", 10, 100.0, driven_by="risk_rule",
             execution_status="followed"),
        _leg("BBB", "buy", 4, 80.0, driven_by="technical",
             execution_status="not_followed"),
    ]}]

    out = shadow.attribute_fills(events, {"AAA": 5.0, "BBB": 30.0})

    total = out["total_contribution"]
    for dimension in ("by_driver", "by_direction", "by_execution_status"):
        assert sum(out[dimension].values()) == pytest.approx(total), dimension
    assert sum(row["contribution"] for row in out["by_ticker"]) == pytest.approx(total)


def test_perturbing_one_fill_moves_only_its_own_buckets():
    base = [{"legs": [
        _leg("AAA", "sell", 10, 100.0, driven_by="risk_rule"),
        _leg("BBB", "sell", 10, 100.0, driven_by="technical"),
    ]}]
    prices = {"AAA": 5.0, "BBB": 5.0}

    before = shadow.attribute_fills(deepcopy(base), prices)
    moved = deepcopy(base)
    moved[0]["legs"][0]["notional"] = 130.0
    after = shadow.attribute_fills(moved, prices)

    assert after["by_driver"]["risk_rule"] == before["by_driver"]["risk_rule"] + 30
    assert after["by_driver"]["technical"] == before["by_driver"]["technical"]
    assert after["total_contribution"] == before["total_contribution"] + 30


def test_an_unpriced_ticker_breaks_the_identity_instead_of_contributing_zero():
    """A silent zero would let the buckets look complete while missing a leg."""
    events = [{"legs": [_leg("AAA", "sell", 10, 100.0),
                        _leg("GONE", "sell", 10, 500.0)]}]

    out = shadow.attribute_fills(events, {"AAA": 5.0})
    identity = shadow._attribution_identity(out, cumulative_diff=50.0)

    assert out["unpriced_tickers"] == ["GONE"]
    # The unpriced leg contributes nothing at all — not a fabricated mark of 0,
    # which would have booked its whole notional as if the stock went to zero.
    assert out["total_contribution"] == 50.0
    assert [row["ticker"] for row in out["by_ticker"]] == ["AAA"]
    assert identity["closes"] is False
    assert "GONE" in identity["reason"]


def test_turnover_counts_gross_notional_on_both_sides():
    events = [{"legs": [_leg("AAA", "sell", 10, 100.0),
                        _leg("BBB", "buy", 2, 40.0)]}]

    turnover = shadow.attribute_fills(events, {"AAA": 5.0, "BBB": 30.0})["turnover"]

    assert turnover == {"sell_notional": 100.0, "buy_notional": 40.0,
                        "gross_notional": 140.0}


def test_unfilled_legs_contribute_nothing_and_are_not_counted_as_turnover():
    events = [{"legs": [
        {"ticker": "AAA", "direction": "sell", "filled_shares": 0,
         "status": "skipped_no_inventory", "driven_by": "risk_rule"},
    ]}]

    out = shadow.attribute_fills(events, {"AAA": 5.0})

    assert out["filled_legs"] == 0
    assert out["total_contribution"] == 0.0
    assert out["turnover"]["gross_notional"] == 0.0


def test_attribution_is_skipped_with_a_reason_when_nothing_was_published():
    out = shadow.attribute_fills([], {})

    identity = shadow._attribution_identity(out, cumulative_diff=None)

    assert identity["closes"] is None
    assert "no published final point" in identity["reason"]


def test_every_fill_carries_the_provenance_attribution_needs():
    """Without driven_by and execution_status a leg is an anonymous cash move
    and the sidecar cannot say which kind of rule earned the gap."""
    portfolio = _portfolio(us_holdings=[_holding("AAA", 10)])
    state = {"cash": 0.0, "inventory": {"AAA": 10}}
    decision = _decision("sell-1", "AAA", "cut", 10)
    decision["driven_by"] = "risk_rule"
    fill = {"price": 10.0, "type": "ohlc_assumption", "model": "fixture"}

    leg = shadow._execute_sell(state, decision, fill, portfolio)

    assert leg["driven_by"] == "risk_rule"
    assert leg["execution_status"] == "not_followed"
    # decision_id is intentionally absent: 7KB across ~200 legs with no consumer.
    assert "decision_id" not in leg


def test_a_decision_without_a_driver_is_labelled_unknown_not_dropped():
    leg = shadow._leg_provenance({"decision_id": "x"})

    assert leg["driven_by"] == "unknown"
    assert leg["execution_status"] == "unknown"


def test_expected_sessions_disclose_missing_marks_and_emit_curve_gaps():
    days = [
        "2026-07-13",
        "2026-07-14",
        "2026-07-15",
        "2026-07-16",
    ]
    portfolio = _portfolio(
        us_holdings=[_holding("AAA", 1), _holding("BBB", 1)],
    )
    decisions = [
        _decision("sell-aaa", "AAA", "cut", 1, day=days[0], price=10),
    ]
    bars = {
        "AAA": {
            days[0]: {"close": 10},
            days[1]: {"close": 11},  # BBB missing: partial coverage
            days[3]: {"close": 12},
        },
        "BBB": {
            days[0]: {"close": 20},
            # Both required books have no usable bar on 07-15.
            days[3]: {"close": 22},
        },
    }
    bar_loader, bar_map_loader = _loaders(bars)

    result = shadow.build_shadow_portfolio(
        portfolio,
        decisions,
        as_of=days[-1],
        bar_loader=bar_loader,
        bar_map_loader=bar_map_loader,
        matched={},
    )
    usd = result["curves"]["USD"]

    assert usd["mark_coverage"]["expected_sessions"] == 4
    assert usd["mark_coverage"]["skipped_dates"] == [
        {
            "date": days[1],
            "reason": "partial_coverage",
            "tickers": ["BBB"],
        },
        {
            "date": days[2],
            "reason": "no_bar",
            "tickers": ["AAA", "BBB"],
        },
    ]
    assert [point["date"] for point in usd["curve"]] == days
    assert usd["curve"][1]["followed_sim"] is None
    assert usd["curve"][1]["buy_and_hold"] is None
    assert usd["curve"][1]["gap_reason"] == "partial_coverage"
    assert usd["curve"][2]["followed_sim"] is None
    assert usd["curve"][2]["gap_reason"] == "no_bar"
    assert usd["curve"][3]["followed_sim"] is not None


def test_shadow_frontend_fails_closed_and_discloses_mark_gaps():
    html = (ROOT / "site/index.html").read_text(encoding="utf-8") + "".join(
        (ROOT / "site" / "assets" / "js" / name).read_text(encoding="utf-8")
        for name in (
            "dashboard.core.js",
            "dashboard.charts.js",
            "dashboard.render.js",
            "dashboard.ui.js",
        )
    )

    assert 'sidecar && sidecar.computed === false' in html
    assert 'summary.textContent = "⚠️ 政策模拟本次无法计算"' in html
    assert 'id="shadow-coverage-note"' in html
    assert "个市场交易日缺行情未计价" in html
    assert "connectNulls: false" in html
