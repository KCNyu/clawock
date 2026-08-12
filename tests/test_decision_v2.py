import copy
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "growth"))
from clawock.decision import ledger as dv2
from clawock_kcnyu.harness.intraday_watchdog import deterministic_fallback as intraday_fallback
from clawock_kcnyu.harness.report_watchdog import deterministic_fallback as report_fallback


def test_decision_engine_is_owned_by_the_product_package():
    assert Path(dv2.__file__).relative_to(ROOT).as_posix() == "src/clawock/decision/ledger.py"
    assert not (ROOT / "scripts" / "data" / "decision_v2.py").exists()


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


def test_technical_add_without_setup_trace_is_invalid():
    row = dv2.legacy_action_to_decision({
        "ticker": "AAA", "strategy_id": "tactical_entry",
        "action": "add_only_on_trigger",
        "condition": {"type": "price_above", "price": 10},
        "size": {"shares": 1}, "confidence": 0.6,
        "driven_by": "technical",
    }, "2026-07-01")
    row["episode_id"] = "ep-test"

    issues = dv2.validate_decision(row)

    assert "technical add requires technical_setup_id" in issues
    assert "technical add requires technical_campaign_id" in issues
    assert "technical add requires invalidation_price" in issues
    assert "technical add requires tranche_number >= 1" in issues


def test_metrics_attribute_settled_technical_adds_to_the_named_setup():
    row = decision(
        "2026-07-01", strategy="tactical_entry",
        action="add_only_on_trigger", benefit=2.5,
    )
    row["technical_setup_id"] = "trend_pullback"

    metrics = dv2.compute_metrics([row], window_days=365)

    assert metrics["by_technical_setup"]["trend_pullback"]["n_episodes"] == 1
    assert metrics["by_technical_setup"]["trend_pullback"]["avg_benefit_pct"] == 2.5


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

    def test_active_passive_split_is_single_sourced_with_broadcaster(self):
        # The Nostr broadcast and the dashboard must classify active vs passive the
        # same way, or they publish two different "active win rate"s. `watch` is a
        # standing stance and settles passively, so it must not count as active.
        import rick_broadcast
        self.assertIs(rick_broadcast.ACTIVE, dv2.ACTIVE_ACTIONS)
        self.assertIs(rick_broadcast.PASSIVE, dv2.PASSIVE_ACTIONS)
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
        row = decision((date.today() - timedelta(days=days_ago)).isoformat(), action=action)
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
        from clawock_kcnyu.harness import brief_preflight

        row = {"plan_date": (date.today() - timedelta(days=10)).isoformat(),
               "ticker": "AAA", "bucket": "cut"}
        with mock.patch.object(brief_preflight, "_shares_at_date", return_value=5):
            self.assertEqual(brief_preflight._detect_followed(row), "false")
            with mock.patch.object(dv2, "verification_window_days", return_value=3650):
                self.assertEqual(brief_preflight._detect_followed(row), "unknown")


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
