"""The measured edge had no vote in the lane that decides (#1086).

kcn, 2026-08-26: 「我们现在主要是缺少加仓决策」.

#856 backtested eight months of real bars, 28 non-overlapping votes, and one
formation came back positive at every horizon:

    breakout (close > prior 20d high, z < 2)
        H1 52.5%  H5 54.0%  H10 52.5%  H20 55.9% [49,63] avg +16.25%
        HK leg    H20 59.4% avg +38.7%
    deep dip (<= 92% of the 20d high)
        H1 49.2%  H5 43.9%  H10 42.7%  H20 44.0%

#856 wired it into `add_side.py`, imported only by the two intraday harness
modules — the lane that TALKS. `classify_authority` took
`(factor, peer, information)` and never saw a price trend, so a clean breakout
contributed exactly zero to add authority. Measured on 2026-08-26:
`blocker_counts == {'independent_evidence_families': 8}` on a ten-name book,
71 retained intraday contexts holding 46 reject / 102 wait / **0 candidate**,
and August closed with zero add decisions.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def add_alpha():
    return pytest.importorskip("clawock.decision.add_alpha")


@pytest.fixture(scope="module")
def policy():
    return json.loads(
        (ROOT / "config" / "add-alpha-policy.json").read_text(encoding="utf-8"))


# One family short on its own — exactly SPCX / SPCH / 00100 on the measured day.
FACTOR_ONLY = {"market_percentile": 0.99, "coverage_pct": 99.0,
               "sector_universe_size": 9, "usable_for_decisions": False}
NO_PEER = {"triggered_rules": [], "available_peer_count": 5}
NO_INFO = {"signed_score": 0.0}


def _authority(add_alpha, policy, technical, *, leveraged=False):
    return add_alpha.classify_authority(
        FACTOR_ONLY, NO_PEER, NO_INFO, leveraged=leveraged,
        policy=policy, market="US", technical=technical)


def _breakout(z=1.2, status="fresh"):
    return {"status": status, "close": 100.0, "prior_20d_high": 95.0, "zscore20": z}


def test_a_confirmed_breakout_is_the_second_family(add_alpha, policy):
    """The unlock. One price-relative family plus a breakout reaches exploration."""
    before = _authority(add_alpha, policy, {})
    assert before["tier"] == "none"
    assert "independent_evidence_families" in before["blockers"]

    after = _authority(add_alpha, policy, _breakout())
    assert after["tier"] == "exploration"
    assert after["evidence_families"] == ["price_relative", "technical_breakout"]
    assert after["technical_reasons"], "the reason must be auditable, not implied"


def test_the_bar_itself_does_not_move(add_alpha, policy):
    """A third family is not a relaxation — two are still required.

    A breakout ALONE must not authorise anything, or this stops being an
    evidence bar and becomes a momentum trigger.
    """
    assert policy["minimum_evidence_families"] == 2
    alone = add_alpha.classify_authority(
        {}, NO_PEER, NO_INFO, leveraged=False, policy=policy,
        market="US", technical=_breakout())
    assert alone["evidence_families"] == ["technical_breakout"]
    assert alone["tier"] == "none"
    assert "independent_evidence_families" in alone["blockers"]


@pytest.mark.parametrize("technical, why", [
    ({}, "no technical row at all"),
    ({"status": "fresh", "close": 90.0, "prior_20d_high": 95.0, "zscore20": -1.0},
     "below the 20-day high — the deep-dip zone measured at 44%"),
    (_breakout(z=2.4), "broken out but overheated"),
    (_breakout(status="stale"), "a stale row is not evidence of anything"),
    ({"status": "fresh", "close": 100.0, "prior_20d_high": None, "zscore20": 1.0},
     "no level to break"),
])
def test_everything_that_is_not_a_clean_breakout_stays_blocked(
        add_alpha, policy, technical, why):
    result = _authority(add_alpha, policy, technical)
    assert "technical_breakout" not in result["evidence_families"], why
    assert result["tier"] == "none", why


def test_the_overheat_ceiling_is_the_policy_value_not_a_new_number(add_alpha, policy):
    """`early_no_chase_zscore` already exists; a second overheat constant would
    be the twin that drifts."""
    ceiling = policy["early_no_chase_zscore"]
    assert _authority(add_alpha, policy, _breakout(z=ceiling - 0.01))["tier"] == "exploration"
    assert _authority(add_alpha, policy, _breakout(z=ceiling))["tier"] == "none"


def test_a_price_pattern_never_promotes_a_leveraged_name(add_alpha, policy):
    """`validated` still needs decision-usable evidence on both sides.

    The three names carrying open hard stops are all leveraged. If a chart could
    promote them, this change would have re-opened the exact exposure the risk
    ledger is trying to close.
    """
    result = _authority(add_alpha, policy, _breakout(), leveraged=True)
    assert result["tier"] == "none"
    assert "leveraged_requires_validated_evidence" in result["blockers"]


def test_the_decision_lane_is_actually_wired_to_it():
    """#856's edge reached only `add_side.py`, which the plan path never imports.

    Asserted at the call site, because that is the thing that was missing —
    the classifier could grow the parameter and still never be handed one.
    """
    source = (ROOT / "src" / "clawock" / "decision" / "packet.py").read_text(
        encoding="utf-8")
    call = source.split("add_alpha.classify_authority(", 1)[1].split(")", 1)[0]
    assert "technical=technical" in call, (
        "the packet must hand the classifier the price trend, or the family "
        "can never fire in the lane that writes decisions")


def test_the_authority_constant_is_stated_once_for_the_packet(add_alpha):
    """It was 125 bytes duplicated per holding inside a 96KB cap with 873 to spare.

    Measured before the move: the packet was 97,431/98,304 on a ten-name book —
    0.9% headroom, growing with every position. A constant repeated per row is
    waste by construction, and nothing read it.
    """
    import inspect
    source = inspect.getsource(add_alpha.classify_authority)
    assert '"discipline":' not in source, (
        "the per-ticker copy is back; put constants in the packet-level policy")
    assert isinstance(add_alpha.AUTHORITY_DISCIPLINE, str)
    assert "two independent families" in add_alpha.AUTHORITY_DISCIPLINE


def test_the_skill_tells_the_writer_the_third_family_exists():
    """Shipping the capability without telling the writer is an inert fix.

    The same anti-inert assertion #1075 needed: the packet can publish a family
    the plan writer has never been told to read.
    """
    skill = (ROOT / "skills" / "daily-deep-brief" / "SKILL.md").read_text(
        encoding="utf-8")
    for token in ("technical_breakout", "technical_reasons",
                  "early_no_chase_zscore"):
        assert token in skill, f"the packet publishes {token}; nothing reads it"
    assert "两族" in skill or "两个" in skill, (
        "the writer must be told the bar did NOT move")
