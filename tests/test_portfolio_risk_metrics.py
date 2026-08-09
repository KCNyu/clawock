import pytest


np = pytest.importorskip("numpy")

import json
import math
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
from clawock.portfolio import risk


def _utc_epoch(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def test_daily_returns_are_simple_close_to_close_returns():
    closes = np.array([100.0, 110.0, 99.0, 99.0])

    returns = risk.daily_returns(closes)

    assert len(returns) == len(closes) - 1
    assert returns == pytest.approx([0.10, -0.10, 0.0])


def test_max_drawdown_matches_hand_computed_peak_to_trough():
    # Wealth path: 1.10 -> 0.88 -> 1.10 -> 0.99.  The trough is 20% below
    # the running peak; the later 10% drawdown is smaller.
    returns = np.array([0.10, -0.20, 0.25, -0.10])

    assert risk.max_drawdown(returns) == pytest.approx(-0.20)


def test_max_drawdown_is_zero_for_monotonically_rising_wealth():
    assert risk.max_drawdown(np.array([0.01, 0.02, 0.03])) == pytest.approx(0.0)


def test_max_drawdown_counts_a_first_period_loss_from_initial_wealth():
    # Regression: the wealth path is anchored to the 1.0 baseline, so a
    # drawdown that starts on the very first period is captured (was reported 0).
    assert risk.max_drawdown(np.array([-0.20, 0.10])) == pytest.approx(-0.20)


def test_sharpe_annualizes_the_mean_and_subtracts_the_risk_free_rate():
    returns = np.array([0.01, 0.01, 0.01, 0.01, 0.01])
    expected = (0.01 * risk.TRADING_DAYS - risk.RISK_FREE_ANNUAL) / 0.20

    assert expected == pytest.approx(12.375)
    assert risk.sharpe(returns, 0.20) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("returns", "vol_annual"),
    [(np.array([]), 0.20), (np.array([0.01, -0.01]), 0.0)],
)
def test_sharpe_guard_returns_zero_for_empty_returns_or_zero_volatility(
    returns, vol_annual
):
    assert risk.sharpe(returns, vol_annual) == 0.0


def test_beta_obeys_identity_and_linear_scaling():
    benchmark = np.array([-0.02, 0.01, 0.03, -0.01, 0.02, 0.04])

    assert risk.beta(benchmark, benchmark) == pytest.approx(1.0)
    assert risk.beta(2.0 * benchmark, benchmark) == pytest.approx(2.0)


def test_beta_returns_none_for_a_zero_variance_benchmark():
    portfolio = np.array([-0.02, 0.01, 0.03, -0.01, 0.02, 0.04])
    flat_benchmark = np.zeros(portfolio.size)

    assert risk.beta(portfolio, flat_benchmark) is None


@pytest.mark.parametrize(
    ("ticker", "expected"),
    [("00100", "0100.HK"), ("02208", "2208.HK"), ("07226", "7226.HK")],
)
def test_hk_yahoo_symbol_uses_yahoos_four_digit_hk_form(ticker, expected):
    assert risk.hk_yahoo_symbol(ticker) == expected


def test_parse_tencent_extracts_utc_dates_and_close_prices_from_qfqday():
    payload = {
        "code": 0,
        "msg": "",
        "data": {
            "hk00100": {
                "qfqday": [
                    ["2026-07-14", "285.0", "291.4", "295.0", "282.0", "123456"],
                    ["2026-07-15", "292.0", "297.4", "301.0", "289.0", "234567"],
                ],
                "qt": {"hk00100": ["100", "MINIMAX-W"]},
            }
        },
    }

    assert risk._parse_tencent("hk00100", payload) == [
        (_utc_epoch("2026-07-14"), 291.4),
        (_utc_epoch("2026-07-15"), 297.4),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": {"hk00100": {"qfqday": [["2026-07-15", "292.0"]]}}},
        {"data": {"hk00100": {"qfqday": [["bad-date"], ["2026-07-15", "292.0"]]}}},
    ],
)
def test_parse_tencent_returns_none_for_missing_or_short_rows(payload):
    assert risk._parse_tencent("hk00100", payload) is None


