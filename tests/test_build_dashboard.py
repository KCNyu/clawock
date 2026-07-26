"""Behavioral tests for build_dashboard's pure public-number derivations.

All inputs are synthetic in-memory values.  The module has no heavy third-party
imports and its filesystem orchestration is guarded by ``main()``, so importing
it does not read snapshots, portfolio data, or the network.
"""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import build_dashboard as dashboard  # noqa: E402


def _portfolio(*, us=None, hk=None):
    return {
        "portfolios": {
            "us_stocks": us or {"holdings": []},
            "hk_stocks": hk or {"holdings": []},
        }
    }


def _snapshot(day, *, us_equity, hk_equity, us_profit=None, hk_profit=None):
    return {
        "date": day,
        "us_equity": us_equity,
        "hk_equity": hk_equity,
        "us_profit": us_profit,
        "hk_profit": hk_profit,
    }


def test_guardrail_compute_exception_is_an_explicit_failure_dict(monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("synthetic guardrail failure")

    fake_preflight = SimpleNamespace(
        compute_risk_guardrail=explode,
        compute_concentration=lambda _holdings: {},
        compute_breakeven_math=lambda *_args, **_kwargs: {"rows": []},
    )
    monkeypatch.setitem(sys.modules, "brief_preflight", fake_preflight)

    result = dashboard.compute_guardrail_outputs(_portfolio(), risk={})

    assert isinstance(result["risk_guardrail"], dict)
    assert result["risk_guardrail"]["computed"] is False
    assert result["risk_guardrail"]["error"] == "synthetic guardrail failure"
    assert result["breakeven_math"] == {"computed": False}


def test_shadow_failure_replaces_stale_result_and_success_clears_marker(
    monkeypatch, tmp_path,
):
    sidecar = tmp_path / "shadow_portfolio.json"
    sidecar.write_text(json.dumps({
        "as_of": "2026-07-16T23:00:00+08:00",
        "cumulative_diff": {"HKD": 26428.93},
        "curves": {"HKD": {"curve": [{"date": "2026-07-16"}]}},
    }), encoding="utf-8")

    def explode(*_args, **_kwargs):
        raise RuntimeError("synthetic shadow failure")

    monkeypatch.setitem(
        sys.modules,
        "shadow_portfolio",
        SimpleNamespace(write_shadow_portfolio=explode),
    )
    failed = dashboard.write_shadow_sidecar({}, [], sidecar)
    written_failure = json.loads(sidecar.read_text(encoding="utf-8"))

    assert failed == written_failure == {
        "computed": False,
        "error": "synthetic shadow failure",
        "stale_as_of": "2026-07-16T23:00:00+08:00",
    }
    assert "curves" not in written_failure
    assert "cumulative_diff" not in written_failure
    assert all(value is not None for value in written_failure.values())

    def succeed(_portfolio, _decisions, out_path):
        result = {
            "as_of": "2026-07-17T23:00:00+08:00",
            "curves": {},
            "cumulative_diff": {},
        }
        Path(out_path).write_text(json.dumps(result), encoding="utf-8")
        return result

    monkeypatch.setitem(
        sys.modules,
        "shadow_portfolio",
        SimpleNamespace(write_shadow_portfolio=succeed),
    )
    succeeded = dashboard.write_shadow_sidecar({}, [], sidecar)
    written_success = json.loads(sidecar.read_text(encoding="utf-8"))

    assert succeeded == written_success
    assert "computed" not in written_success
    assert "error" not in written_success
    assert "stale_as_of" not in written_success


def test_profit_curve_max_drawdown_matches_known_peak_and_trough():
    result = dashboard._profit_extremes([
        ("2026-07-01", 100.0),
        ("2026-07-02", 180.0),
        ("2026-07-03", 135.0),
        ("2026-07-04", 220.0),  # running peak before the worst drop
        ("2026-07-05", 120.0),  # worst trough: 100 / 220 = 45.45%
        ("2026-07-06", 200.0),
    ])

    assert result["max_dd_abs"] == -100.0
    assert result["max_dd_pct"] == -45.45
    assert result["max_dd_peak_date"] == "2026-07-04"
    assert result["max_dd_trough_date"] == "2026-07-05"
    assert result["max_dd_peak_val"] == 220.0
    assert result["max_dd_trough_val"] == 120.0
    assert result["from_peak_abs"] == -20.0
    assert result["current_dd_pct"] == -9.09


def test_profit_curve_that_crosses_nonpositive_disables_percentage_drawdown():
    result = dashboard._profit_extremes([
        ("2026-07-01", 100.0),
        ("2026-07-02", 0.0),
        ("2026-07-03", -25.0),
    ])

    assert result["max_dd_abs"] == -125.0
    assert result["max_dd_pct"] is None
    assert result["current_dd_pct"] is None
    assert result["max_dd_peak_date"] == "2026-07-01"
    assert result["max_dd_trough_date"] == "2026-07-03"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "OPEN display-intent question for kcn (not a confirmed bug): the inline "
        "comment says current_dd_pct is 'positive across the span', but the guard "
        "checks only the endpoints (peak>0 and cur>0), so a series that dips to 0 "
        "and recovers still reports today's peak-to-current give-back. That value "
        "is defensible; whether an intermediate zero-touch should suppress it is a "
        "public-display call, left to a human. max_dd_pct is separately None here."
    ),
)
def test_profit_curve_percentage_stays_disabled_after_recovering_from_zero():
    result = dashboard._profit_extremes([
        ("2026-07-01", 100.0),
        ("2026-07-02", 0.0),
        ("2026-07-03", 80.0),
    ])

    assert result["max_dd_pct"] is None
    assert result["current_dd_pct"] is None


