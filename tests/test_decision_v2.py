import copy
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "growth"))
from clawock import sessions as _cal
from clawock.decision import ledger as dv2
from clawock.harness.intraday_watchdog import deterministic_fallback as intraday_fallback
from clawock.harness.report_watchdog import deterministic_fallback as report_fallback


def test_decision_engine_is_owned_by_the_product_package():
    assert Path(dv2.__file__).relative_to(ROOT).as_posix() == "src/clawock/decision/ledger.py"
    assert not (ROOT / "scripts" / "data" / "decision_v2.py").exists()


def test_malformed_legacy_horizon_falls_back_to_one_session():
    row = dv2.legacy_action_to_decision({
        "ticker": "AAA", "action": "cut", "size": {"shares": 1},
        "horizon_sessions": "abc", "confidence": 0.8,
    }, "2026-09-26")
    assert row["horizon_sessions"] == 1


def test_technical_add_trace_fields_survive_normalization_and_validate():
    row = dv2.legacy_action_to_decision({
        "ticker": "AAA", "strategy_id": "tactical_entry",
        "action": "add_only_on_trigger",
        "condition": {"type": "price_above", "price": 10},
        "size": {"shares": 1}, "confidence": 0.6,
        "driven_by": "technical",
        "technical_setup_id": "trend_pullback",
        "technical_campaign_id": "trend_pullback:2026-07-01",
        "invalidation_price": 9,
        "tranche_number": 1,
    }, "2026-07-01")
    row["episode_id"] = "ep-test"

    assert row["technical_setup_id"] == "trend_pullback"
    assert row["technical_campaign_id"] == "trend_pullback:2026-07-01"
    assert row["invalidation_price"] == 9
    assert row["tranche_number"] == 1
    assert dv2.validate_decision(row) == []


def test_an_add_on_its_own_entry_states_what_it_bets_on_and_where_it_is_wrong():
    row = dv2.legacy_action_to_decision({
        "ticker": "AAA", "strategy_id": "tactical_entry",
        "action": "add_only_on_trigger",
        "condition": {"type": "price_above", "price": 10},
        "size": {"shares": 1}, "confidence": 0.6,
        "driven_by": "technical",
    }, "2026-07-01")
    row["episode_id"] = "ep-test"

    issues = dv2.validate_decision(row)

    # No registered setup is required (#2842); a hypothesis and the level at
    # which the add is wrong are.
    assert issues == [
        "technical add requires invalidation_price",
        "technical add without a technical_setup_id requires hypothesis",
    ]
    row.update(invalidation_price=9.0, hypothesis="站回 20 日线说明抛压出清")
    assert dv2.validate_decision(row) == []
    # Naming a registered setup still carries that setup's trace.
    row["technical_setup_id"] = "trend_pullback"
    assert dv2.validate_decision(row) == [
        "technical add requires technical_campaign_id",
        "technical add requires tranche_number >= 1",
    ]


def test_legacy_technical_add_remains_readable_without_new_trace_contract():
    row = dv2.legacy_action_to_decision({
        "ticker": "AAA", "strategy_id": "tactical_entry",
        "action": "add_only_on_trigger",
        "condition": {"type": "price_above", "price": 10},
        "size": {"shares": 1}, "confidence": 0.6,
        "driven_by": "technical",
    }, "2026-07-01")
    row["episode_id"] = "ep-test"
    row.pop("technical_trace_version")

    assert dv2.validate_decision(row) == []


def test_metrics_attribute_settled_technical_adds_to_the_named_setup():
    row = decision(
        "2026-07-01", strategy="tactical_entry",
        action="add_only_on_trigger", benefit=2.5,
    )
    row["technical_setup_id"] = "trend_pullback"

    metrics = dv2.compute_metrics([row], window_days=365)

    assert metrics["by_technical_setup"]["trend_pullback"]["n_episodes"] == 1
    assert metrics["by_technical_setup"]["trend_pullback"]["avg_benefit_pct"] == 2.5


def test_metrics_attribute_packet_time_overlay_at_three_horizons():
    base = decision(
        "2026-07-01", strategy="tactical_entry",
        action="add_only_on_trigger", benefit=1.0,
    )
    base["technical_setup_id"] = "trend_pullback"
    base["signal_provenance"] = {
        "schema_version": 1,
        "sizing": {"sizing_active": False, "contributors": []},
    }
    base["evaluation"]["benefit_t20_pct"] = 3.0
    informed = copy.deepcopy(base)
    informed["decision_id"] = "dec-informed"
    informed["episode_id"] = "ep-informed"
    informed["ticker"] = "BBB"
    informed["signal_provenance"]["sizing"] = {
        "sizing_active": True,
        "sizing_multiplier": 1.2,
        "contributors": ["information_positive_surprise"],
    }
    informed["evaluation"].update(
        benefit_t1_pct=2.0, benefit_t5_pct=4.0, benefit_t20_pct=8.0,
    )

    overlay = dv2.compute_metrics(
        [base, informed], window_days=365
    )["information_overlay"]

    assert overlay["n_eligible_decisions"] == 2
    assert overlay["horizons"]["t1"]["cohorts"]["setup_only"]["n_settled"] == 1
    assert overlay["horizons"]["t5"]["cohorts"]["setup_plus_information"]["avg_benefit_pct"] == 4.0
    assert overlay["horizons"]["t20"]["contributors"]["information_positive_surprise"]["avg_benefit_pct"] == 8.0


def decision(day, ticker="AAA", strategy="core_position", action="hold_and_watch",
             benefit=1.0, triggered=True, capital=100.0):
    d = dv2.legacy_action_to_decision({
        "ticker": ticker, "strategy_id": strategy, "action": action,
        "condition": {"type": "open"}, "confidence": 0.6,
        "driven_by": "technical",
    }, day)
    d["evaluation"] = {
        "status": "settled", "triggered": triggered,
        "benefit_t1_pct": benefit if triggered else None,
        "benefit_t5_pct": benefit if triggered else None,
        "outcome": "win" if benefit and benefit > 0 else "loss",
        "capital": capital,
    }
    return d


def _bar(o, h=None, l=None, c=None):
    o = float(o)
    return {"open": o, "high": float(h if h is not None else o),
            "low": float(l if l is not None else o), "close": float(c if c is not None else o)}


def _with_bars(bars, sessions=None, leg="US"):
    """Patch the canonical bar store. ``bars`` is {date: bar}."""
    days = sorted(sessions or bars)
    return (mock.patch.object(dv2, "load_ticker_bars", return_value=bars),
            mock.patch.object(dv2, "leg_sessions", return_value=days),
            mock.patch.object(dv2, "is_session", side_effect=lambda lg, d: d in days))


def _settle_against(now_date, t1_price, action="cut", condition=None, bars=None,
                    plan_date="2026-07-01", ticker="AAA"):
    """Settle one call against canonical bars rather than a portfolio snapshot."""
    row = dv2.legacy_action_to_decision({
        "ticker": ticker, "strategy_id": "core_position", "action": action,
        "condition": condition or {"type": "open"}, "confidence": 0.6,
        "driven_by": "technical",
    }, plan_date)
    store = bars or {"2026-07-01": _bar(10.0), "2026-07-02": _bar(t1_price)}
    patches = _with_bars(store)
    for p in patches:
        p.start()
    try:
        dv2.settle_decisions([row], now_date=now_date)
    finally:
        for p in patches:
            p.stop()
    return row["evaluation"]


class UnfinishedSessionTest(unittest.TestCase):
    """A session that has not closed must never score a call."""

    def test_todays_session_never_settles(self):
        self.assertEqual(_settle_against("2026-07-02", 9.0)["outcome"], "pending")

    def test_the_tape_cannot_move_a_settled_record(self):
        # The bug: on 07-02 intraday this call read 'win' at one print and 'loss'
        # at the next. Pending at both is the whole point.
        up = _settle_against("2026-07-02", 9.0)     # cut, stock down -> would win
        down = _settle_against("2026-07-02", 11.0)  # cut, stock up   -> would lose
        self.assertEqual(up["outcome"], down["outcome"])
        self.assertIsNone(up["benefit_t1_pct"])

    def test_a_finalised_session_still_settles(self):
        ev = _settle_against("2026-07-03", 9.0)
        self.assertEqual(ev["outcome"], "win")       # cut at 10, next close 9
        self.assertEqual(ev["benefit_t1_pct"], 10.0)


