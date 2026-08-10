"""Behavioral tests for the in-memory logic in preflight_integrity.

The production ``check`` entry point accepts a path, but the integrity rules
themselves operate on the decoded portfolio dictionary.  ``run_check`` replaces
only that path adapter plus the snapshot/calendar adapters, so every case below
uses synthetic dictionaries and performs no portfolio/snapshot filesystem I/O.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


WS = Path(__file__).resolve().parents[1]
@pytest.fixture(scope="module")
def pi():
    """Import lazily so an unavailable local dependency cannot break collection."""
    return pytest.importorskip("clawock.portfolio.integrity")


@pytest.fixture
def run_check(pi, monkeypatch):
    """Run the real gate against JSON held entirely in memory."""

    def run(data, *, last_session="2026-07-17", previous_cash=None):
        payload = json.dumps(data)
        monkeypatch.setattr(
            pi,
            "Path",
            lambda _unused: SimpleNamespace(read_text=lambda: payload),
        )
        monkeypatch.setattr(pi, "_last_session", lambda _market: last_session)
        monkeypatch.setattr(
            pi, "_prev_snapshot_cash", lambda _region, _field: previous_cash
        )
        return pi.check("in-memory-only")

    return run


def _holding(
    *,
    ticker="ACME",
    shares=10.0,
    current=100.0,
    cost=90.0,
    previous=98.0,
    today_change_pct=None,
    data_source="synthetic quote 2026-07-17",
    trades=None,
):
    if trades is None:
        trades = [
            {
                "date": "2026-07-01",
                "action": "buy",
                "shares": shares,
                "price": cost,
            }
        ]
    if today_change_pct is None:
        today_change_pct = (current - previous) / previous * 100
    return {
        "ticker": ticker,
        "shares": shares,
        "current_price": current,
        "day_low": min(current, previous) * 0.95,
        "day_high": max(current, previous) * 1.05,
        "current_value": shares * current,
        "cost_basis": cost,
        "pnl_abs": shares * (current - cost),
        "prev_close": previous,
        "prev_close_date": "2026-07-16",
        "day_session_date": "2026-07-17",
        "today_change": shares * (current - previous),
        "today_change_pct": today_change_pct,
        "data_source": data_source,
        "trades": trades,
    }


def _portfolio_data(*, region="us_stocks", holdings=None, cash=100.0):
    holdings = [_holding()] if holdings is None else holdings
    currency = "USD" if region == "us_stocks" else "HKD"
    cash_field = "cash_usd" if region == "us_stocks" else "cash_hkd"
    active = [h for h in holdings if float(h.get("shares", 0) or 0) > 0]
    total_value = sum(float(h.get("current_value", 0) or 0) for h in active)
    total_cost = sum(
        float(h.get("shares", 0) or 0) * float(h.get("cost_basis", 0) or 0)
        for h in active
        if h.get("cost_basis") is not None
    )
    total_pnl = total_value - total_cost
    port = {
        "currency": currency,
        "holdings": holdings,
        "total_current_value": total_value,
        "total_cost": total_cost,
        "total_pnl": total_pnl,
        "total_pnl_percent": total_pnl / total_cost * 100 if total_cost else 0,
        "today_total_change": sum(
            float(h.get("today_change", 0) or 0) for h in active
        ),
        "realized_pnl": 0.0,
        "true_principal": total_cost or None,
        cash_field: cash,
        "cash_reconciled": cash,
        "cash_reconciled_date": "2026-07-01",
        "cash_adjustments": [],
    }
    return {
        "portfolios": {region: port},
        "gold_dca": {"principal_invested": 100.0, "units_held": 10.0, "nav": 10.0},
    }


def _port(data, region="us_stocks"):
    return data["portfolios"][region]


def _assert_clean(report):
    assert report["findings"] == []
    assert report["ok"] is True
    assert (report["error_count"], report["warn_count"]) == (0, 0)


def _assert_only(report, code, level, message_fragment):
    assert [finding["code"] for finding in report["findings"]] == [code]
    finding = report["findings"][0]
    assert finding["level"] == level
    assert message_fragment in finding["msg"]
    assert report["error_count"] == (level == "ERROR")
    assert report["warn_count"] == (level == "WARN")
    assert report["ok"] is (level != "ERROR")


def _sync_totals(port):
    active = [h for h in port["holdings"] if float(h.get("shares", 0) or 0) > 0]
    port["total_current_value"] = sum(h["current_value"] for h in active)
    port["total_cost"] = sum(h["shares"] * h["cost_basis"] for h in active)
    port["total_pnl"] = port["total_current_value"] - port["total_cost"]
    port["total_pnl_percent"] = (
        port["total_pnl"] / port["total_cost"] * 100 if port["total_cost"] else 0
    )
    port["today_total_change"] = sum(h["today_change"] for h in active)
    port["true_principal"] = port["total_cost"] or None


# Pure helpers -----------------------------------------------------------------


def test_num_and_active_define_numeric_and_positive_share_inputs(pi):
    assert pi._num("1.25") == 1.25
    assert pi._num(None) is None
    assert pi._num("not-a-number") is None
    holdings = [
        {"ticker": "POS", "shares": "1"},
        {"ticker": "ZERO", "shares": 0},
        {"ticker": "NEG", "shares": -1},
        {"ticker": "BAD", "shares": "?"},
        {"ticker": "MISSING"},
    ]
    assert [h["ticker"] for h in pi._active(holdings)] == ["POS"]


def test_moving_average_cost_is_stable_by_date_and_sells_at_running_average(pi):
    trades = [
        {"date": "2026-07-02", "action": "buy", "shares": 10, "price": 20},
        {"date": "2026-07-01", "action": "buy", "shares": 10, "price": 10},
        {"date": "2026-07-02", "action": "sell", "shares": 5, "price": 99},
    ]
    average, shares = pi._moving_avg_cost(trades)
    assert shares == 15
    assert average == pytest.approx(15.0)
    assert pi._moving_avg_cost(
        [
            {"action": "buy", "shares": 1, "price": 10},
            {"action": "sell", "shares": 1, "price": 20},
        ]
    ) == (None, 0.0)


def test_trade_cashflow_uses_strict_after_date_and_known_actions_only(pi):
    holdings = [
        {
            "trades": [
                {"date": "2026-07-01", "action": "buy", "shares": 9, "price": 9},
                {"date": "2026-07-02", "action": "buy", "shares": 2, "price": 10},
                {"date": "2026-07-03", "action": "sell", "shares": 1, "price": 25},
                {"date": "2026-07-04", "action": "split", "shares": 100, "price": 1},
                {"date": "", "action": "sell", "shares": 100, "price": 1},
            ]
        }
    ]
    assert pi._trade_cashflow_after(holdings, "2026-07-01") == (5.0, 2)
    assert pi._trade_cashflow_after([], "2026-07-01") == (0.0, 0)


def test_derive_cash_combines_baseline_trades_adjustments_and_rounds_cents(pi):
    port = {
        "cash_reconciled": "100.005",
        "cash_reconciled_date": "2026-07-01",
        "holdings": [
            {
                "trades": [
                    {"date": "2026-07-01", "action": "buy", "shares": 50, "price": 2},
                    {"date": "2026-07-02", "action": "buy", "shares": 2, "price": 10},
                    {"date": "2026-07-03", "action": "sell", "shares": 1, "price": 25},
                ]
            }
        ],
        "cash_adjustments": [
            {"date": "2026-07-01", "amount": 999},
            {"date": "2026-07-04", "amount": "10"},
            {"date": "2026-07-05", "amount": None},
        ],
    }
    assert pi.derive_cash(port) == (115.0, 100.005, "2026-07-01", 2)
    assert pi.derive_cash({"cash_reconciled": 100, "holdings": []}) is None
    assert pi.derive_cash({"cash_reconciled_date": "2026-07-01", "holdings": []}) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("quote 2026-7-2 close", "2026-07-02"),
        ("quote 2026/07/02 close", "2026-07-02"),
        ("as of Jul 2, 2026", "2026-07-02"),
        ("as of July 2, 2026", "2026-07-02"),
        ("2026-02-31", None),
        ("undated", None),
        (None, None),
    ],
)
def test_extract_iso_accepts_documented_dates_and_rejects_missing_or_invalid(pi, raw, expected):
    assert pi._extract_iso(raw) == expected


# Clean and edge paths ---------------------------------------------------------


def test_fully_coherent_portfolio_has_no_findings(run_check):
    _assert_clean(run_check(_portfolio_data()))


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"portfolios": {}},
        {"portfolios": {"ignored_region": None}},
        {
            "portfolios": {
                "us_stocks": {
                    "currency": "USD",
                    "holdings": [],
                    "cash_usd": 500,
                    "cash_reconciled": 500,
                    "cash_reconciled_date": "2026-07-01",
                },
                "hk_stocks": {"currency": "HKD", "holdings": []},
            }
        },
    ],
)
def test_empty_and_all_cash_portfolios_do_not_crash_or_false_positive(run_check, data):
    _assert_clean(run_check(data))


def test_missing_optional_holding_fields_are_skipped_without_false_positive(run_check):
    data = {
        "portfolios": {
            "us_stocks": {
                "currency": "USD",
                "holdings": [
                    {
                        "ticker": "SPARSE",
                        "shares": 1,
                        "data_source": "synthetic 2026-07-17",
                    }
                ],
            }
        }
    }
    _assert_clean(run_check(data))


# Region and aggregate gates ---------------------------------------------------


def test_fx_tag_accepts_canonical_currency_and_rejects_wrong_currency(run_check):
    good = _portfolio_data()
    _assert_clean(run_check(good))
    bad = copy.deepcopy(good)
    _port(bad)["currency"] = "HKD"
    _assert_only(run_check(bad), "FX_TAG", "ERROR", "currency=HKD 应为 USD")


def test_fx_tag_rejects_missing_required_currency(run_check):
    data = _portfolio_data()
    del _port(data)["currency"]
    _assert_only(run_check(data), "FX_TAG", "ERROR", "应为 USD")


def test_tcv_sum_exact_tolerance_passes_and_just_over_fails(run_check):
    exact = _portfolio_data()
    p = _port(exact)
    p["total_current_value"] += 1.0
    p["total_pnl"] += 1.0
    p["total_pnl_percent"] = p["total_pnl"] / p["total_cost"] * 100
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    p = _port(over)
    p["total_current_value"] += 0.01
    p["total_pnl"] += 0.01
    p["total_pnl_percent"] = p["total_pnl"] / p["total_cost"] * 100
    _assert_only(run_check(over), "TCV_SUM", "ERROR", "Σ活跃持仓 current_value")


def test_cost_total_exact_tolerance_passes_and_just_over_fails(run_check):
    exact = _portfolio_data()
    p = _port(exact)
    p["total_cost"] += 1.0
    p["total_pnl"] = p["total_current_value"] - p["total_cost"]
    p["total_pnl_percent"] = p["total_pnl"] / p["total_cost"] * 100
    p["true_principal"] = p["total_cost"]
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    p = _port(over)
    p["total_cost"] += 0.01
    p["total_pnl"] = p["total_current_value"] - p["total_cost"]
    p["total_pnl_percent"] = p["total_pnl"] / p["total_cost"] * 100
    p["true_principal"] = p["total_cost"]
    _assert_only(run_check(over), "COST_TOTAL", "ERROR", "shares×cost_basis")


def test_pnl_total_exact_tolerance_passes_and_just_over_fails(run_check):
    exact = _portfolio_data()
    p = _port(exact)
    p["total_pnl"] += 1.0
    p["total_pnl_percent"] = p["total_pnl"] / p["total_cost"] * 100
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    p = _port(over)
    p["total_pnl"] += 0.01
    p["total_pnl_percent"] = p["total_pnl"] / p["total_cost"] * 100
    _assert_only(run_check(over), "PNL_TOTAL", "ERROR", "TCV−cost")


def test_pnl_percent_exact_half_point_passes_and_just_over_warns(run_check):
    expected = 100.0 / 900.0 * 100
    exact = _portfolio_data()
    _port(exact)["total_pnl_percent"] = expected + 0.5
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over)["total_pnl_percent"] = expected + 0.5001
    _assert_only(run_check(over), "PNL_PCT", "WARN", "total_pnl/total_cost")


def test_today_total_exact_tolerance_passes_and_just_over_warns(run_check):
    exact = _portfolio_data()
    _port(exact)["today_total_change"] += 1.0
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over)["today_total_change"] += 0.01
    _assert_only(run_check(over), "TODAY_TOTAL", "WARN", "Σ活跃持仓 today_change")


def test_realized_sum_exact_tolerance_passes_and_just_over_warns(run_check):
    exact = _portfolio_data()
    _port(exact)["realized_pnl"] = 1.0
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over)["realized_pnl"] = 1.01
    _assert_only(run_check(over), "REALIZED_SUM", "WARN", "trades 汇总=0.00")


# Per-holding arithmetic and quote gates ---------------------------------------


def test_price_range_exact_half_percent_extension_passes_and_just_outside_warns(run_check):
    exact = _portfolio_data()
    h = _port(exact)["holdings"][0]
    h["day_high"] = h["current_price"] / 1.005
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over)["holdings"][0]["day_high"] -= 0.0001
    _assert_only(run_check(over), "PRICE_RANGE", "WARN", "越出当日区间")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "genuine bug (high confidence): PRICE_RANGE uses `if cur`, so zero bypasses "
        "the bad-tick gate even when the positive day range proves it impossible"
    ),
)
def test_zero_current_price_is_flagged_as_outside_positive_day_range(run_check):
    h = _holding(current=0.0, previous=98.0)
    h["day_low"] = 95.0
    h["day_high"] = 105.0
    data = _portfolio_data(holdings=[h])
    _assert_only(run_check(data), "PRICE_RANGE", "WARN", "越出当日区间")


def test_value_leg_uses_larger_of_half_unit_and_one_percent_tolerance(run_check):
    exact = _portfolio_data()
    h = _port(exact)["holdings"][0]
    h["current_value"] += 10.0  # 1% of the definitional 1,000 value
    _sync_totals(_port(exact))
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over)["holdings"][0]["current_value"] += 0.01
    _sync_totals(_port(over))
    _assert_only(run_check(over), "VALUE_LEG", "ERROR", "shares×current_price")


def test_pnl_leg_uses_larger_of_half_unit_and_one_percent_tolerance(run_check):
    exact = _portfolio_data()
    _port(exact)["holdings"][0]["pnl_abs"] += 1.0  # 1% of definitional 100 P&L
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over)["holdings"][0]["pnl_abs"] += 0.01
    _assert_only(run_check(over), "PNL_LEG", "WARN", "shares×(cur−cost)")


def test_today_leg_exact_half_unit_passes_and_just_over_warns(run_check):
    exact = _portfolio_data()
    h = _port(exact)["holdings"][0]
    h["today_change"] += 0.5  # max(0.5, 2% of definitional 20) == 0.5
    _sync_totals(_port(exact))
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over)["holdings"][0]["today_change"] += 0.01
    _sync_totals(_port(over))
    _assert_only(run_check(over), "TODAY_LEG", "WARN", "cur−prev_close")


def test_today_leg_skips_position_opened_in_current_session(run_check):
    h = _holding(
        current=100,
        previous=80,
        trades=[
            {"date": "2026-07-17", "action": "buy", "shares": 10, "price": 90}
        ],
    )
    h["today_change"] = 1.0  # deliberately not shares * (current - previous)
    data = _portfolio_data(holdings=[h])
    _port(data)["today_total_change"] = 1.0
    _port(data)["cash_reconciled_date"] = "2026-07-17"
    _assert_clean(run_check(data))


def test_cost_basis_exact_half_percent_passes_and_just_over_fails(run_check):
    exact = _portfolio_data()
    h = _port(exact)["holdings"][0]
    h["cost_basis"] = 90.0 / 1.005
    h["pnl_abs"] = h["shares"] * (h["current_price"] - h["cost_basis"])
    _sync_totals(_port(exact))
    _assert_clean(run_check(exact))

    over = _portfolio_data()
    h = _port(over)["holdings"][0]
    h["cost_basis"] = 90.0 / 1.005001
    h["pnl_abs"] = h["shares"] * (h["current_price"] - h["cost_basis"])
    _sync_totals(_port(over))
    _assert_only(run_check(over), "COST_BASIS", "ERROR", "trades 移动加权")


def test_cost_basis_skips_incomplete_trade_ledger_but_share_ledger_reports_it(run_check):
    """COST_BASIS must stay silent on a half ledger — its moving average cannot
    be verified against a list that is missing the opening buy, and raising an
    ERROR there would fail the book for something it cannot know.

    SHARE_LEDGER is the other half of that trade-off (#456): the same input is
    exactly what it exists to report, so silence here is now proven to be
    COST_BASIS declining to judge, not the incompleteness going unseen.
    """
    data = _portfolio_data()
    h = _port(data)["holdings"][0]
    h["trades"] = [
        {"date": "2026-07-01", "action": "buy", "shares": 2, "price": 1}
    ]
    _assert_only(run_check(data), "SHARE_LEDGER", "WARN", "无法当股数账本重放")


# Cross-field, freshness, principal, and cash gates ----------------------------


def test_leverage_direction_ignores_exact_noise_floor_and_warns_just_over(run_check):
    exact_holdings = [
        _holding(ticker="07226", current=101.0, previous=100.0, today_change_pct=1.0),
        _holding(ticker="03033", current=99.95, previous=100.0, today_change_pct=-0.05),
    ]
    exact = _portfolio_data(region="hk_stocks", holdings=exact_holdings)
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over, "hk_stocks")["holdings"][1]["today_change_pct"] = -0.0501
    _assert_only(run_check(over), "LEV_DIRECTION", "WARN", "方向矛盾")


def test_us_asof_accepts_one_session_and_warns_on_mixed_sessions(run_check):
    same = _portfolio_data(
        holdings=[_holding(ticker="A"), _holding(ticker="B", shares=5)]
    )
    _assert_clean(run_check(same))

    mixed = copy.deepcopy(same)
    _port(mixed)["holdings"][1]["data_source"] = "synthetic quote 2026-07-16"
    # Isolate US_ASOF from per-name STALENESS: this test is about mixed vintages.
    report = run_check(mixed, last_session=None)
    _assert_only(report, "US_ASOF", "WARN", "横跨多个 session 日期")


def test_staleness_accepts_last_session_and_warns_one_session_behind(run_check):
    fresh = _portfolio_data()
    _assert_clean(run_check(fresh, last_session="2026-07-17"))

    stale = copy.deepcopy(fresh)
    _port(stale)["holdings"][0]["data_source"] = "synthetic quote 2026-07-16"
    _assert_only(
        run_check(stale, last_session="2026-07-17"),
        "STALENESS",
        "WARN",
        "早于上一交易日 2026-07-17",
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "genuine bug (high confidence): an active holding with no parseable timestamp "
        "silently bypasses STALENESS although the documented gate requires freshness"
    ),
)
def test_staleness_rejects_missing_timestamp_on_active_holding(run_check):
    data = _portfolio_data()
    del _port(data)["holdings"][0]["data_source"]
    _assert_only(
        run_check(data, last_session="2026-07-17"),
        "STALENESS",
        "WARN",
        "missing",
    )


def test_true_principal_allows_exact_one_unit_headroom_and_warns_just_over(run_check):
    exact = _portfolio_data()
    _port(exact)["true_principal"] = 899.0  # net principal 900 == tp + 1
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over)["true_principal"] = 898.99
    _assert_only(run_check(over), "TRUE_PRINCIPAL", "WARN", "峰值净投入常量疑过期")


def test_cash_sanity_flags_nonnumeric_and_negative_cash(run_check):
    nonnumeric = _portfolio_data()
    p = _port(nonnumeric)
    p["cash_usd"] = "broken"
    del p["cash_reconciled"]
    _assert_only(run_check(nonnumeric), "CASH_SANITY", "WARN", "非数值")

    negative = _portfolio_data(cash=-1.0)
    _assert_only(run_check(negative), "CASH_SANITY", "WARN", "为负")


def test_cash_sanity_ratio_boundaries_are_inclusive(run_check):
    below_upper = _portfolio_data(cash=99.99)
    _port(below_upper)["cash_reconciled"] = 99.99
    _assert_clean(run_check(below_upper, previous_cash=(20.0, "2026-07-01")))

    exact_upper = _portfolio_data(cash=100.0)
    _assert_only(
        run_check(exact_upper, previous_cash=(20.0, "2026-07-01")),
        "CASH_SANITY",
        "WARN",
        "跳变 5.0×",
    )

    above_lower = _portfolio_data(cash=20.01)
    _port(above_lower)["cash_reconciled"] = 20.01
    _assert_clean(run_check(above_lower, previous_cash=(100.0, "2026-07-01")))

    exact_lower = _portfolio_data(cash=20.0)
    _assert_only(
        run_check(exact_lower, previous_cash=(100.0, "2026-07-01")),
        "CASH_SANITY",
        "WARN",
        "跳变 0.2×",
    )


def test_logged_cash_adjustment_is_removed_before_ratio_gate(run_check):
    data = _portfolio_data(cash=600.0)
    p = _port(data)
    p["cash_reconciled"] = 100.0
    p["cash_adjustments"] = [{"date": "2026-07-02", "amount": 500.0}]
    _assert_clean(run_check(data, previous_cash=(100.0, "2026-07-01")))


def test_cash_reconstruction_exact_tolerance_passes_and_just_over_fails(run_check):
    exact = _portfolio_data(cash=101.0)  # derived baseline remains 100; difference == 1
    _port(exact)["cash_reconciled"] = 100.0
    _assert_clean(run_check(exact))

    over = copy.deepcopy(exact)
    _port(over)["cash_usd"] = 101.01
    _assert_only(run_check(over), "CASH_RECON", "ERROR", "≠ 派生值 100.00")


def test_cash_reconstruction_without_baseline_is_intentionally_skipped(run_check):
    data = _portfolio_data(cash=999.0)
    p = _port(data)
    del p["cash_reconciled"]
    del p["cash_reconciled_date"]
    _assert_clean(run_check(data))


# Gold reconciliation ----------------------------------------------------------


def test_gold_reconciliation_ratio_boundaries_pass_and_just_outside_warns(run_check):
    exact_low = {"gold_dca": {"principal_invested": 3.0, "units_held": 1.0, "nav": 10.0}}
    _assert_clean(run_check(exact_low))
    exact_high = {"gold_dca": {"principal_invested": 30.0, "units_held": 1.0, "nav": 10.0}}
    _assert_clean(run_check(exact_high))

    over = {"gold_dca": {"principal_invested": 30.001, "units_held": 1.0, "nav": 10.0}}
    _assert_only(run_check(over), "GOLD_RECON", "WARN", "偏离 3.00×")


def test_gold_reconciliation_rejects_nonpositive_reconciled_values(run_check):
    bad = {"gold_dca": {"principal_invested": 0.0, "units_held": 1.0, "nav": 10.0}}
    _assert_only(run_check(bad), "GOLD_RECON", "WARN", "principal_invested/units_held 非正")


def test_missing_optional_gold_fields_are_skipped(run_check):
    _assert_clean(run_check({"gold_dca": {"nav": 10.0}}))
