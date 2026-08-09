"""Behavioral tests for build_dashboard's pure public-number derivations.

All inputs are synthetic in-memory values.  The module has no heavy third-party
imports and its filesystem orchestration is guarded by ``main()``, so importing
it does not read snapshots, portfolio data, or the network.
"""
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import build_dashboard as dashboard  # noqa: E402


def _portfolio(*, us=None, hk=None):
    """A two-book ledger shaped like the real one.

    `currency` is not decoration: the legs, and the currency a combined figure is
    denominated in, are read off the books (#262 slice 3). A fixture without it
    models a ledger the money rules refuse to combine.
    """
    return {
        "portfolios": {
            "us_stocks": {"currency": "USD", **(us or {"holdings": []})},
            "hk_stocks": {"currency": "HKD", **(hk or {"holdings": []})},
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


def test_session_asof_without_a_dated_active_holding_is_none():
    assert dashboard._session_asof({"holdings": []}, 2026) is None
    assert dashboard._session_asof({
        "holdings": [{"shares": 1, "data_source": "fallback without a date"}],
    }, 2026) is None


def _fresh_build_status_fixture(monkeypatch, tmp_path, at):
    data_dir = tmp_path / "assets" / "data"
    data_dir.mkdir(parents=True)
    for name in dashboard._FRESHNESS_POLICY:
        path = tmp_path / name if name == "portfolio.json" else data_dir / name
        path.write_text("{}")
        os.utime(path, (at.timestamp(), at.timestamp()))
    monkeypatch.setattr(dashboard, "WS_ROOT", tmp_path)
    monkeypatch.setitem(
        sys.modules,
        "clawock.portfolio.integrity",
        SimpleNamespace(check=lambda: {
            "ok": True, "error_count": 0, "warn_count": 0, "findings": [],
        }),
    )
    return _portfolio(), data_dir


def test_guardrail_compute_exception_is_an_explicit_failure_dict(monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("synthetic guardrail failure")

    fake_preflight = SimpleNamespace(
        compute_risk_guardrail=explode,
        compute_concentration=lambda _holdings: {},
        compute_breakeven_math=lambda *_args, **_kwargs: {"rows": []},
    )
    monkeypatch.setitem(
        sys.modules, "clawock_kcnyu.harness.brief_preflight", fake_preflight
    )

    result = dashboard.compute_guardrail_outputs(_portfolio(), risk={})

    assert isinstance(result["risk_guardrail"], dict)
    assert result["risk_guardrail"]["computed"] is False
    assert result["risk_guardrail"]["error"] == "synthetic guardrail failure"
    assert result["breakeven_math"] == {"computed": False}


def test_shadow_failure_replaces_stale_result_and_success_clears_marker(monkeypatch):
    previous = {
        "as_of": "2026-07-16T23:00:00+08:00",
        "cumulative_diff": {"HKD": 26428.93},
        "curves": {"HKD": {"curve": [{"date": "2026-07-16"}]}},
    }

    def explode(*_args, **_kwargs):
        raise RuntimeError("synthetic shadow failure")

    monkeypatch.setitem(
        sys.modules,
        "clawock.portfolio.shadow",
        SimpleNamespace(
            load_leg_config=lambda _path: {},
            build_shadow_portfolio=explode,
        ),
    )
    failed = dashboard.build_shadow_sidecar({}, [], previous)

    assert failed == {
        "computed": False,
        "error": "synthetic shadow failure",
        "stale_as_of": "2026-07-16T23:00:00+08:00",
    }, "a failed refresh keeps only the old as_of as provenance, never its curves"
    assert "curves" not in failed
    assert "cumulative_diff" not in failed
    assert all(value is not None for value in failed.values())

    def succeed(_portfolio, _decisions, **_kwargs):
        return {
            "as_of": "2026-07-17T23:00:00+08:00",
            "curves": {},
            "cumulative_diff": {},
        }

    monkeypatch.setitem(
        sys.modules,
        "clawock.portfolio.shadow",
        SimpleNamespace(
            load_leg_config=lambda _path: {},
            build_shadow_portfolio=succeed,
        ),
    )
    succeeded = dashboard.build_shadow_sidecar({}, [], failed)

    assert "computed" not in succeeded
    assert "error" not in succeeded
    assert "stale_as_of" not in succeeded


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
    from clawock.market_data import sessions as trading_calendar

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
    from clawock.market_data import sessions as trading_calendar

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
        "clawock.portfolio.integrity",
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


@pytest.mark.parametrize("at", [
    datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc),
    datetime(2026, 8, 2, 6, 0, tzinfo=timezone.utc),
])
def test_weekday_scan_newer_than_friday_fire_stays_fresh_on_weekend(
    monkeypatch, tmp_path, at,
):
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    # Friday-HKT producers fire Thursday UTC.  These commits landed after their
    # nominal fires but are 31-55h old when inspected over the weekend.
    mtimes = {
        "macro.json": datetime(2026, 7, 30, 22, 15, tzinfo=timezone.utc),
        "sentiment.json": datetime(2026, 7, 30, 22, 0, tzinfo=timezone.utc),
        "us_news_digest.json": datetime(2026, 7, 31, 15, 15, tzinfo=timezone.utc),
        "influencer_feed.json": datetime(2026, 7, 31, 15, 15, tzinfo=timezone.utc),
    }
    friday_brief = datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
    mtimes.update({name: friday_brief for name in dashboard._BRIEF_FRESHNESS_ARTIFACTS})
    for name, mtime in mtimes.items():
        os.utime(data_dir / name, (mtime.timestamp(), mtime.timestamp()))

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)

    assert "macro.json" not in status["stale_files"]
    assert "sentiment.json" not in status["stale_files"]
    assert status["healthy"] is True


def test_scan_does_not_become_due_inside_its_measured_grace(monkeypatch, tmp_path):
    at = datetime(2026, 8, 3, 2, 30, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    friday_commit = datetime(2026, 7, 30, 22, 15, tzinfo=timezone.utc)
    os.utime(
        data_dir / "macro.json",
        (friday_commit.timestamp(), friday_commit.timestamp()),
    )

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)
    macro = next(row for row in status["files"] if row["name"] == "macro.json")

    assert macro["latest_due_at"] == "2026-07-30T21:45:00+00:00"
    assert macro["stale"] is False


def test_missed_monday_scan_becomes_stale_after_grace(monkeypatch, tmp_path):
    at = datetime(2026, 8, 3, 2, 46, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    friday_commit = datetime(2026, 7, 30, 22, 15, tzinfo=timezone.utc)
    os.utime(
        data_dir / "macro.json",
        (friday_commit.timestamp(), friday_commit.timestamp()),
    )

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)
    macro = next(row for row in status["files"] if row["name"] == "macro.json")

    assert macro["stale"] is True
    assert macro["latest_due_at"] == "2026-08-02T21:45:00+00:00"
    assert macro["deadline_at"] == "2026-08-03T02:45:00+00:00"
    assert macro["grace_hours"] == 5
    assert "macro.json" in status["stale_files"]
    assert status["healthy"] is False


@pytest.mark.parametrize("at", [
    datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc),
    datetime(2026, 8, 2, 6, 0, tzinfo=timezone.utc),
])
def test_genuine_friday_miss_remains_stale_through_weekend(
    monkeypatch, tmp_path, at,
):
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    thursday_commit = datetime(2026, 7, 29, 22, 15, tzinfo=timezone.utc)
    os.utime(
        data_dir / "macro.json",
        (thursday_commit.timestamp(), thursday_commit.timestamp()),
    )

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)

    assert "macro.json" in status["stale_files"]


