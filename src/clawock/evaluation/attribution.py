"""Where a return came from, when the thing that produced it is a linear score.

Two questions, one of which has an exact answer
-----------------------------------------------
**"Why is this name ranked here?"** has an exact answer and nobody was giving it.
`composite_score` is a weighted mean of nine sector-neutral ranks, so each
factor's contribution to it is `w_f · rank_f / Σw`, additively and without
approximation. Reaching for SHAP or LIME on a linear model — which is what the
competitor-port issue proposed — approximates something that can simply be
computed, and then reports the approximation's error as though it were a
subtlety of the model. `explain_composite` computes it, and adds the exact
leave-one-out: recompute the name's cross-sectional percentile with one factor
removed and report how far it moves, which answers "would dropping quality
change where this name sits" rather than "how much quality contributed".

**"Where did the portfolio's return come from?"** does not have an exact answer,
and the honest form of it is a regression whose standard errors have to be
published next to it. Per session, the cross-section of forward returns is
regressed on the factor loadings; the coefficients are the factor returns
(Fama-MacBeth). Portfolio exposure to each factor is the weighted sum of its
loadings, and the return splits into:

* **common** — what the factor exposures explain;
* **specific** — what is left, which is where an unmodelled bet lives;
* **tilt** — the part of common attributable to the *average* exposure, i.e. the
  standing bet;
* **timing** — the part attributable to exposure moving around that average.

`tilt + timing == common` by construction and a test pins it.

The sample this is being asked to support
------------------------------------------
About twenty-one names in the cross-section and nine factors. That is 21
observations for 10 parameters, which is not a comfortable regression, and the
correlations among the loadings make it worse: momentum at one, three and six
months are not nine independent directions. So every session's fit carries its
R², its condition number and its residual degrees of freedom, `factor_returns`
refuses a session with fewer than `MIN_NAMES_PER_FACTOR` names per factor, and
the aggregate reports how many sessions it had to skip. An attribution computed
over the twelve sessions that happened to have a wide enough cross-section is a
statement about those twelve sessions.
"""
from __future__ import annotations

import math
import statistics

import numpy as np

#: Names per factor below which the cross-sectional regression is fitting noise.
#: Three is already thin; below it the residual degrees of freedom are in single
#: figures and the coefficient standard errors are wider than the coefficients.
MIN_NAMES_PER_FACTOR = 3

#: Above this the loading matrix is close enough to singular that the split of a
#: return between two collinear factors is arbitrary. Reported rather than
#: silently ridge-regularised: a caller told the design is collinear can drop a
#: factor, whereas a caller handed a stabilised number cannot see the problem.
CONDITION_WARN = 100.0


#: The nine registered factors grouped into three blocks. This is a reduction,
#: not a search: the grouping follows the names the factor universe already
#: uses, no alternative grouping was tried, and the block loading is the same
#: weighted mean the composite uses — restricted to the block's members — so it
#: is derived from the pre-registration rather than invented beside it.
#:
#: It exists because the nine-factor regression is structurally unavailable on
#: this book. The cross-section that has both registered ranks and canonical
#: bars is **13 names at the median**, and nine factors plus an intercept need
#: 27 by the `MIN_NAMES_PER_FACTOR` rule: every one of the eighteen sessions is
#: skipped. Three blocks need nine, which thirteen clears.
FACTOR_BLOCKS = {
    'momentum': ('residual_mom_1m', 'residual_mom_3m', 'residual_mom_6m',
                 'relative_strength'),
    'stability': ('low_volatility', 'drawdown_resilience'),
    'quality_liquidity': ('quality_profitability', 'liquidity', 'breadth'),
}


def block_loadings(ranks, weights, blocks=None) -> dict:
    """Collapse per-factor ranks into per-block loadings, by registered weight."""
    blocks = blocks or FACTOR_BLOCKS
    out = {}
    for block, members in blocks.items():
        present = [(float(weights[factor]), float(ranks[factor]))
                   for factor in members
                   if factor in weights and ranks.get(factor) is not None]
        if present:
            total = sum(weight for weight, _ in present)
            out[block] = sum(weight * value for weight, value in present) / total
    return out


def to_blocks(sessions, weights, blocks=None) -> dict:
    """Rewrite a `{as_of: (loadings, forward)}` map in block space."""
    blocks = blocks or FACTOR_BLOCKS
    return {
        as_of: ({name: block_loadings(ranks, weights, blocks)
                 for name, ranks in loadings.items()}, forward)
        for as_of, (loadings, forward) in sessions.items()
    }


def _design(loadings_by_name, factors, names):
    matrix = np.array([[float(loadings_by_name[name].get(factor, 0.0))
                        for factor in factors] for name in names], dtype=float)
    return np.column_stack([np.ones(len(names)), matrix])