class CanonicalBarSettlementTest(unittest.TestCase):
    """The defects that made snapshot-based settlement wrong, as fixtures."""

    def test_gap_through_a_sell_trigger_fills_at_the_open_not_the_trigger(self):
        # 00100 2026-06-22: trigger 'rebound above 480', real bar opened at 520.
        # Assuming a 480 fill invents a worse sale than was ever available and
        # booked a real winner as a loss.
        ev = _settle_against("2026-07-03", None, action="trim_on_rebound",
                             condition={"type": "price_above", "price": 480.0},
                             bars={"2026-07-01": _bar(520, 637.5, 502, 616.5),
                                   "2026-07-02": _bar(515, 515, 515, 515)})
        self.assertEqual(ev["execution_price"], 520.0)
        self.assertEqual(ev["fill_reason"], "gap_through")
        self.assertEqual(ev["outcome"], "win")

    def test_intraday_cross_fills_at_the_trigger(self):
        ev = _settle_against("2026-07-03", None, action="trim_on_rebound",
                             condition={"type": "price_above", "price": 480.0},
                             bars={"2026-07-01": _bar(470, 500, 465, 495),
                                   "2026-07-02": _bar(460, 460, 460, 460)})
        self.assertEqual(ev["execution_price"], 480.0)
        self.assertEqual(ev["fill_reason"], "intraday_cross")

    def test_touching_the_trigger_exactly_counts_as_fired(self):
        ev = _settle_against("2026-07-03", None, action="trim_on_rebound",
                             condition={"type": "price_above", "price": 500.0},
                             bars={"2026-07-01": _bar(470, 500.0, 465, 495),
                                   "2026-07-02": _bar(460, 460, 460, 460)})
        self.assertIs(ev["triggered"], True)

    def test_a_high_below_the_trigger_is_not_triggered(self):
        # 07226 2026-05-27: stored day_high 4.192 was carried over from an earlier
        # session and said TRIGGERED; the real high was 3.96 and it never fired.
        ev = _settle_against("2026-07-03", None, action="cut",
                             condition={"type": "price_above", "price": 4.10},
                             bars={"2026-07-01": _bar(3.934, 3.96, 3.776, 3.808),
                                   "2026-07-02": _bar(3.8, 3.8, 3.8, 3.8)})
        self.assertIs(ev["triggered"], False)
        self.assertEqual(ev["status"], "not_triggered")

    def test_a_sell_below_trigger_gap_fills_at_the_open(self):
        ev = _settle_against("2026-07-03", None, action="cut",
                             condition={"type": "price_below", "price": 100.0},
                             bars={"2026-07-01": _bar(92, 95, 90, 93),
                                   "2026-07-02": _bar(94, 94, 94, 94)})
        self.assertEqual(ev["execution_price"], 92.0)   # never 100
        self.assertEqual(ev["fill_reason"], "gap_through")

    def test_zero_benefit_is_flat_not_loss(self):
        ev = _settle_against("2026-07-03", 10.0)   # cut at 10, next close 10
        self.assertEqual(ev["outcome"], "flat")

    def test_a_hold_records_a_reference_price_never_a_fill(self):
        ev = _settle_against("2026-07-03", 11.0, action="hold_and_watch")
        self.assertEqual(ev["evaluation_mode"], "passive_stance")
        self.assertEqual(ev["reference_price"], 10.0)
        self.assertIsNone(ev.get("execution_price"))
        self.assertFalse(ev["fill_assumed"])
        self.assertEqual(ev["condition_role"], "invalidation")

    def test_t1_skips_a_closed_session_instead_of_borrowing_it(self):
        # 2026-06-19 was closed on both legs; the old code graded 06-18 calls
        # against its snapshot, which had not moved.
        bars = {"2026-06-18": _bar(19.74, 20.07, 16.27, 18.97),
                "2026-06-22": _bar(13.0, 13.0, 12.0, 12.68)}
        ev = _settle_against("2026-07-03", None, action="cut", plan_date="2026-06-18",
                             bars=bars)
        self.assertEqual(ev["mark_t1_session"], "2026-06-22")
        self.assertEqual(ev["outcome"], "win")

    def test_a_weekday_holiday_is_not_rolled_forward(self):
        row = dv2.legacy_action_to_decision({
            "ticker": "AAA", "strategy_id": "core_position", "action": "cut",
            "condition": {"type": "open"}, "confidence": 0.6, "driven_by": "technical",
        }, "2026-07-03")
        with mock.patch.object(dv2, "is_session", side_effect=lambda lg, d: d != "2026-07-03"):
            sess, reason = dv2.evaluation_session(row)
        self.assertIsNone(sess)
        self.assertEqual(reason, "market_closed")

    def test_a_weekend_brief_is_graded_on_the_next_session(self):
        row = dv2.legacy_action_to_decision({
            "ticker": "AAA", "strategy_id": "core_position", "action": "cut",
            "condition": {"type": "open"}, "confidence": 0.6, "driven_by": "technical",
        }, "2026-05-17")   # a Sunday
        with mock.patch.object(dv2, "is_session", side_effect=lambda lg, d: d == "2026-05-18"):
            sess, reason = dv2.evaluation_session(row)
        self.assertEqual(sess, "2026-05-18")
        self.assertEqual(reason, "weekend_brief_graded_next_session")

    def test_a_decision_authored_after_its_plan_date_is_quarantined(self):
        row = dv2.legacy_action_to_decision({
            "ticker": "AAA", "strategy_id": "core_position", "action": "cut",
            "condition": {"type": "open"}, "confidence": 0.6, "driven_by": "technical",
            "created_at": "2026-06-02T08:00:00+08:00",
        }, "2026-06-01")
        sess, reason = dv2.evaluation_session(row)
        self.assertIsNone(sess)
        self.assertEqual(reason, "invalid_authored_timestamp")


class DecisionAuditSidecarTest(unittest.TestCase):
    def _executed(self, ticker, leg, action, shares, price, close, day="2026-07-01"):
        row = dv2.legacy_action_to_decision({
            "ticker": ticker,
            "leg": leg,
            "strategy_id": "core_position",
            "action": action,
            "condition": {"type": "open", "description": "authored condition"},
            "size": {"shares": shares},
            "confidence": 0.7,
            "driven_by": "technical",
            "rationale": "authored rationale",
        }, day)
        row["evaluation"] = {
            "status": "settled",
            "outcome": "win",
            "triggered": True,
            "trigger_session": day,
            "execution_price": price + 99,  # OHLC assumption, deliberately not real
            "fill_assumed": True,
            "fill_reason": "intraday_cross",
            "fill_model": "daily_ohlc_gap_aware_v1",
            "mark_t1_session": "2026-07-02",
            "mark_t5_session": "2026-07-03",
        }
        row["execution"] = {"status": "followed", "source": "manual"}
        trade_action = "sell" if action in dv2.SELL_ACTIONS else "buy"
        holding = {
            "ticker": ticker,
            "trades": [{
                "date": day, "action": trade_action, "shares": shares, "price": price,
            }],
        }
        bars = {
            day: _bar(close, close + 1, close - 1, close),
            "2026-07-02": _bar(close + 1),
            "2026-07-03": _bar(close + 2),
        }
        return row, holding, bars

    def test_audit_preserves_authored_text_all_states_and_canonical_path(self):
        settled, holding, bars = self._executed(
            "00100", "HK", "cut", 20, 105, 100)
        rows = [settled]
        for state in ("not_triggered", "not_evaluable", "pending"):
            row = copy.deepcopy(settled)
            row["decision_id"] = f"dec-{state}"
            row["evaluation"] = {"status": state, "outcome": state}
            row["execution"] = {"status": "unknown"}
            rows.append(row)
        portfolio = {
            "portfolios": {
                "hk_stocks": {"holdings": [holding]},
                "us_stocks": {"holdings": []},
            }
        }

        with mock.patch.object(dv2, "load_ticker_bars", return_value=bars):
            sidecar = dv2.build_audit_sidecar(
                rows, portfolio, as_of="2026-07-17T12:00:00+08:00")

        self.assertEqual(sidecar["schema_version"], 1)
        self.assertEqual(sidecar["primary_key"], "decision_id")
        self.assertEqual(
            set(sidecar["state_counts"]),
            {"settled", "not_triggered", "not_evaluable", "pending"})
        record = next(r for r in sidecar["records"]
                      if r["decision_id"] == settled["decision_id"])
        self.assertEqual(record["authored"]["rationale"], "authored rationale")
        self.assertEqual(
            record["authored"]["condition"]["description"], "authored condition")
        self.assertEqual(record["execution"]["actual"]["price"], 105.0)
        self.assertEqual(
            record["execution"]["ohlc_assumption"]["price"], 204.0)
        self.assertEqual(record["fill_model"], "real_portfolio_trade")
        self.assertTrue(record["coverage"]["canonical_only"])
        self.assertEqual(
            [point["close"] for point in record["path"]],
            [100.0, 101.0, 102.0])

    def test_timing_diagnostic_uses_real_fill_vs_same_day_close_per_currency(self):
        hk, hk_holding, hk_bars = self._executed(
            "00100", "HK", "cut", 20, 105, 100)
        us, us_holding, us_bars = self._executed(
            "MSFT", "US", "add_only_on_trigger", 2, 95, 100)
        portfolio = {
            "portfolios": {
                "hk_stocks": {"holdings": [hk_holding]},
                "us_stocks": {"holdings": [us_holding]},
            }
        }

        def bars_for(ticker):
            return hk_bars if ticker == "00100" else us_bars

        with mock.patch.object(dv2, "load_ticker_bars", side_effect=bars_for):
            diagnostic = dv2.compute_timing_diagnostic([hk, us], portfolio)

        hk_event = diagnostic["by_currency"]["HKD"]["events"][0]
        us_event = diagnostic["by_currency"]["USD"]["events"][0]
        self.assertEqual(hk_event["improvement_amount"], 100.0)
        self.assertEqual(hk_event["improvement_bps"], 500.0)
        self.assertEqual(us_event["improvement_amount"], 10.0)
        self.assertEqual(us_event["improvement_bps"], 500.0)
        self.assertEqual(diagnostic["by_currency"]["HKD"]["median_bps"], 500.0)
        self.assertEqual(diagnostic["by_currency"]["USD"]["median_bps"], 500.0)
        self.assertNotIn("combined", diagnostic)
        self.assertTrue(diagnostic["cross_ticker_swaps_excluded"])

    def test_ambiguous_trade_is_not_attributed_without_transaction_id(self):
        first, holding, bars = self._executed(
            "00100", "HK", "cut", 20, 105, 100)
        second = copy.deepcopy(first)
        second["decision_id"] = "dec-second"
        portfolio = {
            "portfolios": {
                "hk_stocks": {"holdings": [holding]},
                "us_stocks": {"holdings": []},
            }
        }
        with mock.patch.object(dv2, "load_ticker_bars", return_value=bars):
            diagnostic = dv2.compute_timing_diagnostic([first, second], portfolio)
        self.assertEqual(diagnostic["by_currency"]["HKD"]["n_events"], 0)

    def test_resettling_twice_is_idempotent(self):
        bars = {"2026-07-01": _bar(10.0), "2026-07-02": _bar(9.0)}
        row = dv2.legacy_action_to_decision({
            "ticker": "AAA", "strategy_id": "core_position", "action": "cut",
            "condition": {"type": "open"}, "confidence": 0.6, "driven_by": "technical",
        }, "2026-07-01")
        patches = _with_bars(bars)
        for p in patches:
            p.start()
        try:
            dv2.settle_decisions([row], now_date="2026-07-03")
            first = copy.deepcopy(row["evaluation"])
            dv2.settle_decisions([row], now_date="2026-07-03")
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(first, row["evaluation"])