def test_missed_friday_brief_artifact_remains_stale_through_weekend(
    monkeypatch, tmp_path,
):
    at = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    old = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    os.utime(data_dir / "risk.json", (old.timestamp(), old.timestamp()))

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)

    assert "risk.json" in status["stale_files"]


def test_flat_sla_portfolio_keeps_age_based_behavior_on_weekend(monkeypatch, tmp_path):
    at = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    old = at - timedelta(hours=27)
    os.utime(tmp_path / "portfolio.json", (old.timestamp(), old.timestamp()))

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)
    row = next(row for row in status["files"] if row["name"] == "portfolio.json")

    assert row["freshness_mode"] == "max_age"
    assert row["sla_hours"] == 26
    assert row["stale"] is True


def test_weekday_market_holiday_still_expects_scan(monkeypatch, tmp_path):
    # Christmas is a market holiday, but the GitHub scan cron still fires.
    at = datetime(2026, 12, 25, 3, 0, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    old = datetime(2026, 12, 23, 22, 15, tzinfo=timezone.utc)
    os.utime(data_dir / "macro.json", (old.timestamp(), old.timestamp()))

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)

    assert "macro.json" in status["stale_files"]


def test_brief_fire_is_skipped_when_both_covered_markets_are_closed(
    monkeypatch, tmp_path,
):
    # Monday 2026-04-06 is an HK holiday; at 08:00 HKT the US date is Sunday.
    # The producer skips, so Friday's successful brief remains the latest due.
    at = datetime(2026, 4, 6, 7, 0, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    friday_commit = datetime(2026, 4, 3, 1, 0, tzinfo=timezone.utc)
    os.utime(data_dir / "risk.json", (friday_commit.timestamp(), friday_commit.timestamp()))

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)
    risk = next(row for row in status["files"] if row["name"] == "risk.json")

    assert risk["latest_due_at"] == "2026-04-03T00:00:00+00:00"
    assert risk["stale"] is False


