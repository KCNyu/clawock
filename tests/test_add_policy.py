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


def test_the_read_lane_quotes_the_size_the_packet_uses():
    pct = add_policy.tier_terms(POLICY, "exploration")["tranche_pct_of_position"]
    assert add_policy.size_cap_text(POLICY) == (
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
        exploration_max_book_pct=0.03)
    assert plan["suggested_shares"] == 0
    assert plan["exploration_budget_value"] == 103.67
    # A cheaper unit inside the cap is bridged to one share.
    plan = add_policy.tranche_plan(
        tier="exploration", price=19.18, lot=1, shares=10, current_value=191.8,
        capital=3455.57, cash=461.63, setup_pcts=[0.025])
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
    assert holdings_of == {"RKLB": ["RKLB", "RKLX"], "SPCX": ["SPCX", "SPCH"]}
    # HSTECH has no series here, so 07226 keeps its own chart.
    assert through == {"RKLX", "SPCH"}