class DecisionV2Test(unittest.TestCase):
    def test_same_ticker_same_day_different_strategies_are_separate(self):
        rows = [decision("2026-07-01", strategy="core_position"),
                decision("2026-07-01", strategy="intraday_t", action="t_only")]
        dv2.assign_episode_ids(rows)
        self.assertNotEqual(rows[0]["episode_id"], rows[1]["episode_id"])

    def test_reaffirmation_continues_episode_but_action_change_does_not(self):
        rows = [decision("2026-07-01"), decision("2026-07-02"),
                decision("2026-07-03", action="cut")]
        dv2.assign_episode_ids(rows)
        self.assertEqual(rows[0]["episode_id"], rows[1]["episode_id"])
        self.assertNotEqual(rows[1]["episode_id"], rows[2]["episode_id"])

    def test_an_interleaved_hold_does_not_shatter_a_running_cut(self):
        # The model shouts cut for weeks and wobbles into hold on the quiet days.
        # That is one opinion, not two independent bets (v1's disease).
        rows = [decision("2026-07-01", action="cut"),
                decision("2026-07-02", action="hold_and_watch"),
                decision("2026-07-03", action="cut")]
        dv2.assign_episode_ids(rows)
        self.assertEqual(rows[0]["episode_id"], rows[2]["episode_id"])
        self.assertNotEqual(rows[0]["episode_id"], rows[1]["episode_id"])

    def test_a_reissued_action_after_a_long_silence_is_a_new_episode(self):
        rows = [decision("2026-07-01", action="cut"),
                decision("2026-07-20", action="cut")]
        dv2.assign_episode_ids(rows)
        self.assertNotEqual(rows[0]["episode_id"], rows[1]["episode_id"])

    def test_existing_episode_is_continued_by_new_decision(self):
        first = decision("2026-07-01")
        dv2.assign_episode_ids([first])
        second = decision("2026-07-02")
        dv2.assign_episode_ids([first, second])
        self.assertEqual(first["episode_id"], second["episode_id"])

    def test_only_triggered_episode_representative_counts_once(self):
        rows = [decision("2026-07-01", benefit=2), decision("2026-07-02", benefit=-3)]
        dv2.assign_episode_ids(rows)
        reps = dv2.episode_representatives(rows)
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0]["plan_date"], "2026-07-01")

    def test_zero_mean_episode_is_flat_not_loss(self):
        # An episode whose settled calls average to exactly zero is a wash, not a
        # loss — the per-decision contract (_outcome) already draws that line and the
        # episode representative must reuse it, not reintroduce the old fall-through.
        rows = [decision("2026-07-01", benefit=1), decision("2026-07-02", benefit=-1)]
        dv2.assign_episode_ids(rows)
        reps = dv2.episode_representatives(rows)
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0]["evaluation"]["benefit_t1_pct"], 0.0)
        self.assertEqual(reps[0]["evaluation"]["outcome"], "flat")

    def test_active_passive_split_classifies_watch_passive(self):
        # The dashboard must classify active vs passive consistently, or it
        # publishes two different "active win rate"s. `watch` is a standing
        # stance and settles passively, so it must not count as active.
        # (The rick_broadcast cross-check was removed with the module in #592;
        # dv2.ACTIVE_ACTIONS/PASSIVE_ACTIONS are now the single source.)
        self.assertNotIn("watch", dv2.ACTIVE_ACTIONS)
        self.assertIn("watch", dv2.PASSIVE_ACTIONS)

    def test_backtest_method_matches_the_real_episode_rule(self):
        # The published method string must describe how episodes are actually formed;
        # it used to claim a moved trigger starts a new one, which is the rejected
        # design that fabricated independent wins.
        method = dv2.compute_backtest([decision("2026-07-01", action="cut", benefit=1)])["method"]
        self.assertNotIn("a moved trigger starts a new episode", method)
        self.assertIn("ticker, strategy, action", method)

    def test_untriggered_and_manual_are_not_scored(self):
        row = decision("2026-07-01", triggered=False)
        dv2.assign_episode_ids([row])
        self.assertEqual(dv2.episode_representatives([row]), [])
        manual = dv2.legacy_action_to_decision({
            "ticker": "AAA", "strategy_id": "event_trade", "action": "cut",
            "condition": {"type": "manual"}, "confidence": .5, "driven_by": "catalyst"
        }, "2026-07-01")
        self.assertEqual(dv2.condition_execution(manual, _bar(10.0)),
                         (None, None, "needs_human_evidence"))

    def test_degenerate_bar_is_not_trigger_evidence(self):
        active = dv2.legacy_action_to_decision({
            "ticker": "AAA", "strategy_id": "tactical_entry",
            "action": "add_only_on_trigger",
            "condition": {"type": "price_above", "price": 10},
            "confidence": .6, "driven_by": "technical",
        }, "2026-07-01")
        halted = {**_bar(12.0), "degenerate": True}

        self.assertEqual(
            dv2.condition_execution(active, halted),
            (None, None, "degenerate_bar"),
        )

    def test_settlement_does_not_invalidate_an_add_on_a_degenerate_bar(self):
        halted = {**_bar(9.0), "degenerate": True}
        row = dv2.legacy_action_to_decision({
            "ticker": "AAA", "strategy_id": "tactical_entry",
            "action": "add_only_on_trigger",
            "condition": {"type": "price_above", "price": 12},
            "invalidation_price": 10,
            "confidence": .6, "driven_by": "technical",
        }, "2026-07-01")
        patches = _with_bars({"2026-07-01": halted})
        for patch in patches:
            patch.start()
        try:
            dv2.settle_decisions([row], now_date="2026-07-02")
        finally:
            for patch in patches:
                patch.stop()

        self.assertEqual(row["evaluation"]["status"], "not_evaluable")
        self.assertEqual(
            row["evaluation"]["not_evaluable_reason"], "degenerate_bar")
        self.assertEqual(row["evaluation"]["evaluation_schema_version"], 7)
        self.assertNotEqual(
            row["evaluation"].get("not_evaluable_reason"), "campaign_invalidated")

    def test_settlement_can_trigger_on_a_later_real_bar_in_the_window(self):
        halted = {**_bar(12.0), "degenerate": True}
        bars = {
            "2026-07-01": halted,
            "2026-07-02": _bar(10.0, h=12.5, l=9.5, c=12.0),
            "2026-07-03": _bar(11.0),
        }
        ev = _settle_against(
            "2026-07-04", 11.0,
            condition={
                "type": "price_above", "price": 12,
                "valid_for_sessions": 2,
            },
            bars=bars,
        )

        self.assertTrue(ev["triggered"])
        self.assertEqual(ev["trigger_session"], "2026-07-02")
        self.assertEqual(ev["execution_price"], 12.0)

    def test_a_real_bar_that_misses_still_settles_next_to_a_halted_one(self):
        """The mirror of the case above: a real bar is evidence either way.

        Letting the halted session rewrite a measured miss into
        `not_evaluable` turns "did not trigger" into "no evidence" — the two
        are mutually exclusive everywhere downstream (the calibration stats in
        `brief_preflight` count `not_triggered` and skip `unknown`; the
        scorecard counts `not_evaluable` as uncovered) — and it points
        `trigger_session` at a day that never traded.
        """
        halted = {**_bar(12.0), "degenerate": True}
        bars = {"2026-07-01": halted, "2026-07-02": _bar(10.0)}
        ev = _settle_against(
            "2026-07-03", 10.0,
            action="add_only_on_trigger",
            condition={"type": "price_above", "price": 12,
                       "valid_for_sessions": 2},
            bars=bars,
        )

        self.assertIs(ev["triggered"], False)
        self.assertEqual(ev["status"], "not_triggered")
        self.assertEqual(ev["outcome"], "not_triggered")
        self.assertEqual(ev["fill_reason"], "high_below_trigger")
        self.assertIsNone(ev["trigger_session"])
        self.assertNotIn("not_evaluable_reason", ev)

    def test_a_halted_session_does_not_close_an_open_confirmation_window(self):
        """Same narrowing, the other neighbour: with the window still open a
        real miss is pending, not an unknown the halted bar forced."""
        halted = {**_bar(12.0), "degenerate": True}
        row = dv2.legacy_action_to_decision({
            "ticker": "AAA", "strategy_id": "tactical_entry",
            "action": "add_only_on_trigger",
            "condition": {"type": "price_above", "price": 12,
                          "valid_for_sessions": 3},
            "confidence": .6, "driven_by": "technical",
        }, "2026-07-01")
        patches = _with_bars(
            {"2026-07-01": halted, "2026-07-02": _bar(10.0)},
            sessions=["2026-07-01", "2026-07-02", "2026-07-03"])
        for patch in patches:
            patch.start()
        try:
            dv2.settle_decisions([row], now_date="2026-07-03")
        finally:
            for patch in patches:
                patch.stop()

        self.assertEqual(row["evaluation"]["status"], "pending")
        self.assertEqual(row["evaluation"]["pending_reason"],
                         "confirmation_window_open")

    def test_backtest_is_capital_weighted_and_compounded(self):
        rows = [decision("2026-07-01", action="cut", benefit=10, capital=900),
                decision("2026-07-01", ticker="BBB", action="cut", benefit=-10, capital=100),
                decision("2026-07-02", ticker="CCC", action="cut", benefit=10, capital=100)]
        dv2.assign_episode_ids(rows)
        curve = dv2.compute_backtest(rows)["horizons"]["t1"]["active_curve"]
        self.assertAlmostEqual(curve[0]["daily_benefit_pct"], 8.0)
        self.assertAlmostEqual(curve[-1]["compounded_benefit_pct"], 18.8)

    def test_backtest_preserves_complete_ai_line_including_migrated_holds(self):
        rows = [decision("2026-07-01", action="hold_and_watch", benefit=4),
                decision("2026-07-02", ticker="BBB", action="cut", benefit=-2)]
        dv2.assign_episode_ids(rows)
        bt = dv2.compute_backtest(rows)["horizons"]["t1"]
        self.assertEqual(bt["all"]["n_episodes"], 2)
        self.assertEqual(bt["active"]["n_episodes"], 1)
        self.assertEqual(len(bt["all_curve"]), 2)
        self.assertEqual(bt["all_win_rate_curve"][-1]["win_rate"], 0.5)
        self.assertEqual(bt["active_win_rate_curve"][-1]["win_rate"], 0.0)

    def test_money_impact_is_added_not_compounded(self):
        # Two +10% calls on 1000 of capital are worth 200, not 1000*1.1^2-1000=210.
        # Compounding is what let the old benefit curve reach -26% on a book that
        # never had that much at risk.
        rows = [decision("2026-07-01", action="cut", benefit=10, capital=1000),
                decision("2026-07-02", ticker="BBB", action="cut", benefit=10, capital=1000)]
        for r in rows:
            r["leg"] = "US"
        dv2.assign_episode_ids(rows)
        leg = dv2.compute_money_impact(rows)["legs"]["US"]
        self.assertAlmostEqual(leg["all_active"]["money"], 200.0)
        self.assertEqual([p["cumulative_money"] for p in leg["curve"]], [100.0, 200.0])
        self.assertEqual(leg["currency"], "USD")

    def test_money_impact_reports_unpriced_calls_rather_than_hiding_them(self):
        priced = decision("2026-07-01", action="cut", benefit=10, capital=1000)
        unpriced = decision("2026-07-01", ticker="BBB", action="cut", benefit=10, capital=None)
        for r in (priced, unpriced):
            r["leg"] = "US"
        dv2.assign_episode_ids([priced, unpriced])
        leg = dv2.compute_money_impact([priced, unpriced])["legs"]["US"]
        self.assertEqual(leg["all_active"]["n_episodes"], 2)
        self.assertEqual(leg["all_active"]["n_priced"], 1)
        self.assertEqual(leg["coverage_pct"], 50.0)
        self.assertAlmostEqual(leg["all_active"]["money"], 100.0)

    def test_unresolved_reason_counts_distinct_episodes_not_reaffirmation_rows(self):
        reaffirmations = [decision(f"2026-07-0{day}", action="cut") for day in (1, 2, 3)]
        for row in reaffirmations:
            row["evaluation"] = {
                "status": "not_evaluable",
                "not_evaluable_reason": "needs_human_evidence",
                "triggered": False,
                "benefit_t1_pct": None,
                "benefit_t5_pct": None,
                "outcome": "pending",
            }
        # A settled control keeps compute_metrics' unrelated calibration fields
        # populated while coverage exercises the three-row unresolved episode.
        rows = reaffirmations + [decision("2026-07-01", ticker="BBB", action="cut")]
        dv2.assign_episode_ids(rows)
        self.assertEqual(len({row["episode_id"] for row in reaffirmations}), 1)

        coverage = dv2.compute_metrics(rows, window_days=365)["coverage_active"]
        self.assertEqual(coverage["episodes_unresolved"], 1)
        self.assertEqual(coverage["unresolved_reasons"]["needs_human_evidence"], 1)

    def test_money_impact_never_sums_across_currencies(self):
        us = decision("2026-07-01", action="cut", benefit=10, capital=1000)
        us["leg"] = "US"
        hk = decision("2026-07-01", ticker="00700", action="cut", benefit=10, capital=1000)
        hk["leg"] = "HK"
        dv2.assign_episode_ids([us, hk])
        legs = dv2.compute_money_impact([us, hk])["legs"]
        self.assertEqual(legs["US"]["currency"], "USD")
        self.assertEqual(legs["HK"]["currency"], "HKD")
        self.assertAlmostEqual(legs["US"]["all_active"]["money"], 100.0)
        self.assertAlmostEqual(legs["HK"]["all_active"]["money"], 100.0)

    def test_plan_date_must_match_filename(self):
        plan = {"schema_version": 2, "date": "2026-06-02",
                "decisions": [decision("2026-06-02")]}
        self.assertFalse([e for e in dv2.validate_plan(plan, "memory/2026-06-02-plan.json")
                          if "filename" in e])
        errors = dv2.validate_plan(plan, "memory/2026-06-01-plan.json")
        self.assertTrue(any("must match filename" in e for e in errors))
        # Without a path the check cannot run and must not invent a failure.
        self.assertFalse([e for e in dv2.validate_plan(plan) if "filename" in e])

    def test_v1_actions_are_rejected(self):
        self.assertIn("v1 actions field is forbidden", dv2.validate_plan({
            "schema_version": 2, "date": "2026-07-01", "actions": [], "decisions": []
        }))

    def test_normalization_is_deterministic(self):
        authored = {"schema_version": 2, "date": "2026-07-01", "decisions": [{
            "ticker": "AAA", "strategy_id": "intraday_t", "action": "t_only",
            "condition": {"type": "price_above", "price": 12},
            "confidence": .7, "driven_by": "technical"
        }]}
        a = dv2.normalize_authored_plan(copy.deepcopy(authored), Path("/nonexistent-ledger"))
        b = dv2.normalize_authored_plan(copy.deepcopy(authored), Path("/nonexistent-ledger"))
        self.assertEqual(a["decisions"][0]["decision_id"], b["decisions"][0]["decision_id"])

    def test_normalization_defaults_to_the_hk_desk_date(self):
        authored = {"schema_version": 2, "decisions": [decision("2026-07-01")]}
        with mock.patch.object(dv2._cal, "hkt_today", return_value=date(2026, 7, 2)):
            normalized = dv2.normalize_authored_plan(
                authored, Path("/nonexistent-ledger"))

        self.assertEqual(normalized["decisions"][0]["plan_date"], "2026-07-02")

    def test_watchdog_fallback_preserves_preflight_block(self):
        raw = "第一行\n价格 12.34\n风险提示"
        for formatter in (intraday_fallback, report_fallback):
            body = formatter(raw, "hk-open", "未完成")
            self.assertIn("确定性兜底", body)
            self.assertTrue(body.endswith(raw))


