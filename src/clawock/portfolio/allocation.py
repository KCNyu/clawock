"""Where the risk in this book actually sits, and what a diversified one looks like.

The question this is for
------------------------
`correlation_xray` reports that the book has 3.78 effective names and **1.98
effective bets**: eight positions behaving as two. It says that clearly, and
then stops, because knowing the book is concentrated does not say *which*
position is carrying the concentration, or what the alternative would have been.

Two things close that gap and neither is an optimiser telling anyone what to
hold:

* **Risk contribution.** Weight is not risk. A 40% position in an uncorrelated
  name and a 40% position that co-moves with the other 60% are the same number
  on the holdings table and different books. `risk_contributions` splits total
  portfolio volatility into per-name shares that sum to it exactly (Euler
  decomposition), so "00100 is 40% of the money" can be read next to "and N% of
  the risk".
* **A reference allocation.** `hierarchical_risk_parity` (López de Prado 2016)
  builds the weights a purely diversification-driven allocator would hold on the
  same covariance — no expected returns, no matrix inversion, so it is stable at
  the sample sizes this book has. It is a *ruler*, not a recommendation: the
  distance between the live weights and HRP's is a measurement of how much of
  the concentration is a choice rather than an accident.

Why HRP rather than mean-variance
---------------------------------
Mean-variance needs `Σ⁻¹`, and at eight names on sixty sessions the smallest
eigenvalue of the sample correlation is inside the Marchenko–Pastur noise band
(see `portfolio.covariance.spectrum_report`) — inverting it puts the largest
weights on the directions that are purest estimation error. HRP never inverts:
it clusters, orders the matrix so similar names are adjacent, and splits capital
down the tree by inverse variance. `minimum_variance` is still here, because the
comparison between the two is informative, but it takes the shrunk covariance
and says so.
"""
from __future__ import annotations

import numpy as np
from scipy.cluster.hierarchy import linkage, to_tree
from scipy.spatial.distance import squareform

from clawock.portfolio.covariance import correlation_from


def _as_weights(weights) -> np.ndarray:
    vector = np.asarray(weights, dtype=float)
    total = vector.sum()
    if total <= 0:
        raise ValueError('weights must sum to a positive number')
    return vector / total


def portfolio_volatility(weights, covariance) -> float:
    vector = _as_weights(weights)
    return float(np.sqrt(vector @ np.asarray(covariance, dtype=float) @ vector))


def risk_contributions(weights, covariance, names=None) -> dict:
    """Euler decomposition of portfolio volatility into per-name shares.

    `RC_i = w_i * (Σw)_i / sqrt(wᵀΣw)`, and the shares sum to the portfolio
    volatility exactly — which is the property that makes this a decomposition
    rather than an attribution heuristic, and which the tests check.

    The interesting column is `risk_share - weight_share`: positive means the
    name carries more of the book's risk than its size, which is what a
    correlated overweight looks like from the inside.
    """
    vector = _as_weights(weights)
    matrix = np.asarray(covariance, dtype=float)
    total_volatility = float(np.sqrt(vector @ matrix @ vector))
    if total_volatility <= 0:
        return {'status': 'degenerate', 'reason': 'portfolio variance is zero'}
    marginal = matrix @ vector / total_volatility
    contributions = vector * marginal
    names = list(names or range(len(vector)))
    rows = [
        {
            'name': str(name),
            'weight_share': round(float(vector[index]), 6),
            'risk_contribution': round(float(contributions[index]), 8),
            'risk_share': round(float(contributions[index] / total_volatility), 6),
            'risk_share_minus_weight_share': round(
                float(contributions[index] / total_volatility - vector[index]), 6),
            'marginal_risk': round(float(marginal[index]), 8),
        }
        for index, name in enumerate(names)
    ]
    rows.sort(key=lambda row: -row['risk_share'])
    return {
        'status': 'measured',
        'portfolio_volatility': round(total_volatility, 8),
        'rows': rows,
        'sums_to_volatility': round(float(contributions.sum()), 8),
        'method': 'Euler decomposition; shares sum to portfolio volatility exactly',
    }


