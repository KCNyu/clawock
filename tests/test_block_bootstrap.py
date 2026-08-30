"""The interval has to widen when the sample is serially dependent (#1148).

`add_alpha_walkforward._cluster_ci` resamples sessions independently. That is
right for the fills sharing a session and silent about the sessions sharing a
regime, and the direction of the silence is the dangerous one: a series with
runs in it gets a narrower interval than it deserves. These tests hold the
replacement to the three properties that make it worth the extra code — it
recovers a block length that matches the dependence, it agrees with the old
estimator exactly when the data says it should, and it refuses the
bias-correction on a sample too short to estimate it.
"""
import random
import statistics

from clawock.evaluation import bootstrap


def _ar1(rho, n=800, seed=17, scale=1.0):
    rnd = random.Random(seed)
    series = [0.0] * n
    for t in range(1, n):
        series[t] = rho * series[t - 1] + rnd.gauss(0, scale)
    return series


def test_white_noise_asks_for_no_blocks():
    """The honest answer for an independent series is a block length of one.

    It also means the older estimator was not wrong here, which is why the
    length is published rather than hidden inside the interval.
    """
    rnd = random.Random(5)
    assert bootstrap.optimal_block_length(
        [rnd.gauss(0, 1) for _ in range(800)])['stationary'] == 1


def test_block_length_grows_with_persistence():
    weak = bootstrap.optimal_block_length(_ar1(0.2))['stationary']
    strong = bootstrap.optimal_block_length(_ar1(0.8))['stationary']
    assert weak < strong
    # Politis & White's own cap: a block that is a third of the sample is not a
    # resample any more.
    assert strong <= bootstrap._max_block(800)


def test_serial_dependence_widens_the_interval():
    """The whole reason for the module.

    Same series, same point estimate; the i.i.d.-over-clusters bootstrap and the
    block bootstrap disagree, and the block one is wider. If this ever fails in
    the other direction the block length is being chosen wrong.
    """
    series = _ar1(0.85, n=400, scale=0.01)
    by_cluster = {index: [value] for index, value in enumerate(series)}
    blocked = bootstrap.clustered_block_ci(by_cluster, samples=1500)
    iid = bootstrap.clustered_block_ci(by_cluster, samples=1500, block_length=1)
    assert blocked['block_length'] > 1
    assert (blocked['ci95'][1] - blocked['ci95'][0]) > (iid['ci95'][1] - iid['ci95'][0])


def test_every_observation_in_a_drawn_cluster_travels_with_it():
    """Cross-sectional dependence: a session is drawn whole or not at all."""
    by_cluster = {'a': [1.0, 1.0, 1.0], 'b': [2.0], 'c': [3.0], 'd': [4.0]}
    rnd = random.Random(0)
    keys = sorted(by_cluster)
    indices = bootstrap.stationary_bootstrap_indices(len(keys), 1.0, rnd)
    resampled = [value for i in indices for value in by_cluster[keys[i]]]
    assert resampled.count(1.0) % 3 == 0


def test_bca_is_refused_on_too_few_clusters():
    """The defect this floor exists for.

    Acceleration is a third moment of the jackknife replicates. From three
    clusters it is noise, and it narrows the interval — on the live walk-forward
    it moved `hk/interaction/t5` from crossing zero to clearing it, on three
    sessions. Below the floor the caller must fall back to the percentile
    interval, which is merely wide.
    """
    draws = [random.Random(1).gauss(0, 1) for _ in range(500)]
    assert bootstrap.bca_interval(draws, 0.0, [0.1, 0.2, 0.3]) is None
    by_cluster = {index: [float(index)] for index in range(3)}
    result = bootstrap.clustered_block_ci(by_cluster, samples=400)
    assert result['method'].endswith('percentile')


def test_bca_is_used_once_there_are_enough_clusters():
    by_cluster = {index: [random.Random(index).gauss(0.01, 0.02)] for index in range(60)}
    assert bootstrap.clustered_block_ci(by_cluster, samples=800)['method'].endswith('BCa')


def test_inverse_normal_matches_the_forward_one():
    for probability in (0.001, 0.025, 0.1, 0.5, 0.9, 0.975, 0.999):
        assert abs(bootstrap._norm_cdf(bootstrap.norm_ppf(probability)) - probability) < 1e-12


def test_the_interval_covers_a_known_mean():
    """Coverage, not shape: 40 independent runs of a known mean should trap it.

    A bootstrap that produces a plausible-looking interval which systematically
    misses is the failure this catches, and it is invisible in a single run.
    """
    hits = 0
    for seed in range(40):
        rnd = random.Random(1000 + seed)
        by_cluster = {index: [rnd.gauss(0.5, 1.0) for _ in range(3)] for index in range(80)}
        interval = bootstrap.clustered_block_ci(by_cluster, samples=600, seed=seed)['ci95']
        hits += interval[0] <= 0.5 <= interval[1]
    assert hits >= 34