class HierarchicalCalibrationTest(unittest.TestCase):
    @staticmethod
    def row(day, ordinal, win=True, action="cut", driver="technical",
            condition="open", regime="neutral"):
        row = decision(
            day, ticker=f"T{ordinal}", action=action,
            benefit=1.0 if win else -1.0,
        )
        row["decision_id"] = f"cal-{day}-{ordinal}"
        row["episode_id"] = f"cal-ep-{day}-{ordinal}"
        row["driven_by"] = driver
        row["condition"]["type"] = condition
        row["regime"] = regime
        row["confidence"] = 0.9
        return row

    def test_same_date_outcomes_cannot_leak_between_predictions(self):
        rows = [
            self.row("2026-07-01", 1, win=True),
            self.row("2026-07-01", 2, win=False),
        ]
        predictions = dv2.hierarchical_prequential_calibration(
            rows)["prequential_predictions"]
        self.assertEqual(
            predictions[0]["calibrated_probability"],
            predictions[1]["calibrated_probability"],
        )
        self.assertEqual(predictions[0]["ci95"], predictions[1]["ci95"])
        self.assertEqual(predictions[0]["prior_episodes"], 0)
        self.assertEqual(predictions[1]["prior_episodes"], 0)

    def test_future_outcome_cannot_change_an_earlier_prediction(self):
        past = [
            self.row("2026-07-01", 1, win=True),
            self.row("2026-07-02", 2, win=False),
        ]
        before = dv2.hierarchical_prequential_calibration(
            past)["prequential_predictions"]
        after = dv2.hierarchical_prequential_calibration(
            past + [self.row("2026-07-03", 3, win=True)]
        )["prequential_predictions"][:2]
        self.assertEqual(before, after)

    def test_delayed_episode_outcome_updates_only_when_observable(self):
        delayed = self.row("2026-07-01", 1, win=True)
        delayed["evaluation"]["episode_outcome_available_date"] = "2026-07-03"
        day_two = self.row("2026-07-02", 2, win=False)
        day_two["evaluation"]["episode_outcome_available_date"] = "2026-07-05"
        day_four = self.row("2026-07-04", 4, win=True)
        day_four["evaluation"]["episode_outcome_available_date"] = "2026-07-05"

        predictions = dv2.hierarchical_prequential_calibration(
            [delayed, day_two, day_four])["prequential_predictions"]
        by_date = {row["plan_date"]: row for row in predictions}
        self.assertEqual(by_date["2026-07-02"]["prior_episodes"], 0)
        self.assertEqual(by_date["2026-07-04"]["prior_episodes"], 1)
        self.assertEqual(
            by_date["2026-07-04"]["outcome_available_date"], "2026-07-05")

    def test_sparse_leaf_shrinks_toward_broader_prior(self):
        rows = [
            self.row(f"2026-06-{i:02d}", i, win=True)
            for i in range(1, 21)
        ]
        rows.append(self.row(
            "2026-06-21", 21, win=False, action="t_only",
            driver="sentiment", condition="price_below", regime="risk_off",
        ))
        rows.append(self.row(
            "2026-06-22", 22, win=False, action="t_only",
            driver="sentiment", condition="price_below", regime="risk_off",
        ))
        last = dv2.hierarchical_prequential_calibration(
            rows)["prequential_predictions"][-1]
        self.assertEqual(
            last["resolved_level"], "action_driver_condition_regime")
        self.assertEqual(last["resolved_level_n"], 1)
        self.assertGreater(last["calibrated_probability"], 0.25)
        self.assertLess(last["calibrated_probability"], 0.8)

    def test_regime_is_a_real_calibration_dimension(self):
        rows = []
        for i in range(1, 11):
            rows.append(self.row(
                f"2026-05-{i:02d}", i, win=True, regime="risk_on"))
            rows.append(self.row(
                f"2026-05-{i:02d}", 100 + i, win=False, regime="risk_off"))
        rows.extend([
            self.row("2026-05-20", 201, win=True, regime="risk_on"),
            self.row("2026-05-20", 202, win=False, regime="risk_off"),
        ])
        predictions = dv2.hierarchical_prequential_calibration(
            rows)["prequential_predictions"][-2:]
        by_regime = {row["regime"]: row for row in predictions}
        self.assertGreater(
            by_regime["risk_on"]["calibrated_probability"],
            by_regime["risk_off"]["calibrated_probability"],
        )

    def test_insufficient_history_abstains_but_supported_edge_can_size(self):
        rows = [
            self.row(f"2026-04-{i:02d}", i, win=True)
            for i in range(1, 22)
        ]
        predictions = dv2.hierarchical_prequential_calibration(
            rows)["prequential_predictions"]
        self.assertTrue(predictions[0]["abstain"])
        self.assertEqual(predictions[0]["signal_size_multiplier"], 0.0)
        self.assertFalse(predictions[-1]["abstain"])
        self.assertTrue(predictions[-1]["edge_supported"])
        self.assertGreater(predictions[-1]["signal_size_multiplier"], 0.0)

    def test_normalization_records_regime_and_rejects_bad_value(self):
        row = dv2.legacy_action_to_decision({
            "ticker": "AAA", "strategy_id": "core_position", "action": "cut",
            "condition": {"type": "open"}, "confidence": 0.6,
            "driven_by": "technical", "regime": "risk_off",
        }, "2026-07-01")
        row["episode_id"] = "ep-test"
        self.assertEqual(row["regime"], "risk_off")
        row["regime"] = "bullish"
        self.assertIn("bad regime 'bullish'", dv2.validate_decision(row))

    def test_unknown_regime_is_a_prospective_plan_warning(self):
        row = self.row("2026-07-01", 1)
        row["regime"] = "unknown"
        self.assertEqual(
            dv2.missing_regime_warnings([row]),
            ["regime missing/unknown for T1/core_position"],
        )


