"""What a Sharpe ratio is worth once you count how many were computed.

The gap this closes
-------------------
`add_alpha_walkforward` reports four variants across three horizons in two
markets and the reader's eye goes to the best cell. `cscv` already answers one
half of what that costs — how often the in-sample winner is below median out of
sample — and answers it by resampling, which needs enough sessions to fill eight
groups. The other half is cheaper and available immediately: **the maximum of N
draws from a zero-mean Sharpe distribution is not zero.** With twenty-four cells
searched, a best-of Sharpe around 0.5 on a short sample is the expected result
of searching, not a finding.

`expected_max_sharpe` is that null: the expected largest Sharpe under `n_trials`
independent trials whose true Sharpe is zero (Bailey & López de Prado, *The
Deflated Sharpe Ratio*, 2014, eq. 5), using the extreme-value approximation with
the Euler-Mascheroni constant. `deflated_sharpe_ratio` then reports
`P(true SR > 0)` after subtracting that null and correcting the standard error
for the skewness and kurtosis of the returns — because the usual
`SR·sqrt(T-1)` statistic assumes normal returns, and a negatively skewed,
fat-tailed return stream makes a given Sharpe far less impressive than the
normal approximation says.

Two things this is not
----------------------
* **It is not PBO, and `1 - DSR` is not PBO.** They answer different questions
  from different inputs: DSR deflates one estimate by the size of the search,
  from the moments of one return stream; PBO measures how the ranking of the
  searched configurations behaves out of sample, from the whole matrix. A rule
  can have a high DSR and a high PBO (a real edge whose *selection* among near
  ties is unstable) or the reverse. `evaluation.cscv` owns PBO; this module does
  not compute it and must not be read as computing it.
* **It is not a licence to report a number from three observations.** Both
  functions refuse a sample too short for their own approximation rather than
  returning a decoration.
"""
from __future__ import annotations

import math
import statistics

from clawock.evaluation.bootstrap import norm_ppf, _norm_cdf

#: Euler-Mascheroni. It appears because the maximum of N i.i.d. normals
#: converges to a Gumbel, whose location involves it.
EULER_MASCHERONI = 0.5772156649015329

#: Below this the moment estimates that carry the whole correction (skew and
#: kurtosis, which are fourth-order quantities) are noise, and a DSR computed
#: from them says more about the sample than the strategy.
MIN_OBSERVATIONS = 20


def expected_max_sharpe(n_trials: int, variance_of_trials: float) -> float | None:
    """E[max Sharpe] over `n_trials` independent trials with true Sharpe 0.

    `variance_of_trials` is the variance of the Sharpe ratios that the search
    actually produced — the spread of the thing being maximised, not the
    variance of returns. A search over configurations that all score nearly the
    same has little to gain from being maximised, and this formula says so.
    """
    if n_trials < 2 or variance_of_trials <= 0:
        return None
    sigma = math.sqrt(variance_of_trials)
    return sigma * (
        (1 - EULER_MASCHERONI) * norm_ppf(1 - 1.0 / n_trials)
        + EULER_MASCHERONI * norm_ppf(1 - 1.0 / (n_trials * math.e))
    )


def sharpe(returns, *, periods_per_year: int | None = None) -> float | None:
    """Sharpe of a return series, unannualised unless a period count is given."""
    values = [float(value) for value in returns]
    if len(values) < 2:
        return None
    deviation = statistics.stdev(values)
    if deviation == 0:
        return None
    ratio = statistics.fmean(values) / deviation
    if periods_per_year:
        ratio *= math.sqrt(periods_per_year)
    return ratio


def _skew_kurtosis(values) -> tuple[float, float]:
    """Population skewness and *non-excess* kurtosis (normal = 3)."""
    n = len(values)
    mean = statistics.fmean(values)
    m2 = sum((value - mean) ** 2 for value in values) / n
    if m2 == 0:
        return 0.0, 3.0
    m3 = sum((value - mean) ** 3 for value in values) / n
    m4 = sum((value - mean) ** 4 for value in values) / n
    return m3 / m2 ** 1.5, m4 / m2 ** 2


def deflated_sharpe_ratio(returns, *, n_trials: int,
                          variance_of_trials: float | None = None,
                          trial_sharpes=None) -> dict:
    """P(true Sharpe > 0) after deflating for the size of the search.

    Give either `variance_of_trials` or the `trial_sharpes` the search produced;
    with the latter the variance is measured rather than assumed. Returns the
    probability alongside every input it was computed from, because a DSR quoted
    without its trial count and its benchmark Sharpe cannot be argued with.
    """
    values = [float(value) for value in returns]
    n = len(values)
    if n < MIN_OBSERVATIONS:
        return {'status': 'insufficient_sample', 'dsr': None,
                'reason': f'{n} observations is below the {MIN_OBSERVATIONS} floor',
                'n_observations': n, 'n_trials': n_trials}
    observed = sharpe(values)
    if observed is None:
        return {'status': 'insufficient_sample', 'dsr': None,
                'reason': 'return series has no dispersion',
                'n_observations': n, 'n_trials': n_trials}

    if variance_of_trials is None and trial_sharpes:
        finite = [float(value) for value in trial_sharpes if value is not None]
        variance_of_trials = statistics.pvariance(finite) if len(finite) > 1 else None
    if not variance_of_trials or variance_of_trials <= 0 or n_trials < 2:
        return {'status': 'insufficient_search', 'dsr': None,
                'reason': ('a deflation needs at least two trials with different '
                           'Sharpe ratios; a single pre-registered configuration '
                           'has no search to deflate'),
                'n_observations': n, 'n_trials': n_trials,
                'observed_sharpe': round(observed, 6)}

    benchmark = expected_max_sharpe(n_trials, variance_of_trials)
    skewness, kurtosis = _skew_kurtosis(values)
    # Bailey & López de Prado eq. 9. The denominator is the standard error of a
    # Sharpe estimate under non-normal returns; it grows with negative skew and
    # with excess kurtosis, which is why a fat-tailed stream needs a larger
    # Sharpe to reach the same significance.
    variance_term = 1 - skewness * observed + (kurtosis - 1) / 4.0 * observed ** 2
    if variance_term <= 0:
        return {'status': 'insufficient_sample', 'dsr': None,
                'reason': 'moment correction is non-positive; sample too extreme',
                'n_observations': n, 'n_trials': n_trials}
    statistic = (observed - benchmark) * math.sqrt(n - 1) / math.sqrt(variance_term)
    return {
        'status': 'measured',
        'method': 'Bailey & Lopez de Prado (2014) deflated Sharpe ratio',
        'dsr': round(_norm_cdf(statistic), 6),
        'observed_sharpe': round(observed, 6),
        'benchmark_sharpe': round(benchmark, 6),
        'n_trials': n_trials,
        'variance_of_trials': round(variance_of_trials, 8),
        'n_observations': n,
        'skewness': round(skewness, 4),
        'kurtosis': round(kurtosis, 4),
        'reading': ('probability the true Sharpe exceeds zero once the expected '
                    'maximum of the search is subtracted; not one minus PBO'),
    }
