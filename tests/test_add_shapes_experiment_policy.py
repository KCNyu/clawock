"""Candidate sizing is testable without enabling it in the live policy."""
import json
from pathlib import Path

from clawock.decision import add_policy


POLICY = json.loads((Path(__file__).resolve().parents[1] / "config" /
                     "add-shapes-experiment.json").read_text())


def test_left_side_is_not_live_and_experiment_is_disabled():
    live = json.loads((Path(__file__).resolve().parents[1] / "config" /
                       "add-alpha-policy.json").read_text())
    assert "left_side" not in live
    assert POLICY["left_side"]["enabled"] is False


def test_legacy_plan_is_identical_with_or_without_disabled_candidate():
    args = dict(tier="exploration_cold_start", price=148.03, lot=1, shares=1,
                current_value=148.03, capital=3455.57, cash=461.63,
                setup_pcts=[0.0125])
    assert add_policy.tranche_plan(**args) == add_policy.tranche_plan(
        **args, policy={"left_side": {**POLICY["left_side"], "enabled": False}})


def test_candidate_unit_bridge_obeys_loss_and_notional_caps():
    args = dict(tier="exploration_cold_start", price=148.03, lot=1, shares=1,
                current_value=148.03, capital=3455.57, cash=461.63,
                setup_pcts=[], policy=POLICY,
                setup_tiers=["exploration_cold_start"])
    inside = add_policy.tranche_plan(**args, stop_distance=148.03 * 0.08)
    outside = add_policy.tranche_plan(**args, stop_distance=148.03 * 0.15)
    unknown = add_policy.tranche_plan(**args, stop_distance=None)
    assert inside["suggested_shares"] == 1 and inside["unit_bridged"] is True
    assert outside["suggested_shares"] == 0
    assert unknown["suggested_shares"] == 0 and unknown["risk_unbounded"] is True
