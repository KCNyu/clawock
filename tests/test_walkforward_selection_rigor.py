"""The variant table is a search, and the report has to price it (#1143/#1145).

`add_alpha_walkforward` prints four variants across three horizons in two
markets. Nothing in the output said how many of those cells were compared to
produce the sentence a reader writes, and nothing said how many sessions the
comparison rests on. `selection_rigor` adds both, and these tests hold it to the
part that matters most on this dataset: when the common sample is three sessions
it must say so and produce no number, because a decorated PBO on three sessions
is worse than no PBO at all.
"""
import random
import statistics

from clawock.evaluation import add_alpha_walkforward as wf


def _observations(per_variant_dates, seed=3, drift=None):
    """Build the `observations[market][variant][horizon]` shape `evaluate` makes."""
    rnd = random.Random(seed)
    drift = drift or {}
    market = {variant: {horizon: [] for horizon in wf.HORIZONS} for variant in wf.VARIANTS}
    for variant, dates in per_variant_dates.items():
        for day in dates:
            for horizon in wf.HORIZONS:
                market[variant][horizon].append({
                    "date": day,
                    "ticker": "TEST",
                    "return": rnd.gauss(drift.get(variant, 0.0), 0.02),
                })
    return {"test": market}


def _dates(n, start=1):
    return [f"2026-01-{index:02d}" for index in range(start, start + n)]


def test_only_sessions_every_variant_traded_enter_the_comparison():
    """A variant that skipped the bad weeks must not win by having skipped them.

    `price_relative` trades every session; `interaction` trades three. The
    comparison is restricted to the three they share, and the count is published
    so a reader can see the comparison is three sessions wide rather than
    twenty-three.
    """
    observations = _observations({
        "setup_only": _dates(20),
        "price_relative": _dates(20),
        "information": _dates(20),
        "interaction": _dates(3),
    })
    sessions, matrix = wf._daily_variant_matrix(observations["test"], 1)
    assert len(sessions) == 3
    assert len(matrix) == 3 and len(matrix[0]) == len(wf.VARIANTS)


def test_a_three_session_overlap_produces_no_number():
    """The live shape as of 2026-08-30, and the reason this block exists.

    On the real ledger the four variants share nine, six and one session in the
    US and three in HK. Both corrections must refuse: PBO because eight groups
    cannot be filled, DSR because twenty observations are not there.
    """
    observations = _observations({variant: _dates(3) for variant in wf.VARIANTS})
    rigor = wf._selection_rigor(observations)["test"]["t1"]
    assert rigor["n_sessions_all_variants_traded"] == 3
    assert rigor["pbo"]["status"] == "insufficient_sample"
    assert rigor["pbo"]["pbo"] is None
    assert rigor["deflated_sharpe"]["dsr"] is None


def test_a_long_enough_overlap_produces_both_numbers():
    observations = _observations({variant: _dates(28) for variant in wf.VARIANTS})
    rigor = wf._selection_rigor(observations)["test"]["t1"]
    assert rigor["pbo"]["status"] == "measured"
    assert 0.0 <= rigor["pbo"]["pbo"] <= 1.0
    assert rigor["deflated_sharpe"]["status"] == "measured"
    assert rigor["best_variant_by_sharpe"] in wf.VARIANTS
    # The deflation is for the whole table, not for the row that won.
    assert rigor["search_size"] == len(wf.VARIANTS) * len(wf.HORIZONS)
    assert rigor["deflated_sharpe"]["n_trials"] == rigor["search_size"]


def test_a_variant_search_over_noise_does_not_look_like_a_finding():
    """Four variants of nothing; the best one must not deflate to a claim."""
    observations = _observations({variant: _dates(28) for variant in wf.VARIANTS}, seed=11)
    rigor = wf._selection_rigor(observations)["test"]["t1"]
    assert rigor["deflated_sharpe"]["dsr"] < 0.9


def test_no_common_sessions_is_a_named_state_not_an_empty_number():
    observations = _observations({
        "setup_only": _dates(5, start=1),
        "price_relative": _dates(5, start=1),
        "information": _dates(5, start=1),
        "interaction": _dates(5, start=20),
    })
    rigor = wf._selection_rigor(observations)["test"]["t1"]
    assert rigor["status"] == "no_common_sessions"
    assert rigor["pbo"] is None and rigor["deflated_sharpe"] is None


def test_the_block_interval_is_reported_next_to_the_old_one():
    """Both intervals ship. The block length is how a reader tells them apart."""
    rows = [{"date": f"2026-02-{index:02d}", "ticker": "T", "return": 0.0,
             "excess_vs_setup": random.Random(index).gauss(0.001, 0.01)}
            for index in range(1, 26)]
    summary = wf._summary(rows)
    assert summary["excess_date_cluster_ci95"] is not None
    block = summary["excess_block_ci95"]
    assert block["n_clusters"] == 25
    assert block["block_length"] >= 1
    assert block["ci95"][0] <= summary["mean_excess_vs_same_date_setup"] <= block["ci95"][1]
