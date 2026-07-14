import copy
import sys
import unittest
from pathlib import Path

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