def test_profit_curve_monotonic_up_has_no_drawdown():
    result = dashboard._profit_extremes([
        ("2026-07-01", 10.0),
        ("2026-07-02", 25.0),
        ("2026-07-03", 40.0),
    ])

    assert result["max_dd_abs"] == 0.0
    assert result["max_dd_pct"] == 0.0
    assert result["from_peak_abs"] == 0.0
    assert result["current_dd_pct"] == 0.0
    assert result["max_dd_peak_date"] == "2026-07-01"
    assert result["max_dd_trough_date"] == "2026-07-01"


def test_profit_curve_empty_single_and_all_zero_edges():
    assert dashboard._profit_extremes([]) is None
    assert dashboard._profit_extremes([("2026-07-01", None)]) is None

    single = dashboard._profit_extremes([("2026-07-01", 12.5)])
    assert single["max_dd_abs"] == 0.0
    assert single["max_dd_pct"] == 0.0
    assert single["current_dd_pct"] == 0.0
    assert single["peak"] == single["trough"] == single["current"]

    zeros = dashboard._profit_extremes([
        ("2026-07-01", 0.0),
        ("2026-07-02", 0.0),
    ])
    assert zeros["max_dd_abs"] == 0.0
    assert zeros["max_dd_pct"] is None
    assert zeros["current_dd_pct"] is None
    assert zeros["from_peak_abs"] == 0.0


def test_equity_extremes_report_known_positive_series_drawdown():
    result = dashboard._series_extremes([
        ("d1", 100.0),
        ("d2", 160.0),
        ("d3", 120.0),
        ("d4", 180.0),
        ("d5", 90.0),
    ])

    assert result["max_dd_abs"] == 90.0
    assert result["max_dd_pct"] == -50.0
    assert result["max_dd_peak_date"] == "d4"
    assert result["max_dd_trough_date"] == "d5"
    assert result["current_dd_pct"] == -50.0
    assert result["at_low"] is True


def test_compute_drawdown_combines_currencies_additively_after_fx_conversion():
    snapshots = [
        _snapshot("d1", us_equity=100, hk_equity=1000, us_profit=10, hk_profit=100),
        _snapshot("d2", us_equity=120, hk_equity=1100, us_profit=30, hk_profit=80),
        _snapshot("d3", us_equity=110, hk_equity=900, us_profit=20, hk_profit=60),
    ]

    result = dashboard.compute_drawdown(snapshots, fx_rate=8.0)

    # Combined profit is HKD-native: US profit * 8 + HK profit.  The points are
    # 180, 320, 220; they are added once, never compounded or raw-summed.
    combined = result["profit"]["combined"]
    assert combined["peak"] == {"value": 320.0, "date": "d2"}
    assert combined["current"] == {"value": 220.0, "date": "d3"}
    assert combined["max_dd_abs"] == -100.0
    assert combined["max_dd_pct"] == -31.25
    assert combined["max_dd_peak_date"] == "d2"
    assert combined["max_dd_trough_date"] == "d3"
    assert combined["currency"] == "HKD"
    assert combined["fx_usdhkd"] == 8.0

    # The same FX-safe addition applies to equity: 100*8+1000 = 1800, etc.
    assert result["combined"]["peak"] == {"value": 2060.0, "date": "d2"}
    assert result["combined"]["current"] == {"value": 1780.0, "date": "d3"}