def effective_bets(weights, covariance) -> dict:
    """Two concentration numbers that disagree on purpose.

    `1 / sum(w²)` counts *names* and knows nothing about how they move.
    `1 / (wᵀρw)` counts *bets* and collapses toward one as the book co-moves.
    The gap between them is the part of the diversification that is nominal.
    """
    vector = _as_weights(weights)
    correlation = correlation_from(np.asarray(covariance, dtype=float))
    quadratic = float(vector @ correlation @ vector)
    deviations = np.sqrt(np.diag(np.asarray(covariance, dtype=float)))
    weighted_sigma = float(vector @ deviations)
    volatility = portfolio_volatility(vector, covariance)
    return {
        'effective_names': round(1.0 / float(np.sum(vector ** 2)), 4),
        'effective_bets': round(1.0 / quadratic, 4) if quadratic > 0 else None,
        'diversification_ratio': round(weighted_sigma / volatility, 4)
        if volatility > 0 else None,
    }


def _quasi_diagonal_order(link) -> list[int]:
    """Leaf order of the dendrogram: similar names end up adjacent."""
    return list(to_tree(link).pre_order(lambda node: node.id))


def _inverse_variance_weights(covariance: np.ndarray, indices) -> np.ndarray:
    variances = np.diag(covariance)[indices]
    with np.errstate(divide='ignore'):
        inverse = np.where(variances > 0, 1.0 / variances, 0.0)
    total = inverse.sum()
    return inverse / total if total > 0 else np.full(len(indices), 1.0 / len(indices))


def _cluster_variance(covariance: np.ndarray, indices) -> float:
    block = covariance[np.ix_(indices, indices)]
    weights = _inverse_variance_weights(covariance, indices)
    return float(weights @ block @ weights)