def test_brief_artifact_turns_stale_after_next_required_fire(monkeypatch, tmp_path):
    # Tuesday's HK leg is closed too, but Monday's US session is open, so the
    # two-market brief runs and must supersede Friday after its grace window.
    at = datetime(2026, 4, 7, 7, 0, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    friday_commit = datetime(2026, 4, 3, 1, 0, tzinfo=timezone.utc)
    os.utime(data_dir / "risk.json", (friday_commit.timestamp(), friday_commit.timestamp()))

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)
    risk = next(row for row in status["files"] if row["name"] == "risk.json")

    assert risk["latest_due_at"] == "2026-04-07T00:00:00+00:00"
    assert risk["stale"] is True


def test_multiple_daily_fires_use_latest_due_schedule(monkeypatch, tmp_path):
    at = datetime(2026, 7, 31, 19, 0, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    after_early_fire = datetime(2026, 7, 30, 22, 0, tzinfo=timezone.utc)
    os.utime(
        data_dir / "influencer_feed.json",
        (after_early_fire.timestamp(), after_early_fire.timestamp()),
    )

    status = dashboard.compute_build_status(portfolio, data_dir, at=at)
    influencer = next(
        row for row in status["files"] if row["name"] == "influencer_feed.json"
    )

    assert influencer["latest_due_at"] == "2026-07-31T12:50:00+00:00"
    assert influencer["deadline_at"] == "2026-07-31T18:50:00+00:00"
    assert influencer["grace_hours"] == 6
    assert influencer["stale"] is True


def test_digest_uses_its_own_seven_hour_grace(monkeypatch, tmp_path):
    friday_commit = datetime(2026, 7, 31, 15, 15, tzinfo=timezone.utc)
    before_deadline = datetime(2026, 8, 3, 19, 59, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(
        monkeypatch, tmp_path, before_deadline
    )
    os.utime(
        data_dir / "us_news_digest.json",
        (friday_commit.timestamp(), friday_commit.timestamp()),
    )

    before = dashboard.compute_build_status(portfolio, data_dir, at=before_deadline)
    row = next(r for r in before["files"] if r["name"] == "us_news_digest.json")
    assert row["latest_due_at"] == "2026-07-31T13:00:00+00:00"
    assert row["stale"] is False

    after_deadline = datetime(2026, 8, 3, 20, 1, tzinfo=timezone.utc)
    after = dashboard.compute_build_status(portfolio, data_dir, at=after_deadline)
    row = next(r for r in after["files"] if r["name"] == "us_news_digest.json")
    assert row["latest_due_at"] == "2026-08-03T13:00:00+00:00"
    assert row["deadline_at"] == "2026-08-03T20:00:00+00:00"
    assert row["stale"] is True


def test_scheduled_mtime_boundary_and_missing_file(monkeypatch, tmp_path):
    at = datetime(2026, 8, 3, 2, 46, tzinfo=timezone.utc)
    portfolio, data_dir = _fresh_build_status_fixture(monkeypatch, tmp_path, at)
    due = datetime(2026, 8, 2, 21, 45, tzinfo=timezone.utc)
    macro = data_dir / "macro.json"

    os.utime(macro, (due.timestamp(), due.timestamp()))
    exact = dashboard.compute_build_status(portfolio, data_dir, at=at)
    row = next(r for r in exact["files"] if r["name"] == "macro.json")
    assert row["stale"] is False

    os.utime(macro, (due.timestamp() - 1, due.timestamp() - 1))
    one_second_old = dashboard.compute_build_status(portfolio, data_dir, at=at)
    row = next(r for r in one_second_old["files"] if r["name"] == "macro.json")
    assert row["stale"] is True

    macro.unlink()
    missing = dashboard.compute_build_status(portfolio, data_dir, at=at)
    row = next(r for r in missing["files"] if r["name"] == "macro.json")
    assert row["present"] is False
    assert row["stale"] is True
    assert "macro.json" in missing["stale_files"]


def _cron_python_weekdays(field):
    names = {name: i for i, name in enumerate(
        ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    )}

    def cron_day(value):
        value = value.upper()
        if value in names:
            return names[value]
        number = int(value)
        return 6 if number in (0, 7) else number - 1

    if field == "*":
        return tuple(range(7))
    days = set()
    for part in field.split(","):
        start, sep, end = part.partition("-")
        if sep:
            first, last = cron_day(start), cron_day(end)
            if first <= last:
                days.update(range(first, last + 1))
            else:
                days.update(range(first, 7))
                days.update(range(0, last + 1))
        else:
            days.add(cron_day(start))
    return tuple(sorted(days))


def test_gha_freshness_registry_matches_workflow_crons():
    workflow_for_artifact = {
        "macro.json": "macro-scan.yml",
        "sentiment.json": "sentiment-scan.yml",
        "us_news_digest.json": "news-digest.yml",
        "influencer_feed.json": "influencer-scan.yml",
    }
    expected_graces = {
        "macro.json": [5],
        "sentiment.json": [6],
        "us_news_digest.json": [7],
        "influencer_feed.json": [6, 6],
    }

    scheduled = {
        name for name, policy in dashboard._FRESHNESS_POLICY.items()
        if policy.get("schedule")
    }
    assert scheduled - dashboard._BRIEF_FRESHNESS_ARTIFACTS == set(
        workflow_for_artifact
    )

    for artifact, workflow in workflow_for_artifact.items():
        text = (ROOT / ".github" / "workflows" / workflow).read_text()
        expressions = re.findall(
            r"^\s*-\s+cron:\s*['\"]([^'\"]+)['\"]\s*$", text, re.MULTILINE
        )
        assert len(expressions) == text.count("- cron:"), (
            f"unsupported cron syntax in {workflow}"
        )
        actual = set()
        for expression in expressions:
            minute, hour, dom, month, dow = expression.split()
            assert dom == month == "*"
            assert minute.isdigit() and hour.isdigit()
            actual.add(("UTC", _cron_python_weekdays(dow), int(hour), int(minute)))

        policy = dashboard._FRESHNESS_POLICY[artifact]["schedule"]
        expected = {
            (fire["timezone"], tuple(fire["weekdays"]), fire["hour"], fire["minute"])
            for fire in policy["fires"]
        }
        assert actual == expected, f"{artifact} cadence drifted from {workflow}"
        assert sorted(fire["grace_hours"] for fire in policy["fires"]) == (
            expected_graces[artifact]
        )


def test_brief_freshness_registry_matches_host_cron_contract():
    contract = json.loads((ROOT / "config" / "cron-schedules.json").read_text())
    job = next(job for job in contract["jobs"] if job["name"] == "盘前深度简报")

    assert job["schedule"] == {
        "kind": "cron",
        "expr": "0 8 * * 1-5",
        "tz": "Asia/Shanghai",
    }
    assert dashboard._BRIEF_FIRE == {
        "weekdays": (0, 1, 2, 3, 4),
        "hour": 8,
        "minute": 0,
        "grace_hours": 6,
        "timezone": "Asia/Shanghai",
        "required_when": "any_market_open",
    }


def test_dashboard_tooltip_distinguishes_schedule_deadlines_from_age_slas():
    renderer = (ROOT / "site" / "assets" / "js" / "dashboard.render.js").read_text()
    block = renderer.split("// tooltip：逐文件年龄", 1)[1].split(
        "(ig.top || [])", 1
    )[0]

    assert "f.freshness_mode === 'scheduled_fire'" in block
    assert "f.deadline_at" in block
    assert "timeZone: 'Asia/Hong_Kong'" in block
    assert "HKT 前刷新" in block
    assert "/ SLA ${f.sla_hours}h" in block


def test_dashboard_market_tooltip_uses_canonical_quote_sessions():
    renderer = (ROOT / "site" / "assets" / "js" / "dashboard.render.js").read_text()
    helper = renderer.split("function quoteSessionLabel", 1)[1].split(
        "// ── A2 系统健康卡", 1
    )[0]
    market_block = renderer.split("if (bs.markets)", 1)[1].split(
        "(wf.recent || [])", 1
    )[0]

    assert "market.oldest_quote_session" in helper
    assert "market.newest_quote_session" in helper
    assert "oldest === newest" in helper
    assert "${oldest} → ${newest}" in helper
    assert "行情会话未知" in helper
    assert "quoteSessionLabel(v)" in market_block
    assert "v.closed_today" in market_block
    assert "last_updated" not in market_block


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


def test_a_ledger_with_different_books_publishes_its_own_legs():
    """#262 slice 3 acceptance, in miniature: the leg shape comes from the ledger,
    not from this file. A workspace whose books are not `us_stocks`/`hk_stocks`
    still produces a payload — keyed by its own legs, denominated in its own base
    currency."""
    ledger = {"portfolios": {
        "jp_stocks": {"currency": "JPY", "holdings": [], "realized_pnl": 300.0,
                      "total_pnl": -100.0},
        "eu_stocks": {"currency": "EUR", "holdings": [], "realized_pnl": 80.0,
                      "total_pnl": 20.0},
    }}

    assert [leg.key for leg in dashboard.resolve_legs(ledger)] == ["jp", "eu"], (
        "publication order is the ledger's — the payload is serialized unsorted")

    result = dashboard.compute_realized_vs_unrealized(ledger, fx_rate=4.0)

    assert result["jp"] == {"realized": 300.0, "unrealized": -100.0}
    assert result["eu"] == {"realized": 80.0, "unrealized": 20.0}
    assert result["combined_jpy"] == {"realized": 320.0, "unrealized": -95.0}
    assert "us" not in result and "combined_usd" not in result


def test_a_book_without_a_declared_currency_is_never_combined():
    """The iron rule is that two currencies may not be added. A book that never
    said which currency it holds cannot be folded into a total, and the total
    must not be labelled as if it had — the per-leg values still publish."""
    ledger = {"portfolios": {
        "us_stocks": {"holdings": [], "realized_pnl": 30.0, "total_pnl": -10.0},
        "hk_stocks": {"currency": "HKD", "holdings": [], "realized_pnl": 80.0,
                      "total_pnl": 20.0},
    }}

    assert dashboard.leg_pair(ledger) == (None, None)

    result = dashboard.compute_realized_vs_unrealized(ledger, fx_rate=8.0)

    assert result["us"] == {"realized": 30.0, "unrealized": -10.0}
    assert result["hk"] == {"realized": 80.0, "unrealized": 20.0}
    assert result["combined"] == {"realized": None, "unrealized": None}
    assert "combined_" not in result, "an unlabelled currency must not become a key"


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


# ── the previous published payload as an explicit input (#262) ──────────────
#
# The merge is the one part of the output that does not come from the workspace,
# so what it took and where it came from have to be answerable. Since slice 2 it
# is also opt-in: a build reads a previously published payload only when a caller
# names the file.


def test_merge_takes_only_the_keys_whose_source_was_absent_and_names_them():
    out = {"anomalies": [], "status_banner": "fresh"}
    previous = {"anomalies": ["yesterday"], "status_banner": "stale", "totals": {"hk": 1}}

    taken = dashboard.merge_previous_payload(
        out, previous, {"anomalies": False, "status_banner": True})

    assert out["anomalies"] == ["yesterday"], "absent source must not blank the card"
    assert out["status_banner"] == "fresh", "a present source must win over the old payload"
    assert taken == ["anomalies"]
    assert "totals" not in out, "only the listed cards may come from the previous payload"


def test_an_absent_source_with_nothing_published_before_stays_absent():
    """The fallback is 'keep the last non-empty value', not 'invent one'."""
    out = {"anomalies": []}

    taken = dashboard.merge_previous_payload(out, {"anomalies": []}, {"anomalies": False})

    assert out["anomalies"] == []
    assert taken == []


def test_the_default_build_reads_no_previously_published_file():
    """Acceptance criterion for #262: no output depends on a previously published
    file unless that file is passed in explicitly. A bare invocation resolves to
    no source at all, so the merge is a no-op even where every sidecar is absent
    — which is what makes a workspace the complete input to a build."""
    assert dashboard.resolve_previous_source(dashboard.parse_args([])) is None
    assert dashboard.resolve_previous_source(dashboard.parse_args(["--no-previous"])) is None
    assert dashboard.resolve_previous_source(
        dashboard.parse_args(["--previous", "assets/data/dashboard.json"])
    ) == Path("assets/data/dashboard.json"), "a named file must still be honoured"

    out = {"anomalies": []}
    assert dashboard.load_previous_payload(None) == (None, False)
    assert dashboard.merge_previous_payload(out, None, {"anomalies": False}) == []
    assert out["anomalies"] == []


def test_every_publishing_caller_opts_into_preservation():
    """The default is safe for a build, but silent for a *publisher*: a fresh
    checkout has no memory/.tmp, so a publishing caller that forgets `--previous`
    publishes blank narrative cards (the 2026-06-21 regression).

    Two callers publish what they build. `.githooks/pre-commit` was the third
    until #314 — it rebuilt and staged the outputs so a portfolio.json commit
    could not drift from the views it implied, and with the outputs untracked
    there is no longer a commit for them to drift inside of.

    Every other caller — system_check's buildability gate, the two Actions
    validation jobs, the gold refresh path — either never publishes or runs only
    on the host, and is deliberately left bare.
    """
    publishers = [
        "ops/publish/publish_dashboard.sh",   # host crontab, every 20 minutes
        "instances/kcnyu/src/clawock_kcnyu/harness/_harness_common.py",
    ]
    for rel in publishers:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        invocations = [
            i for i, line in enumerate(lines)
            if "build_dashboard.py" in line and "python3" in line
            and not line.lstrip().startswith("#")
        ]
        assert invocations, f"{rel} no longer invokes build_dashboard.py"
        for i in invocations:
            window = "\n".join(lines[i:i + 3])
            assert "--previous" in window, (
                f"{rel}:{i + 1} publishes its build but does not opt into "
                "restoring cards whose sidecar is absent from this checkout")


def test_the_projection_computes_and_writes_nothing():
    """#262 slice 3: `build_projection` returns the generation, `main` writes it.

    The split only holds while it holds — a write added back into the compute
    path would restore the coupling silently, and no output test would notice
    because the bytes would be identical. So this reads the function itself.
    """
    import ast

    source = (ROOT / "scripts" / "data" / "build_dashboard.py").read_text(encoding="utf-8")
    projection = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "build_projection"
    )
    writers = {"safe_write_text", "write_text", "mkdir", "record_preservation"}
    found = sorted({
        f"{getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)}"
        f" (line {node.lineno})"
        for node in ast.walk(projection)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "attr", None) or getattr(node.func, "id", None)) in writers
    })
    assert not found, f"build_projection must not touch the filesystem: {found}"


