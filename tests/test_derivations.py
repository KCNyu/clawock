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
import functools
import json
import os
import sys

import pytest

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WS, "scripts", "data"))

from clawock.portfolio import integrity as pi  # noqa: E402
from clawock.portfolio import realized as rr  # noqa: E402
from clawock.portfolio import aggregates as ra  # noqa: E402
from clawock.publish import dashboard as bd  # noqa: E402


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
        ra.recompute(d, dry_run=False, percent_rounding={"us_stocks": 4})
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
        assert C["current_value"] == 0                     # closed holding sanitized

    def test_an_empty_book_agrees_with_the_quote_writers_and_converges(self):
        """#1856: us_quotes/hk_analysis write 0 on a zero-cost book; recompute
        wrote None, so every fetch/reconcile round flipped the field."""
        from types import SimpleNamespace
        from clawock.publish.dashboard import leg_totals
        d = {"portfolios": {"us_stocks": {
            "holdings": [], "total_current_value": 0, "total_cost": 0,
            "total_pnl": 0, "total_pnl_percent": 0, "today_total_change": 0}}}
        assert "total_pnl_percent" not in ra.recompute(d, dry_run=True)
        ra.recompute(d, dry_run=False)
        us = d["portfolios"]["us_stocks"]
        assert us["total_pnl_percent"] == 0
        assert leg_totals(SimpleNamespace(currency="USD"), us)["pnl_pct"] == 0

    def test_closed_holding_clears_all_stale_mark_to_market_fields(self):
        d = self._book()
        closed = d["portfolios"]["us_stocks"]["holdings"][-1]
        closed.update({
            "pnl_abs": -12.0,
            "pnl_percent": -20.0,
            "today_change": 3.0,
            "today_change_pct": 4.0,
        })

        changes = ra.recompute(d, dry_run=False)

        for field in ("current_value", "pnl_abs", "pnl_percent",
                      "today_change", "today_change_pct"):
            assert closed[field] == 0
            assert f"holdings.{field}" in changes["us_stocks"]

    def test_fixes_phantom_peak_drift(self):
        # the real bug (3a68822): a manual T+0 sell left total_current_value inflated.
        d = self._book()
        ra.recompute(d, dry_run=False, percent_rounding={"us_stocks": 4})
        d["portfolios"]["us_stocks"]["total_current_value"] += 906.0   # inject drift
        changes = ra.recompute(
            d, dry_run=False, percent_rounding={"us_stocks": 4})
        assert d["portfolios"]["us_stocks"]["total_current_value"] == 180.0
        assert "us_stocks" in changes                      # and report it changed

    def test_cost_correction_rebuilds_pnl_percent_beside_pnl_abs(self):
        # #1552: reconcile after a cost fix (10 → 5, price 8) rebuilt pnl_abs
        # to +30 but kept the fetcher's -20%, and a second pass called that
        # consistent. Both come from the same leaves, at the book's precision.
        d = {"portfolios": {
            "us_stocks": {"holdings": [
                {"ticker": "FIX", "shares": 10, "cost_basis": 5.0,
                 "current_price": 8.0, "pnl_abs": -20.0, "pnl_percent": -20.0},
                {"ticker": "ODD", "shares": 3, "cost_basis": 3.0,
                 "current_price": 2.0, "pnl_abs": -3.0, "pnl_percent": -33.3333},
            ]},
            "hk_stocks": {"holdings": [
                {"ticker": "00100", "shares": 100, "cost_basis": 3.0,
                 "current_price": 2.0, "pnl_abs": -100.0, "pnl_percent": -33.33},
            ]},
        }}
        precision = {"us_stocks": 4, "hk_stocks": 2}
        dry = ra.recompute(json.loads(json.dumps(d)), dry_run=True, percent_rounding=precision)
        assert dry["us_stocks"]["holdings.pnl_percent"] == [("FIX", -20.0, 60.0)]
        ra.recompute(d, dry_run=False, percent_rounding=precision)
        fix, odd = d["portfolios"]["us_stocks"]["holdings"]
        assert fix["pnl_abs"] == 30.0 and fix["pnl_percent"] == 60.0
        assert odd["pnl_percent"] == -33.3333                # untouched: already right
        assert d["portfolios"]["hk_stocks"]["holdings"][0]["pnl_percent"] == -33.33
        assert ra.recompute(d, dry_run=False, percent_rounding=precision) == {}

    def test_price_correction_rebuilds_today_change_pct_beside_today_change(self):
        # #1780, the today-leg twin of #1552: 100 sh, prev_close 100, price
        # corrected to 110 → +1000 was rebuilt but the fetcher's stale +5% stayed,
        # and a second pass called that consistent. A fresh lot runs from cost.
        d = {"portfolios": {
            "us_stocks": {"holdings": [
                {"ticker": "FIX", "shares": 100, "cost_basis": 90.0,
                 "current_price": 110.0, "prev_close": 100.0,
                 "today_change": 500.0, "today_change_pct": 5.0},
                {"ticker": "NEW", "shares": 10, "cost_basis": 100.0,
                 "current_price": 105.0, "prev_close": 120.0,
                 "day_session_date": "2026-09-16", "today_change_pct": -12.5,
                 "trades": [{"date": "2026-09-16", "action": "buy", "shares": 10, "price": 100}]},
                # Untouched fetch: the fetcher's pct came from the unrounded
                # quote 1.000049, so the stored price alone would say 0.0.
                {"ticker": "ROUND", "shares": 1000, "cost_basis": 1.0,
                 "current_price": 1.0, "prev_close": 1.0,
                 "today_change": 0.05, "today_change_pct": 0.0049},
                # A penny quote the fetcher saw as 0.100049 over 0.049951
                # stores as 0.1/0.05; its +100.2943% stays.
                {"ticker": "PENNY", "shares": 10, "cost_basis": 1.0,
                 "current_price": 0.1, "prev_close": 0.05,
                 "today_change": 0.5, "today_change_pct": 100.2943},
                # A fresh lot runs from its exact cost: a correction to 101 moves
                # +0% to +1% even at a price where rounding alone could not.
                {"ticker": "LOT", "shares": 100, "cost_basis": 100.0,
                 "current_price": 101.0, "prev_close": 101.0,
                 "day_session_date": "2026-09-16", "today_change": 0.0, "today_change_pct": 0.0,
                 "trades": [{"date": "2026-09-16", "action": "buy", "shares": 100, "price": 100}]},
                # A sub-cent correction (1.0000 → 1.0010 on one share) leaves the
                # amount at 0.00 but still moves the percentage.
                {"ticker": "TICK", "shares": 1, "cost_basis": 1.0,
                 "current_price": 1.001, "prev_close": 1.0,
                 "today_change": 0.0, "today_change_pct": 0.0},
            ]},
            "hk_stocks": {"holdings": [
                {"ticker": "00100", "shares": 100, "cost_basis": 3.0,
                 "current_price": 2.0, "prev_close": 3.0, "today_change_pct": -33.33},
                # No 3-decimal pair around 100.000/100.000 reaches +0.01%.
                {"ticker": "00200", "shares": 100, "cost_basis": 90.0,
                 "current_price": 100.0, "prev_close": 100.0, "today_change_pct": 0.01},
            ]},
        }}
        precision = {"us_stocks": 4, "hk_stocks": 2}
        prices = {"us_stocks": 4, "hk_stocks": 3}
        rebuild = functools.partial(ra.recompute, percent_rounding=precision, price_rounding=prices)
        dry = rebuild(json.loads(json.dumps(d)), dry_run=True)
        assert dry["us_stocks"]["holdings.today_change_pct"] == [
            ("FIX", 5.0, 10.0), ("NEW", -12.5, 5.0), ("LOT", 0.0, 1.0), ("TICK", 0.0, 0.1)]
        assert dry["us_stocks"]["holdings.today_change"][0] == ("FIX", 500.0, 1000.0)
        rebuild(d, dry_run=False)
        fix, new, rnd, penny, lot, tick = d["portfolios"]["us_stocks"]["holdings"]
        assert penny["today_change_pct"] == 100.2943 and lot["today_change_pct"] == 1.0
        assert fix["today_change"] == 1000.0 and fix["today_change_pct"] == 10.0
        assert new["today_change"] == 50.0 and new["today_change_pct"] == 5.0
        assert rnd["today_change_pct"] == 0.0049
        assert tick["today_change_pct"] == 0.1
        hk_kept, hk_stale = d["portfolios"]["hk_stocks"]["holdings"]
        assert hk_kept["today_change_pct"] == -33.33 and hk_stale["today_change_pct"] == 0
        assert rebuild(d, dry_run=False) == {}

    def test_position_bought_this_session_keeps_the_cost_basis_day_change(self):
        # #1527: the US fetcher writes today_change from cost for a lot bought
        # entirely this session (10@100, now 105 → +50); reconcile must not
        # rebuild it from a prev_close (120) the book never held at.
        d = {"portfolios": {"us_stocks": {"holdings": [
            {"ticker": "NEW", "shares": 10, "cost_basis": 100.0,
             "current_price": 105.0, "prev_close": 120.0,
             "day_session_date": "2026-09-16", "today_change": 50.0,
             "trades": [{"date": "2026-09-16", "action": "buy", "shares": 10, "price": 100}]},
            # re-entry: an earlier sold-out lot doesn't make today's lot old,
            # but a lot still partly held from before does.
            {"ticker": "PART", "shares": 10, "cost_basis": 100.0,
             "current_price": 105.0, "prev_close": 120.0,
             "day_session_date": "2026-09-16",
             "trades": [{"date": "2026-09-01", "action": "buy", "shares": 5, "price": 100},
                        {"date": "2026-09-16", "action": "buy", "shares": 5, "price": 100}]},
        ]}}}
        ra.recompute(d, dry_run=False)
        new, part = d["portfolios"]["us_stocks"]["holdings"]
        assert new["today_change"] == 50.0
        assert part["today_change"] == -150.0
        assert d["portfolios"]["us_stocks"]["today_total_change"] == -100.0

    def test_dry_run_writes_nothing(self):
        d = self._book()
        d["portfolios"]["us_stocks"]["total_current_value"] = 777
        ra.recompute(d, dry_run=True)
        assert d["portfolios"]["us_stocks"]["total_current_value"] == 777  # unchanged
