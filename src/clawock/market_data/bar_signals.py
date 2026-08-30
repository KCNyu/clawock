"""What a daily bar can say about liquidity and volatility, and what it cannot.

Why this module exists at all
-----------------------------
The competitor-port issues that asked for market microstructure (#1172) and
volatility modelling (#1173) both proposed an execution layer: slippage models,
a matching engine, option pricers, an implied-volatility surface. clawock does
not place orders, has no order book, and receives no option quotes, so none of
that has an input. What it *does* have is a daily OHLCV bar for every name in
the universe, and half a century of literature on what a daily bar can be made
to reveal about the two things an order book would have told you directly:

* **how expensive this name is to move** — Amihud's price impact per dollar
  traded, Roll's spread implied by the bounce in consecutive price changes, and
  Corwin & Schultz's spread implied by the gap between the day's range and the
  two-day range;
* **how much it is about to move** — an EWMA and a GARCH(1,1) conditional
  variance, the ratio between the forecast and trailing realised volatility,
  and the volatility of that volatility.

These are estimators, not measurements, and each has a regime where it is
undefined rather than merely imprecise. Roll's spread requires a *negative*
serial covariance in price changes; on a trending name the covariance is
positive and the estimator has no real root. The convention in practice is to
set those to zero, which turns "this estimator does not apply here" into "this
name has no spread" — the most liquid-looking value in the cross-section, on
exactly the names where it should be silent. Every function here returns `None`
instead, and the share of names where that happened is published beside the
factor.

Nothing here joins the pre-registered composite. `factor_weights` must exactly
match `RAW_FACTORS` and sum to one; adding a constituent is a re-registration
and a research decision, not a code change. These are emitted as their own
block, land in the registered history point-in-time, and are scored by
`clawock signal-panel` like any other source — measurement first, and a rule
only if the measurement earns one.
"""
from __future__ import annotations

import math
import statistics

#: RiskMetrics. Not fitted — a fitted decay on 250 observations is one more
#: searched parameter, and the point of the EWMA here is to be the un-searched
#: baseline the GARCH forecast has to beat.
EWMA_LAMBDA = 0.94

TRADING_DAYS = 252

#: A GARCH(1,1) on fewer than this is fitting three parameters to noise.
MIN_GARCH_OBSERVATIONS = 200


def _returns(bars, end_index, sessions):
    start = max(1, end_index - sessions + 1)
    out = []
    for index in range(start, end_index + 1):
        previous, current = bars[index - 1].get('close'), bars[index].get('close')
        if previous and current:
            out.append(current / previous - 1)
    return out


def amihud_illiquidity(bars, index, sessions=20):
    """Mean |return| per dollar traded (Amihud 2002), scaled to 1e9 dollars.

    The cleanest daily-bar proxy for price impact: how far the price moves for
    each dollar that changes hands. High means illiquid. Returns `None` rather
    than a partial average when volume is missing for more than a third of the
    window, because an Amihud computed over the six days a vendor happened to
    report volume is a ranking of the vendor's coverage.
    """
    if index is None or index < sessions:
        return None
    ratios, missing = [], 0
    for position in range(index - sessions + 1, index + 1):
        previous, current = bars[position - 1], bars[position]
        volume = current.get('volume')
        close = current.get('close')
        if not volume or not close or not previous.get('close'):
            missing += 1
            continue
        dollars = close * volume
        if dollars <= 0:
            missing += 1
            continue
        ratios.append(abs(current['close'] / previous['close'] - 1) / dollars)
    if not ratios or missing > sessions / 3:
        return None
    return statistics.fmean(ratios) * 1e9


def roll_spread(bars, index, sessions=20):
    """Effective spread implied by the bid-ask bounce (Roll 1984).

    `2 * sqrt(-cov(dp_t, dp_{t-1}))`. The model says consecutive price changes
    are negatively autocorrelated because trades alternate between the bid and
    the ask; when the covariance comes out positive the name was trending and
    the model does not describe it. That is returned as `None`, never as zero:
    zero is the most liquid value in the cross-section and would be assigned to
    precisely the trending names.
    """
    if index is None or index < sessions + 1:
        return None
    prices = [bars[position].get('close')
              for position in range(index - sessions, index + 1)]
    if any(not price for price in prices):
        return None
    changes = [prices[position] - prices[position - 1]
               for position in range(1, len(prices))]
    if len(changes) < 3:
        return None
    pairs = list(zip(changes, changes[1:]))
    mean_current = statistics.fmean(value for value, _ in pairs)
    mean_lagged = statistics.fmean(value for _, value in pairs)
    covariance = statistics.fmean(
        (current - mean_current) * (lagged - mean_lagged)
        for current, lagged in pairs)
    if covariance >= 0:
        return None
    reference = prices[-1]
    return 100 * 2 * math.sqrt(-covariance) / reference if reference else None


