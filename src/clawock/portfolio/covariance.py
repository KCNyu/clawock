"""Estimating a covariance matrix from fewer sessions than it has entries.

The problem this is for
-----------------------
`correlation_xray` publishes `effective_bets`, `diversification_ratio`, VaR and
the cluster map from `np.corrcoef` over a 60-session window. Every one of those
is a functional of the correlation matrix, so every one of them inherits that
estimator's error — and at this shape the error is not small and not symmetric.

A sample covariance of `n` names from `T` observations estimates `n(n+1)/2`
numbers from `nT`. With eight holdings and sixty sessions that is 36 parameters
from 480 observations, a ratio where the Marchenko–Pastur law says the sample
eigenvalues are *systematically* spread wider than the true ones: the largest is
biased up and the smallest is biased down. Anything that inverts the matrix, or
divides by a small eigenvalue, amplifies exactly the part that is noise.
`effective_bets = 1 / (wᵀρw)` does not invert it, but it is dominated by the
top eigenvalue, which is the biased-up one — so a concentrated book's
concentration is *understated* by the estimator that measures it.

Shrinkage is the standard answer and it is not a smoothing preference: Ledoit &
Wolf derive the intensity that minimises expected squared error against the true
matrix, so there is a right amount and it can be computed rather than chosen.

What is here
------------
* `ledoit_wolf` — shrink toward the constant-correlation target (Ledoit & Wolf,
  *Honey, I Shrunk the Sample Covariance Matrix*, 2004). The right target for
  equities: it keeps each name's own variance and pulls only the correlations
  toward their common mean.
* `oas` — Oracle Approximating Shrinkage toward a scaled identity (Chen, Wiesel,
  Eldar & Hero 2010). Stronger shrinkage in very short samples, and the honest
  choice when even the average correlation is unstable.
* `ewma_covariance` — exponential weighting, for when the question is "what is
  the correlation *now*" rather than "over the window".
* `spectrum_report` — where the sample eigenvalues sit relative to the
  Marchenko–Pastur edge, i.e. how many of them are distinguishable from noise at
  this `T/n`. This is the number that says whether shrinkage is a refinement or
  a rescue.

None of this decides anything on its own. It is the input to
`portfolio.allocation`, and it is published beside the sample estimate rather
than replacing it, so the size of the correction is visible.
"""
from __future__ import annotations

import numpy as np


def _validate(returns: np.ndarray) -> np.ndarray:
    matrix = np.asarray(returns, dtype=float)
    if matrix.ndim != 2:
        raise ValueError('returns must be a 2-D array of shape (sessions, names)')
    if matrix.shape[0] < 3 or matrix.shape[1] < 2:
        raise ValueError('need at least three sessions and two names')
    if not np.isfinite(matrix).all():
        raise ValueError('returns contain non-finite values')
    return matrix


def sample_covariance(returns) -> np.ndarray:
    """Plain sample covariance, divided by `T` rather than `T - 1`.

    The maximum-likelihood normalisation, because the shrinkage intensities
    below are derived for it; mixing the two would apply a correction computed
    for one estimator to another.
    """
    matrix = _validate(returns)
    centred = matrix - matrix.mean(axis=0)
    return centred.T @ centred / matrix.shape[0]


def _constant_correlation_target(covariance: np.ndarray) -> tuple[np.ndarray, float]:
    variances = np.diag(covariance)
    deviations = np.sqrt(variances)
    outer = np.outer(deviations, deviations)
    with np.errstate(divide='ignore', invalid='ignore'):
        correlation = np.where(outer > 0, covariance / outer, 0.0)
    n = covariance.shape[0]
    off_diagonal = (correlation.sum() - np.trace(correlation)) / (n * (n - 1))
    target = off_diagonal * outer
    np.fill_diagonal(target, variances)
    return target, float(off_diagonal)


def ledoit_wolf(returns) -> dict:
    """Shrink the sample covariance toward constant correlation.

    Returns the shrunk matrix, the intensity that produced it, and the target's
    average correlation — because an intensity of 0.6 means something different
    when the target correlation is 0.9 (the book is already one bet and the
    target agrees) than when it is 0.1.
    """
    matrix = _validate(returns)
    sessions, names = matrix.shape
    centred = matrix - matrix.mean(axis=0)
    sample = centred.T @ centred / sessions
    target, average_correlation = _constant_correlation_target(sample)

    # pi: the sum of the asymptotic variances of the sample covariance entries.
    squared = centred ** 2
    pi_matrix = (squared.T @ squared) / sessions - sample ** 2
    pi = float(pi_matrix.sum())

    # rho: the covariance between the sample entries and the target's entries.
    variances = np.diag(sample)
    deviations = np.sqrt(variances)
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio = np.where(deviations > 0, 1.0 / deviations, 0.0)
    term = (centred ** 3).T @ centred / sessions - variances * sample
    rho = float(np.trace(pi_matrix))
    for i in range(names):
        for j in range(names):
            if i == j:
                continue
            rho += average_correlation * 0.5 * (
                deviations[j] * ratio[i] * term[i, j]
                + deviations[i] * ratio[j] * term[j, i])

    gamma = float(((target - sample) ** 2).sum())
    if gamma <= 0:
        intensity = 0.0
    else:
        intensity = max(0.0, min(1.0, (pi - rho) / gamma / sessions))
    shrunk = intensity * target + (1 - intensity) * sample
    return {
        'covariance': shrunk,
        'sample_covariance': sample,
        'target': target,
        'shrinkage': round(intensity, 6),
        'target_average_correlation': round(average_correlation, 6),
        'method': 'Ledoit & Wolf (2004), constant-correlation target',
        'n_sessions': sessions,
        'n_names': names,
    }


