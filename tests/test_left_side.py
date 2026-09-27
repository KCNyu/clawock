"""Left-side scale-in (kcn 2026-09-26 「偏左侧」): the rule, not its opinion.

The evidence and its limits are in `decision/left_side.py` and
`config/left-side-policy.json`; these tests pin the rule the backtest measured
and the observe mode it runs in live (kcn 2026-09-27).
"""
from __future__ import annotations

import json
from pathlib import Path

from clawock.decision import left_side

LIVE = left_side.load_policy(
    Path(__file__).resolve().parents[1] / "config" / "left-side-policy.json")
# The rule tests below exercise the setup a sized form would emit; live runs
# `observe`, which `test_observe_mode_never_emits_a_setup` pins.
POLICY = {"left_side": {**LIVE["left_side"], "mode": "authorize"}}


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


def test_observe_mode_never_emits_a_setup():
    """Live is `observe`: the ladder is read, nothing the packet could size."""
    assert LIVE["left_side"]["enabled"] is True
    assert LIVE["left_side"]["mode"] == "observe"
    assert left_side.ladder(_row(), LIVE) is not None
    assert left_side.scale_in_setup(_row(), LIVE, ticker="MSFT", market="US",
                                    leveraged=False) is None


def test_live_left_terms_stay_out_of_the_add_alpha_policy():
    """add-alpha-policy.json's hash is the exploration campaign id; putting the
    left rule there would reset every one-tranche-per-policy count."""
    live = json.loads((Path(__file__).resolve().parents[1] / "config" /
                       "add-alpha-policy.json").read_text())
    assert "left_side" not in live


def _observe(thesis_state="intact", blockers=(), leveraged=False):
    return left_side.observe(_row(), LIVE, leveraged=leveraged,
                             thesis_state=thesis_state, blockers=blockers)


def test_each_gate_is_named_in_the_order_the_packet_checks_it():
    passed = _observe()
    assert passed["gate"] is None and passed["authorization"] is None
    assert passed["rungs"] == left_side.ladder(_row(), LIVE)["rungs"]
    for kwargs, gate in ((dict(leveraged=True, thesis_state="broken"), "leveraged_excluded"),
                         (dict(thesis_state="unknown"), "thesis_unrecorded"),
                         (dict(thesis_state="weakening"), "thesis_not_intact"),
                         (dict(blockers=["negative_information", "peer_laggard_avoidance"]),
                          "negative_information"),
                         (dict(blockers=["peer_laggard_avoidance"]), "peer_laggard")):
        assert _observe(**kwargs)["gate"] == gate
    # Not fired at all (too shallow) is None, not a gate.
    assert left_side.observe(_row(close=95.0), LIVE, leveraged=False,
                             thesis_state="intact") is None


def test_both_entries_read_the_left_ladder_as_an_unsized_wait():
    """The slot and the brief name the same rung through the same code; the
    read stays `wait` with no size, and a proxy standing in for a leveraged
    product produces no left row."""
    from clawock.decision import add_policy, add_side

    params_policy = json.loads((Path(__file__).resolve().parents[1] / "config" /
                                "add-alpha-policy.json").read_text())
    sig = {**_row(), "zscore20": -1.8, "prior_5d_low": 88.0}
    out = {}
    for entry in ("brief", "intraday"):
        profile = add_policy.entry_profile(entry)
        radar = add_side.radar({"MSFT": sig, "RKLB": sig},
                               holdings_of={"RKLB": ["RKLX"]},
                               confirmed_at_close=profile["close_confirmed"],
                               left_policy=LIVE, **add_policy.read_params(params_policy))
        out[entry] = add_side.read_rows(radar=radar, levels=radar["levels"],
                                        plan_context={"open": []}, leveraged={"RKLX"},
                                        close_confirmed=profile["close_confirmed"],
                                        policy=params_policy)["rows"]
    assert out["brief"] == out["intraday"]
    (row,) = out["brief"]
    levels = left_side.ladder(_row(), LIVE)
    assert (row["ticker"], row["verdict"], row["kind"]) == ("MSFT", "wait", "left_scale_in")
    assert row["evidence"]["left_rung"] == levels["rungs"][0]
    assert row["invalidation"] == levels["invalidation_price"]
    assert row["authorization"] is None and "size_cap" not in row
    assert row["why"].startswith("左侧观察(不给尺寸)")
    assert row["needs"].startswith(f"首档 ≤{levels['rungs'][0]}")


def test_held_leveraged_product_has_no_left_ladder_or_weakness_row():
    from clawock.decision import add_policy, add_side

    policy = json.loads((Path(__file__).resolve().parents[1] / "config" /
                         "add-alpha-policy.json").read_text())
    sig = {**_row(), "prior_5d_low": 70.0}
    radar = add_side.radar({"07226": sig}, holdings_of={"07226": ["07226"]},
                           left_policy=LIVE, **add_policy.read_params(policy))
    assert "left_rung" not in radar["levels"]["07226"]
    rows = add_side.read_rows(radar=radar, levels=radar["levels"],
                              plan_context={"open": []}, leveraged={"07226"},
                              policy=policy)["rows"]
    assert not any("left_weakness" in row["triggers"] for row in rows)


def test_a_quiet_day_is_a_recorded_zero_and_a_rerun_replaces_it(tmp_path):
    path = tmp_path / "left_side_history.jsonl"
    packet = {"_meta": {"generation_id": "g1"}, "date": "2026-09-28",
              "tickers": {"MSFT": {"leg": "US", "quant": {}}}}
    assert left_side.record_history(packet, path)["rows"] == {}
    fired = {**packet, "_meta": {"generation_id": "g2"}, "tickers": {"MSFT": {
        "leg": "US", "quant": {"left_side": _observe()}}}}
    left_side.record_history(fired, path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(r["as_of"], r["generation_id"]) for r in rows] == [("2026-09-28", "g2")]
    assert rows[0]["rows"]["MSFT"]["gate"] is None
    assert rows[0]["rows"]["MSFT"]["leg"] == "US"