def test_compute_drawdown_empty_and_all_zero_edges():
    empty = dashboard.compute_drawdown([], fx_rate=8.0)
    assert empty["us"] is None
    assert empty["hk"] is None
    assert empty["combined"] is None
    assert empty["profit"]["combined"] is None

    zeros = dashboard.compute_drawdown([
        _snapshot("d1", us_equity=0, hk_equity=0, us_profit=0, hk_profit=0),
        _snapshot("d2", us_equity=0, hk_equity=0, us_profit=0, hk_profit=0),
    ], fx_rate=8.0)
    assert zeros["us"]["max_dd_abs"] == 0.0
    assert zeros["us"]["max_dd_pct"] == 0.0
    assert zeros["profit"]["us"]["max_dd_abs"] == 0.0
    assert zeros["profit"]["us"]["max_dd_pct"] is None
    assert zeros["combined"]["current"]["value"] == 0.0


def test_pct_change_rejects_a_negative_baseline():
    # Regression: a negative baseline is invalid (no % off a <=0 profit base),
    # per the docstring and the profit-basis-curve rule — now returns None.
    assert dashboard._pct_change(5.0, -10.0) is None


def test_delta_windows_activate_only_at_exact_point_boundaries():
    seven = [
        _snapshot(f"d{i}", us_equity=100 + i, hk_equity=200 + 2 * i)
        for i in range(7)
    ]
    assert dashboard.compute_delta(seven) == {
        "us": {"today_pct": 0.95, "7d_pct": None, "30d_pct": None},
        "hk": {"today_pct": 0.95, "7d_pct": None, "30d_pct": None},
    }

    eight = seven + [_snapshot("d7", us_equity=107, hk_equity=214)]
    assert dashboard.compute_delta(eight)["us"] == {
        "today_pct": 0.94,
        "7d_pct": 7.0,
        "30d_pct": None,
    }
    assert dashboard.compute_delta(eight)["hk"]["7d_pct"] == 7.0

    thirty = [
        _snapshot(f"d{i}", us_equity=100 + i, hk_equity=200 + i)
        for i in range(30)
    ]
    assert dashboard.compute_delta(thirty)["us"]["30d_pct"] is None

    thirty_one = thirty + [_snapshot("d30", us_equity=130, hk_equity=230)]
    assert dashboard.compute_delta(thirty_one)["us"]["30d_pct"] == 30.0
    assert dashboard.compute_delta(thirty_one)["hk"]["30d_pct"] == 15.0


def test_delta_empty_single_and_zero_baseline_edges():
    expected_empty = {
        "us": {"today_pct": None, "7d_pct": None, "30d_pct": None},
        "hk": {"today_pct": None, "7d_pct": None, "30d_pct": None},
    }
    assert dashboard.compute_delta([]) == expected_empty
    assert dashboard.compute_delta([
        _snapshot("d1", us_equity=10, hk_equity=20)
    ]) == expected_empty

    zero_base = dashboard.compute_delta([
        _snapshot("d1", us_equity=0, hk_equity=0),
        _snapshot("d2", us_equity=10, hk_equity=20),
    ])
    assert zero_base["us"]["today_pct"] is None
    assert zero_base["hk"]["today_pct"] is None


def test_today_movers_includes_exact_threshold_and_excludes_just_inside_it():
    us = [
        {"ticker": "UP", "today_change_pct": 3.0, "current_price": 10},
        {"ticker": "INSIDE", "today_change_pct": 2.999, "current_price": 20},
    ]
    hk = [
        {"ticker": "DOWN", "today_change_pct": -3.0, "current_price": 30},
        {"ticker": "BIG", "today_change_pct": -7.125, "current_price": 40},
        {"ticker": "MISSING", "today_change_pct": None, "current_price": 50},
    ]

    result = dashboard.compute_today_movers(us, hk)

    assert [row["ticker"] for row in result] == ["BIG", "UP", "DOWN"]
    assert [row["today_change_pct"] for row in result] == [-7.12, 3.0, -3.0]
    assert [row["region"] for row in result] == ["hk", "us", "hk"]


def test_today_movers_caps_output_at_ten_after_absolute_move_sorting():
    holdings = [
        {"ticker": f"T{i}", "today_change_pct": float(i), "current_price": i}
        for i in range(3, 15)
    ]

    result = dashboard.compute_today_movers(holdings, [])

    assert len(result) == 10
    assert [row["ticker"] for row in result] == [f"T{i}" for i in range(14, 4, -1)]


