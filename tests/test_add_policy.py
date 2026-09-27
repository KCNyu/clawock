"""`decision/add_policy.py`: one reader of the add policy, one sizing rule.

The brief packet, the brief opportunity read and the intraday add-side read all
take their numbers from here (see the module docstring's table); these tests pin
the behaviours the three used to implement separately.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawock.decision import add_policy

POLICY = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "add-alpha-policy.json").read_text())


def test_an_explicit_zero_survives_and_a_broken_value_falls_back():
    # #649/#666: 0 is a legal setting (z >= 0 never chases), not "missing".
    assert add_policy.read_params({"early_no_chase_zscore": 0,
                                   "opportunity_near_pct": 0}) == {
        "near_pct": 0.0, "no_chase_z": 0.0}
    assert add_policy.read_params({}) == {"near_pct": 5.0, "no_chase_z": 2.0}
    # A malformed file must not red a brief or a slot.
    assert add_policy.read_params({"early_no_chase_zscore": "x"})["no_chase_z"] == 2.0
    assert add_policy.read_params(None) == {"near_pct": 5.0, "no_chase_z": 2.0}


def test_every_tier_size_is_read_from_the_policy_file():
    assert add_policy.tier_terms(POLICY, "validated") == {
        "max_tranches": POLICY["validated_max_tranches"],
        "tranche_pct_of_position": POLICY["validated_tranche_pct"],
        "target_tranche_level": 1.0}
    assert add_policy.tier_terms(POLICY, "exploration")["tranche_pct_of_position"] == (
        POLICY["exploration_tranche_pct"])
    assert add_policy.tier_terms(POLICY, "exploration_cold_start") == {
        "max_tranches": 1,
        "tranche_pct_of_position": POLICY["cold_start_tranche_pct"],
        "target_tranche_level": 0.125}
    with pytest.raises(ValueError):
        add_policy.tier_terms(POLICY, "none")


LEGACY = {key: value for key, value in POLICY.items() if key != "sizing"}


def test_the_read_lane_quotes_the_size_the_packet_uses():
    sizing = POLICY["sizing"]
    assert add_policy.size_cap_text(POLICY) == (
        f"上限探索档 {round(sizing['tranche_book_pct']['exploration'] * 100, 4):g}% 市值、"
        f"失效位亏损 ≤{round(sizing['max_tranche_risk_book_pct'] * 100, 4):g}% 市值"
        "(add-alpha-policy)")
    pct = add_policy.tier_terms(LEGACY, "exploration")["tranche_pct_of_position"]
    assert add_policy.size_cap_text(LEGACY) == (
        f"上限探索档 {round(pct * 100, 4):g}%(add-alpha-policy)")


def test_an_unknown_entry_is_refused_rather_than_defaulted():
    assert add_policy.entry_profile("brief")["close_confirmed"] is True
    assert add_policy.entry_profile("intraday")["close_confirmed"] is False
    with pytest.raises(ValueError):
        add_policy.entry_profile("report")


def test_exploration_one_unit_rule_uses_the_market_book_cap():
    """F17 (#1890) as sized today: a $148 share against a 3% cap of a $3,455
    book ($103.65) does not fit, so the cold-start tranche is zero shares."""
    plan = add_policy.tranche_plan(
        tier="exploration_cold_start", price=148.03, lot=1, shares=1,
        current_value=148.03, capital=3455.57, cash=461.63, setup_pcts=[0.0125],
        exploration_max_book_pct=0.03, policy=LEGACY)
    assert plan["suggested_shares"] == 0
    assert plan["exploration_budget_value"] == 103.67
    # A cheaper unit inside the cap is bridged to one share.
    plan = add_policy.tranche_plan(
        tier="exploration", price=19.18, lot=1, shares=10, current_value=191.8,
        capital=3455.57, cash=461.63, setup_pcts=[0.025], policy=LEGACY)
    assert plan["suggested_shares"] == 1


def test_validated_keeps_one_market_unit_inside_the_concentration_room():
    plan = add_policy.tranche_plan(
        tier="validated", price=10.0, lot=100, shares=1000, current_value=10000.0,
        capital=100000.0, cash=50000.0, setup_pcts=[0.075])
    assert plan["suggested_shares"] == 100
    # No concentration room left: 60% of the book is already this name.
    plan = add_policy.tranche_plan(
        tier="validated", price=10.0, lot=100, shares=6000, current_value=60000.0,
        capital=100000.0, cash=50000.0, setup_pcts=[0.075])
    assert plan["suggested_shares"] == 0
    assert plan["position_room_shares"] == 0


def test_a_leveraged_product_is_read_through_its_underlying_when_it_has_bars():
    from clawock.decision import add_side

    holdings_of, through = add_side.read_through(
        ["RKLB", "RKLX", "SPCX", "SPCH", "07226"],
        {"RKLX": "RKLB", "SPCH": "SPCX", "07226": "HSTECH"})
    assert holdings_of == {"RKLB": ["RKLX"], "SPCX": ["SPCH"]}
    # HSTECH has no series here, so 07226 keeps its own chart.
    assert through == {"RKLX", "SPCH"}


def _book_plan(**overrides):
    args = dict(tier="exploration_cold_start", price=148.03, lot=1, shares=1,
                current_value=148.03, capital=3455.57, cash=461.63, setup_pcts=[],
                policy=POLICY, setup_tiers=["exploration_cold_start"],
                stop_distance=148.03 * 0.08)
    args.update(overrides)
    return add_policy.tranche_plan(**args)


def test_one_unit_is_allowed_when_its_loss_at_the_stop_fits_the_risk_cap():
    """SPCX without the F17 zero: the target (0.5% of $3,455) is below one
    $148 share, but one share is under the 5% bridge and loses ~$11.8 at an 8%
    invalidation, inside the 0.5% ($17.3) per-tranche risk cap."""
    plan = _book_plan()
    assert plan["suggested_shares"] == 1
    assert plan["unit_bridged"] is True
    assert plan["risk_cap_value"] == round(3455.57 * POLICY["sizing"]["max_tranche_risk_book_pct"], 2)


def test_a_unit_whose_stop_is_too_far_is_still_refused():
    # 15% to the invalidation: one share loses ~$22 > the $17.3 cap.
    assert _book_plan(stop_distance=148.03 * 0.15)["suggested_shares"] == 0
    # No invalidation at all: the loss is unbounded, nothing is bridged.
    plan = _book_plan(stop_distance=None)
    assert plan["suggested_shares"] == 0 and plan["risk_unbounded"] is True


def test_a_tranche_is_a_share_of_the_book_not_of_the_position():
    """HK 03033: 1% of a 64,568 HKD book is ~646 HKD, below one 200-share lot
    (854 HKD), which bridges; validated sizes whole lots by target."""
    common = dict(price=4.272, lot=200, shares=1000, current_value=4272.0,
                  capital=64568.4, cash=12781.0, stop_distance=4.272 * 0.06)
    assert _book_plan(tier="exploration", setup_tiers=["exploration"], **common)[
        "suggested_shares"] == 200
    validated = _book_plan(tier="validated", setup_tiers=["validated"], **common)
    pct = POLICY["sizing"]["tranche_book_pct"]["validated"]
    assert validated["suggested_shares"] == int(64568.4 * pct // (4.272 * 200)) * 200 > 0
    assert "unit_bridged" not in validated


def test_cash_is_reported_not_a_cap_and_concentration_still_is():
    plan = _book_plan(tier="validated", setup_tiers=["validated"], price=10.0, lot=100,
                      current_value=10000.0, capital=100000.0, cash=0.0,
                      stop_distance=0.5)
    expected = int(100000 * POLICY["sizing"]["tranche_book_pct"]["validated"] // 1000) * 100
    assert plan["suggested_shares"] == expected > 0
    assert plan["cash_shortfall_value"] == expected * 10.0
    full = _book_plan(tier="validated", setup_tiers=["validated"], price=10.0, lot=100,
                      current_value=60000.0, capital=100000.0, cash=50000.0,
                      stop_distance=0.5)
    assert full["suggested_shares"] == 0


def test_a_leveraged_name_sizes_against_the_guardrails_35_percent_cap():
    common = dict(tier="validated", setup_tiers=["validated"], price=10.0, lot=100,
                  capital=100000.0, cash=50000.0, stop_distance=0.5)
    assert _book_plan(current_value=36000.0, leveraged=True, **common)["suggested_shares"] == 0
    assert _book_plan(current_value=36000.0, leveraged=False, **common)["suggested_shares"] > 0


def test_the_smallest_tier_present_sets_the_size():
    plan = _book_plan(tier="validated", setup_tiers=["validated", "left_scale_in"],
                      price=10.0, lot=1, current_value=1000.0, capital=100000.0,
                      cash=50000.0, stop_distance=0.5)
    assert plan["tranche_book_pct"] == POLICY["sizing"]["tranche_book_pct"]["left_scale_in"]
