"""Left-side scale-in (kcn 2026-09-26 「偏左侧」): the rule, not its opinion.

The evidence and its limits are in `decision/left_side.py` and the policy's
`left_side.rationale`; these tests pin the rule the backtest measured.
"""
from __future__ import annotations

import json
from pathlib import Path

from clawock.decision import left_side
from clawock.decision import packet

POLICY = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "add-alpha-policy.json").read_text())


def _row(close=90.0, high=100.0, atr_pct=4.0, ma200=80.0):
    # ATR = 3.6 at close 90, so 10 points below the high is 2.78 ATR deep.
    return {"close": close, "prior_20d_high": high, "atr14_pct": atr_pct, "ma200": ma200}


def test_weakness_inside_the_trend_places_three_rungs_one_atr_apart():
    levels = left_side.ladder(_row(), POLICY)
    atr = 3.6
    assert levels["depth_atr"] == round(10 / atr, 2)
    assert levels["rungs"] == [round(100 - 2 * atr - i * atr, 4) for i in range(3)]
    assert levels["invalidation_price"] == round(100 - 2 * atr - 3 * atr, 4)
    assert levels["trend_floor"] == 80.0


def test_no_rungs_below_ma200_or_before_the_fall_is_deep_enough():
    assert left_side.ladder(_row(close=90.0, ma200=95.0), POLICY) is None
    assert left_side.ladder(_row(close=95.0), POLICY) is None   # 1.3 ATR deep


def test_leveraged_products_are_excluded_not_half_sized():
    assert left_side.scale_in_setup(_row(), POLICY, ticker="TQQQ", market="US",
                                    leveraged=True) is None


def test_the_next_rung_follows_the_ledgers_filled_count():
    first = left_side.scale_in_setup(_row(), POLICY, ticker="MSFT", market="US",
                                     leveraged=False)
    second = left_side.scale_in_setup(_row(), POLICY, ticker="MSFT", market="US",
                                      leveraged=False, used_tranches=1)
    assert first["campaign_id"] == second["campaign_id"]
    assert first["entry_type"] == "price_below"
    assert (first["entry_price"], second["entry_price"]) == tuple(first["rungs"][:2])
    assert first["authority_tier"] == "left_scale_in"


def test_a_disabled_policy_places_nothing():
    off = {**POLICY, "left_side": {**POLICY["left_side"], "enabled": False}}
    assert left_side.ladder(_row(), off) is None


def _gate(thesis_state="intact", blockers=(), leveraged=False):
    return packet._left_side(
        _row(), {"usable": True, "as_of": "2026-09-25"}, {"state": thesis_state},
        {"blockers": list(blockers)}, POLICY, ticker="MSFT", market="US",
        leveraged=leveraged, usage={})


def test_value_destruction_is_held_back_upstream_and_says_why():
    setup, gate = _gate()
    assert setup["setup_id"] == "left_scale_in" and gate == {"fired": True, "depth_atr": 2.78}
    for kwargs, reason in ((dict(thesis_state="unknown"), "thesis_not_intact"),
                           (dict(thesis_state="weakening"), "thesis_not_intact"),
                           (dict(blockers=["negative_information"]),
                            "negative_information_or_laggard"),
                           (dict(leveraged=True), "leveraged_excluded")):
        setup, gate = _gate(**kwargs)
        assert setup is None and gate["blocked"] == reason


def test_both_entries_read_the_left_ladder_as_a_wait_with_its_rung():
    """The slot and the brief name the same rung through the same code; the
    read stays `wait` (baseline-level evidence, size is the packet's call)
    and a proxy standing in for a leveraged product produces no left row."""
    from clawock.decision import add_policy, add_side

    sig = {**_row(), "zscore20": -1.8, "prior_5d_low": 88.0}
    out = {}
    for entry in ("brief", "intraday"):
        profile = add_policy.entry_profile(entry)
        radar = add_side.radar({"MSFT": sig, "RKLB": sig},
                               holdings_of={"RKLB": ["RKLX"]},
                               confirmed_at_close=profile["close_confirmed"],
                               policy=POLICY, **add_policy.read_params(POLICY))
        out[entry] = add_side.read_rows(radar=radar, levels=radar["levels"],
                                        plan_context={"open": []}, leveraged={"RKLX"},
                                        close_confirmed=profile["close_confirmed"],
                                        policy=POLICY)["rows"]
    assert out["brief"] == out["intraday"]
    (row,) = out["brief"]
    levels = left_side.ladder(_row(), POLICY)
    assert (row["ticker"], row["verdict"], row["kind"]) == ("MSFT", "wait", "left_scale_in")
    assert row["evidence"]["left_rung"] == levels["rungs"][0]
    assert row["invalidation"] == levels["invalidation_price"]
