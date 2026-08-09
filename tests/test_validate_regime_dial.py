"""The leverage dial's justification was one in-sample number over one crash.

`compute_regime.py` gates the largest exposure in the book on thresholds chosen
over the same window the improvement is reported on. The repo already refuses
retrospective activation elsewhere (`cross_sectional_factor`) and gates factors
on a clustered CI (`quant_signal_review`); the dial was the exception.

These tests hold the validator itself honest: no look-ahead, a null that is hard
rather than easy to beat, and a tier mapping that cannot drift away from the one
in production.

Run: python3 -m pytest tests/test_validate_regime_dial.py -q
"""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "data"
sys.path.insert(0, str(DATA))

import validate_regime_dial as dial  # noqa: E402


def _ramp(n, step=0.01, start=100.0):
    """A monotonically rising series — trend-on everywhere once the MA forms."""
    closes, price = [], start
    for _ in range(n):
        closes.append(price)
        price *= (1 + step)
    return closes


def _crash(n_up=300, n_down=300, step=0.01):
    closes = _ramp(n_up, step)
    price = closes[-1]
    for _ in range(n_down):
        price *= (1 - step)
        closes.append(price)
    return closes


# ── the mapping must be production's, not a lookalike ───────────────────────

@pytest.mark.parametrize("trend_on", [True, False])
@pytest.mark.parametrize("vol_ok", [True, False])
def test_the_tier_mapping_matches_the_shipped_classifier(trend_on, vol_ok):
    """If compute_regime.classify changes and this does not, the validator
    silently starts validating a rule nobody ships."""
    from clawock import compute_regime

    close = 110.0 if trend_on else 90.0
    vol = 0.10 if vol_ok else 0.90
    _, _, prod_tier, prod_mult, _ = compute_regime.classify(close, 100.0, vol)

    assert dial.tier_for(trend_on, vol_ok) == prod_tier
    assert dial.TIER_MULT[prod_tier] == prod_mult


def test_the_production_constants_match_compute_regime():
    from clawock import compute_regime

    assert dial.PROD_MA == compute_regime.MA_WINDOW
    assert dial.PROD_VOL_CAP == compute_regime.VOL_CAP
    assert dial.PROD_VOL_WINDOW == compute_regime.VOL_WINDOW


# ── no look-ahead ───────────────────────────────────────────────────────────

def test_the_signal_for_a_day_cannot_see_that_day():
    """Exposure for session i must be a function of closes through i-1 only.

    Two series identical except for the final bar must produce the same exposure
    for that final session — a rule that peeked at today's close would size
    itself differently once today's close changed. (Checking that appending a
    bar leaves earlier exposures alone does NOT catch this: a trailing MA never
    depends on the future either way.)
    """
    # A flat series puts the MA exactly at the price, so the two variants land on
    # opposite sides of it and a peeking rule is forced to disagree with itself.
    # (A crash fixture does not work here: deep in a downtrend both variants are
    # still below the MA, so look-ahead changes nothing and the test passes.)
    flat = [100.0] * 400
    crashed = flat[:-1] + [50.0]
    mooned = flat[:-1] + [150.0]

    _, exposure_flat, _ = dial.exposure_path(flat)
    _, exposure_crashed, _ = dial.exposure_path(crashed)
    _, exposure_mooned, _ = dial.exposure_path(mooned)

    assert exposure_crashed[-1] == exposure_mooned[-1], (
        "the last session's exposure moved with the last session's own close — "
        "the trend leg is reading the bar it is supposed to precede")
    # Compared against the untouched history too, so the *volatility* leg is
    # pinned as well: a final -50% bar blows the 20d vol past the cap, and a rule
    # that reads vols[i] instead of vols[i-1] would de-risk on a day it could not
    # yet have seen. Comparing the two shocked variants alone misses that,
    # because both shocks move vol the same way.
    assert exposure_crashed == exposure_flat == exposure_mooned


def test_a_rising_series_is_held_at_full_leverage():
    closes = _ramp(400)
    _, exposure, tiers = dial.exposure_path(closes)

    tail = exposure[-50:]
    assert all(e == dial.BASE_LEVERAGE for e in tail), set(tail)
    assert tiers[-1] == "green"


def test_a_collapsing_series_ends_de_risked():
    closes = _crash()
    _, exposure, tiers = dial.exposure_path(closes)

    assert exposure[-1] < dial.BASE_LEVERAGE
    assert tiers[-1] in {"amber", "red"}


# ── the arithmetic ──────────────────────────────────────────────────────────

def test_nav_compounds_the_levered_return():
    nav = dial.nav_from([0.10, -0.10], [2.0, 2.0])

    assert nav[-1] == pytest.approx(1.2 * 0.8)


def test_max_drawdown_is_peak_to_trough():
    assert dial.max_drawdown([1.0, 1.5, 0.75, 1.0]) == pytest.approx(-0.5)


def test_summarize_reports_improvement_as_dial_minus_hold():
    returns = [0.05, -0.20, 0.05]
    stats = dial.summarize(returns, [2.0, 0.0, 2.0])

    assert stats["dial_max_drawdown"] > stats["hold_max_drawdown"]
    assert stats["drawdown_improvement"] > 0