def test_a_missing_ledger_is_a_clean_exit_not_a_traceback(monkeypatch, capsys):
    """`main` turns an unbuildable input into the exit code the pre-push
    buildability gate and every postflight already read. Letting the exception
    escape would change a handled failure into a crash."""
    def no_ledger(*_args, **_kwargs):
        raise dashboard.MissingPortfolio("portfolio.json")

    monkeypatch.setattr(dashboard, "build_projection", no_ledger)

    assert dashboard.main([]) == 1
    assert "FATAL: portfolio.json missing" in capsys.readouterr().err


def test_a_ledger_of_the_wrong_shape_says_so_instead_of_claiming_it_is_missing(
    monkeypatch, capsys,
):
    """Both input failures exit 1, but they are not the same failure. Reporting a
    three-book ledger as "portfolio.json missing" would send whoever reads the
    gate looking for a file that is sitting right there."""
    def wrong_shape(*_args, **_kwargs):
        raise dashboard.UnsupportedLegShape(
            "portfolio.json must declare exactly two books, each with a currency; "
            "found [('us_stocks', 'USD'), ('hk_stocks', 'HKD'), ('jp_stocks', '')]")

    monkeypatch.setattr(dashboard, "build_projection", wrong_shape)

    assert dashboard.main([]) == 1
    err = capsys.readouterr().err
    assert "exactly two books" in err and "jp_stocks" in err
    assert "portfolio.json missing" not in err