def cross_sectional_fit(loadings_by_name, forward_by_name, factors) -> dict | None:
    """One session: regress forward returns on factor loadings.

    Returns the coefficients (the session's factor returns), plus everything
    needed to argue with them. `None` when the cross-section is too narrow —
    silently returning coefficients from an underdetermined fit is how an
    attribution table fills up with numbers that mean nothing.
    """
    names = sorted(set(loadings_by_name) & set(forward_by_name))
    if len(names) < MIN_NAMES_PER_FACTOR * len(factors):
        return None
    design = _design(loadings_by_name, factors, names)
    target = np.array([float(forward_by_name[name]) for name in names])
    coefficients, residuals, rank, singular = np.linalg.lstsq(design, target, rcond=None)
    fitted = design @ coefficients
    residual = target - fitted
    total_variance = float(((target - target.mean()) ** 2).sum())
    degrees = len(names) - design.shape[1]
    condition = (float(singular[0] / singular[-1])
                 if len(singular) and singular[-1] > 0 else math.inf)
    return {
        'names': names,
        'intercept': float(coefficients[0]),
        'factor_returns': {factor: float(value)
                           for factor, value in zip(factors, coefficients[1:])},
        'r_squared': (1 - float((residual ** 2).sum()) / total_variance
                      if total_variance > 0 else None),
        'residual_degrees_of_freedom': degrees,
        'condition_number': round(condition, 2) if math.isfinite(condition) else None,
        'collinear': bool(condition > CONDITION_WARN),
        'n_names': len(names),
    }


def factor_returns(sessions, factors) -> dict:
    """Fama-MacBeth across sessions, with the sessions it could not fit.

    `sessions` is `{as_of: (loadings_by_name, forward_by_name)}`. The t-statistic
    is over the *time series* of per-session coefficients, which is the whole
    point of the two-pass procedure: it sidesteps the cross-sectional
    correlation that makes a single pooled regression's standard errors fiction.
    """
    fits, skipped = {}, []
    for as_of in sorted(sessions):
        loadings, forward = sessions[as_of]
        fit = cross_sectional_fit(loadings, forward, factors)
        if fit is None:
            skipped.append(as_of)
        else:
            fits[as_of] = fit
    if len(fits) < 3:
        return {'status': 'insufficient_sample', 'n_sessions': len(fits),
                'skipped_sessions': len(skipped), 'factors': list(factors)}

    series = {factor: [fit['factor_returns'][factor] for fit in fits.values()]
              for factor in factors}
    summary = {}
    for factor, values in series.items():
        mean = statistics.fmean(values)
        deviation = statistics.stdev(values) if len(values) > 1 else 0.0
        standard_error = deviation / math.sqrt(len(values)) if len(values) else None
        summary[factor] = {
            'mean_factor_return': round(mean, 6),
            'std_error': round(standard_error, 6) if standard_error else None,
            't_stat': round(mean / standard_error, 3)
            if standard_error else None,
            'n_sessions': len(values),
        }
    return {
        'status': 'measured',
        'factors': list(factors),
        'n_sessions': len(fits),
        'skipped_sessions': len(skipped),
        'skipped_reason': (f'fewer than {MIN_NAMES_PER_FACTOR} names per factor '
                           f'in the cross-section'),
        'mean_r_squared': round(statistics.fmean(
            [fit['r_squared'] for fit in fits.values()
             if fit['r_squared'] is not None]), 4) if fits else None,
        'collinear_sessions': sum(1 for fit in fits.values() if fit['collinear']),
        'per_factor': summary,
        'per_session': {as_of: fit['factor_returns'] for as_of, fit in fits.items()},
        'method': ('Fama-MacBeth: cross-sectional regression per session, '
                   't-statistic over the time series of coefficients'),
    }


