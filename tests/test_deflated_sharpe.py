"""A Sharpe ratio has to be deflated by the size of the search (#1134/#1145).

The walk-forward prints twelve cells and the sentence a reader writes from it
names the best one. The maximum of twelve zero-mean draws is not zero, so that
sentence needs a null to be compared against. These tests hold the deflation to
the properties that make it a null rather than a decoration: it grows with the
number of trials, it kills a winner selected out of noise, it survives a real
edge, it charges fat tails, and it refuses a search of one.
"""
import math
import random
import statistics

import pytest

from clawock.evaluation import bootstrap, cscv, deflated_sharpe as ds


def _returns(mean, sigma, n, seed):
    rnd = random.Random(seed)
    return [rnd.gauss(mean, sigma) for _ in range(n)]


def _rescaled_to_sharpe(series, target):
    """Scale a series about its own mean until its Sharpe equals `target`."""
    mean = statistics.fmean(series)
    deviation = statistics.stdev(series)
    wanted = mean / target
    return [mean + (value - mean) * (wanted / deviation) for value in series]


def test_the_null_grows_with_the_number_of_trials():
    """Search harder and the bar rises. That is the whole mechanism."""
    small = ds.expected_max_sharpe(4, 0.01)
    large = ds.expected_max_sharpe(400, 0.01)
    assert 0 < small < large


def test_the_null_is_zero_width_when_the_trials_do_not_differ():
    """Twelve configurations that all score the same have nothing to maximise."""
    assert ds.expected_max_sharpe(12, 0.0) is None


def test_a_winner_picked_out_of_noise_does_not_survive_deflation():
    """Twelve pure-noise streams; deflate the best one against its own search.

    Without the deflation the best of twelve noise streams has a positive
    Sharpe and a t-statistic that looks like evidence. With it, the probability
    the true Sharpe is positive collapses — that is the correction earning its
    place, on the exact shape the walk-forward's variant table has.
    """
    trials = [_returns(0.0, 0.02, 500, seed) for seed in range(12)]
    sharpes = [ds.sharpe(series) for series in trials]
    best = max(range(12), key=lambda index: sharpes[index])
    result = ds.deflated_sharpe_ratio(trials[best], n_trials=12, trial_sharpes=sharpes)
    assert result['status'] == 'measured'
    # Undeflated, the winner reads as a finding: a t-statistic past 1.6 and a
    # one-sided probability past 0.94.
    undeflated = bootstrap._norm_cdf(result['observed_sharpe'] * math.sqrt(499))
    assert undeflated > 0.9
    # Deflated, it lands where a search over nothing belongs: the winner's
    # Sharpe is the expected maximum of the search, so the probability that its
    # true Sharpe is positive is a coin flip, not a finding.
    assert result['observed_sharpe'] == pytest.approx(result['benchmark_sharpe'], abs=0.03)
    assert 0.3 < result['dsr'] < 0.7


def test_a_real_edge_survives_the_same_deflation():
    """The other half: the correction must not simply reject everything.

    Same search size, same sample length, same deflation — one stream with a
    real drift. The two tests together are what separate a null from a filter
    that says no to whatever it is shown.
    """
    trials = [_returns(0.0, 0.02, 500, seed) for seed in range(11)]
    edge = _returns(0.006, 0.02, 500, 99)
    sharpes = [ds.sharpe(series) for series in trials + [edge]]
    result = ds.deflated_sharpe_ratio(edge, n_trials=12, trial_sharpes=sharpes)
    assert result['dsr'] > 0.95


def test_fat_tails_are_charged_for():
    """Same Sharpe, heavier tails, lower probability.

    The plain `SR*sqrt(T-1)` statistic assumes normal returns. A stream with the
    same mean and the same standard deviation but a fatter tail deserves less
    confidence, and the moment correction is what makes it get less.
    """
    rnd = random.Random(4)
    normal = [rnd.gauss(0.004, 0.02) for _ in range(500)]
    # A normal mixture: 95% of the days at the same scale, 5% at four times it.
    # Same mean, fatter tail — the shape a return stream with occasional gaps
    # actually has, and the one the normal approximation flatters.
    heavy = [0.004 + (value - 0.004) * (4.0 if rnd.random() < 0.05 else 1.0)
             for value in normal]
    # Rescale so both carry the *same* Sharpe and only the shape differs.
    heavy = _rescaled_to_sharpe(heavy, ds.sharpe(normal))
    common = dict(n_trials=12, variance_of_trials=0.01)
    normal_result = ds.deflated_sharpe_ratio(normal, **common)
    heavy_result = ds.deflated_sharpe_ratio(heavy, **common)
    assert heavy_result['kurtosis'] > normal_result['kurtosis'] + 1.0
    assert abs(heavy_result['observed_sharpe'] - normal_result['observed_sharpe']) < 1e-6
    assert heavy_result['dsr'] < normal_result['dsr']


def test_a_single_pre_registered_configuration_is_refused():
    """There is nothing to deflate, and printing 1.0 would read as evidence."""
    result = ds.deflated_sharpe_ratio(_returns(0.004, 0.02, 250, 1), n_trials=1)
    assert result['dsr'] is None
    assert result['status'] == 'insufficient_search'


def test_a_short_sample_is_refused_rather_than_estimated():
    result = ds.deflated_sharpe_ratio(_returns(0.004, 0.02, 8, 1),
                                      n_trials=12, variance_of_trials=0.01)
    assert result['dsr'] is None
    assert result['status'] == 'insufficient_sample'


def test_deflated_sharpe_is_not_one_minus_pbo():
    """The two corrections are independent, and the issue text conflated them.

    Construct a search where one configuration has a genuine edge and the rest
    are noise: PBO is low (the ranking is stable) and DSR is high (the level
    survives). If DSR were `1 - PBO` these two would sum to one, and they do
    not. They answer different questions from different inputs and are reported
    side by side for that reason.
    """
    def search(drift, seed):
        rnd = random.Random(seed)
        matrix = [[rnd.gauss(drift, 0.01) for _ in range(8)] for _ in range(600)]
        pbo = cscv.probability_of_backtest_overfitting(
            matrix, lambda values: statistics.fmean(values) if values else None)
        sharpes = [ds.sharpe([row[column] for row in matrix]) for column in range(8)]
        best = max(range(8), key=lambda column: sharpes[column])
        dsr = ds.deflated_sharpe_ratio([row[best] for row in matrix],
                                       n_trials=8, trial_sharpes=sharpes)
        return pbo['pbo'], dsr['dsr']

    # Two searches over eight configurations each. They differ only by a common
    # drift added to every configuration, so the *ranking* problem is identical
    # in both — same seed, same relative order, same splits.
    without_edge = [search(0.0, seed) for seed in range(6)]
    with_edge = [search(0.004, seed) for seed in range(6)]

    # PBO cannot tell them apart, and should not: picking between eight
    # identical configurations is a coin flip whether or not they all make
    # money.
    assert [row[0] for row in without_edge] == [row[0] for row in with_edge]
    # DSR moves the whole way, because the level is what it prices.
    assert statistics.fmean([row[1] for row in without_edge]) < 0.6
    assert statistics.fmean([row[1] for row in with_edge]) > 0.95
    # A quantity that is byte-identical across two samples whose DSR differs by
    # half cannot be one minus that DSR.