def corwin_schultz_spread(bars, index, sessions=20):
    """Spread implied by one-day vs two-day high-low ranges (Corwin & Schultz 2012).

    Two days of range contain two days of volatility and *one* spread, one day
    contains one of each; the difference identifies the spread. Estimates come
    out negative when the two-day range is smaller than the model allows, which
    happens on gaps; those days are dropped and their count returned, rather
    than floored at zero, for the same reason as `roll_spread`.
    """
    if index is None or index < sessions + 1:
        return None
    root = 3 - 2 * math.sqrt(2)
    estimates, negative = [], 0
    for position in range(index - sessions + 1, index + 1):
        first, second = bars[position - 1], bars[position]
        highs = [first.get('high'), second.get('high')]
        lows = [first.get('low'), second.get('low')]
        if not all(highs) or not all(lows):
            continue
        beta = sum(math.log(high / low) ** 2 for high, low in zip(highs, lows))
        two_day_high, two_day_low = max(highs), min(lows)
        gamma = math.log(two_day_high / two_day_low) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / root - math.sqrt(gamma / root)
        spread = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
        if spread < 0:
            negative += 1
            continue
        estimates.append(spread)
    if not estimates:
        return None
    return 100 * statistics.fmean(estimates)


def volume_ratio(bars, index, recent=20, baseline=60):
    """Recent volume against the name's own longer-run median.

    Cross-sectional volume levels are not comparable — a HK blue chip and a US
    small cap differ by orders of magnitude for reasons that have nothing to do
    with today. Each name against its own baseline is.
    """
    if index is None or index < baseline:
        return None
    def volumes(sessions):
        return [bars[position].get('volume')
                for position in range(index - sessions + 1, index + 1)
                if bars[position].get('volume')]
    near, far = volumes(recent), volumes(baseline)
    if len(near) < recent / 2 or len(far) < baseline / 2:
        return None
    reference = statistics.median(far)
    return statistics.fmean(near) / reference if reference else None


def ewma_volatility(bars, index, sessions=250, decay=EWMA_LAMBDA):
    """Annualised RiskMetrics EWMA volatility."""
    returns = _returns(bars, index, sessions) if index is not None else []
    if len(returns) < 20:
        return None
    variance = statistics.pvariance(returns[:20])
    for value in returns[20:]:
        variance = decay * variance + (1 - decay) * value * value
    return math.sqrt(variance * TRADING_DAYS)


def fit_garch11(returns, *, grid=12, refinements=3):
    """GARCH(1,1) by variance targeting and a refined grid over (alpha, beta).

    Variance targeting fixes `omega = s2 * (1 - alpha - beta)` at the sample
    variance, leaving two free parameters, and a grid over two bounded
    parameters is deterministic where a gradient optimiser on a
    non-differentiable-at-the-boundary likelihood is not. Three refinement
    passes reach a resolution finer than the parameters are identified to on 250
    observations, which is the honest limit here — a tighter optimiser would
    report more digits of a number the sample does not contain.

    Returns `None` below `MIN_GARCH_OBSERVATIONS`: fitting persistence to a
    hundred days produces alpha + beta near 1 whatever the data does, which is
    the classic small-sample artefact and reads as "extremely persistent
    volatility" instead of "not enough data".
    """
    values = [float(value) for value in returns]
    if len(values) < MIN_GARCH_OBSERVATIONS:
        return None
    mean = statistics.fmean(values)
    centred = [value - mean for value in values]
    sample_variance = statistics.pvariance(centred)
    if sample_variance <= 0:
        return None

    def log_likelihood(alpha, beta):
        if alpha <= 0 or beta < 0 or alpha + beta >= 0.999:
            return -math.inf
        omega = sample_variance * (1 - alpha - beta)
        variance = sample_variance
        total = 0.0
        for value in centred:
            if variance <= 0:
                return -math.inf
            total += -0.5 * (math.log(variance) + value * value / variance)
            variance = omega + alpha * value * value + beta * variance
        return total

    low_alpha, high_alpha = 0.005, 0.4
    low_beta, high_beta = 0.30, 0.995
    best = (None, None, -math.inf)
    for _ in range(refinements):
        for step_a in range(grid):
            alpha = low_alpha + (high_alpha - low_alpha) * step_a / (grid - 1)
            for step_b in range(grid):
                beta = low_beta + (high_beta - low_beta) * step_b / (grid - 1)
                score = log_likelihood(alpha, beta)
                if score > best[2]:
                    best = (alpha, beta, score)
        if best[0] is None:
            return None
        span_a = (high_alpha - low_alpha) / (grid - 1)
        span_b = (high_beta - low_beta) / (grid - 1)
        low_alpha, high_alpha = max(0.005, best[0] - span_a), min(0.4, best[0] + span_a)
        low_beta, high_beta = max(0.0, best[1] - span_b), min(0.995, best[1] + span_b)

    alpha, beta, score = best
    omega = sample_variance * (1 - alpha - beta)
    variance = sample_variance
    for value in centred:
        variance = omega + alpha * value * value + beta * variance
    return {
        'alpha': round(alpha, 6),
        'beta': round(beta, 6),
        'omega': omega,
        'persistence': round(alpha + beta, 6),
        'log_likelihood': round(score, 4),
        'n_observations': len(values),
        'next_variance': variance,
        'annualised_forecast': math.sqrt(variance * TRADING_DAYS),
        'long_run_annualised': math.sqrt(sample_variance * TRADING_DAYS),
    }