def test_hhi_uses_value_weights_and_reports_top_two_concentration():
    holdings = [
        {"ticker": "A", "name": "A", "is_active": True, "current_value": 60.0},
        {"ticker": "B", "name": "B", "is_active": True, "current_value": 30.0},
        {"ticker": "C", "name": "C", "is_active": True, "current_value": 10.0},
        {"ticker": "EXIT", "name": "X", "is_active": False, "current_value": 999.0},
    ]

    result = dashboard.compute_hhi(holdings)

    assert result["total"] == 100.0
    assert result["hhi"] == 0.46  # .6^2 + .3^2 + .1^2
    assert result["top2"] == 0.9
    assert [row["ticker"] for row in result["positions"]] == ["A", "B", "C"]


def test_latest_completed_session_skips_holiday_weekend_before_close():
    import trading_calendar

    before_close = datetime(
        2026, 7, 6, 15, 0, tzinfo=ZoneInfo("America/New_York")
    )
    after_close = datetime(
        2026, 7, 6, 17, 0, tzinfo=ZoneInfo("America/New_York")
    )

    assert dashboard._latest_completed_session(
        "us", trading_calendar, before_close
    ).isoformat() == "2026-07-02"
    assert dashboard._latest_completed_session(
        "us", trading_calendar, after_close
    ).isoformat() == "2026-07-06"


def test_market_leg_freshness_exposes_one_frozen_holding():
    import trading_calendar

    at = datetime(
        2026, 7, 24, 17, 0, tzinfo=ZoneInfo("America/New_York")
    )
    leg = {
        "last_updated": "Jun 24, 2026 16:00 ET close",
        "holdings": [
            {
                "ticker": "FRESH",
                "shares": 1,
                "data_source": "Nasdaq API Jul 24, 2026 16:00 ET",
            },
            {
                "ticker": "FROZEN",
                "shares": 1,
                "data_source": "Nasdaq API Jul 23, 2026 16:00 ET",
            },
            {"ticker": "EXITED", "shares": 0, "data_source": "old"},
        ],
    }

    status = dashboard._market_leg_freshness(
        leg, "us", trading_calendar, at=at
    )

    assert status["expected_completed_session"] == "2026-07-24"
    assert status["fresh"] is False
    assert status["stale_tickers"] == ["FROZEN"]
    assert status["quote_sessions"]["FRESH"] == "2026-07-24"
    assert "EXITED" not in status["quote_sessions"]


def test_stale_market_leg_makes_build_unhealthy(monkeypatch, tmp_path):
    data_dir = tmp_path / "assets" / "data"
    data_dir.mkdir(parents=True)
    for name in dashboard._FRESHNESS_SLA_H:
        path = tmp_path / name if name == "portfolio.json" else data_dir / name
        path.write_text("{}")
        os.utime(path, None)
    monkeypatch.setattr(dashboard, "WS_ROOT", tmp_path)
    monkeypatch.setitem(
        sys.modules,
        "preflight_integrity",
        SimpleNamespace(check=lambda: {
            "ok": True, "error_count": 0, "warn_count": 0, "findings": [],
        }),
    )
    portfolio = _portfolio(
        us={"holdings": [{
            "ticker": "US", "shares": 1, "data_source": "Nasdaq Jan 01, 2026"
        }]},
        hk={"holdings": [{
            "ticker": "HK", "shares": 1, "data_source": "Tencent Jan 01 2026"
        }]},
    )

    status = dashboard.compute_build_status(portfolio, data_dir)

    assert status["stale_files"] == []
    assert status["stale_markets"] == ["us", "hk"]
    assert status["healthy"] is False


@pytest.mark.parametrize("holdings", [[], [
    {"ticker": "ZERO", "name": "Z", "is_active": True, "current_value": 0.0},
]])
def test_hhi_empty_and_all_zero_books_have_zero_concentration(holdings):
    assert dashboard.compute_hhi(holdings) == {
        "hhi": 0,
        "top2": 0,
        "positions": [],
        "total": 0,
    }


def test_hhi_verdict_boundaries_are_strict_and_two_dimensional():
    assert dashboard.hhi_verdict(0.1499, 0.3999)["level"] == "healthy"
    assert dashboard.hhi_verdict(0.15, 0.3999)["level"] == "moderate"
    assert dashboard.hhi_verdict(0.2499, 0.60)["level"] == "concentrated"
    assert dashboard.hhi_verdict(0.3999, 0.75)["level"] == "danger"


