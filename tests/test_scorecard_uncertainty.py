"""The published win rate must carry its own sample-size bound (#1115).

The scorecard printed a hit rate next to `cluster_ci95` — an interval on the
*average benefit*, not on the rate it sat beside. So the one number a visitor
reads as "does this thing work" was the only number with no band, on a book
whose active bucket is a couple of dozen episodes. At that size a rate and a
coin flip are the same picture.

`win_rate_ci95` is the Wilson interval on the episode hit rate. It is not a new
statistic for the project: `setup_review.wilson_ci` already gates the T+0 setup
review on exactly this question, and this imports that function rather than
restating the algebra.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clawock.decision import ledger as dv2  # noqa: E402


def _episodes(benefits):
    return [{"plan_date": f"2026-08-{i + 1:02d}",
             "evaluation": {"benefit_t1_pct": b}}
            for i, b in enumerate(benefits)]


def test_the_interval_brackets_the_rate_and_widens_as_the_sample_shrinks():
    small = dv2._aggregate(_episodes([1.0, -1.0, 1.0, -1.0, 1.0, -1.0]),
                           "benefit_t1_pct")
    large = dv2._aggregate(_episodes([1.0, -1.0] * 60), "benefit_t1_pct")

    for agg in (small, large):
        lo, hi = agg["win_rate_ci95"]
        assert lo <= agg["win_rate"] <= hi
        assert 0.0 <= lo and hi <= 1.0

    small_width = small["win_rate_ci95"][1] - small["win_rate_ci95"][0]
    large_width = large["win_rate_ci95"][1] - large["win_rate_ci95"][0]
    assert small_width > large_width * 2, (
        "the interval is the whole point: six episodes must not look like 120")


def test_a_small_sample_that_looks_like_an_edge_still_straddles_a_coin_flip():
    """Six wins out of ten reads as 60% — and is not distinguishable from 50%."""
    agg = dv2._aggregate(_episodes([1.0] * 6 + [-1.0] * 4), "benefit_t1_pct")

    assert agg["win_rate"] == 0.6
    lo, hi = agg["win_rate_ci95"]
    assert lo < 0.5 < hi


def test_a_decisive_sample_clears_the_coin_flip():
    agg = dv2._aggregate(_episodes([1.0] * 45 + [-1.0] * 5), "benefit_t1_pct")

    assert agg["win_rate_ci95"][0] > 0.5, (
        "the bound must be able to say yes, or it is decoration")


def test_the_interval_is_the_same_function_the_setup_review_gates_on():
    from clawock.decision.setup_review import wilson_ci

    agg = dv2._aggregate(_episodes([1.0, 1.0, -1.0, 1.0, -1.0]), "benefit_t1_pct")

    assert agg["win_rate_ci95"] == wilson_ci(3, 5)


def test_an_empty_bucket_reports_no_interval_rather_than_a_fabricated_one():
    agg = dv2._aggregate([], "benefit_t1_pct")

    assert agg["win_rate"] is None and agg["win_rate_ci95"] is None
    # Same key set as the populated branch: a consumer reads these fields
    # unconditionally, and a missing key aborts a card instead of degrading it.
    assert set(dv2._aggregate(_episodes([1.0]), "benefit_t1_pct")) >= set(agg)


def test_the_scorecard_labels_both_intervals_and_will_not_colour_a_coin_flip():
    """Frontend contract, in the manner of the shadow-card checks above it.

    Two bands sit in that tile and they measure different things; and a rate
    whose interval straddles 50% must not be painted green, because green is
    the page saying "this worked".
    """
    js = (ROOT / "site" / "assets" / "js" / "dashboard.render.js").read_text(
        encoding="utf-8")
    tile = js.split("function renderPlanReview()", 1)[1].split("\n  function ", 1)[0]

    assert "胜率95%CI" in tile and "方向分CI" in tile, (
        "an unlabelled band next to a number it does not describe is worse "
        "than no band")
    assert 'wc[0] > 0.5 ? "pos"' in tile and 'wc[1] < 0.5 ? "neg"' in tile, (
        "colour must follow the interval, not the point estimate")

    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert "这不是什么" in html and "跨过 50%" in html, (
        "the limits have to be legible on the page, not only in the README")