def realised_moments(bars, index, sessions=60):
    """Skewness and non-excess kurtosis of the recent return distribution.

    Not a forecast; a description of what the tail has looked like. It is here
    because the deflated Sharpe ratio in `evaluation.deflated_sharpe` charges
    for exactly these two moments, and a name whose returns are negatively
    skewed and fat-tailed needs a larger edge to be worth the same.
    """
    returns = _returns(bars, index, sessions) if index is not None else []
    if len(returns) < 30:
        return None
    mean = statistics.fmean(returns)
    m2 = statistics.pvariance(returns)
    if m2 <= 0:
        return None
    m3 = statistics.fmean((value - mean) ** 3 for value in returns)
    m4 = statistics.fmean((value - mean) ** 4 for value in returns)
    return {'realised_skew': m3 / m2 ** 1.5, 'realised_kurtosis': m4 / m2 ** 2}


def volatility_of_volatility(bars, index, window=20, sessions=60):
    """Dispersion of the rolling realised volatility over the recent past."""
    if index is None or index < window + sessions:
        return None
    series = []
    for position in range(index - sessions + 1, index + 1):
        returns = _returns(bars, position, window)
        if len(returns) >= window - 1:
            series.append(statistics.pstdev(returns))
    if len(series) < 20:
        return None
    mean = statistics.fmean(series)
    return statistics.pstdev(series) / mean if mean > 0 else None


def bar_signal_row(bars, index) -> dict:
    """Every bar-derived estimator for one name at one point in time.

    `None` entries are kept rather than dropped: "this estimator does not apply
    to this name today" is a different statement from "this name was not
    covered", and the panel counts them separately.
    """
    garch = fit_garch11(_returns(bars, index, 250)) if index is not None else None
    ewma = ewma_volatility(bars, index)
    moments = realised_moments(bars, index) or {}
    trailing = None
    returns = _returns(bars, index, 20) if index is not None else []
    if len(returns) >= 19:
        trailing = statistics.pstdev(returns) * math.sqrt(TRADING_DAYS)
    forecast = garch['annualised_forecast'] if garch else None
    return {
        'amihud_illiquidity': amihud_illiquidity(bars, index),
        'roll_spread_pct': roll_spread(bars, index),
        'corwin_schultz_spread_pct': corwin_schultz_spread(bars, index),
        'volume_ratio': volume_ratio(bars, index),
        'ewma_volatility': ewma,
        'realised_volatility_20d': trailing,
        'garch_forecast_volatility': forecast,
        # The forecast against what just happened. Above one is an expansion the
        # model expects and the trailing window has not seen yet, which is the
        # only part of a volatility model that carries information a plain
        # trailing standard deviation does not already have.
        'garch_vol_expansion': (forecast / trailing
                                if forecast and trailing else None),
        'garch_persistence': garch['persistence'] if garch else None,
        'vol_of_vol': volatility_of_volatility(bars, index),
        **{key: value for key, value in moments.items()},
    }


#: The estimators that are undefined on some names by construction rather than
#: by coverage. Their per-session availability is published so a reader can tell
#: a thin cross-section from a regime where the model does not apply.
CONDITIONALLY_DEFINED = ('roll_spread_pct', 'corwin_schultz_spread_pct')


def availability(rows: dict) -> dict:
    """How many names each estimator produced a value for, this session."""
    if not rows:
        return {}
    fields = sorted({key for row in rows.values() for key in row})
    return {
        'n_tickers': len(rows),
        'defined': {
            field: sum(1 for row in rows.values() if row.get(field) is not None)
            for field in fields
        },
        'conditionally_defined': list(CONDITIONALLY_DEFINED),
        'reading': ('a conditionally-defined estimator missing on a name means '
                    'the model does not apply there (Roll needs a negative '
                    'serial covariance), not that the name is liquid'),
    }
