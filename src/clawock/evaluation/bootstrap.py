"""Resampling that keeps the dependence the sample actually has.

The gap this closes
-------------------
`add_alpha_walkforward._cluster_ci` resamples **dates** with replacement and
pools every fill inside a drawn date. That is the right answer to one of the two
dependencies in this data — several tickers filling on the same session are not
independent observations — and no answer at all to the other: consecutive
sessions are not independent either. A momentum rule that is right for six weeks
and wrong for six weeks produces a run structure that an i.i.d.-over-dates
bootstrap cannot see, so the interval it prints is too narrow, and too narrow in
the direction that makes a result look publishable.

The fix is not a different confidence level. It is to resample **blocks** of
consecutive dates, so a draw can contain a whole good stretch or a whole bad one
the way the sample did. `stationary_bootstrap` implements Politis & Romano
(1994): block lengths are Geometric(1/b) and the series is wrapped, which is
what keeps the resampled series stationary — fixed-length blocks do not have
that property at the ends.

Choosing the block length
-------------------------
`b` is not a taste parameter. Too small and the bootstrap collapses back to the
i.i.d. one it was meant to replace; too large and every draw is nearly the
original sample and the interval collapses the other way. `optimal_block_length`
implements Politis & White (2004) with Patton, Politis & White's (2009)
correction: estimate the autocovariance out to a lag where the correlogram has
gone quiet, weight it with the flat-top kernel, and solve for the length that
minimises the MSE of the variance estimate. It returns lengths for both the
stationary and circular schemes because the two have different constants, and it
returns `1` for a series with no detectable serial dependence — which is the
honest answer, and is also exactly the case where the old estimator was right.

BCa rather than percentile
--------------------------
The statistic here is a mean of a skewed, bounded-below quantity (a return), and
the percentile interval is biased whenever the bootstrap distribution is not
centred on the estimate. `bca_interval` applies Efron's bias-correction and
acceleration: `z0` from the share of draws below the point estimate, `a` from a
delete-one jackknife **over the clusters**, not over the rows, because deleting
one fill out of a date leaves the rest of that date's fills in place and would
understate the influence of the date.

Everything here is standard library. The repository has one hard dependency
(`requests`) and this module is not a reason to acquire pandas, numpy, scipy or
scikit-learn — none of the three algorithms above needs a matrix.
"""
from __future__ import annotations

import math
import random
import statistics

#: Politis & White's own bound. Beyond this the "block" is a sizeable fraction
#: of the sample and the resample stops being a resample.
def _max_block(n: int) -> int:
    return max(1, math.ceil(min(3.0 * math.sqrt(n), n / 3.0)))


def _flat_top(t: float) -> float:
    """Politis & Romano's trapezoidal lag window: flat to 1/2, down to 0 at 1."""
    t = abs(t)
    if t <= 0.5:
        return 1.0
    if t <= 1.0:
        return 2.0 * (1.0 - t)
    return 0.0


def autocovariances(series, max_lag: int) -> list[float]:
    """Biased (divide-by-n) autocovariances, lag 0..max_lag.

    Biased on purpose: the divide-by-n estimator is the one whose lag window
    weighting Politis & White's constants were derived for, and it keeps the
    implied spectral density non-negative.
    """
    n = len(series)
    if n == 0:
        return []
    mean = statistics.fmean(series)
    centred = [value - mean for value in series]
    out = []
    for lag in range(0, min(max_lag, n - 1) + 1):
        out.append(sum(centred[i] * centred[i + lag] for i in range(n - lag)) / n)
    return out


