import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))
import decision_v2 as dv2
sys.path.insert(0, str(ROOT / "scripts" / "harness"))
from intraday_watchdog import deterministic_fallback as intraday_fallback
from report_watchdog import deterministic_fallback as report_fallback


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


if __name__ == "__main__":
    unittest.main()