def test_realized_unrealized_attribution_keeps_legs_native_and_converts_combined():
    portfolio = _portfolio(
        us={"holdings": [], "realized_pnl": 30.0, "total_pnl": -10.0},
        hk={"holdings": [], "realized_pnl": 80.0, "total_pnl": 20.0},
    )

    result = dashboard.compute_realized_vs_unrealized(portfolio, fx_rate=8.0)

    assert result["us"] == {"realized": 30.0, "unrealized": -10.0}
    assert result["hk"] == {"realized": 80.0, "unrealized": 20.0}
    assert result["combined_usd"] == {"realized": 40.0, "unrealized": -7.5}
    assert result["combined_usd"]["realized"] != 110.0  # never raw-sum USD + HKD


def test_realized_unrealized_all_zero_book_stays_zero():
    result = dashboard.compute_realized_vs_unrealized(_portfolio(), fx_rate=8.0)

    assert result["us"] == {"realized": 0.0, "unrealized": 0.0}
    assert result["hk"] == {"realized": 0.0, "unrealized": 0.0}
    assert result["combined_usd"] == {"realized": 0.0, "unrealized": 0.0}


def test_capital_deployed_adds_cost_and_realized_without_compounding():
    portfolio = _portfolio(
        us={"holdings": [], "total_cost": 100.0, "realized_pnl": 20.0},
        hk={"holdings": [], "total_cost": 800.0, "realized_pnl": -80.0},
    )

    result = dashboard.compute_capital_deployed(portfolio, fx_rate=8.0)

    assert result["us"] == {"native": 120.0, "usd": 120.0}
    assert result["hk"] == {"native": 720.0, "usd": 90.0}
    assert result["combined_usd"] == 210.0


def test_sector_exposure_groups_values_within_each_currency_leg():
    portfolio = _portfolio(
        us={"holdings": [
            {"ticker": "NVDA", "shares": 1, "current_value": 60.0},
            {"ticker": "SOXL", "shares": 1, "current_value": 40.0},
            {"ticker": "EXIT", "shares": 0, "current_value": 900.0},
        ]},
        hk={"holdings": [
            {"ticker": "00100", "shares": 1, "current_value": 75.0},
            {"ticker": "03032", "shares": 1, "current_value": 25.0},
        ]},
    )

    result = dashboard.compute_sector_exposure(portfolio)

    assert result["us"] == [
        {"sector": "Semiconductor", "value": 60.0, "pct": 60.0, "tickers": ["NVDA"]},
        {"sector": "Semiconductor ETF", "value": 40.0, "pct": 40.0, "tickers": ["SOXL"]},
    ]
    assert result["hk"] == [
        {"sector": "AI / 大模型", "value": 75.0, "pct": 75.0, "tickers": ["00100"]},
        {"sector": "恒生科技 ETF", "value": 25.0, "pct": 25.0, "tickers": ["03032"]},
    ]


def test_leveraged_exposure_combined_total_is_fx_safe():
    portfolio = _portfolio(
        us={"holdings": [
            {"ticker": "PLTU", "shares": 1, "current_value": 100.0},
            {"ticker": "AAPL", "shares": 1, "current_value": 100.0},
        ]},
        hk={"holdings": [
            {"ticker": "07226", "shares": 1, "current_value": 800.0},
            {"ticker": "00100", "shares": 1, "current_value": 800.0},
        ]},
    )

    result = dashboard.compute_leveraged_etf_exposure(portfolio, fx_rate=8.0)

    assert result == {
        "us_pct": 50.0,
        "hk_pct": 50.0,
        "combined_pct": 50.0,
        "tickers": ["07226", "PLTU"],
    }


def test_today_ranges_uses_current_price_denominator_and_strict_top_n():
    portfolio = _portfolio(
        us={"holdings": [
            {"ticker": "A", "shares": 1, "day_high": 12, "day_low": 8, "current_price": 10},
            {"ticker": "FLAT", "shares": 1, "day_high": 5, "day_low": 5, "current_price": 5},
        ]},
        hk={"holdings": [
            {"ticker": "B", "shares": 1, "day_high": 21, "day_low": 19, "current_price": 20},
            {"ticker": "EXIT", "shares": 0, "day_high": 99, "day_low": 1, "current_price": 2},
        ]},
    )

    assert dashboard.compute_today_ranges(portfolio, top_n=1) == [{
        "ticker": "A",
        "region": "us",
        "high": 12.0,
        "low": 8.0,
        "current": 10.0,
        "range_pct": 40.0,
    }]