class ExecutionCoverageTests(unittest.TestCase):
    """An unknown that will never resolve is censoring, not a pending gap."""

    def _unknown(self, days_ago, action):
        # The desk date, not the host's. `_exec_rate` measures the window from
        # `_cal.hkt_today()` — deliberately, so the answer is the same on every
        # host (the test below pins exactly that) — and a row dated from the
        # runner's own calendar is a different number of days old on a UTC host
        # for the eight hours a day the two dates disagree. CI runs in UTC: a
        # `cut` placed "1 day ago" was 2 desk-days old, its T+2 window had
        # closed, and it was stranded rather than pending.
        row = decision((_cal.hkt_today() - timedelta(days=days_ago)).isoformat(),
                       action=action)
        row["execution"] = {"status": "unknown", "detected_at": None, "source": None}
        return row

    def test_an_unknown_past_its_window_is_stranded_and_the_window_is_per_action(self):
        # A cut gets T+2 and a hold gets T+1, so one day back separates them:
        # the hold can never resolve again, the cut still can.
        rows = [self._unknown(1, "cut"), self._unknown(1, "hold_and_watch")]
        dv2.assign_episode_ids(rows)

        by_kind = dv2.compute_metrics(rows, window_days=365)["execution_by_kind"]

        self.assertEqual((by_kind["active"]["pending"], by_kind["active"]["stranded"]), (1, 0))
        self.assertEqual((by_kind["passive"]["pending"], by_kind["passive"]["stranded"]), (0, 1))
        for leg in by_kind.values():
            self.assertEqual(leg["unknown"], leg["pending"] + leg["stranded"])

    def test_exec_rate_defaults_to_the_hk_desk_date(self):
        """The pending window follows the ledger's desk day on every host.

        The fixed desk day predates the test runner, so the old host-calendar
        default would close this two-day window and misclassify it as stranded.
        """
        row = decision("2026-07-01", action="add_on_breakout")
        row["execution"] = {"status": "unknown"}
        with (
            mock.patch.object(dv2._cal, "hkt_today", return_value=date(2026, 7, 2)),
            mock.patch.object(dv2, "verification_window_days", return_value=2),
        ):
            rate = dv2._exec_rate([row])

        self.assertEqual(rate["pending"], 1)
        self.assertEqual(rate["stranded"], 0)

    def test_detect_followed_agrees_with_exec_rate_on_the_hk_desk_date(self):
        """`_detect_followed`'s too-early gate must use the same desk-day clock
        as `_exec_rate`'s pending/stranded split (#1749).

        Before the fix, `_detect_followed` gated on `datetime.now()` (host
        clock) while `_exec_rate` gated on `_cal.hkt_today()`. For the ~8
        UTC hours where the two dates disagree, a still-open window could be
        scored `stranded` (permanently unresolved) by the ledger while the
        resolver still believed it was too early to check and kept retrying.
        Both must now open and close the window on the same day.
        """
        from clawock.harness import brief_preflight

        row = {"plan_date": "2026-07-01", "ticker": "AAA", "bucket": "add_on_breakout"}

        # One day before the window closes: both sides call it still open.
        with (
            mock.patch.object(dv2._cal, "hkt_today", return_value=date(2026, 7, 2)),
            mock.patch.object(dv2, "verification_window_days", return_value=2),
            mock.patch.object(brief_preflight, "_shares_at_date",
                               side_effect=AssertionError("shares lookup happened while still pending")),
        ):
            rate = dv2._exec_rate([{**row, "action": row["bucket"], "execution": {"status": "unknown"}}])
            verdict = brief_preflight._detect_followed(row, min_window_days=2)

        self.assertEqual((rate["pending"], rate["stranded"]), (1, 0))
        self.assertEqual(verdict, "unknown")  # too early; no shares lookup fired

        # The day the window closes: both sides call it resolvable now.
        # dv2._cal and brief_preflight.trading_calendar are the same `clawock.sessions`
        # module object, so one patch of hkt_today reaches both call sites.
        with (
            mock.patch.object(dv2._cal, "hkt_today", return_value=date(2026, 7, 3)),
            mock.patch.object(dv2, "verification_window_days", return_value=2),
            mock.patch.object(brief_preflight, "_shares_at_date", return_value=5),
        ):
            rate = dv2._exec_rate([{**row, "action": row["bucket"], "execution": {"status": "unknown"}}])
            verdict = brief_preflight._detect_followed(row, min_window_days=2)

        self.assertEqual((rate["pending"], rate["stranded"]), (0, 1))
        self.assertNotEqual(verdict, "unknown")  # window closed; resolver actually checked shares

    def test_an_unusable_plan_date_cannot_hide_in_pending(self):
        """`pending` means "wait and it resolves". A row with no readable date
        never will, so it must not sit in the bucket that promises it might.
        Exercised on `_exec_rate` directly: such a row cannot reach the ledger,
        and the surrounding metrics parse plan_date for their own reasons."""
        row = self._unknown(30, "cut")
        row["plan_date"] = "not-a-date"

        self.assertEqual(dv2._exec_rate([row])["pending"], 0)
        self.assertEqual(dv2._exec_rate([row])["stranded"], 1)

    def test_the_verification_window_has_a_single_definition(self):
        """`_detect_followed` must read the rule, not keep its own copy.

        Two copies drift silently — the first measurement for #294 read the
        wrong field, got the wrong window for every passive row and produced a
        plausible answer that was off by six points.
        """
        from clawock.harness import brief_preflight

        row = {"plan_date": (_cal.hkt_today() - timedelta(days=10)).isoformat(),
               "ticker": "AAA", "bucket": "cut"}
        with mock.patch.object(brief_preflight, "_shares_at_date", return_value=5):
            self.assertEqual(brief_preflight._detect_followed(row), "false")
            with mock.patch.object(dv2, "verification_window_days", return_value=3650):
                self.assertEqual(brief_preflight._detect_followed(row), "unknown")

    def test_add_verification_counts_the_own_legs_sessions_across_a_long_holiday(self):
        # HK LNY: the five-session campaign starting 2026-02-13 ends on 02-24,
        # not at the old fixed nine-calendar-day cutoff on 02-22. The window
        # closes the day after (02-25): 11 closed it on the last session's own
        # date, the #1914 miss.
        self.assertEqual(
            dv2.verification_window_days(
                "add_only_on_trigger", plan_date="2026-02-13", leg="HK",
                valid_for_sessions=5,
            ),
            12,
        )

    def test_a_last_session_fill_is_inside_the_window_and_the_next_week_is_not(self):
        """#1914: a US add valid Wed/Thu/Fri (2026-09-23..25) closed on Friday
        HKT, before the Friday US session (Sat ~04:00 HKT) had even ended, so
        its fill could only be read as `not_followed`. The window now reaches
        Saturday — and stops there: a buy the following week is not this
        plan's fill."""
        from clawock.harness import brief_preflight

        window = dv2.verification_window_days(
            "add_only_on_trigger", plan_date="2026-09-23", leg="US",
            valid_for_sessions=3)
        self.assertEqual(window, 3)

        row = {"plan_date": "2026-09-23", "ticker": "AAA",
               "bucket": "add_only_on_trigger", "leg": "US",
               "condition": {"valid_for_sessions": 3}}
        booked = {"2026-09-22": 10}

        def shares(_ticker, day):
            return next((n for d, n in sorted(booked.items(), reverse=True)
                         if d <= day), None)

        with mock.patch.object(brief_preflight, "_shares_at_date", side_effect=shares), \
                mock.patch.object(brief_preflight.trading_calendar, "hkt_today",
                                  return_value=date(2026, 10, 5)):
            booked["2026-09-26"] = 20          # Friday's US fill, booked Saturday HKT
            self.assertEqual(brief_preflight._detect_followed(row), "true")
            del booked["2026-09-26"]
            booked["2026-09-29"] = 20          # an unrelated buy the next week
            self.assertEqual(brief_preflight._detect_followed(row), "false")


