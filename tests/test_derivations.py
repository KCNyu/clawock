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
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WS, "scripts", "data"))

import preflight_integrity as pi  # noqa: E402
import recompute_realized as rr  # noqa: E402
import recompute_aggregates as ra  # noqa: E402
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


# ── CASH_SANITY: a logged deposit/withdrawal must explain a jump, not trip it ──
class TestCashSanityDeposit:
    """The fat-finger gate flags a ≥5× cash jump vs the last snapshot. A *confirmed*
    deposit (HK$30k, 2026-07-07) logged in cash_adjustments must NOT read as a typo,
    while an unlogged jump still must."""

    def _cash_sanity(self, tmp_path, monkeypatch, port, prev):
        monkeypatch.setattr(pi, "_prev_snapshot_cash", lambda region, field: prev)
        data = {"portfolios": {"hk_stocks": {"currency": "HKD", **port}}}
        f = tmp_path / "p.json"
        f.write_text(json.dumps(data))
        rep = pi.check(f)
        return [x for x in rep["findings"] if x["code"] == "CASH_SANITY"]

    def test_logged_deposit_suppresses_jump(self, tmp_path, monkeypatch):
        # 4597 → 34597 is 7.5×, but +30000 logged after the snapshot explains it.
        hits = self._cash_sanity(
            tmp_path, monkeypatch,
            {"cash_hkd": 34597, "cash_adjustments": [{"date": "2026-07-07", "amount": 30000}]},
            (4597.0, "2026-07-06"))
        assert hits == []

    def test_unlogged_jump_still_warns(self, tmp_path, monkeypatch):
        # Same jump, no adjustment logged → still a fat-finger WARN (protection intact).
        hits = self._cash_sanity(
            tmp_path, monkeypatch, {"cash_hkd": 34597}, (4597.0, "2026-07-06"))
        assert len(hits) == 1

    def test_adjustment_not_after_snapshot_does_not_explain(self, tmp_path, monkeypatch):
        # An adjustment dated on/before the snapshot can't explain a later jump
        # (strict-after, same rule as derive_cash) → WARN stands.
        hits = self._cash_sanity(
            tmp_path, monkeypatch,
            {"cash_hkd": 34597, "cash_adjustments": [{"date": "2026-07-06", "amount": 30000}]},
            (4597.0, "2026-07-06"))
        assert len(hits) == 1


# ── TODAY_LEG: a position opened THIS session uses cost (not prev_close) basis ──
class TestTodayLegSameSessionBuild:
    """For a holding bought during the current session you weren't holding it at
    prev_close, so its daily-P&L basis is cost (today_change==current−cost==pnl_abs),
    and shares×(cur−prev_close) doesn't apply — e.g. an IPO first day with no real
    prior close. That case must NOT warn, while a genuinely stale prev_close on a
    normally-held position still must (protection intact)."""

    def _today_leg(self, tmp_path, holding):
        data = {"portfolios": {"us_stocks": {"currency": "USD", "holdings": [holding]}}}
        f = tmp_path / "p.json"
        f.write_text(json.dumps(data))
        rep = pi.check(f)
        return [x for x in rep["findings"] if x["code"] == "TODAY_LEG"]

    def test_ipo_first_day_build_does_not_warn(self, tmp_path):
        # today_change=-0.84 (=current−cost) is CORRECT for a same-session build;
        # shares×(cur−prev_close)=+0.34 would be wrong → exemption suppresses the WARN.
        hits = self._today_leg(tmp_path, {
            "ticker": "IPO1", "shares": 1, "current_price": 168.34, "cost_basis": 169.185,
            "prev_close": 168.004, "prev_close_date": "2026-07-10",
            "day_session_date": "2026-07-10", "today_change": -0.84,
            "trades": [{"date": "2026-07-10", "action": "buy", "shares": 1, "price": 169.185}]})
        assert hits == []

    def test_stale_prev_close_on_held_position_still_warns(self, tmp_path):
        # Held since June, prev_close is a real prior close → formula applies, and a
        # today_change that ignores a 20/sh gap must still trip the gate.
        hits = self._today_leg(tmp_path, {
            "ticker": "OLD1", "shares": 10, "current_price": 100.0, "cost_basis": 90.0,
            "prev_close": 80.0, "prev_close_date": "2026-07-09",
            "day_session_date": "2026-07-10", "today_change": 5.0,
            "trades": [{"date": "2026-06-01", "action": "buy", "shares": 10, "price": 90}]})
        assert len(hits) == 1


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


# ── recompute_aggregates: leaf shares/price/cost → derived fields + region totals ─
class TestRecomputeAggregates:
    def _book(self):
        # one region, two active holdings + one closed (shares 0, must be excluded)
        return {"portfolios": {"us_stocks": {
            "total_current_value": 0, "total_cost": 0, "total_pnl": 0,
            "total_pnl_percent": 0, "today_total_change": 0,
            "holdings": [
                {"ticker": "A", "shares": 10, "cost_basis": 5.0,
                 "current_price": 8.0, "prev_close": 7.0,
                 "current_value": 999, "pnl_abs": 999, "today_change": 999},
                {"ticker": "B", "shares": 4, "cost_basis": 20.0,
                 "current_price": 25.0, "prev_close": 24.0,
                 "current_value": 0, "pnl_abs": 0, "today_change": 0},
                {"ticker": "CLOSED", "shares": 0, "cost_basis": 3.0,
                 "current_price": 1.0, "prev_close": 1.0, "current_value": 123},
            ],
        }}}

    def test_leaf_and_region_derivation(self):
        d = self._book()
        ra.recompute(d, dry_run=False)
        us = d["portfolios"]["us_stocks"]
        A, B, C = us["holdings"]
        # per-holding leaves rebuilt from shares/price/cost
        assert A["current_value"] == 80.0 and A["pnl_abs"] == 30.0 and A["today_change"] == 10.0
        assert B["current_value"] == 100.0 and B["pnl_abs"] == 20.0 and B["today_change"] == 4.0
        # region totals over ACTIVE only (closed C excluded, its stale 123 not summed)
        assert us["total_current_value"] == 180.0          # 80 + 100
        assert us["total_cost"] == 130.0                   # 10*5 + 4*20
        assert us["total_pnl"] == 50.0                     # 180 - 130
        assert us["total_pnl_percent"] == pytest.approx(38.4615, abs=1e-3)
        assert us["today_total_change"] == 14.0            # 10 + 4
        assert C["current_value"] == 123                   # closed holding untouched

    def test_fixes_phantom_peak_drift(self):
        # the real bug (3a68822): a manual T+0 sell left total_current_value inflated.
        d = self._book()
        ra.recompute(d, dry_run=False)                     # make consistent
        d["portfolios"]["us_stocks"]["total_current_value"] += 906.0   # inject drift
        changes = ra.recompute(d, dry_run=False)           # recompute must fix it
        assert d["portfolios"]["us_stocks"]["total_current_value"] == 180.0
        assert "us_stocks" in changes                      # and report it changed

    def test_dry_run_writes_nothing(self):
        d = self._book()
        d["portfolios"]["us_stocks"]["total_current_value"] = 777
        ra.recompute(d, dry_run=True)
        assert d["portfolios"]["us_stocks"]["total_current_value"] == 777  # unchanged
