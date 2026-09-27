"""Left-side scale-in (kcn 2026-09-26 「偏左侧」): the rule, not its opinion.

The evidence and its limits are in `decision/left_side.py` and the policy's
`left_side.rationale`; these tests pin the rule the backtest measured.
"""
from __future__ import annotations

import json
from pathlib import Path

from clawock.decision import left_side

POLICY = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "add-shapes-experiment.json").read_text())
POLICY["left_side"]["enabled"] = True


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