def optimal_block_length(series) -> dict:
    """Politis & White (2004), Patton/Politis/White (2009) correction.

    Returns ``{'stationary': b_sb, 'circular': b_cb, 'm_hat': m, 'n': n}``.
    ``b = 1`` means the correlogram never left the noise band: the series has no
    detectable serial dependence at this length and block resampling would only
    add variance.
    """
    values = [float(value) for value in series]
    n = len(values)
    if n < 8:
        return {'stationary': 1, 'circular': 1, 'm_hat': 0, 'n': n}
    variance = statistics.pvariance(values)
    if variance <= 0:
        return {'stationary': 1, 'circular': 1, 'm_hat': 0, 'n': n}

    # The lag beyond which the correlogram is indistinguishable from noise.
    # `k_n` consecutive lags must all sit inside the band before we accept that
    # it has: a single dip below the threshold is not evidence of quiet.
    k_n = max(5, int(math.ceil(math.sqrt(math.log10(n)))))
    max_lag = min(n - 1, int(math.ceil(math.sqrt(n))) + k_n)
    gamma = autocovariances(values, max_lag)
    rho = [value / gamma[0] for value in gamma] if gamma[0] > 0 else [0.0] * len(gamma)
    band = 2.0 * math.sqrt(math.log10(n) / n)

    m_hat = 0
    for lag in range(1, len(rho)):
        window = rho[lag:lag + k_n]
        if len(window) < k_n:
            break
        if all(abs(value) < band for value in window):
            m_hat = lag - 1
            break
    else:
        m_hat = max(0, len(rho) - 1)
    if m_hat <= 0:
        return {'stationary': 1, 'circular': 1, 'm_hat': 0, 'n': n}

    big_m = min(2 * m_hat, n - 1)
    # g_hat and d_hat are the two moments of the flat-top-weighted correlogram
    # that the MSE-optimal length trades off: g_hat is the bias term (how much
    # dependence is being smoothed away) and d_hat the variance term.
    g_hat = 0.0
    sum_weighted = gamma[0]
    for lag in range(1, big_m + 1):
        if lag >= len(gamma):
            break
        weight = _flat_top(lag / big_m)
        g_hat += 2.0 * weight * lag * gamma[lag]
        sum_weighted += 2.0 * weight * gamma[lag]
    if g_hat == 0.0 or sum_weighted == 0.0:
        return {'stationary': 1, 'circular': 1, 'm_hat': m_hat, 'n': n}

    d_sb = 2.0 * sum_weighted ** 2
    d_cb = (4.0 / 3.0) * sum_weighted ** 2
    cap = _max_block(n)
    b_sb = min(cap, max(1, round((2.0 * g_hat ** 2 / d_sb) ** (1.0 / 3.0) * n ** (1.0 / 3.0))))
    b_cb = min(cap, max(1, round((2.0 * g_hat ** 2 / d_cb) ** (1.0 / 3.0) * n ** (1.0 / 3.0))))
    return {'stationary': int(b_sb), 'circular': int(b_cb), 'm_hat': m_hat, 'n': n}


def stationary_bootstrap_indices(n: int, block_length: float, rnd: random.Random):
    """One resampled index path of length `n` (Politis & Romano 1994).

    Geometric block lengths with mean `block_length`, wrapped at the end. The
    wrap is what makes it *stationary*: without it the first and last
    observations would be under-represented in every draw.
    """
    if n <= 0:
        return []
    probability = 1.0 / max(1.0, float(block_length))
    out = []
    index = rnd.randrange(n)
    while len(out) < n:
        out.append(index)
        if rnd.random() < probability:
            index = rnd.randrange(n)
        else:
            index = (index + 1) % n
    return out


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