def test_active_holdings_filters_nonpositive_shares_and_maps_leverage_and_symbols():
    portfolio = {
        "portfolios": {
            "growth_book": {
                "holdings": [
                    {"ticker": "PLTU", "shares": 5, "current_value": 120.0},
                    {"ticker": "AAPL", "shares": 0, "current_value": 200.0},
                    {"ticker": "MSFT", "shares": -1, "current_value": 300.0},
                ]
            },
            "hstech_book": {
                "holdings": [
                    {"ticker": "07226", "shares": 10, "current_value": 400.0},
                    {"ticker": "00100", "shares": 0, "current_value": 500.0},
                ]
            },
        }
    }

    assert risk.active_holdings(portfolio, "growth_book") == [
        {
            "ticker": "PLTU",
            "current_value": 120.0,
            "current_price": 24.0,
            "shares": 5.0,
            "trades": [],
            "leverage": 2,
            "yahoo_symbol": "PLTU",
        }
    ]
    assert risk.active_holdings(portfolio, "hstech_book") == [
        {
            "ticker": "07226",
            "current_value": 400.0,
            "current_price": 40.0,
            "shares": 10.0,
            "trades": [],
            "leverage": 2,
            "yahoo_symbol": "7226.HK",
        }
    ]


@pytest.mark.parametrize(
    "portfolio",
    [
        {},
        {"portfolios": {"us_stocks": {"holdings": []}}},
        {
            "portfolios": {
                "us_stocks": {
                    "holdings": [
                        {"ticker": "AAPL", "shares": 0, "current_value": 100.0}
                    ]
                }
            }
        },
    ],
)
def test_active_holdings_returns_empty_for_missing_empty_or_all_zero_buckets(portfolio):
    assert risk.active_holdings(portfolio, "us_stocks") == []


def test_risk_book_config_is_explicit_and_distinct(tmp_path):
    path = tmp_path / "portfolio-derivations.json"
    path.write_text(
        '{"risk_books":{"us":{"portfolio_key":"growth"},'
        '"hk":{"portfolio_key":"hstech"}}}')
    assert risk.load_risk_config(path) == {"us": "growth", "hk": "hstech"}

    path.write_text(
        '{"risk_books":{"us":{"portfolio_key":"same"},'
        '"hk":{"portfolio_key":"same"}}}')
    with pytest.raises(ValueError, match="distinct"):
        risk.load_risk_config(path)


def test_align_to_dates_keeps_only_the_sorted_date_intersection():
    series = {
        "AAA": [
            (_utc_epoch("2026-07-14"), 10.0),
            (_utc_epoch("2026-07-15"), 11.0),
            (_utc_epoch("2026-07-16"), 12.0),
        ],
        "BBB": [
            (_utc_epoch("2026-07-13"), 20.0),
            (_utc_epoch("2026-07-15"), 21.0),
            (_utc_epoch("2026-07-16"), 22.0),
        ],
    }

    dates, aligned = risk.align_to_dates(series)

    assert dates == ["2026-07-15", "2026-07-16"]
    assert aligned["AAA"] == pytest.approx([11.0, 12.0])
    assert aligned["BBB"] == pytest.approx([21.0, 22.0])


def test_compute_leverage_is_value_weighted_after_currency_conversion():
    holdings = {
        "us": [
            {"current_value": 100.0, "leverage": 1},
            {"current_value": 100.0, "leverage": 3},
        ],
        "hk": [{"current_value": 800.0, "leverage": 1}],
    }

    # At HKD->USD 0.125, the HK leg is USD 100.  Total capital is USD 300;
    # leveraged exposure is 100*1 + 100*3 + 800*0.125*1 = USD 500.
    result = risk.compute_leverage(holdings, fx_hkd_to_usd=0.125)

    assert result == {
        "us_leverage_factor_avg": 2.0,
        "hk_leverage_factor_avg": 1.0,
        "combined_avg": 1.6667,
        "margin_at_risk_pct": 16.6667,
    }


def test_compute_leverage_returns_zeroes_for_an_empty_book():
    assert risk.compute_leverage({"us": [], "hk": []}, fx_hkd_to_usd=0.125) == {
        "us_leverage_factor_avg": 0.0,
        "hk_leverage_factor_avg": 0.0,
        "combined_avg": 0.0,
        "margin_at_risk_pct": 0.0,
    }


def test_build_alerts_emits_each_documented_strict_threshold_breach():
    us = {"beta_spx": 3.1}
    combined = {
        "vol_30d_annualized": 0.51,
        "max_dd_30d": -0.11,
        "sharpe_30d": -0.01,
    }
    leverage = {"combined_avg": 2.1}

    alerts = risk.build_alerts(us, None, combined, leverage)

    assert [(alert["type"], alert["severity"]) for alert in alerts] == [
        ("high_beta", "high"),
        ("high_vol", "high"),
        ("deep_dd", "medium"),
        ("high_leverage", "high"),
        ("negative_sharpe", "medium"),
    ]