def hierarchical_risk_parity(covariance, names=None, *, method='single') -> dict:
    """López de Prado (2016). Cluster, reorder, then bisect by inverse variance.

    The distance is `sqrt((1 - rho) / 2)`, the standard correlation metric, so
    two names that move together are close. Recursive bisection splits capital
    between the two halves of each split in inverse proportion to their cluster
    variance, which means the concentrated half gets less without anyone
    inverting anything.
    """
    matrix = np.asarray(covariance, dtype=float)
    n = matrix.shape[0]
    names = list(names or range(n))
    if n < 2:
        return {'status': 'degenerate', 'reason': 'need at least two names'}
    correlation = np.clip(correlation_from(matrix), -1.0, 1.0)
    distance = np.sqrt(np.maximum(0.0, (1.0 - correlation) / 2.0))
    np.fill_diagonal(distance, 0.0)
    link = linkage(squareform(distance, checks=False), method=method)
    order = _quasi_diagonal_order(link)

    weights = np.ones(n)
    clusters = [order]
    while clusters:
        clusters = [
            half
            for cluster in clusters
            for half in (cluster[:len(cluster) // 2], cluster[len(cluster) // 2:])
            if len(cluster) > 1
        ]
        for index in range(0, len(clusters), 2):
            left, right = clusters[index], clusters[index + 1]
            left_variance = _cluster_variance(matrix, left)
            right_variance = _cluster_variance(matrix, right)
            total = left_variance + right_variance
            factor = 1 - left_variance / total if total > 0 else 0.5
            weights[left] *= factor
            weights[right] *= 1 - factor
        clusters = [cluster for cluster in clusters if len(cluster) > 1]

    weights = weights / weights.sum()
    return {
        'status': 'measured',
        'weights': {str(names[index]): round(float(weights[index]), 6)
                    for index in range(n)},
        'leaf_order': [str(names[index]) for index in order],
        'linkage_method': method,
        'method': ('Lopez de Prado (2016) hierarchical risk parity; no matrix '
                   'inversion and no expected returns'),
        'reading': ('a reference allocation for comparison, not a '
                    'recommendation: the distance from the live weights is a '
                    'measurement of how much concentration is deliberate'),
    }


def minimum_variance(covariance, names=None, *, long_only=True) -> dict:
    """The long-only minimum-variance weights, by projected gradient descent.

    Deliberately *not* the closed form `Σ⁻¹1 / 1ᵀΣ⁻¹1`. That inverts a matrix
    whose smallest eigenvalues are, at this sample size, inside the
    Marchenko–Pastur noise band, and it answers with large offsetting long and
    short positions in whichever pair of names happened to look most correlated.
    A simplex-projected descent stays inside the set of allocations the book
    could actually hold, and it converges in a few hundred steps on a matrix this
    size.

    Feed it a *shrunk* covariance. `used_shrunk_covariance` is recorded by the
    caller, not inferred here, because this function cannot tell.
    """
    matrix = np.asarray(covariance, dtype=float)
    n = matrix.shape[0]
    names = list(names or range(n))
    weights = np.full(n, 1.0 / n)
    if not long_only:
        ones = np.ones(n)
        inverse = np.linalg.pinv(matrix)
        weights = inverse @ ones / float(ones @ inverse @ ones)
        return {'status': 'measured', 'long_only': False,
                'weights': {str(names[i]): round(float(weights[i]), 6)
                            for i in range(n)},
                'method': 'closed form; may be leveraged and short'}
    step = 1.0 / (np.linalg.norm(matrix, 2) * 2 + 1e-12)
    for _ in range(2000):
        gradient = 2 * matrix @ weights
        weights = _project_to_simplex(weights - step * gradient)
    return {
        'status': 'measured',
        'long_only': True,
        'weights': {str(names[index]): round(float(weights[index]), 6)
                    for index in range(n)},
        'volatility': round(portfolio_volatility(weights, matrix), 8),
        'method': 'projected gradient descent on the long-only simplex',
    }


def _project_to_simplex(vector: np.ndarray) -> np.ndarray:
    """Euclidean projection onto {w : w >= 0, sum(w) = 1} (Duchi et al. 2008)."""
    n = len(vector)
    ordered = np.sort(vector)[::-1]
    cumulative = np.cumsum(ordered)
    indices = np.arange(1, n + 1)
    condition = ordered - (cumulative - 1) / indices > 0
    rho = int(indices[condition][-1])
    theta = (cumulative[rho - 1] - 1) / rho
    return np.maximum(vector - theta, 0.0)


def allocation_report(returns, weights, names, *, covariance_estimate) -> dict:
    """Everything above on one covariance, with the live weights beside it.

    `covariance_estimate` is the dict from `portfolio.covariance` — passed in
    rather than computed here so the report records which estimator produced the
    numbers and how hard it shrank.
    """
    matrix = covariance_estimate['covariance']
    live = _as_weights(weights)
    reference = hierarchical_risk_parity(matrix, names)
    hrp_weights = np.array([reference['weights'][str(name)] for name in names]) \
        if reference.get('status') == 'measured' else None
    report = {
        'covariance': {
            'method': covariance_estimate.get('method'),
            'shrinkage': covariance_estimate.get('shrinkage'),
            'n_sessions': covariance_estimate.get('n_sessions'),
            'n_names': covariance_estimate.get('n_names'),
        },
        'live': {
            **effective_bets(live, matrix),
            'volatility': round(portfolio_volatility(live, matrix), 8),
        },
        'risk_contributions': risk_contributions(live, matrix, names),
        'hierarchical_risk_parity': reference,
    }
    if hrp_weights is not None:
        report['reference_comparison'] = {
            **{f'hrp_{key}': value
               for key, value in effective_bets(hrp_weights, matrix).items()},
            'hrp_volatility': round(portfolio_volatility(hrp_weights, matrix), 8),
            # L1 distance between the two allocations, in the units a reader
            # thinks in: half of it is the share of the book that would have to
            # change hands to get from one to the other.
            'turnover_to_reference': round(
                float(np.abs(live - hrp_weights).sum() / 2), 6),
        }
    return report