def test_a_wrapper_card_is_not_restored_when_its_previous_items_were_empty():
    """peer_divergence is a dict that stays truthy after its items list empties;
    republishing that is not preservation, it is publishing an empty card as if
    it had been kept."""
    out = {"peer_divergence": {"as_of": "2026-08-04", "items": []}}
    usable = {"peer_divergence": lambda v: isinstance(v, dict) and bool(v.get("items"))}

    empty = dashboard.merge_previous_payload(
        out, {"peer_divergence": {"as_of": "2026-08-01", "items": []}},
        {"peer_divergence": False}, usable=usable)
    assert empty == []
    assert out["peer_divergence"]["as_of"] == "2026-08-04", "must not adopt an empty older card"

    filled = dashboard.merge_previous_payload(
        out, {"peer_divergence": {"as_of": "2026-08-01", "items": [{"ticker": "AAPL"}]}},
        {"peer_divergence": False}, usable=usable)
    assert filled == ["peer_divergence"]
    assert out["peer_divergence"]["items"] == [{"ticker": "AAPL"}]


def test_the_published_source_is_workspace_relative(monkeypatch, tmp_path):
    """Two publishers build this file — the live host and the brief-fallback
    Actions job. An absolute path would differ between them, and semantic_value()
    does not strip it, so the two would alternate a commit for no reader-visible
    change."""
    monkeypatch.setattr(dashboard, "WS_ROOT", tmp_path)

    assert dashboard.workspace_relative(
        tmp_path / "assets" / "data" / "dashboard.json") == "assets/data/dashboard.json"
    assert dashboard.workspace_relative(None) is None


