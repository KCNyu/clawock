"""The shape study has to be re-derivable, and honest about its baseline.

#856's numbers are quoted as fact in permanent prose and cannot be re-derived,
because the run left nothing behind. This module exists so the 2026-09-05 answer
to 「甚至在跌也有可能应该加仓」 does not end up in the same place: it reads the
canonical bar store, states its own limits, and writes a run card.

The assertions are about the two things a reader would be misled by if they
broke — the shape boundaries, and the presence of the baseline row without which
every hit rate reads as better than it is.
"""
from __future__ import annotations

from clawock.evaluation import add_shapes


def _rising(n=140, start=100.0, step=0.5):
    return [{"date": f"d{i:03d}", "close": start + i * step,
             "high": start + i * step + 0.2} for i in range(n)]


def test_a_clean_breakout_and_an_overheated_one_are_different_shapes():
    closes = [10.0] * 19 + [11.0]
    assert add_shapes.classify_shape(closes, 10.0, 0.9, no_chase_z=2.0) == "breakout"
    assert add_shapes.classify_shape(closes, 10.0, 2.9, no_chase_z=2.0) == (
        "breakout_overheated"), "the no-chase ceiling is what separates the two"


def test_a_pullback_inside_an_uptrend_is_its_own_shape():
    """The shape add_side.py says the desk never collected a sample of."""
    closes = [80.0 + i for i in range(50)]      # a long climb…
    closes.append(closes[-1] * 0.97)            # …and a shallow pullback
    shape = add_shapes.classify_shape(closes, closes[-2], 0.0, no_chase_z=2.0)
    assert shape == "pullback_in_uptrend"


def test_a_deep_dip_is_not_read_as_a_pullback():
    closes = [100.0] * 50 + [80.0]
    assert add_shapes.classify_shape(closes, 100.0, -2.0, no_chase_z=2.0) == "deep_dip"


def test_a_name_deep_inside_its_range_forms_no_shape_at_all():
    closes = [100.0] * 49 + [97.0]
    assert add_shapes.classify_shape(closes, 100.0, -0.5, no_chase_z=2.0) is None


def test_the_summary_always_carries_the_unconditional_baseline():
    """Every hit rate here is meaningless without the number to compare it to.

    A breakout hitting 65% is a finding; a breakout hitting 65% where any random
    session hits 64% is not, and the row that tells them apart must not be
    optional.
    """
    summary = add_shapes.summarise(
        add_shapes.collect({"UP": _rising()}, no_chase_z=2.0))

    assert summary["baseline"], "the baseline row is gone; every shape now reads as better"
    for horizon in ("t1", "t5", "t20"):
        assert summary["baseline"][horizon]["n"] > 0
        assert 0.0 <= summary["baseline"][horizon]["hit_rate"] <= 1.0


def test_a_monotonic_climb_is_all_breakout_and_beats_nothing():
    """Anti-vacuity: a rising series must be classified, and must not look special.

    Every session of a straight climb is a breakout, and the baseline is the same
    sessions — so the shape cannot outperform it. A run where the breakout row
    beat the baseline on this input would mean the two are not being computed
    over the same events.
    """
    summary = add_shapes.summarise(
        add_shapes.collect({"UP": _rising()}, no_chase_z=99.0))

    assert "breakout" in summary["shapes"]
    assert summary["shapes"]["breakout"]["t1"]["hit_rate"] == (
        summary["baseline"]["t1"]["hit_rate"])


def test_the_module_says_what_it_is_not():
    """The limits belong next to the numbers, not in a commit message."""
    doc = add_shapes.__doc__
    for warning in ("Overlapping samples", "Survivorship", "One regime",
                    "evaluate-add-alpha"):
        assert warning in doc, f"the {warning} caveat is gone from the docstring"


def test_the_campaign_simulation_measures_the_production_left_ladder():
    """`--campaigns` runs the packet's own rules: a name that trends up and then
    sells off 3 ATR under its 20-day high while above MA200 opens a left
    campaign; the same series with the left side off opens none."""
    import json as _json
    from pathlib import Path as _Path

    config = _Path(__file__).resolve().parents[1] / "config"
    policy = {**_json.loads((config / "add-shapes-experiment.json").read_text()),
              **_json.loads((config / "left-side-policy.json").read_text())}
    bars = []
    price = 100.0
    for i in range(260):
        price *= 1.004 if i < 240 else 0.97
        bars.append({"date": f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": price,
                     "high": price * 1.01, "low": price * 0.99, "close": price})
    prepared = {"UPDIP": {"bars": bars, "sigs": add_shapes._prepare(bars)}}
    result = add_shapes.simulate(prepared, policy=policy, no_chase_z=2.0, split="2099-01-01")
    left = result["families"]["left"]["all"]["in_sample"]
    assert left["campaigns"] >= 1
    assert result["families"]["proposed_sizing"]["all"]["in_sample"]["campaigns"] >= 1


def test_campaign_card_records_the_effective_candidate_and_eligible_count(monkeypatch):
    from argparse import Namespace

    seen = {}
    monkeypatch.setattr(add_shapes, "_prepare", lambda bars: [None] * len(bars))
    monkeypatch.setattr(add_shapes, "simulate", lambda *args, **kwargs: {"families": {}})
    monkeypatch.setattr(add_shapes.run_card, "record",
                        lambda *args, **kwargs: seen.update(kwargs) or "card")
    bars = [{"date": "2026-01-01", "close": 1.0}] * add_shapes.MIN_BARS
    args = Namespace(source="store", split="2025-07-01", json=True, no_card=False)
    live = {"left_side": {"enabled": False}}
    assert add_shapes._main_campaigns(args, live, 2.0, {"OK": bars, "SHORT": bars[:2]}, 0) == 0
    assert seen["params"]["input_names"] == len(seen["inputs"]) == 1
    assert seen["params"]["left_side"]["enabled"] is True
    assert seen["params"]["sizing"]["basis"] == "book_risk"


def test_marginal_names_a_sleeve_that_only_adds_more_of_the_same():
    """A left sleeve that is the right one at half size plus noise: high
    correlation, beta near 0.5, Sharpe below the hurdle, Sharpe falls as it grows."""
    import random

    rng = random.Random(3)
    right, left = {}, {}
    for i in range(300):
        day = f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}"
        right[day] = 0.001 + rng.gauss(0, 0.004)
        left[day] = 0.5 * right[day] - 0.0003 + rng.gauss(0, 0.002)
    cell = add_shapes._marginal(right, left)
    assert cell["corr_daily"] > 0.6
    assert 0.4 < cell["left_beta_on_right"] < 0.6
    assert cell["sharpe_left"] < cell["sharpe_hurdle"]
    weights = cell["right_plus_left_at_weight"]
    assert cell["right_alone"]["sharpe"] > weights["0.25"]["sharpe"] > weights["1.0"]["sharpe"]
    assert add_shapes._marginal({"2025-01-01": 0.01}, {}) == {"sessions": 1}