#: Acklam's rational approximation, refined once with Halley's method against
#: `erf`. Accurate to well past the precision anything downstream rounds to, and
#: it does not cost a scipy dependency.
_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00)


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    low, high = 0.02425, 1 - 0.02425
    if p < low:
        q = math.sqrt(-2 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1)
    elif p <= high:
        q = p - 0.5
        r = q * q
        x = (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
            (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1)
    error = _norm_cdf(x) - p
    density = math.exp(-x * x / 2) / math.sqrt(2 * math.pi)
    if density > 0:
        u = error / density
        x = x - u / (1 + x * u / 2)
    return x


#: The acceleration term is a third moment of the jackknife replicates. Estimated
#: from three clusters it is noise, and its failure mode is the bad one: it moved
#: `hk/interaction/t5` from an interval crossing zero to one clearing it, on three
#: sessions. Below this floor the correction is refused and the caller falls back
#: to the percentile interval, which is merely wide rather than wrong.
MIN_CLUSTERS_FOR_BCA = 8


def bca_interval(draws, point_estimate, jackknife_values, alpha: float = 0.05) -> list[float] | None:
    """Efron's bias-corrected and accelerated percentile interval.

    `jackknife_values` are the statistic recomputed with each *cluster* left
    out. Returns `None` when acceleration cannot be estimated — fewer than
    `MIN_CLUSTERS_FOR_BCA` clusters, or a jackknife with no spread — because a
    BCa interval whose `a` was silently set to zero is a percentile interval
    wearing a citation, and one whose `a` came from three points is worse than
    that: it narrows the interval using an estimate that has no business being
    trusted.
    """
    if not draws:
        return None
    ordered = sorted(draws)
    total = len(ordered)
    below = sum(1 for value in ordered if value < point_estimate)
    share = below / total
    if share <= 0 or share >= 1:
        return None
    z0 = norm_ppf(share)

    if len(jackknife_values) < MIN_CLUSTERS_FOR_BCA:
        return None
    mean_jack = statistics.fmean(jackknife_values)
    deviations = [mean_jack - value for value in jackknife_values]
    denominator = sum(d * d for d in deviations) ** 1.5
    if denominator == 0:
        return None
    acceleration = sum(d ** 3 for d in deviations) / (6.0 * denominator)

    out = []
    for tail in (alpha / 2, 1 - alpha / 2):
        z = norm_ppf(tail)
        adjusted = z0 + (z0 + z) / (1 - acceleration * (z0 + z))
        probability = min(max(_norm_cdf(adjusted), 1.0 / total), 1 - 1.0 / total)
        out.append(ordered[min(total - 1, max(0, int(round(probability * (total - 1)))))])
    return [round(out[0], 6), round(out[1], 6)]


def clustered_block_ci(values_by_cluster: dict, *, samples: int = 2000,
                       seed: int = 20260830, alpha: float = 0.05,
                       block_length: float | None = None) -> dict | None:
    """Confidence interval for the pooled mean under both dependencies.

    `values_by_cluster` maps an orderable cluster key (a session date) to the
    observations inside it. Clusters are resampled in **blocks of consecutive
    keys** — that is the serial dependence — and every observation inside a
    drawn cluster travels with it — that is the cross-sectional dependence.

    The returned block length is part of the answer, not diagnostics: `1` means
    the data showed no serial dependence and the interval is the i.i.d.-over-
    dates one, so a reader can see when the two estimators agree by construction
    rather than by coincidence.
    """
    keys = sorted(values_by_cluster)
    if len(keys) < 3:
        return None
    per_cluster_mean = [statistics.fmean(values_by_cluster[key]) for key in keys]
    pooled = [value for key in keys for value in values_by_cluster[key]]
    if not pooled:
        return None
    point = statistics.fmean(pooled)

    if block_length is None:
        block_length = optimal_block_length(per_cluster_mean)['stationary']
    rnd = random.Random(seed)
    draws = []
    for _ in range(samples):
        indices = stationary_bootstrap_indices(len(keys), block_length, rnd)
        resampled = [value for i in indices for value in values_by_cluster[keys[i]]]
        draws.append(statistics.fmean(resampled))

    jackknife = []
    for skip in range(len(keys)):
        kept = [value for i, key in enumerate(keys) if i != skip
                for value in values_by_cluster[key]]
        if kept:
            jackknife.append(statistics.fmean(kept))
    interval = bca_interval(draws, point, jackknife, alpha=alpha)
    if interval is None:
        ordered = sorted(draws)
        interval = [round(ordered[int(alpha / 2 * (len(ordered) - 1))], 6),
                    round(ordered[int((1 - alpha / 2) * (len(ordered) - 1))], 6)]
        method = 'stationary block bootstrap; percentile'
    else:
        method = 'stationary block bootstrap; BCa'
    return {
        'point': round(point, 6),
        'ci95': interval,
        'block_length': int(block_length),
        'n_clusters': len(keys),
        'n_observations': len(pooled),
        'samples': samples,
        'method': method,
    }