def perf_attrib(sessions, weights_by_session, factors) -> dict:
    """Split the portfolio return into common, specific, tilt and timing.

    `tilt + timing == common` by construction: tilt uses each factor's *average*
    exposure over the window and timing uses the deviation from it, so the two
    partition the same sum. The interesting number is usually their ratio — a
    book whose common return is nearly all tilt is being paid for a standing
    exposure, and one where timing dominates is being paid for moving it.
    """
    fitted = factor_returns(sessions, factors)
    if fitted.get('status') != 'measured':
        return fitted

    exposures, portfolio_returns, days = {}, {}, []
    for as_of, coefficients in fitted['per_session'].items():
        loadings, forward = sessions[as_of]
        weights = weights_by_session.get(as_of) or {}
        names = [name for name in loadings if name in weights and name in forward]
        if not names:
            continue
        total = sum(abs(weights[name]) for name in names)
        if total <= 0:
            continue
        normalised = {name: weights[name] / total for name in names}
        exposures[as_of] = {
            factor: sum(normalised[name] * float(loadings[name].get(factor, 0.0))
                        for name in names)
            for factor in factors
        }
        portfolio_returns[as_of] = sum(
            normalised[name] * float(forward[name]) for name in names)
        days.append(as_of)
    if len(days) < 3:
        return {'status': 'insufficient_sample',
                'reason': 'fewer than three sessions with both weights and loadings',
                'n_sessions': len(days)}

    average_exposure = {
        factor: statistics.fmean([exposures[day][factor] for day in days])
        for factor in factors
    }
    common, tilt, timing, specific = {}, {}, {}, {}
    for day in days:
        coefficients = fitted['per_session'][day]
        common[day] = sum(exposures[day][factor] * coefficients[factor]
                          for factor in factors)
        tilt[day] = sum(average_exposure[factor] * coefficients[factor]
                        for factor in factors)
        timing[day] = sum((exposures[day][factor] - average_exposure[factor])
                          * coefficients[factor] for factor in factors)
        specific[day] = portfolio_returns[day] - common[day]

    def _mean(mapping):
        return round(statistics.fmean([mapping[day] for day in days]), 6)

    return {
        'status': 'measured',
        'n_sessions': len(days),
        'first_session': days[0],
        'last_session': days[-1],
        'total_return_mean': _mean(portfolio_returns),
        'common_return_mean': _mean(common),
        'specific_return_mean': _mean(specific),
        'tilt_return_mean': _mean(tilt),
        'timing_return_mean': _mean(timing),
        'average_exposures': {factor: round(value, 6)
                              for factor, value in average_exposure.items()},
        'per_session': {
            'total': {day: round(portfolio_returns[day], 6) for day in days},
            'common': {day: round(common[day], 6) for day in days},
            'specific': {day: round(specific[day], 6) for day in days},
        },
        'factor_returns': fitted['per_factor'],
        'fit_quality': {
            'mean_r_squared': fitted['mean_r_squared'],
            'skipped_sessions': fitted['skipped_sessions'],
            'collinear_sessions': fitted['collinear_sessions'],
        },
        'identity': 'tilt + timing == common, by construction',
    }


def explain_composite(ranks, weights, *, cross_section=None, ticker=None) -> dict:
    """Exactly why one name's composite score is what it is.

    No approximation is involved and none is needed: the score is a weighted mean
    of the ranks present, so `w_f · rank_f / Σw` is each factor's contribution,
    and they sum to the score. A SHAP value here would estimate a number that can
    be written down.

    When the rest of the session's `cross_section` is supplied, each factor also
    gets an exact leave-one-out: the name's percentile recomputed with that
    factor dropped from *every* name's composite. That answers the question a
    contribution cannot — "would dropping quality change where this name sits" —
    and the two disagree whenever a factor is large for everybody.
    """
    available = {factor: float(value) for factor, value in ranks.items()
                 if factor in weights and value is not None}
    if not available:
        return {'status': 'no_ranks', 'ticker': ticker}
    total_weight = sum(float(weights[factor]) for factor in available)
    score = sum(float(weights[factor]) * available[factor]
                for factor in available) / total_weight
    contributions = {
        factor: round(float(weights[factor]) * available[factor] / total_weight, 6)
        for factor in available
    }

    def _score(rank_map, dropped=None):
        present = {factor: value for factor, value in rank_map.items()
                   if factor in weights and value is not None and factor != dropped}
        if not present:
            return None
        denominator = sum(float(weights[factor]) for factor in present)
        return sum(float(weights[factor]) * float(present[factor])
                   for factor in present) / denominator

    leave_one_out = {}
    if cross_section:
        def percentile(rank_map_by_name, dropped):
            scores = {name: _score(rank_map, dropped)
                      for name, rank_map in rank_map_by_name.items()}
            scores = {name: value for name, value in scores.items() if value is not None}
            if ticker not in scores or len(scores) < 2:
                return None
            below = sum(1 for value in scores.values() if value < scores[ticker])
            return below / (len(scores) - 1)

        base = percentile(cross_section, None)
        for factor in available:
            without = percentile(cross_section, factor)
            leave_one_out[factor] = {
                'percentile_without': round(without, 4) if without is not None else None,
                'percentile_change': round(without - base, 4)
                if (without is not None and base is not None) else None,
            }
        leave_one_out['_base_percentile'] = round(base, 4) if base is not None else None

    return {
        'status': 'measured',
        'ticker': ticker,
        'composite_score': round(score, 6),
        'contributions': dict(sorted(contributions.items(),
                                     key=lambda item: -abs(item[1]))),
        'contributions_sum': round(sum(contributions.values()), 6),
        'weight_covered': round(total_weight, 4),
        'missing_factors': sorted(set(weights) - set(available)),
        'leave_one_out': leave_one_out,
        'method': ('exact: the composite is linear in the ranks, so contributions '
                   'are computed rather than approximated'),
    }