def test_the_empty_case_is_recorded_so_never_fired_has_a_denominator(tmp_path, monkeypatch):
    """Telemetry answers 'has the merge fired in N days'. A line only on the
    interesting case would make silence ambiguous between 'did not fire' and
    'did not build'."""
    monkeypatch.setattr(dashboard, "WS_ROOT", tmp_path)
    (tmp_path / "memory" / ".tmp").mkdir(parents=True)

    at = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    dashboard.record_preservation(
        {"anomalies": True}, [], Path("dashboard.json"), "out.json", at=at)

    # Dated, because gc_sessions ages memory/.tmp out by whole-file mtime: one
    # append-only file would refresh its own mtime forever and never be collected.
    written = sorted(p.name for p in (tmp_path / "memory" / ".tmp").iterdir())
    assert written == ["preserve-absent-2026-08-04.jsonl"]

    line = json.loads((tmp_path / "memory" / ".tmp" / written[0]).read_text())
    assert line["preserved"] == []
    assert line["absent_sources"] == []
    assert line["previous_source"] == "dashboard.json"


def test_telemetry_never_creates_the_directory_or_raises(tmp_path, monkeypatch):
    """A fresh checkout has no memory/.tmp — measurement must not manufacture a
    workspace, and must never be able to fail a publish."""
    monkeypatch.setattr(dashboard, "WS_ROOT", tmp_path)

    dashboard.record_preservation({"anomalies": False}, ["anomalies"], None, "out.json")

    assert not (tmp_path / "memory").exists()


