"""Weight is not risk, and a sample covariance of this shape is not the truth.

`correlation_xray` publishes `effective_bets` and a diversification ratio from
`np.corrcoef` over sixty sessions. On the live book that is ten names on
thirty-five common sessions — 55 parameters from 350 observations, where the
Marchenko–Pastur law says the sample eigenvalues are systematically spread wider
than the true ones and three of ten sit essentially at zero. Every number
downstream inherits that, and it inherits it in the flattering direction:
`effective_bets` is dominated by the top eigenvalue, which is the biased-up one.

These tests hold the additions to the properties that make them worth having
rather than a longer payload — shrinkage has to *help*, a risk decomposition has
to add up, a shock has to propagate, and a reverse-stress scenario has to be the
one it claims to be.
"""
import json

import numpy as np
import pytest

from clawock.portfolio import allocation, covariance, stress
from clawock.publish.dashboard import trim_deep_risk


def _true_covariance(n=8, seed=1):
    """Two blocks: a tight one, a loose one, and a weak link between them."""
    rng = np.random.default_rng(seed)
    correlation = np.full((n, n), 0.15)
    correlation[:n // 2, :n // 2] = 0.85
    correlation[n // 2:, n // 2:] = 0.35
    np.fill_diagonal(correlation, 1.0)
    deviations = rng.uniform(0.01, 0.05, size=n)
    return np.outer(deviations, deviations) * correlation


def _draw(true, sessions, seed):
    root = np.linalg.cholesky(true + 1e-12 * np.eye(len(true)))
    return np.random.default_rng(seed).normal(size=(sessions, len(true))) @ root.T


def test_shrinkage_decays_as_the_sample_grows():
    """The intensity is derived, not chosen, so it has to behave like one."""
    true = _true_covariance()
    intensities = [
        np.mean([covariance.ledoit_wolf(_draw(true, sessions, seed))['shrinkage']
                 for seed in range(15)])
        for sessions in (30, 60, 250, 2000)
    ]
    assert all(intensities[index] > intensities[index + 1]
               for index in range(len(intensities) - 1)), intensities
    assert intensities[0] > 0.2
    assert intensities[-1] < 0.05


def test_shrinkage_buys_a_lower_out_of_sample_portfolio_variance():
    """The metric that decides whether this is worth the code.

    Frobenius error on the matrix is not the point; what a covariance is used
    for is sizing. Build the long-only minimum-variance portfolio on each
    estimate from one sample, then measure the variance it actually realises
    under the true covariance. Averaged over draws, the shrunk estimate has to
    win — that is the whole claim.
    """
    true = _true_covariance()
    sample_variance, shrunk_variance = [], []
    for seed in range(25):
        returns = _draw(true, 40, seed)
        estimate = covariance.ledoit_wolf(returns)
        for source, sink in ((estimate['sample_covariance'], sample_variance),
                             (estimate['covariance'], shrunk_variance)):
            weights = np.array(list(
                allocation.minimum_variance(source)['weights'].values()))
            sink.append(float(weights @ true @ weights))
    assert np.mean(shrunk_variance) < np.mean(sample_variance)


def test_the_spectrum_separates_a_factor_from_noise():
    rng = np.random.default_rng(4)
    noise = rng.normal(size=(60, 8))
    assert covariance.spectrum_report(noise)['eigenvalues_above_noise'] == 0
    factor = rng.normal(size=(60, 1)) @ rng.uniform(0.5, 1.5, size=(1, 8))
    assert covariance.spectrum_report(
        factor + 0.3 * rng.normal(size=(60, 8)))['eigenvalues_above_noise'] >= 1


def test_risk_contributions_sum_to_the_portfolio_volatility():
    """The property that makes it a decomposition rather than a heuristic."""
    true = _true_covariance()
    weights = np.array([0.40, 0.12, 0.12, 0.09, 0.09, 0.08, 0.06, 0.04])
    report = allocation.risk_contributions(weights, true)
    assert report['sums_to_volatility'] == pytest.approx(
        report['portfolio_volatility'], rel=1e-9)
    assert sum(row['risk_share'] for row in report['rows']) == pytest.approx(1.0, abs=1e-6)


def test_a_correlated_overweight_carries_more_risk_than_its_weight():
    """The sentence the x-ray could not say.

    On the live book `00100` is 40% of the money and 70% of the risk. Here: one
    name inside the tight block, held at the same weight as one outside it, must
    come back with a larger risk share.
    """
    true = _true_covariance()
    weights = np.full(8, 1 / 8)
    rows = {row['name']: row for row in
            allocation.risk_contributions(weights, true, range(8))['rows']}
    inside = statistics_mean([rows[str(index)]['risk_share'] for index in range(4)])
    outside = statistics_mean([rows[str(index)]['risk_share'] for index in range(4, 8)])
    assert inside > outside


def statistics_mean(values):
    return sum(values) / len(values)


def test_hrp_produces_a_long_only_allocation_without_inverting_anything():
    true = _true_covariance()
    names = [f'N{index}' for index in range(8)]
    result = allocation.hierarchical_risk_parity(true, names)
    weights = np.array([result['weights'][name] for name in names])
    assert result['status'] == 'measured'
    assert (weights >= 0).all()
    # 1e-5, not 1e-9: the published weights are rounded to six places, so eight
    # of them can miss the simplex by four parts in a million. Asserting tighter
    # than the payload's own precision would be testing the rounding.
    assert weights.sum() == pytest.approx(1.0, abs=1e-5)
    # The tight block should not receive four independent allocations.
    assert weights[:4].sum() < weights[4:].sum()


def test_hrp_survives_a_singular_covariance_that_would_break_an_inverse():
    """Two identical names make the matrix singular. HRP must still answer.

    This is not hypothetical: `SPCH`/`SPCX` have a sample correlation of exactly
    1.000 in the live x-ray, and the closed-form minimum-variance weights on that
    matrix are whatever `pinv` decides to return.
    """
    base = _true_covariance(6)
    duplicated = np.zeros((7, 7))
    duplicated[:6, :6] = base
    duplicated[6, :6] = base[0]
    duplicated[:6, 6] = base[:, 0]
    duplicated[6, 6] = base[0, 0]
    result = allocation.hierarchical_risk_parity(duplicated)
    assert result['status'] == 'measured'
    assert sum(result['weights'].values()) == pytest.approx(1.0, abs=1e-5)


def test_long_only_minimum_variance_stays_on_the_simplex():
    true = _true_covariance()
    weights = np.array(list(allocation.minimum_variance(true)['weights'].values()))
    assert (weights >= -1e-9).all()
    assert weights.sum() == pytest.approx(1.0, abs=1e-6)
    # And it must actually be lower variance than equal weight, or it is not
    # solving the problem it names.
    equal = np.full(len(true), 1 / len(true))
    assert weights @ true @ weights < equal @ true @ equal


def test_a_shock_propagates_instead_of_leaving_the_others_still():
    """The mistake this exists to prevent.

    Shocking the top position and holding the rest still understates the loss in
    exactly the books where it matters, because a concentrated book is
    concentrated *through* correlation.
    """
    true = _true_covariance()
    weights = np.full(8, 1 / 8)
    names = [f'N{index}' for index in range(8)]
    result = stress.correlated_shock(true, weights, {'N0': -0.20}, names)
    assert result['portfolio_return'] < result['portfolio_return_if_others_held_still']
    assert result['contagion_share'] > 0
    # Names inside N0's block move more than names outside it.
    implied = result['implied']
    assert implied['N1'] < implied['N7']


def test_reverse_stress_hits_the_loss_it_was_asked_for():
    true = _true_covariance()
    weights = np.array([0.40, 0.12, 0.12, 0.09, 0.09, 0.08, 0.06, 0.04])
    names = [f'N{index}' for index in range(8)]
    result = stress.reverse_stress(true, weights, 0.15, names)
    moves = np.array([result['moves'][name] for name in names])
    assert float(weights / weights.sum() @ moves) == pytest.approx(-0.15, abs=1e-5)


def test_reverse_stress_returns_the_least_improbable_shape_not_a_uniform_one():
    """Among all vectors reaching the loss, this is the closest one to the mean.

    A uniform fall reaching the same loss must be *further* away in Mahalanobis
    distance, or the scenario being published is not the one it claims to be.
    """
    true = _true_covariance()
    weights = np.array([0.40, 0.12, 0.12, 0.09, 0.09, 0.08, 0.06, 0.04])
    normalised = weights / weights.sum()
    names = [f'N{index}' for index in range(8)]
    result = stress.reverse_stress(true, weights, 0.15, names)
    chosen = np.array([result['moves'][name] for name in names])
    uniform = np.full(8, -0.15 / normalised.sum())
    inverse = np.linalg.pinv(true)
    assert chosen @ inverse @ chosen < uniform @ inverse @ uniform
    # And the scenario is not "everything falls equally".
    assert chosen.max() - chosen.min() > 0.02


def test_historical_windows_report_the_dates_they_found():
    true = _true_covariance()
    returns = _draw(true, 80, 3)
    dates = [f'2026-01-{index + 1:04d}' for index in range(80)]
    report = stress.historical_worst_windows(
        returns, np.full(8, 1 / 8), dates=dates)
    worst = report['worst_5_session'][0]
    assert worst['return'] < 0
    assert worst['from'] in dates and worst['to'] in dates
    assert report['worst_5_session'][0]['return'] <= report['worst_5_session'][1]['return']


def test_the_deep_block_degrades_instead_of_taking_the_x_ray_down():
    """It is an addition to a payload the risk card already depends on."""
    from clawock.portfolio import risk
    out = risk._deep_risk_view(np.zeros((2, 2)), [0.5, 0.5], ['A', 'B'], ['d', 'e'])
    assert out['deep_risk']['status'] == 'unavailable'
    assert out['deep_risk']['reason']


def test_the_embedded_copy_keeps_the_sentences_and_drops_the_working():
    from clawock.portfolio import risk
    returns = _draw(_true_covariance(), 40, 9)
    deep = risk._deep_risk_view(returns, np.full(8, 1 / 8),
                                [f'N{index}' for index in range(8)],
                                [f'd{index}' for index in range(40)])
    payload = {'correlation': {'effective_bets': 2.0, **deep}}
    trimmed = trim_deep_risk(payload)
    assert len(json.dumps(trimmed)) < len(json.dumps(payload)) / 2
    summary = trimmed['correlation']['deep_risk']
    assert summary['conditioning'] and summary['shrinkage']
    assert summary['largest_risk_overweight']['name']
    assert summary['top_position_shock']['portfolio_return'] is not None
    assert summary['detail_source'] == 'assets/data/risk.json'
    # The detail is gone from the embedded copy, not from the file.
    assert 'risk_contributions' not in summary
    assert 'reference_allocation' not in summary
