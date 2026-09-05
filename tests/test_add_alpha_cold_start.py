"""Two of three evidence families were never online, so "any two" meant "chase".

`classify_authority` has three independent families — price-relative (factor or
peer residual), point-in-time information, and a confirmed un-overheated 20-day
breakout — and `minimum_evidence_families = 2`. That design is deliberately not
momentum-only. What shipped was, because on 2026-09-05 the counters read:

    cross_sectional_factor  prospective_dates  8/24   (+ clustered_edge, membership_history)
    news evidence graph     history_dates     16/24
    peer_residual           blockers: dates, hit_rate_ci, signed_residual_ci

With two families structurally unable to fire, the only way to reach two was to
pair the survivor with `technical_breakout` — so a breakout became mandatory.
Ten holdings, ten `independent_evidence_families` blockers, zero add decisions
in 47 days.

The cold-start exception is the smallest change that breaks that: one family,
half the tranche, non-leveraged only, negative information still blocking, and
a price confirmation still required. It retires itself when the counters fill —
which is the property most of these assertions are about, because an exception
that outlives its reason is just a weaker rule.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawock.decision import add_alpha, packet

POLICY = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "add-alpha-policy.json")
    .read_text(encoding="utf-8"))

PASSING_PEER = {
    "leader_continuation": {"eligible": True, "signed_residual": 0.05,
                            "peer_count": 5, "hit_rate": 0.6},
    "usable_for_decisions": False,
}


def _authority(**over):
    kwargs = dict(
        factor={}, peer={}, information={},
        leveraged=False, policy=POLICY, market="US", cold_start=True,
    )
    kwargs.update(over)
    return add_alpha.classify_authority(
        kwargs.pop("factor"), kwargs.pop("peer"), kwargs.pop("information"),
        **kwargs)


def _one_family_technical():
    """A clean breakout is one family — the survivor that used to be mandatory."""
    return {"close": 103.23, "prior_20d_high": 96.40, "zscore20": 0.9}


def test_one_family_authorises_a_half_slice_while_the_others_warm_up():
    out = _authority(technical=_one_family_technical())

    assert out["evidence_families"] == ["technical_breakout"]
    assert out["blockers"] == [], (
        "one family used to be an automatic independent_evidence_families block, "
        "which with two families offline meant nothing could ever be authorised")
    assert out["tier"] == "exploration_cold_start", (
        "a one-family authorisation must never be indistinguishable from a "
        "two-family one in the ledger")
    assert out["cold_start_relief"] is True


def test_the_exception_retires_itself_when_the_families_come_online():
    """The property that keeps this from becoming a permanently weaker rule."""
    out = _authority(technical=_one_family_technical(), cold_start=False)

    assert out["tier"] == "none"
    assert "independent_evidence_families" in out["blockers"]


def test_a_leveraged_name_is_still_refused():
    out = _authority(technical=_one_family_technical(), leveraged=True)

    assert out["tier"] == "none"
    assert "independent_evidence_families" in out["blockers"]
    assert "leveraged_requires_validated_evidence" in out["blockers"]


def test_negative_information_still_blocks_before_anything_else():
    out = _authority(
        technical=_one_family_technical(),
        information={"signed_score": -0.5},
    )

    assert "negative_information" in out["blockers"]
    assert out["tier"] == "none", "a relaxed count must not outrank a red flag"


def test_zero_families_is_still_zero():
    out = _authority()

    assert out["evidence_families"] == []
    assert out["tier"] == "none"
    assert "independent_evidence_families" in out["blockers"]


def test_the_slice_is_half_the_exploration_one_and_still_needs_a_confirmation():
    setup = add_alpha.confirmation_setup(
        {"close": 103.23, "prior_20d_high": 96.40, "zscore20": 0.9,
         "prior_5d_high": 101.0, "prior_5d_low": 95.0, "ma20": 97.0,
         "chandelier_stop": 92.0, "as_of": "2026-09-05",
         "usable": True, "stop_state": "intact", "atr14": 2.0},
        {"tier": "exploration_cold_start", "market": "US",
         "sources": ["technical_breakout"],
         "evidence_families": ["technical_breakout"]},
        POLICY, ticker="CRCL",
    )

    assert setup is not None, (
        "the tier exists but builds no execution intent — a decorative tier is "
        "worse than none, it reads as authority in the packet and does nothing")
    assert setup["tranche_pct_of_position"] == POLICY["cold_start_tranche_pct"]
    assert setup["tranche_pct_of_position"] * 2 == pytest.approx(
        POLICY["exploration_tranche_pct"]), "half, by construction"
    assert setup["max_tranches"] == 1
    assert setup["entry_type"] == "price_above", (
        "the relaxed count must not also relax the confirmation — this is an "
        "add-if-it-confirms, never a market order")


def test_the_activation_reader_reports_each_family_and_what_it_is_waiting_for():
    read = packet.add_alpha_activation({
        "cross_sectional_factor": {"activation": {
            "active": False, "usable_for_decisions": False,
            "checks": {"prospective_dates": {"actual": 8, "required": 24}},
            "blockers": ["prospective_dates"]}},
        "peer_residual": {"rule_activation": {
            "leader_continuation": {"active": False, "blockers": ["dates"]}}},
        "news_evidence_graph": {"information_overlay": {"activation": {
            "active": False,
            "checks": {"history_dates": {"actual": 16, "required": 24}},
            "blockers": ["history_dates"]}}},
    })

    assert read["cold_start"] is True
    assert set(read["warming_up"]) == {
        "price_relative_factor", "price_relative_peer", "point_in_time_information"}
    assert read["families"]["price_relative_factor"]["progress"] == {
        "prospective_dates": [8, 24]}
    assert read["families"]["point_in_time_information"]["progress"] == {
        "history_dates": [16, 24]}


def test_all_families_active_means_no_cold_start():
    read = packet.add_alpha_activation({
        "cross_sectional_factor": {"activation": {"active": True}},
        "peer_residual": {"rule_activation": {"active": True}},
        "news_evidence_graph": {"information_overlay": {"activation": {"active": True}}},
    })

    assert read["cold_start"] is False and read["warming_up"] == []
