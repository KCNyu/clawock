"""The leverage dial must report how much of its fit is the search (#1114).

`validate-regime-dial` already walked the dial forward and permuted its timing.
Neither answers the question a 16-candidate grid raises: how often is the pair
that looks best in-sample below the median out of sample? Four walk-forward
folds cannot say; every symmetric half-split can.

These tests hold the estimator to the two behaviours that make it worth
publishing — it separates a real edge from a search over noise, and it refuses
to produce a number from a sample that cannot support one.
"""
import random

import pytest

from clawock.evaluation import cscv
from clawock.evaluation import regime_validation as rv


def _sum(values):
    return sum(values)


def _noise_matrix(n_obs=600, n_configs=12, seed=7):
    rnd = random.Random(seed)
    return [[rnd.gauss(0, 0.01) for _ in range(n_configs)] for _ in range(n_obs)]


def _matrix_with_one_real_edge(n_obs=600, n_configs=12, winner=3, seed=11):
    rnd = random.Random(seed)
    return [[rnd.gauss(0, 0.01) + (0.004 if c == winner else 0.0)
             for c in range(n_configs)] for _ in range(n_obs)]


def test_a_search_over_pure_noise_reports_a_coin_flip():
    """The number that makes PBO worth having.

    Twelve configurations of nothing but noise: whichever wins in-sample has no
    reason to win out of sample, so the in-sample winner lands below the
    out-of-sample median about half the time.
    """
    result = cscv.probability_of_backtest_overfitting(
        _noise_matrix(), _sum, n_groups=8, embargo=6)

    assert result['status'] == 'measured'
    assert result['n_splits'] == 70, "every symmetric half-split must be scored"
    assert 0.35 <= result['pbo'] <= 0.65, (
        f"a pure search should look like a coin flip, got {result['pbo']}")


def test_a_configuration_with_a_real_edge_is_not_flagged_as_overfit():
    result = cscv.probability_of_backtest_overfitting(
        _matrix_with_one_real_edge(), _sum, n_groups=8, embargo=6)

    assert result['pbo'] <= 0.05, (
        "an edge present in every window must not read as selection")
    assert result['selection_counts'] == {'3': 70}, (
        "the search should land on the same configuration in every split")
    assert result['mean_out_of_sample_degradation'] is not None


def test_the_estimator_refuses_a_sample_that_cannot_support_it():
    """A PBO from six splits is a decoration with a citation attached."""
    too_few_groups = cscv.probability_of_backtest_overfitting(
        _noise_matrix(), _sum, n_groups=4)
    assert too_few_groups['status'] == 'insufficient_sample'
    assert too_few_groups['pbo'] is None
    assert '4 groups' in too_few_groups['reason']

    single_config = cscv.probability_of_backtest_overfitting(
        _noise_matrix(n_configs=1), _sum, n_groups=8)
    assert single_config['status'] == 'insufficient_sample'
    assert single_config['pbo'] is None, (
        "one pre-registered configuration has nothing to overfit; reporting "
        "0.0 would read as evidence")


def test_the_embargo_removes_training_bars_on_both_sides_of_every_test_block():
    train = list(range(0, 10)) + list(range(20, 30))
    test = list(range(10, 20))

    kept = cscv.purge(train, test, embargo=3)

    assert kept == [0, 1, 2, 3, 4, 5, 6, 23, 24, 25, 26, 27, 28, 29], (
        "a trailing feature reaches backwards and a forward label reaches "
        "forwards: embargoing one side only would look rigorous and leak")
    assert cscv.purge(train, test, embargo=0) == train


def test_the_embargo_spans_each_block_of_a_split_not_only_the_first():
    train = list(range(0, 40))
    test = [5, 6, 7, 25, 26, 27]

    kept = cscv.purge(train, test, embargo=2)

    for blocked in (3, 4, 8, 9, 23, 24, 28, 29):
        assert blocked not in kept, f"{blocked} sits inside an embargo"
    assert 0 in kept and 15 in kept and 39 in kept


def test_groups_are_contiguous_and_partition_every_observation():
    groups = cscv.contiguous_groups(101, 8)

    assert sum(len(g) for g in groups) == 101
    assert sorted(index for g in groups for index in g) == list(range(101))
    for group in groups:
        assert group == list(range(group[0], group[-1] + 1))


def test_every_split_is_a_disjoint_cover_of_the_groups():
    seen = set()
    for train, test in cscv.splits(8):
        assert not set(train) & set(test)
        assert sorted(train + test) == list(range(8))
        assert len(test) == 4
        seen.add(tuple(test))
    assert len(seen) == 70


def _random_walk(n=1400, seed=3):
    rnd = random.Random(seed)
    closes = [100.0]
    for _ in range(n):
        closes.append(closes[-1] * (1 + rnd.gauss(0.0004, 0.015)))
    return closes


def test_the_dial_reports_pbo_over_the_same_grid_walk_forward_searches():
    result = rv.overfitting_probability(_random_walk())

    assert result['status'] == 'measured'
    assert result['n_configs'] == len(rv.MA_GRID) * len(rv.VOL_CAP_GRID), (
        "PBO must cover the grid the selection actually searches")
    assert result['n_splits'] == 70
    assert result['embargo'] >= 1 and result['purged_per_split'] > 0, (
        "an unpurged CSCV over trailing-window features is the leak this closes")
    assert 0.0 <= result['pbo'] <= 1.0
    assert 'de-risking' in result['caveat'], (
        "the objective rewards being out of the market; the report has to say so")


def test_a_sample_shorter_than_the_warmup_reports_no_number():
    result = rv.overfitting_probability(_random_walk(n=150))

    assert result['status'] == 'insufficient_sample'
    assert result['pbo'] is None


def test_the_dial_objective_is_the_one_the_search_selects_on():
    """CSCV has to score what `best_thresholds` ranks on, or it measures a proxy.

    Same quantity as `_score`'s first element: dial drawdown minus always-on
    drawdown over the same bars.
    """
    closes = _random_walk(n=600)
    returns, exposure, _ = rv.exposure_path(closes, ma_window=100, vol_cap=0.5)
    pairs = [(exposure[i] * returns[i], rv.BASE_LEVERAGE * returns[i])
             for i in range(len(returns))]

    expected = rv.summarize(returns, exposure)['drawdown_improvement']

    assert rv._drawdown_improvement(pairs) == pytest.approx(expected, abs=1e-6)