def test_build_alerts_does_not_fire_at_the_strict_threshold_boundaries():
    us = {"beta_spx": 3.0}
    combined = {
        "vol_30d_annualized": 0.50,
        "max_dd_30d": -0.10,
        "sharpe_30d": 0.0,
    }
    leverage = {"combined_avg": 2.0}

    assert risk.build_alerts(us, None, combined, leverage) == []


def test_dynamic_stream_does_not_let_a_new_listing_truncate_established_names():
    holdings = [
        {
            "ticker": "OLD",
            "shares": 10.0,
            "current_value": 1300.0,
            "current_price": 130.0,
            "trades": [],
        },
        {
            "ticker": "NEW",
            "shares": 5.0,
            "current_value": 250.0,
            "current_price": 50.0,
            "trades": [{"date": "2026-01-25", "action": "buy", "shares": 5}],
        },
    ]
    old = [(_utc_epoch(f"2026-01-{day:02d}"), 100.0 + day)
           for day in range(1, 32)]
    new = [(_utc_epoch(f"2026-01-{day:02d}"), 40.0 + day)
           for day in range(25, 32)]

    stream = risk.build_dynamic_return_stream(
        holdings, {"OLD": old, "NEW": new}
    )

    assert len(stream["return_by_date"]) == 30
    assert min(stream["coverage_by_date"].values()) == pytest.approx(1.0)


def test_dynamic_weights_reverse_later_trades_instead_of_using_current_weight():
    holding = {
        "ticker": "AAA",
        "shares": 5.0,
        "current_value": 100.0,
        "current_price": 20.0,
        "trades": [{"date": "2026-01-03", "action": "sell", "shares": 5}],
    }

    assert risk._shares_on(holding, "2026-01-02") == 10.0
    assert risk._shares_on(holding, "2026-01-03") == 5.0


def test_alert_thresholds_are_withheld_when_window_is_not_eligible():
    us = {"beta_spx": 4.0, "threshold_eligible": False, "n_returns": 9,
          "threshold_min_returns": 20}
    combined = {
        "vol_30d_annualized": 0.9,
        "max_dd_30d": -0.3,
        "sharpe_30d": -4.0,
        "threshold_eligible": False,
    }

    alerts = risk.build_alerts(us, None, combined, {"combined_avg": 1.0})

    assert [a["type"] for a in alerts] == ["insufficient_observations"]


def test_one_non_finite_return_does_not_poison_the_whole_window():
    """np.std over an array holding a single nan returns nan, so vol, drawdown,
    Sharpe and expected shortfall would all go non-finite together — the card
    reads as broken rather than as missing. The bad date is dropped and named."""
    dates = [f"2026-01-{day:02d}" for day in range(1, 26)]
    # Alternating signs so volatility is genuinely non-zero: a flat series would
    # make Sharpe None for an unrelated reason and hide what is under test.
    returns = {d: (0.01 if i % 2 else -0.006) for i, d in enumerate(dates)}
    returns["2026-01-10"] = float("inf")
    returns["2026-01-11"] = None  # a junk value must be excluded, not crash
    coverage = {d: 1.0 for d in dates}

    stats = risk._stream_stats(returns, coverage)

    assert stats["missingness"]["excluded_non_finite_dates"] == [
        "2026-01-10", "2026-01-11"]
    assert stats["n_returns"] == len(dates) - 2
    for key in ("vol_30d_annualized", "max_dd_30d", "sharpe_30d",
                "expected_shortfall_95", "ewma_vol_annualized"):
        value = stats[key]
        assert value is not None, f"{key} was dropped instead of computed"
        assert math.isfinite(value), f"{key} is non-finite: {value}"


def test_a_non_finite_metric_is_published_as_null_never_as_nan():
    assert risk._round_finite(float("nan")) is None
    assert risk._round_finite(float("inf")) is None
    assert risk._round_finite(None) is None
    assert risk._round_finite(1.23456) == 1.2346
    json.dumps({"beta": risk._round_finite(float("nan"))}, allow_nan=False)


def test_beta_alert_is_withheld_when_benchmark_overlap_is_too_short():
    us = {
        "beta_spx": 4.0,
        "threshold_eligible": True,
        "beta_threshold_eligible": False,
        "benchmark_n_returns": 7,
    }

    alerts = risk.build_alerts(us, None, None, {})

    assert [a["type"] for a in alerts] == ["insufficient_observations"]
    assert "7 aligned returns" in alerts[0]["detail"]
