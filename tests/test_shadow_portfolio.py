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