if __name__ == "__main__":
    unittest.main()


class EmptyCalibrationPopulation(unittest.TestCase):
    """#309: a ledger with nothing scored must not abort the dashboard build.

    `compute_metrics` reads every Brier baseline unconditionally, and
    `build_dashboard.build_projection` calls it outside any per-card try — so a
    calibration branch that returns fewer keys than its sibling takes down the
    whole build, not one card. A fresh workspace and any window in which nothing
    settled both land on that branch.

    These two cases are the guard: a baseline added to the populated branch and
    read by `compute_metrics`, but forgotten in the empty branch, raises KeyError
    here. Comparing the two branches' key sets directly is not possible — `_calib`
    is nested, and `compute_metrics` re-projects explicit field names, so an
    unused extra key is invisible (and harmless).
    """

    def test_an_empty_ledger_reports_no_calibration_instead_of_raising(self):
        metrics = dv2.compute_metrics([])

        self.assertIsNone(metrics["brier"])
        self.assertIsNone(metrics["brier_baseline_constant"])
        self.assertIsNone(metrics["brier_baseline_coinflip"])
        self.assertEqual(metrics["settled_episodes"], 0)

    def test_an_unsettled_ledger_reports_no_calibration_instead_of_raising(self):
        today = date.today().isoformat()
        unsettled = decision(today)
        unsettled["evaluation"] = {}

        self.assertIsNone(dv2.compute_metrics([unsettled])["brier"])


def test_assign_episode_ids_skips_mind_ledger_rows():
    """Mind rows carry no plan_date and must not reach the episode keying (#720).

    `memory/decisions.jsonl` holds two row types. Decision Mind writes
    `schema_version: 0` rows with mind/emotion instead of the plan-decision
    fields — `validate_decision` already routes them to their own validator.
    `assign_episode_ids` did not: it subscripted `d["plan_date"]` directly, and
    `normalize_authored_plan` feeds it the *whole* ledger. The first mind row
    (2026-08-16) therefore made every brief-fallback run die *after* the LLM
    had already produced the brief, throwing the result away.

    Reverting to the bare subscript must fail this test.
    """
    from clawock.decision.ledger import assign_episode_ids

    mind = {
        "schema_version": 0, "source": "conversation",
        "decision_id": "dec-conversation-x",
        "decided_at": "2026-08-16T14:30:50+08:00",
        "subject": {"ticker": "00100"},
    }
    plan_a = {"decision_id": "d1", "plan_date": "2026-08-10", "ticker": "00100",
              "strategy_id": "core", "action": "hold"}
    plan_b = {"decision_id": "d2", "plan_date": "2026-08-12", "ticker": "00100",
              "strategy_id": "core", "action": "hold"}

    out = assign_episode_ids([plan_a, mind, plan_b])

    # It must not raise, the mind row must stay untouched, and the plan rows
    # must still group exactly as they did before the mind row existed.
    assert "episode_id" not in mind, "a mind row has no episode semantics"
    assert plan_a["episode_id"], "plan rows still get an episode id"
    assert plan_a["episode_id"] == plan_b["episode_id"], "a 2-day gap is one episode"
    assert out is not None

    # A plan row missing plan_date degrades (no episode) rather than crashing.
    broken = {"decision_id": "d3", "ticker": "00100", "strategy_id": "core", "action": "hold"}
    assign_episode_ids([broken])
    assert "episode_id" not in broken


class TestSharesLookupMemoization(unittest.TestCase):
    """#916: the verification sweep asks the same dates once per decision row;
    each repeat must not re-run git log + git show + full JSON parse."""

    def test_repeated_dates_and_tickers_are_served_from_cache(self):
        import json as _json
        from types import SimpleNamespace
        from clawock.harness import brief_preflight

        calls = []
        pf = {"portfolios": {"hk_stocks": {"holdings": [
            {"ticker": "00700", "shares": 100}]}},
            "us_stocks": {"holdings": []}}

        def fake_run(cmd, **kwargs):
            calls.append(cmd[:3])
            if cmd[1] == "log":
                return SimpleNamespace(returncode=0, stdout="abc123\n")
            return SimpleNamespace(returncode=0, stdout=_json.dumps(pf))

        monkey = mock.patch.object
        with monkey(brief_preflight.subprocess, "run", fake_run), \
             monkey(brief_preflight, "_shares_sha_cache", {}), \
             monkey(brief_preflight, "_shares_pf_cache", {}):
            self.assertEqual(brief_preflight._shares_at_date("00700", "2026-08-01"), 100)
            self.assertEqual(brief_preflight._shares_at_date("00700", "2026-08-01"), 100)
            self.assertEqual(len(calls), 2)      # log+show once, then cached
            self.assertIsNone(brief_preflight._shares_at_date("00388", "2026-08-01"))
            self.assertEqual(len(calls), 2)      # second ticker reuses the file