def oas(returns) -> dict:
    """Oracle Approximating Shrinkage toward a scaled identity.

    Chen, Wiesel, Eldar & Hero (2010). A stronger, simpler target than constant
    correlation: it assumes nothing about the average correlation, which is what
    makes it the right choice when the sample is short enough that even that
    average is unstable. The cost is that it shrinks the structure the book
    actually has, so it is offered beside `ledoit_wolf` rather than instead.
    """
    matrix = _validate(returns)
    sessions, names = matrix.shape
    centred = matrix - matrix.mean(axis=0)
    sample = centred.T @ centred / sessions
    mean_variance = float(np.trace(sample)) / names
    target = mean_variance * np.eye(names)

    trace_squared = float(np.trace(sample @ sample))
    squared_trace = float(np.trace(sample)) ** 2
    numerator = (1 - 2.0 / names) * trace_squared + squared_trace
    denominator = (sessions + 1 - 2.0 / names) * (
        trace_squared - squared_trace / names)
    intensity = 1.0 if denominator <= 0 else max(0.0, min(1.0, numerator / denominator))
    return {
        'covariance': intensity * target + (1 - intensity) * sample,
        'sample_covariance': sample,
        'target': target,
        'shrinkage': round(intensity, 6),
        'method': 'Chen et al. (2010) oracle approximating shrinkage, identity target',
        'n_sessions': sessions,
        'n_names': names,
    }


def ewma_covariance(returns, decay: float = 0.94) -> dict:
    """Exponentially weighted covariance (RiskMetrics).

    Answers "what is the covariance now" rather than "over the window". The
    effective sample size is `(1 + decay) / (1 - decay)`, and it is returned,
    because an EWMA at 0.94 on sixty sessions is roughly thirty-two effective
    observations — fewer than the window suggests, which matters for every
    conditioning question in this module.
    """
    matrix = _validate(returns)
    sessions, names = matrix.shape
    centred = matrix - matrix.mean(axis=0)
    weights = decay ** np.arange(sessions - 1, -1, -1)
    weights = weights / weights.sum()
    weighted = centred * weights[:, None]
    covariance = centred.T @ weighted
    return {
        'covariance': covariance,
        'decay': decay,
        'effective_sessions': round((1 + decay) / (1 - decay), 2),
        'n_sessions': sessions,
        'n_names': names,
        'method': 'RiskMetrics exponentially weighted covariance',
    }


def correlation_from(covariance: np.ndarray) -> np.ndarray:
    deviations = np.sqrt(np.diag(covariance))
    outer = np.outer(deviations, deviations)
    with np.errstate(divide='ignore', invalid='ignore'):
        correlation = np.where(outer > 0, covariance / outer, 0.0)
    np.fill_diagonal(correlation, 1.0)
    return correlation


def spectrum_report(returns) -> dict:
    """How many eigenvalues are distinguishable from noise at this T/n.

    Under the null that the returns are independent, the sample eigenvalues of
    the correlation matrix fall inside the Marchenko–Pastur support
    `[(1 ± sqrt(n/T))²]`. Eigenvalues above the upper edge are structure; those
    inside it are the estimator's own noise, and any weight the book places on
    them is being placed on nothing.

    This is what decides whether shrinkage is a refinement or a rescue: with one
    eigenvalue above the edge and the rest inside it, the sample matrix is
    describing a single common factor plus noise, and the concentration numbers
    computed from it are describing the noise too.
    """
    matrix = _validate(returns)
    sessions, names = matrix.shape
    correlation = correlation_from(sample_covariance(matrix))
    eigenvalues = np.sort(np.linalg.eigvalsh(correlation))[::-1]
    ratio = names / sessions
    upper = (1 + np.sqrt(ratio)) ** 2
    lower = (1 - np.sqrt(ratio)) ** 2
    above = int((eigenvalues > upper).sum())
    total = float(eigenvalues.sum())
    return {
        'n_sessions': sessions,
        'n_names': names,
        'observations_per_parameter': round(
            sessions * names / (names * (names + 1) / 2), 2),
        'eigenvalues': [round(float(value), 6) for value in eigenvalues],
        'marchenko_pastur_edges': [round(float(lower), 4), round(float(upper), 4)],
        'eigenvalues_above_noise': above,
        'variance_share_of_top_eigenvalue': round(
            float(eigenvalues[0]) / total, 4) if total > 0 else None,
        'condition_number': round(
            float(eigenvalues[0] / eigenvalues[-1]), 2)
        if eigenvalues[-1] > 1e-12 else None,
        'reading': ('eigenvalues inside the Marchenko-Pastur band are what an '
                    'independent book would produce at this T/n; only the ones '
                    'above the upper edge are structure'),
    }