def test_anomaly_order_follows_the_ledger_not_the_brief_context():
    """The high-weight-loss loop appends to a list nothing sorts afterwards, so
    the order it iterates legs in IS the published order of the card.

    The brief-context happens to carry its concentration keys as `hk, us` — the
    reverse of the ledger. Reading legs off that dict looks equivalent and is
    invisible until both legs have an entry on the same day, which is exactly
    when the card would silently reorder.
    """
    brief_ctx = {"concentration": {  # deliberately hk-first, like the real file
        "hk": {"weights": [{"ticker": "09660", "weight_pct": 30.0}]},
        "us": {"weights": [{"ticker": "SOXL", "weight_pct": 30.0}]},
    }}
    us_h = [{"ticker": "SOXL", "pnl_percent": -15.0, "shares": 1}]
    hk_h = [{"ticker": "09660", "pnl_percent": -15.0, "shares": 1}]

    ordered = dashboard.extract_anomalies(
        brief_ctx, us_h, hk_h, leg_keys=["us", "hk"])
    tickers = [a["ticker"] for a in ordered if a["type"] == "high_weight_loss"]
    assert tickers == ["SOXL", "09660"], (
        "leg order must come from the ledger, not from the brief-context's dict")

    reversed_ledger = dashboard.extract_anomalies(
        brief_ctx, us_h, hk_h, leg_keys=["hk", "us"])
    assert [a["ticker"] for a in reversed_ledger
            if a["type"] == "high_weight_loss"] == ["09660", "SOXL"]


def _leg(bucket, key, currency):
    return dashboard.Leg(bucket=bucket, key=key, currency=currency)


def test_the_equity_series_follows_the_ledger_legs_not_us_and_hk():
    """#262 slice 3 acceptance for the snapshot chain: `load_snapshots` writes
    `<leg>_equity` / `<leg>_profit`, and the cards that read them back take the
    same leg list. A ledger of JPY and EUR books gets its own curves."""
    legs = [_leg("jp_stocks", "jp", "JPY"), _leg("eu_stocks", "eu", "EUR")]
    snapshots = [
        {"date": "2026-08-01", "jp_equity": 100.0, "eu_equity": 200.0,
         "jp_profit": 10.0, "eu_profit": 20.0},
        {"date": "2026-08-02", "jp_equity": 110.0, "eu_equity": 180.0,
         "jp_profit": 20.0, "eu_profit": 0.0},
    ]

    delta = dashboard.compute_delta(snapshots, legs=legs)
    assert set(delta) == {"jp", "eu"}
    assert delta["jp"]["today_pct"] == 10.0
    assert delta["eu"]["today_pct"] == -10.0

    dd = dashboard.compute_drawdown(snapshots, fx_rate=2.0, legs=legs)
    assert dd["jp"]["currency"] == "JPY"
    assert dd["eu"]["currency"] == "EUR"
    assert dd["combined"]["currency"] == "EUR", (
        "the combined equity series is denominated in the QUOTE leg's currency")
    assert dd["combined"]["fx_jpyeur"] == 2.0
    assert "us" not in dd and "combined_usd" not in dd


def test_the_legacy_drawdown_keys_keep_their_quote_leg_first_order():
    """`max_pct_30d_*` and `current_pct_*` have always been emitted quote-leg
    first — the reverse of every other block. The payload is serialized unsorted,
    so tidying that would rewrite the whole card for nothing a reader can see."""
    legs = [_leg("jp_stocks", "jp", "JPY"), _leg("eu_stocks", "eu", "EUR")]

    keys = list(dashboard.compute_drawdown([], legs=legs))

    assert keys[:4] == [
        "max_pct_30d_eu", "max_pct_30d_jp", "current_pct_eu", "current_pct_jp",
    ]
    assert keys[4:6] == ["jp", "eu"], "the per-leg block stays in ledger order"


def test_an_explicit_out_dir_keeps_the_generation_together(monkeypatch, tmp_path):
    """#262 slice 3 step 4. The four outputs are one generation, so the thing
    that can actually break here is not "does --out-dir work" but "can a stray
    environment variable move one of the four somewhere else".

    The env redirects are inherited from whatever invoked the build —
    system_check sets one, the Actions validation jobs set others — so a caller
    that named a directory must win over all of them.
    """
    monkeypatch.setenv("BUILD_DASHBOARD_OUT", str(tmp_path / "env" / "dashboard.json"))
    monkeypatch.setenv("DECISION_AUDIT_OUT", str(tmp_path / "env" / "decision_audit.json"))
    monkeypatch.setenv("SHADOW_PORTFOLIO_OUT", str(tmp_path / "env" / "shadow.json"))

    paths = dashboard.resolve_output_paths(tmp_path / "cli")

    assert set(paths) == {"overview", "dashboard", "audit", "shadow"}
    assert {p.parent for p in paths.values()} == {tmp_path / "cli"}, (
        "an inherited redirect must not split one generation across two directories")
    assert sorted(p.name for p in paths.values()) == [
        "dashboard.json", "decision_audit.json", "overview.json", "shadow_portfolio.json",
    ]