def test_checked_in_ledger_has_no_typed_episode_ids():
    # Model-typed episode ids (`ep-20260904-07226-cut`) sliced long-running
    # theses into fresh, independently scored episodes from 2026-07-23 to
    # 2026-09-11. Postflight no longer accepts them, so any that reappear came
    # through some other writer.
    rows = dv2.load_decisions(ROOT / "memory" / "decisions.jsonl")
    assert dv2.rederive_typed_episode_ids(rows) == []


def test_rederive_continues_the_derived_episode_it_interrupted():
    def row(day, episode_id):
        return {"schema_version": 2, "decision_id": f"dec-{day}",
                "episode_id": episode_id, "plan_date": f"2026-09-{day:02d}",
                "ticker": "07226", "strategy_id": "risk_rebalance",
                "action": "cut"}
    rows = [row(4, "ep-0123456789ab"), row(7, "ep-20260907-07226-cut"),
            row(8, "ep-20260907-07226-cut"), row(20, "ep-20260920-07226-cut")]

    changed = dv2.rederive_typed_episode_ids(rows)

    assert [r["episode_id"] for r in rows[:3]] == ["ep-0123456789ab"] * 3
    # A gap over four days still opens a new episode, now a derived one.
    assert rows[3]["episode_id"] not in {"ep-0123456789ab", "ep-20260920-07226-cut"}
    assert rows[3]["episode_id"].startswith("ep-")
    assert [c[0] for c in changed] == ["dec-7", "dec-8", "dec-20"]


def test_unkeyed_plan_decisions_cannot_collapse_into_one_ledger_row(tmp_path):
    """An un-normalized plan must be refused, not merged (2026-09-16).

    The upsert is keyed on `decision_id`. Nine decisions that all still lack
    one key on `None`: the first is inserted and the other eight `update` onto
    it, so the plan lands as a single row carrying the last decision's ticker
    and the union of all nine field sets. That row satisfies no schema, and
    `ops/system_check.py` reads the ledger from `.githooks/pre-push` — so it
    blocked every push from the host, not just the brief's own.
    """
    ledger = tmp_path / "decisions.jsonl"
    plan = {"schema_version": 2, "date": "2026-09-16", "decisions": [
        {"ticker": "SPCH", "action": "cut", "size": {"shares": 300}},
        {"ticker": "RKLX", "action": "hold_and_watch"},
        {"ticker": "SPCX", "action": "hold_and_watch", "evidence_ids": ["x"]},
    ]}

    try:
        dv2.upsert_plan_decisions(copy.deepcopy(plan), path=ledger)
    except ValueError as exc:
        assert "decision_id" in str(exc)
    else:
        raise AssertionError("an un-normalized plan must not be booked")

    assert not ledger.exists() or dv2.load_decisions(ledger) == []


def test_checked_in_ledger_has_no_unkeyed_rows():
    # Every row is addressable by decision_id, or the pre-push ledger check
    # goes CRITICAL and nothing on this host can publish.
    rows = dv2.load_decisions(ROOT / "memory" / "decisions.jsonl")
    assert [i for i, r in enumerate(rows) if not r.get("decision_id")] == []


def test_suspect_trigger_is_not_a_fill_and_cannot_skip_to_a_clean_window():
    flagged = {**_bar(12.0), 'implausible_move': '57.9%'}
    ev = _settle_against('2026-07-04', 13, condition={
        'type': 'price_above', 'price': 11, 'valid_for_sessions': 2},
        bars={'2026-07-01': flagged, '2026-07-02': _bar(13), '2026-07-03': _bar(14)})
    assert ev['status'] == 'not_evaluable' and ev['not_evaluable_reason'] == 'implausible_move'
    assert 'execution_price' not in ev and 'capital' not in ev
    assert 'benefit_t1_pct' not in ev and ev['outcome'] == 'unknown'


def test_suspect_mark_cannot_score_a_clean_fill():
    ev = _settle_against('2026-07-03', 17, bars={
        '2026-07-01': _bar(10),
        '2026-07-02': {**_bar(17), 'implausible_move': '70.0%'}})
    assert ev['status'] == 'not_evaluable' and ev['not_evaluable_reason'] == 'implausible_move'
    assert ev['outcome'] == 'unknown' and ev['benefit_t1_pct'] is None


def test_resettlement_removes_stale_profit_amounts_on_a_suspect_fill():
    row = dv2.legacy_action_to_decision({'ticker': 'AAA', 'action': 'cut',
        'condition': {'type': 'open'}, 'size': {'shares': 14}, 'confidence': .6}, '2026-07-01')
    row['evaluation'] = {'status': 'settled', 'outcome': 'loss',
        'execution_price': 36.98, 'capital': 517.72, 'benefit_t20_pct': -44.7}
    patches = _with_bars({'2026-07-01': {**_bar(36.98), 'implausible_move': '57.9%'}})
    for patch in patches: patch.start()
    try: dv2.settle_decisions([row], now_date='2026-07-04')
    finally:
        for patch in patches: patch.stop()
    ev = row['evaluation']
    assert ev['not_evaluable_reason'] == 'implausible_move'
    assert not {'execution_price', 'capital', 'benefit_t20_pct'} & ev.keys()


def test_t5_mark_cannot_cross_a_suspect_intermediate_session():
    bars = {f'2026-07-0{day}': _bar(10 + day) for day in range(1, 7)}
    bars['2026-07-03']['implausible_move'] = '60.0%'
    ev = _settle_against('2026-07-09', 12, bars=bars)
    assert ev['status'] == 'settled'  # the clean T+1 remains evidence
    assert ev['benefit_t1_pct'] is not None
    assert ev['benefit_t5_pct'] is None and ev['mark_t5_session'] is None
    # #2336: the withheld mark names its reason, like a withheld T+1 does.
    assert ev['mark_t5_reason'] == 'implausible_move'
    assert 'mark_t20_reason' not in ev  # not due yet is not a reason


def test_a_clean_window_carries_no_mark_reason():
    bars = {f'2026-07-0{day}': _bar(10 + day) for day in range(1, 7)}
    ev = _settle_against('2026-07-09', 12, bars=bars)
    assert ev['benefit_t5_pct'] is not None
    assert 'mark_t5_reason' not in ev and 'mark_t20_reason' not in ev


def _patched(bars, sessions=None):
    import contextlib
    stack = contextlib.ExitStack()
    for patch in _with_bars(bars, sessions):
        stack.enter_context(patch)
    stack.enter_context(mock.patch.object(dv2, "last_closed_session", return_value=max(bars)))
    return stack


def test_mark_horizons_names_each_reason_a_mark_is_withheld():
    """The pricing half of settlement on its own (#2596): one fill, four refusals."""
    row = {"action": "cut"}
    days = [f"2026-07-{day:02d}" for day in range(1, 8)]
    marks = lambda bars, today: dv2._mark_horizons(  # noqa: E731
        row, ticker="AAA", leg="US", entry=10.0, fill_session="2026-07-01", today=today)

    clean = {day: _bar(10 + i) for i, day in enumerate(days)}
    with _patched(clean, days):
        out = marks(clean, "2026-07-09")
        assert out["status"] == "settled" and out["mark_t1_session"] == "2026-07-02"
        assert out["mark_t5_session"] == "2026-07-06" and "mark_t5_reason" not in out
        # T+1 dated today never scores, wherever the price came from.
        assert marks(clean, "2026-07-02")["pending_reason"] == "session_not_final"
    no_bar = {day: bar for day, bar in clean.items() if day != "2026-07-02"}
    with _patched(no_bar, days):
        assert marks(no_bar, "2026-07-09")["pending_reason"] == "mark_bar_missing"
    with _patched(no_bar, days), mock.patch.object(dv2, "last_closed_session", return_value="2026-07-01"):
        assert marks(no_bar, "2026-07-09")["pending_reason"] == "mark_pending"
    suspect = {**clean, "2026-07-02": {**clean["2026-07-02"], "implausible_move": "60.0%"}}
    with _patched(suspect, days):
        out = marks(suspect, "2026-07-09")
        assert (out["status"], out["not_evaluable_reason"]) == ("not_evaluable", "implausible_move")
        assert out["mark_t5_reason"] == "implausible_move"