def test_a_dial_that_never_de_risks_shows_no_improvement():
    returns = [0.05, -0.20, 0.05]

    stats = dial.summarize(returns, [2.0, 2.0, 2.0])

    assert stats["drawdown_improvement"] == 0.0
    assert stats["return_improvement"] == 0.0


def test_tier_distribution_sums_to_the_sample():
    _, _, tiers = dial.exposure_path(_crash())

    out = dial.tier_distribution(tiers)

    assert sum(out["counts"].values()) == out["sessions"] == len(tiers)
    assert sum(out["pct"].values()) == pytest.approx(100.0, abs=0.2)


# ── the null has to be hard to beat ─────────────────────────────────────────

def test_the_permutation_null_preserves_time_in_market():
    """A plain shuffle would destroy the exposure path's autocorrelation and make
    almost any signal look significant. A circular shift keeps the shape and only
    breaks the alignment — which is the thing under test."""
    closes = _crash()
    returns, exposure, _ = dial.exposure_path(closes)

    out = dial.permutation_test(returns, exposure, permutations=200)

    assert out["null"].startswith("circular shift")
    assert 0 < out["p_value_drawdown"] <= 1
    # The load-bearing part: a circular shift cannot change how many times the
    # path switches level, so every draw shares the observed count. A shuffle
    # would shatter it, and an easy null makes any signal look significant.
    assert out["null_switch_counts"] == [out["observed_switches"]]
    assert out["observed_switches"] > 1, "fixture must actually switch levels"


def test_a_p_value_of_zero_is_impossible_even_for_a_perfectly_timed_dial():
    """One session carries the entire crash and the dial is flat exactly there.
    No shift can match it, so the raw count is 0 — and 0/N would publish p=0.0,
    a claim no finite sample supports."""
    returns = [0.002] * 60
    returns[30] = -0.45
    exposure = [2.0] * 60
    exposure[30] = 0.0

    out = dial.permutation_test(returns, exposure, permutations=100, seed=3)

    assert out["p_value_drawdown"] == pytest.approx(1 / 101, abs=1e-6)
    assert out["observed_drawdown_improvement"] > 0


def test_a_p_value_can_never_be_exactly_zero():
    """The observed path is itself one draw from the null, so 0.0 is a claim the
    data cannot support."""
    closes = _crash()
    returns, exposure, _ = dial.exposure_path(closes)

    out = dial.permutation_test(returns, exposure, permutations=50)

    assert out["p_value_drawdown"] >= 1 / 51


def test_the_permutation_test_is_deterministic_for_a_seed():
    closes = _crash()
    returns, exposure, _ = dial.exposure_path(closes)

    first = dial.permutation_test(returns, exposure, permutations=100, seed=7)
    second = dial.permutation_test(returns, exposure, permutations=100, seed=7)

    assert first == second


def test_a_short_sample_refuses_rather_than_returning_a_number():
    out = dial.permutation_test([0.01] * 10, [2.0] * 10, permutations=100)

    assert out["p_value_drawdown"] is None
    assert "at least 30" in out["reason"]


# ── walk-forward ────────────────────────────────────────────────────────────

def test_walk_forward_scores_only_the_window_after_the_training_one():
    closes = _crash(400, 400)
    dates = [f"d{i:04d}" for i in range(len(closes))]

    out = dial.walk_forward(dates, closes, folds=2, ma_grid=(100, 200),
                            vol_grid=(0.4, 0.6))

    assert out["n_folds"] == 2
    for fold in out["folds"]:
        assert fold["train"][1] < fold["test"][0], "test window overlaps training"
    # Folds must not overlap each other either.
    first, second = out["folds"]
    assert first["test"][1] < second["test"][0]


def test_walk_forward_says_so_when_the_series_is_too_short():
    closes = _ramp(120)
    dates = [f"d{i:04d}" for i in range(len(closes))]

    out = dial.walk_forward(dates, closes, folds=4)

    assert out["folds"] == []
    assert "warmup" in out["reason"]


def test_walk_forward_reports_the_production_thresholds_alongside_the_chosen_ones():
    """The interesting question is not "what would have been best" but "how did
    the shipped thresholds do out of sample"."""
    closes = _crash(400, 400)
    dates = [f"d{i:04d}" for i in range(len(closes))]

    out = dial.walk_forward(dates, closes, folds=2, ma_grid=(100, 200),
                            vol_grid=(0.4, 0.6))

    for fold in out["folds"]:
        assert "production_thresholds_out_of_sample" in fold
        assert isinstance(fold["chosen_matches_production"], bool)


# ── sensitivity ─────────────────────────────────────────────────────────────

def test_the_sensitivity_surface_ranks_production_against_the_whole_grid():
    closes = _crash(400, 400)

    out = dial.sensitivity_surface(closes, ma_grid=(100, dial.PROD_MA),
                                   vol_grid=(0.4, dial.PROD_VOL_CAP))

    assert out["production"] is not None
    assert 1 <= out["production_rank"] <= len(out["grid"])
    assert out["neighbourhood_spread"] >= 0


def test_every_reported_number_is_finite():
    closes = _crash()
    returns, exposure, _ = dial.exposure_path(closes)

    for value in dial.summarize(returns, exposure).values():
        assert value is None or isinstance(value, int) or math.isfinite(value)
