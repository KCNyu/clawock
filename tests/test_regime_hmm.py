"""What the HMM regime module has to be true about.

The interesting assertions here are not "does EM converge" — they are the two
things that make a regime series either usable or a fiction:

* the **filtered** posterior at session `t` must be unchanged by anything that
  happens after `t`, and the **smoothed** one must not be (otherwise the module
  is publishing the same series under two names);
* the **walk-forward** series must be unchanged by a rewrite of its own future,
  which is the only way to prove the refit loop is not leaking.

Both are written as differential tests against a mutated tail rather than as
inspections of the code, because a look-ahead is a property of the output.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from clawock.evaluation import regime_hmm as rh

#: Two restarts rather than the module's five. The restart count is what
#: `fit_best` uses to avoid a local optimum, and none of these tests is about
#: that; paying for five in every fit turned this file into 86 seconds of CI.
FAST_SEEDS = rh.RESTART_SEEDS[:2]


def two_regime_series(n=600, seed=7):
    """A market with two states that a two-state model should be able to find."""
    rng = np.random.default_rng(seed)
    state, returns = 0, []
    for _ in range(n):
        # Persistent: 2% chance of switching on any session, so the states have
        # a duration rather than being a coin flip per row.
        if rng.random() < 0.02:
            state = 1 - state
        returns.append(rng.normal(0.0012, 0.008) if state == 0
                       else rng.normal(-0.0015, 0.024))
    closes = [100.0]
    for value in returns:
        closes.append(closes[-1] * (1 + value))
    return closes


def observations_of(closes):
    return rh.observation_matrix(closes)[0]


def test_states_come_back_ordered_by_mean_return():
    """`fit_best` owns state identity; every consumer relies on the order."""
    observations = observations_of(two_regime_series())
    model = rh.fit_best(observations, 3, seeds=FAST_SEEDS)
    means = list(model.means[:, 0])
    assert means == sorted(means)


def test_the_same_data_gives_the_same_model():
    """EM is not convex; a regime model that renumbers between runs is unusable."""
    observations = observations_of(two_regime_series())
    first = rh.fit_best(observations, 2, seeds=FAST_SEEDS)
    second = rh.fit_best(observations, 2, seeds=FAST_SEEDS)
    assert np.allclose(first.means, second.means)
    assert np.allclose(first.transitions, second.transitions)


def test_two_state_fit_separates_the_two_regimes():
    observations = observations_of(two_regime_series())
    model = rh.fit_best(observations, 2, seeds=FAST_SEEDS)
    described = rh.describe_states(model, observations, model.smoothed(observations))
    assert len(described) == 2
    low, high = described  # sorted by mean daily return
    assert low['mean_daily_return'] < high['mean_daily_return']
    # The generating process gave the losing state three times the volatility.
    assert low['mean_trailing_volatility'] > high['mean_trailing_volatility']
    assert abs(sum(row['share_of_sessions'] for row in described) - 1.0) < 1e-6


def test_posteriors_are_distributions():
    observations = observations_of(two_regime_series())
    model = rh.fit_best(observations, 3, seeds=FAST_SEEDS)
    for posteriors in (model.filtered(observations), model.smoothed(observations)):
        assert posteriors.shape == (len(observations), 3)
        assert np.allclose(posteriors.sum(axis=1), 1.0)
        assert posteriors.min() >= 0.0


def test_transition_rows_sum_to_one_and_durations_are_at_least_one():
    observations = observations_of(two_regime_series())
    model = rh.fit_best(observations, 3, seeds=FAST_SEEDS)
    assert np.allclose(model.transitions.sum(axis=1), 1.0)
    assert all(value >= 1.0 for value in model.expected_durations())
    stationary = model.stationary_distribution()
    assert abs(sum(stationary) - 1.0) < 1e-4
    assert all(value >= -1e-9 for value in stationary)


def test_expected_duration_is_the_geometric_mean_of_the_diagonal():
    model = rh.GaussianHMM(2, 2)
    model.transitions = np.array([[0.95, 0.05], [0.80, 0.20]])
    assert model.expected_durations() == [20.0, 1.25]


def test_filtered_posterior_does_not_contain_the_future():
    """The load-bearing one: truncate the series, and the label must not move."""
    observations = observations_of(two_regime_series())
    model = rh.fit_best(observations, 2, seeds=FAST_SEEDS)
    cut = 400
    full = model.filtered(observations)
    truncated = model.filtered(observations[:cut])
    assert np.allclose(full[:cut], truncated, atol=1e-12)


def test_smoothed_posterior_does_contain_the_future():
    """The other half of the same claim: the two series must not be the same one."""
    observations = observations_of(two_regime_series())
    model = rh.fit_best(observations, 2, seeds=FAST_SEEDS)
    cut = 400
    full = model.smoothed(observations)
    truncated = model.smoothed(observations[:cut])
    assert not np.allclose(full[:cut], truncated, atol=1e-6)


def test_walk_forward_leaves_the_warmup_unlabelled():
    observations = observations_of(two_regime_series())
    walk = rh.walk_forward_states(observations, n_states=2, warmup=250, step=40,
                                seeds=FAST_SEEDS)
    assert walk is not None
    assert not walk['valid'][:250].any()
    assert walk['valid'][250:].all()
    assert np.isnan(walk['posteriors'][:250]).all()
    assert walk['n_refits'] == len(range(250, len(observations), 40))
    labelled = walk['posteriors'][walk['valid']]
    assert np.allclose(labelled.sum(axis=1), 1.0)


def test_walk_forward_labels_do_not_move_when_the_future_is_rewritten():
    """Refit loop leak detector. Nothing after session `t` may reach label `t`."""
    closes = two_regime_series()
    observations = observations_of(closes)
    baseline = rh.walk_forward_states(observations, n_states=2, warmup=250, step=40,
                                seeds=FAST_SEEDS)

    mutated = observations.copy()
    rng = np.random.default_rng(99)
    mutated[350:] = rng.normal(-0.05, 0.2, size=mutated[350:].shape)
    rewritten = rh.walk_forward_states(mutated, n_states=2, warmup=250, step=40,
                                  seeds=FAST_SEEDS)

    # Labels are produced in blocks of `step` from a model fitted on the prefix,
    # so everything strictly before the block containing 350 must be identical.
    unaffected = 250 + ((350 - 250) // 40) * 40
    assert unaffected < 350
    assert np.allclose(baseline['posteriors'][250:unaffected],
                       rewritten['posteriors'][250:unaffected], atol=1e-12)


def test_walk_forward_returns_none_when_the_sample_cannot_carry_it():
    observations = observations_of(two_regime_series(n=200))
    assert rh.walk_forward_states(
        observations, n_states=2, warmup=250, step=20, seeds=FAST_SEEDS) is None


def test_select_states_publishes_the_whole_curve_not_just_the_winner():
    observations = observations_of(two_regime_series(n=400))
    selection = rh.select_states(observations, candidates=(2, 3), seeds=FAST_SEEDS)
    assert set(selection['bic']) == {2, 3}
    assert selection['n_states'] in (2, 3)
    assert selection['bic'][selection['n_states']] == min(selection['bic'].values())
    assert selection['bic_margin'] >= 0
    assert 'search result' in selection['reading']


def test_bic_penalises_the_larger_model_on_identical_likelihood():
    observations = observations_of(two_regime_series(n=400))
    small, large = rh.GaussianHMM(2, 2), rh.GaussianHMM(4, 2)
    small.log_likelihood = large.log_likelihood = -1000.0
    assert large.bic(observations) > small.bic(observations)
    assert large.n_parameters() > small.n_parameters()


def test_exposure_is_linear_in_the_risk_off_probability():
    posteriors = np.array([[0.0, 1.0], [1.0, 0.0], [0.5, 0.5], [np.nan, np.nan]])
    valid = np.array([True, True, True, False])
    exposure = rh.exposure_from_posteriors(posteriors, valid, base=2.0, floor=0.5)
    assert exposure[0] == pytest.approx(2.0)   # no probability in the worst state
    assert exposure[1] == pytest.approx(0.5)   # all of it
    assert exposure[2] == pytest.approx(1.25)  # a marginal regime reads as marginal
    assert exposure[3] is None                 # unlabelled stays unlabelled


def test_exposure_floor_reaches_the_dial_range_when_asked():
    posteriors = np.array([[1.0, 0.0]])
    exposure = rh.exposure_from_posteriors(posteriors, np.array([True]), floor=0.0)
    assert exposure[0] == pytest.approx(0.0)


def test_observation_matrix_row_describes_the_return_its_index_points_at():
    closes = two_regime_series(n=120)
    observations, index = rh.observation_matrix(closes, volatility_window=20)
    assert len(observations) == len(index)
    for offset in (0, 5, len(index) - 1):
        position = index[offset]
        expected = closes[position] / closes[position - 1] - 1
        assert observations[offset][0] == pytest.approx(expected)
        assert observations[offset][1] > 0


def test_evaluate_refuses_a_sample_it_cannot_fit():
    closes = two_regime_series(n=120)
    result = rh.evaluate_against_dial(closes, [None] * len(closes))
    assert result['status'] == 'insufficient_sample'


def test_evaluate_scores_both_arms_on_the_same_rows():
    """Regression: the dial arm once unpacked a triple and scored an empty path,
    printing a comparison arm with exactly 0.0 return and 0.0 drawdown."""
    closes = two_regime_series(n=700)
    dates = [f'2024-{1 + i % 12:02d}-01' for i in range(len(closes))]
    result = rh.evaluate_against_dial(closes, dates, n_states=2, warmup=250,
                                      step=60, permutations=40, seeds=FAST_SEEDS)
    assert result['status'] == 'measured'
    dial = result['production_dial_exposure']
    hmm = result['hmm_exposure']
    assert dial.get('status') != 'unaligned'
    assert dial['n_sessions'] == hmm['n_sessions'] == result['n_scored_sessions']
    assert dial['dial_total_return'] != 0.0
    assert dial['dial_max_drawdown'] != 0.0
    # Both arms are scored against the same buy-and-hold sleeve.
    assert dial['hold_total_return'] == hmm['hold_total_return']
    for permutation in (result['hmm_permutation'],
                        result['production_dial_permutation']):
        assert 0.0 < permutation['p_value_drawdown'] <= 1.0
    assert result['exposure_floor'] == 0.5
    assert len(result['current_posterior']) == 2
    assert math.isclose(sum(result['current_posterior']), 1.0, abs_tol=1e-3)


def test_evaluate_reports_the_walk_forward_discipline_it_used():
    closes = two_regime_series(n=700)
    result = rh.evaluate_against_dial(closes, [None] * len(closes), n_states=2,
                                      warmup=250, step=60, permutations=20,
                                      seeds=FAST_SEEDS)
    assert result['walk_forward']['warmup'] == 250
    assert result['walk_forward']['step'] == 60
    assert 'filtered' in result['discipline']
    assert result['n_scored_sessions'] < result['n_observations']
