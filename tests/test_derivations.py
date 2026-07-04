"""Unit tests for the deterministic money-integrity derivations.

These are the pure functions behind bugs that actually shipped (and cost real
reconciliation pain):
  - cash double-count $581 (2026-06-25) → derive_cash
  - SPCH avg-price 18.07 vs 18.37 (2026-06-24) → _moving_avg_cost
  - phantom-peak / negative-% drawdown → _profit_extremes
  - realized_pnl hand-written drift → _aggregate

Historically the ONLY defense here was runtime gates + human review; this file
is the missing regression net. Run: `python3 -m pytest tests/ -q`.
"""
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WS, "scripts", "data"))
sys.path.insert(0, os.path.join(WS, "scripts", "harness"))

import preflight_integrity as pi  # noqa: E402
import recompute_realized as rr  # noqa: E402
import build_dashboard as bd  # noqa: E402


# ── derive_cash: baseline + trades cashflow after baseline + adjustments ──────
class TestDeriveCash:
    def test_no_baseline_returns_none(self):
        # No cash_reconciled baseline → un-derivable → gate must skip (not error).
        assert pi.derive_cash({"holdings": []}) is None
        assert pi.derive_cash({"cash_reconciled": 100}) is None  # missing date

    def test_baseline_only(self):
        port = {"cash_reconciled": 854.25, "cash_reconciled_date": "2026-06-19",
                "holdings": []}
        derived, baseline, bdate, n = pi.derive_cash(port)
        assert derived == 854.25 and baseline == 854.25 and n == 0

    def test_sell_after_baseline_adds_cash(self):
        # A sell AFTER the baseline date returns cash: +shares*price.
        port = {
            "cash_reconciled": 100.0, "cash_reconciled_date": "2026-06-19",
            "holdings": [{"ticker": "X", "trades": [
                {"date": "2026-06-20", "action": "sell", "shares": 10, "price": 5.0},
            ]}],
        }
        derived, _, _, n = pi.derive_cash(port)
        assert derived == 150.0 and n == 1

    def test_buy_after_baseline_spends_cash(self):
        port = {
            "cash_reconciled": 100.0, "cash_reconciled_date": "2026-06-19",
            "holdings": [{"ticker": "X", "trades": [
                {"date": "2026-06-20", "action": "buy", "shares": 4, "price": 5.0},
            ]}],
        }
        derived, _, _, n = pi.derive_cash(port)
        assert derived == 80.0 and n == 1

    def test_trades_on_or_before_baseline_are_excluded(self):
        # The $581 double-count root cause: buys already folded into the baseline
        # must NOT be counted again. Only strictly-after-baseline trades flow.
        port = {
            "cash_reconciled": 100.0, "cash_reconciled_date": "2026-06-19",
            "holdings": [{"ticker": "X", "trades": [
                {"date": "2026-06-19", "action": "buy", "shares": 4, "price": 5.0},   # == baseline day, excluded
                {"date": "2026-06-10", "action": "buy", "shares": 4, "price": 5.0},   # before, excluded
                {"date": "2026-06-20", "action": "buy", "shares": 2, "price": 5.0},   # after → −10
            ]}],
        }
        derived, _, _, n = pi.derive_cash(port)
        assert derived == 90.0 and n == 1

    def test_adjustments_after_baseline(self):
        # Deposits/withdrawals recorded as cash_adjustments after baseline.
        port = {
            "cash_reconciled": 100.0, "cash_reconciled_date": "2026-06-19",
            "holdings": [],
            "cash_adjustments": [
                {"date": "2026-06-20", "amount": 50.0},    # deposit
                {"date": "2026-06-18", "amount": 999.0},   # before baseline → ignored
            ],
        }
        derived, _, _, _ = pi.derive_cash(port)
        assert derived == 150.0