def test_without_an_out_dir_the_environment_redirects_still_hold(monkeypatch, tmp_path):
    """system_check's buildability gate redirects the write target so a *check*
    never mutates the published artifact. That behaviour predates --out-dir and
    has to survive it."""
    monkeypatch.setenv("BUILD_DASHBOARD_OUT", str(tmp_path / "check.json"))
    monkeypatch.delenv("DECISION_AUDIT_OUT", raising=False)
    monkeypatch.delenv("SHADOW_PORTFOLIO_OUT", raising=False)

    paths = dashboard.resolve_output_paths()

    assert paths["dashboard"] == tmp_path / "check.json"
    assert paths["overview"] == tmp_path / "overview.json", (
        "the siblings follow the redirected target, not the published directory")
    assert paths["audit"].parent == tmp_path
    assert paths["shadow"].parent == tmp_path


def test_a_named_previous_that_is_not_there_is_reported_not_swallowed(tmp_path, capsys):
    """#314. Both a workspace-only build and a build whose recovery file vanished
    end up with `preserved: []` — they are the same reading and opposite states.

    The one caller where `--previous` does anything is brief-fallback, whose whole
    job is recovery. So the day the path stops resolving — which is the day the
    outputs move off master — recovery stops silently, and the payload still looks
    healthy. This is what makes that visible.
    """
    payload, missing = dashboard.load_previous_payload(tmp_path / "gone.json")

    assert payload is None
    assert missing is True
    assert "does not exist" in capsys.readouterr().err

    present = tmp_path / "there.json"
    present.write_text('{"anomalies": ["kept"]}', encoding="utf-8")
    assert dashboard.load_previous_payload(present) == ({"anomalies": ["kept"]}, False)


def test_the_fresh_checkout_population_is_reported_by_its_only_producer():
    """#302's detector was "scan master's history for a build whose payload has a
    non-empty `build_status.previous_payload.preserved`". #314 replaced that
    history with a force-updated branch holding one generation, so the scan
    cannot be moved — only replaced.

    The replacement is better than what it replaced, and this pins it: the
    population has exactly ONE producer — `brief-fallback.yml`, the only caller
    where `--previous` does anything — so it reports on itself, on the run that
    did it, instead of a corpus scan days later. The host telemetry
    (`memory/.tmp/preserve-absent-*.jsonl`) is blind to this population by
    construction: a runner has no `memory/.tmp`.
    """
    workflow = (ROOT / ".github/workflows/brief-fallback.yml").read_text()

    assert "previous_payload" in workflow, (
        "brief-fallback no longer reports what the recovery restored; the "
        "fresh-checkout population is unobservable again")
    assert "GITHUB_STEP_SUMMARY" in workflow
    # It must run whether or not the build published, and must not be able to
    # fail the job — this is a record, not a gate. Recovering the cards is this
    # workflow's purpose, so doing it is not an error condition.
    report = workflow.split("Report which cards the recovery restored", 1)[1]
    assert "raise SystemExit(0)" in report.split("Commit + push", 1)[0], (
        "a missing payload must end the report, not fail the run")


# --- bear_case ticker resolution (#341) ------------------------------------
#
# `validate_insights` is the hallucination guard for the LLM-authored insights
# sidecar: a bear_case on a name that isn't in the book must never reach the
# public dashboard. On 2026-08-06 that guard also ate a legitimate paired thesis
# written as `RKLX+SPCH` — both real holdings — so a third of the day's bear
# cases vanished with no trace on the page. The guard is about membership, not
# formatting; these pin both halves of that distinction.

def _bear(ticker):
    return {"bear_cases": [{"ticker": ticker, "thesis": "levered pair unwinds together"}]}


def test_composite_bear_case_survives_when_every_component_is_held():
    out = dashboard.validate_insights(_bear("RKLX+SPCH"), {"RKLX", "SPCH", "00100"})
    assert [c["ticker"] for c in out["bear_cases"]] == ["RKLX+SPCH"]


def test_composite_bear_case_is_dropped_when_any_component_is_unknown():
    """The guard must not weaken: one fabricated leg poisons the whole entry."""
    out = dashboard.validate_insights(_bear("RKLX+NVDA"), {"RKLX", "SPCH"})
    assert out["bear_cases"] == []


def test_single_ticker_bear_case_membership_is_unchanged():
    known = {"RKLX", "SPCH"}
    assert dashboard.validate_insights(_bear("RKLX"), known)["bear_cases"][0]["ticker"] == "RKLX"
    assert dashboard.validate_insights(_bear("NVDA"), known)["bear_cases"] == []
