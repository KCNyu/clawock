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


def _snapshot(price):
    return {"portfolios": {
        "us_stocks": {"holdings": [{"ticker": "AAA", "current_price": price,
                                    "day_open": price, "day_high": price, "day_low": price}]},
        "hk_stocks": {"holdings": []}}}


def _settle_against(now_date, t1_price):
    """Settle one 07-01 call when 07-02's snapshot prints ``t1_price``."""
    row = dv2.legacy_action_to_decision({
        "ticker": "AAA", "strategy_id": "core_position", "action": "cut",
        "condition": {"type": "open"}, "confidence": 0.6, "driven_by": "technical",
    }, "2026-07-01")
    snaps = {"2026-07-01": _snapshot(10.0), "2026-07-02": _snapshot(t1_price)}
    with mock.patch.object(dv2, "snapshot_dates", return_value=sorted(snaps)), \
         mock.patch.object(dv2, "load_snapshot", side_effect=snaps.get):
        dv2.settle_decisions([row], now_date=now_date)
    return row["evaluation"]


class LiveSnapshotTest(unittest.TestCase):
    """Today's snapshot is rewritten every ~30min; it must not score a session."""

    def test_todays_snapshot_never_settles(self):
        self.assertEqual(_settle_against("2026-07-02", 9.0)["outcome"], "pending")

    def test_the_tape_cannot_move_a_settled_record(self):
        # The bug: 07-02 intraday, this call read 'win' at one print and 'loss'
        # at the next. Pending at both is the whole point.
        up = _settle_against("2026-07-02", 9.0)     # cut, stock down -> would win
        down = _settle_against("2026-07-02", 11.0)  # cut, stock up   -> would lose
        self.assertEqual(up["outcome"], down["outcome"])
        self.assertIsNone(up["benefit_t1_pct"])

    def test_a_finalised_session_still_settles(self):
        ev = _settle_against("2026-07-03", 9.0)
        self.assertEqual(ev["outcome"], "win")       # cut before a 10 -> 9 drop
        self.assertEqual(ev["benefit_t1_pct"], 10.0)


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
        self.assertEqual(dv2.condition_execution(manual, {}), (None, None))

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