# ── _moving_avg_cost: sells reduce cost at THEN-current avg; avg unchanged ─────
class TestMovingAvgCost:
    def test_simple_average(self):
        trades = [
            {"action": "buy", "shares": 10, "price": 10.0},
            {"action": "buy", "shares": 10, "price": 20.0},
        ]
        avg, sh = pi._moving_avg_cost(trades)
        assert sh == 20 and avg == 15.0

    def test_sell_does_not_move_average(self):
        # SPCH bug: dividing all buys by all bought shares kept T+0-sold cheap lots
        # in the denominator and dragged the average DOWN. Moving-weighted keeps the
        # average flat across a sell.
        trades = [
            {"action": "buy", "shares": 10, "price": 10.0},
            {"action": "buy", "shares": 10, "price": 20.0},   # avg 15
            {"action": "sell", "shares": 5, "price": 30.0},   # avg STILL 15
        ]
        avg, sh = pi._moving_avg_cost(trades)
        assert sh == 15 and avg == pytest.approx(15.0)

    def test_fully_closed_position_avg_none(self):
        trades = [
            {"action": "buy", "shares": 10, "price": 10.0},
            {"action": "sell", "shares": 10, "price": 12.0},
        ]
        avg, sh = pi._moving_avg_cost(trades)
        assert sh == 0 and avg is None


# ── _aggregate: realized_pnl == sum of sell trades' realized_pnl ──────────────
class TestRealizedAggregate:
    def test_sums_sell_realized(self):
        holdings = [
            {"ticker": "A", "trades": [
                {"date": "2026-06-01", "action": "sell", "shares": 5, "price": 3, "realized_pnl": 10.0}]},
            {"ticker": "B", "trades": [
                {"date": "2026-06-02", "action": "sell", "shares": 5, "price": 3, "realized_pnl": -4.5}]},
        ]
        total, note, sells = rr._aggregate(holdings)
        assert total == 5.5 and len(sells) == 2

    def test_buys_and_null_realized_ignored(self):
        holdings = [{"ticker": "A", "trades": [
            {"date": "2026-06-01", "action": "buy", "shares": 5, "price": 3},           # no realized
            {"date": "2026-06-02", "action": "sell", "shares": 5, "price": 4, "realized_pnl": 5.0},
        ]}]
        total, _, sells = rr._aggregate(holdings)
        assert total == 5.0 and len(sells) == 1

    def test_empty(self):
        total, note, sells = rr._aggregate([])
        assert total == 0 and note == "" and sells == []


# ── _profit_extremes: money-only, must not emit a %-of-zero-crossing series ───
class TestProfitExtremes:
    def test_none_on_empty(self):
        assert bd._profit_extremes([]) is None
        assert bd._profit_extremes([("2026-06-01", None)]) is None

    def test_peak_trough_and_drawdown_abs(self):
        series = [
            ("2026-06-01", 100.0),
            ("2026-06-02", 200.0),   # peak
            ("2026-06-03", 50.0),    # trough after peak → drawdown −150
        ]
        r = bd._profit_extremes(series)
        assert r["peak"]["value"] == 200.0 and r["peak"]["date"] == "2026-06-02"
        assert r["trough"]["value"] == 50.0
        # today's shortfall from running peak, absolute, ≤ 0
        assert r["from_peak_abs"] == pytest.approx(-150.0)
        # profit stayed positive the whole span → % drawdown IS meaningful here
        assert r["current_dd_pct"] is not None

    def test_negative_crossing_series_reports_money_not_percent(self):
        # peak +4.8k → trough −25.9k would read −637% as a naive pct → forbidden.
        series = [("d1", 4800.0), ("d2", -25900.0)]
        r = bd._profit_extremes(series)
        assert r["peak"]["value"] == 4800.0 and r["trough"]["value"] == -25900.0
        assert r["from_peak_abs"] == pytest.approx(-30700.0)
        # money-only contract: once the series crosses ≤0, every % field is None
        assert r["current_dd_pct"] is None and r["max_dd_pct"] is None