def test_trigger_window_keeps_a_halted_session_and_a_suspect_one_apart():
    """A degenerate bar is skipped and the scan goes on; a suspect bar ends it (#1717)."""
    row = dv2.legacy_action_to_decision({"ticker": "AAA", "action": "cut",
        "condition": {"type": "open"}, "confidence": .6}, "2026-07-01")
    days = ["2026-07-01", "2026-07-02", "2026-07-03"]
    scan = lambda: dv2._trigger_window(  # noqa: E731
        row, ticker="AAA", leg="US", candidate_sessions=days, today="2026-07-09")

    halted_then_real = {"2026-07-01": {**_bar(10), "degenerate": True}, "2026-07-02": _bar(11)}
    with _patched(halted_then_real, days):
        got = scan()
        assert got["degenerate_session"] == "2026-07-01" and got["implausible_session"] is None
        assert got["evaluated"] == ["2026-07-02"] and got["fired"] is True
        assert got["trigger_session"] == "2026-07-02"
        assert dv2._window_refusal(got, ticker="AAA", leg="US") is None
    suspect_first = {"2026-07-01": {**_bar(10), "implausible_move": "57.9%"}, "2026-07-02": _bar(11)}
    with _patched(suspect_first, days):
        got = scan()
        assert got["implausible_session"] == "2026-07-01" and got["evaluated"] == []
        refusal = dv2._window_refusal(got, ticker="AAA", leg="US")
        assert refusal["not_evaluable_reason"] == "implausible_move"
    only_halted = {"2026-07-01": {**_bar(10), "degenerate": True}}
    with _patched(only_halted, ["2026-07-01"]):
        got = dv2._trigger_window(row, ticker="AAA", leg="US",
                                  candidate_sessions=["2026-07-01"], today="2026-07-09")
        assert dv2._window_refusal(got, ticker="AAA", leg="US")["not_evaluable_reason"] == "degenerate_bar"


def test_plan_revision_replaces_pending_rows_without_orphans(tmp_path):
    path = tmp_path / "decisions.jsonl"
    day = "2026-10-08"
    def row(action, date=day, ticker="02208"):
        return dv2.legacy_action_to_decision(
            {"ticker": ticker, "action": action, "strategy_id": "tactical_entry"}, date)

    previous = row("hold_and_watch", "2026-10-07")
    old = row("add_only_on_trigger")
    removed = row("watch", ticker="SPCH")
    unchanged = row("hold_and_watch", ticker="CRCL")
    unchanged["execution"]["status"] = "followed"
    mind = {"schema_version": 0, "decision_id": "mind-test", "plan_date": day}
    dv2.write_decisions([previous, old, removed, unchanged, mind], path)
    replacement = row("watch")
    plan = {"date": day, "decisions": [replacement, row("hold_and_watch", ticker="CRCL")]}
    assert dv2.upsert_plan_decisions(plan, path=path) == (1, 1)
    result = dv2.load_decisions(path)
    assert {d["decision_id"] for d in result} == {
        previous["decision_id"], replacement["decision_id"], unchanged["decision_id"], "mind-test"}
    assert next(d for d in result if d["ticker"] == "CRCL")["execution"]["status"] == "followed"
    before = path.read_text()
    assert dv2.upsert_plan_decisions(plan, path=path) == (0, 2)
    assert path.read_text() == before


def test_plan_revision_refuses_to_remove_recorded_decisions(tmp_path):
    import pytest

    path = tmp_path / "decisions.jsonl"
    for state in ["followed", "not_followed", "settled"]:
        old = dv2.legacy_action_to_decision({"ticker": "02208", "action": "watch"}, "2026-10-08")
        if state == "settled":
            old["evaluation"]["status"] = state
        else:
            old["execution"]["status"] = state
        dv2.write_decisions([old], path)
        before = path.read_text()
        ledger = dv2.load_decisions(path)
        replacement = dv2.legacy_action_to_decision(
            {"ticker": "02208", "action": "hold_and_watch"}, "2026-10-08")
        plan = {"date": "2026-10-08", "decisions": [replacement]}
        with pytest.raises(ValueError, match="recorded decisions"):
            dv2.upsert_plan_decisions(plan, path=path, ledger=ledger, write=False)
        assert ledger == [old]
        assert path.read_text() == before
        with pytest.raises(ValueError, match="recorded decisions"):
            dv2.upsert_plan_decisions(plan, path=path)
        assert path.read_text() == before


def test_plan_revision_cannot_prune_with_an_empty_or_wrong_date_plan(tmp_path):
    import pytest

    path = tmp_path / "decisions.jsonl"
    old = dv2.legacy_action_to_decision({"ticker": "02208", "action": "watch"}, "2026-10-08")
    dv2.write_decisions([old], path)
    before = path.read_text()
    wrong = dv2.legacy_action_to_decision({"ticker": "02208", "action": "watch"}, "2026-10-07")
    for decisions in [[], [wrong]]:
        with pytest.raises(ValueError, match="empty or date-mismatched"):
            dv2.upsert_plan_decisions({"date": "2026-10-08", "decisions": decisions}, path=path)
        assert path.read_text() == before


def _authored(day, **execution):
    item = {"ticker": "02208", "action": "watch", "strategy_id": "tactical_entry",
            "confidence": 0.6, "regime": "neutral", "condition": {"type": "manual"}}
    if execution:
        item["execution"] = execution
    return {"date": day, "decisions": [item]}


def test_a_new_plan_cannot_report_its_own_execution(tmp_path):
    """#2832: `execution: followed / manual` typed into a new plan rode the
    insert into the ledger, survived settlement, and was skipped by the trade
    detector, which only looks at `unknown`."""
    path = tmp_path / "decisions.jsonl"
    day = "2026-10-08"
    for status in ("followed", "not_followed"):
        plan = dv2.normalize_authored_plan(
            _authored(day, status=status, source="manual",
                      detected_at="2026-10-08T09:00:00+08:00"), path)
        assert dv2.validate_plan(plan, check_book=False) == []
        assert plan["decisions"][0]["execution"] == {
            "status": "unknown", "detected_at": None, "source": None}

    # The ledger's own door holds without the normalizer in front of it.
    forged = dv2.normalize_authored_plan(_authored(day), path)
    forged["decisions"][0]["execution"] = {
        "status": "followed", "source": "manual", "detected_at": None}
    ledger = []
    assert dv2.upsert_plan_decisions(forged, ledger=ledger, write=False) == (1, 0)
    dv2.settle_decisions(ledger)
    assert ledger[0]["execution"]["status"] == "unknown"


def test_a_rerun_keeps_the_execution_the_ledger_recorded(tmp_path):
    path = tmp_path / "decisions.jsonl"
    day = "2026-10-08"
    plan = dv2.normalize_authored_plan(_authored(day), path)
    assert dv2.upsert_plan_decisions(plan, path=path) == (1, 0)
    rows = dv2.load_decisions(path)
    rows[0]["execution"] = {"status": "followed", "source": "manual", "detected_at": None}
    dv2.write_decisions(rows, path)

    # The plan on disk still says `unknown`; a copy that claims otherwise is
    # no more believed than the first one was.
    for claim in ({}, {"status": "not_followed", "source": "manual"}):
        rerun = dv2.normalize_authored_plan(_authored(day, **claim), path)
        assert dv2.upsert_plan_decisions(rerun, path=path) == (0, 1)
        assert dv2.load_decisions(path)[0]["execution"] == {
            "status": "followed", "source": "manual", "detected_at": None}


def test_the_system_looks_up_the_calibrator_row_and_the_plan_cannot_supply_one():
    """#2834: both skills had the model match action+driver+condition+regime by
    hand and multiply its size. The lookup is a fact the system stamps; the
    size stays the plan writer's."""
    def authored(action, **extra):
        return dv2.legacy_action_to_decision({
            "ticker": "AAA", "action": action, "strategy_id": "tactical_entry",
            "driven_by": "technical", "regime": "neutral",
            "condition": {"type": "open"}, **extra}, "2026-10-08")

    row = {"action": "cut", "driver": "technical", "condition": "open",
           "regime": "neutral", "calibrated_probability": 0.4765,
           "ci95": [0.28, 0.68], "resolved_level": "action_driver_condition",
           "resolved_level_n": 17, "prior_episodes": 58, "evidence_sufficient": True,
           "edge_supported": False, "signal_size_multiplier": 0.0,
           "sizing_status": "hit_rate_edge_unsupported", "posterior_alpha": 11.9,
           "payoff": {"reading": "positive_expectancy", "n": 17,
                      "mean_benefit_pct": 1.2, "ci95": [0.1, 2.3]}}
    plan = {"date": "2026-10-08", "decisions": [
        authored("cut"), authored("trim_on_rebound"), authored("hold_and_watch")]}
    plan["decisions"][2]["calibration"] = {"matched": True, "edge_supported": True}
    table = {"current_group_calibrators": [row]}

    hit, miss, passive = dv2.bind_plan_calibration(plan, table)["decisions"]
    assert hit["calibration"] == {"matched": True} | {
        key: row[key] for key in dv2.CALIBRATION_STAMP_FIELDS}
    assert miss["calibration"] == {
        "matched": False, "evidence_sufficient": False, "edge_supported": False,
        "signal_size_multiplier": 0.0, "sizing_status": "abstain_insufficient_evidence"}
    assert "calibration" not in passive, "a typed stamp does not survive"
    assert hit["size"] == plan["decisions"][0]["size"], "the size is not touched"
    # No table this run: nothing is claimed either way.
    assert all("calibration" not in d
               for d in dv2.bind_plan_calibration(plan, None)["decisions"])
