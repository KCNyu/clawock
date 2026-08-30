"""Three questions a volatility number does not answer.

`correlation_xray` publishes a 30-day volatility, a 95% VaR and an expected
shortfall. Those describe the middle of the distribution and one point in its
tail, under the window that happened to be sampled. The questions that actually
come up when a position is being sized are shaped differently:

* **"What has this book already survived?"** — `historical_worst_windows` replays
  the realised weights over the sample and reports the worst k-session stretches
  with their dates. Not a model: the loss the current allocation would have taken
  through the specific weeks that happened.
* **"If the big one halves, what happens to the rest?"** — `correlated_shock`
  propagates a move in named positions to the others through the covariance,
  `E[r_rest | r_shocked] = Σ_rs Σ_ss⁻¹ shock`. Shocking a name and holding the
  rest still is the mistake this exists to prevent: in a book whose top two
  eigenvalues carry most of the variance, the rest do not hold still.
* **"What is the most likely way to lose 15%?"** — `reverse_stress` inverts the
  question. Among all return vectors producing a given portfolio loss, it returns
  the one with the smallest Mahalanobis distance, i.e. the *least improbable*
  one: `r* = -loss · Σw / (wᵀΣw)`. That vector is the scenario worth writing down,
  because it is the shape the market would most plausibly take to get there — and
  it is usually not "everything falls equally".

Every function takes a covariance the caller chose. Feed it a shrunk one: at
this book's sample size, three of ten eigenvalues sit essentially at zero, and
`Σ_ss⁻¹` on the sample matrix would put the whole shock into whichever direction
is purest estimation error.
"""
from __future__ import annotations

import numpy as np


def _weights(vector) -> np.ndarray:
    array = np.asarray(vector, dtype=float)
    total = array.sum()
    if total <= 0:
        raise ValueError('weights must sum to a positive number')
    return array / total


def historical_worst_windows(returns, weights, *, sessions=(1, 5, 20),
                             dates=None, top=3) -> dict:
    """Worst k-session realised losses for the current allocation.

    Weights are held fixed at today's — this is "what would this book have done
    through those weeks", not a replay of a rebalancing history it did not have.
    The distinction matters and is stated in the payload rather than assumed.
    """
    matrix = np.asarray(returns, dtype=float)
    vector = _weights(weights)
    if matrix.ndim != 2 or matrix.shape[1] != len(vector):
        raise ValueError('returns and weights disagree on the number of names')
    portfolio = matrix @ vector
    dates = list(dates or range(len(portfolio)))
    out = {}
    for window in sessions:
        if len(portfolio) < window:
            continue
        cumulative = [
            (float(np.prod(1 + portfolio[start:start + window]) - 1), start)
            for start in range(len(portfolio) - window + 1)
        ]
        cumulative.sort()
        out[f'worst_{window}_session'] = [
            {
                'return': round(value, 6),
                'from': str(dates[start]),
                'to': str(dates[min(start + window - 1, len(dates) - 1)]),
            }
            for value, start in cumulative[:top]
        ]
    return {
        'status': 'measured',
        'n_sessions': len(portfolio),
        'basis': 'current weights held fixed through past returns; not a rebalancing replay',
        **out,
    }


def correlated_shock(covariance, weights, shocks, names) -> dict:
    """Propagate a shock in named positions to the rest through the covariance.

    `shocks` maps a name to its return under the scenario. The others are not
    held still: their conditional expectation is
    `Σ_rest,shocked @ pinv(Σ_shocked,shocked) @ shock`.

    The unconditional version — shock one name, freeze the others — understates
    the loss in exactly the books where it matters, because a concentrated book
    is concentrated *through* correlation.
    """
    matrix = np.asarray(covariance, dtype=float)
    names = list(names)
    vector = _weights(weights)
    index_of = {str(name): position for position, name in enumerate(names)}
    shocked = [index_of[str(name)] for name in shocks if str(name) in index_of]
    if not shocked:
        return {'status': 'no_named_position', 'names': list(shocks)}
    rest = [position for position in range(len(names)) if position not in set(shocked)]
    shock_vector = np.array([float(shocks[str(names[position])])
                             for position in shocked])

    moves = np.zeros(len(names))
    moves[shocked] = shock_vector
    if rest:
        block_ss = matrix[np.ix_(shocked, shocked)]
        block_rs = matrix[np.ix_(rest, shocked)]
        moves[rest] = block_rs @ np.linalg.pinv(block_ss) @ shock_vector

    naive = float(sum(vector[position] * moves[position] for position in shocked))
    return {
        'status': 'measured',
        'shocked': {str(names[position]): round(float(moves[position]), 6)
                    for position in shocked},
        'implied': {str(names[position]): round(float(moves[position]), 6)
                    for position in rest},
        'portfolio_return': round(float(vector @ moves), 6),
        'portfolio_return_if_others_held_still': round(naive, 6),
        'contagion_share': round(
            float(1 - naive / (vector @ moves)), 4) if abs(vector @ moves) > 0 else None,
        'method': 'conditional expectation under the supplied covariance',
    }


def reverse_stress(covariance, weights, loss, names) -> dict:
    """The least improbable return vector that produces a given portfolio loss.

    Among all `r` with `wᵀr = -loss`, the one minimising `rᵀΣ⁻¹r` is
    `r* = -loss · Σw / (wᵀΣw)`, which needs no inversion. Its Mahalanobis
    distance is `loss / sqrt(wᵀΣw)` — the number of portfolio standard deviations
    the scenario is away, and the honest way to say how far-fetched it is.

    The output is deliberately per-name: the useful part is that the scenario is
    almost never "everything falls equally", and seeing which name has to move
    most is what turns a limit into a decision.
    """
    matrix = np.asarray(covariance, dtype=float)
    vector = _weights(weights)
    names = list(names)
    variance = float(vector @ matrix @ vector)
    if variance <= 0:
        return {'status': 'degenerate', 'reason': 'portfolio variance is zero'}
    moves = -abs(float(loss)) * (matrix @ vector) / variance
    return {
        'status': 'measured',
        'target_loss': round(-abs(float(loss)), 6),
        'moves': {str(names[index]): round(float(moves[index]), 6)
                  for index in range(len(names))},
        'largest_mover': str(names[int(np.argmin(moves))]),
        'sigmas_away': round(abs(float(loss)) / float(np.sqrt(variance)), 3),
        'method': ('minimum-Mahalanobis scenario reaching the loss; the least '
                   'improbable shape, not the worst one'),
    }


def scenario_suite(covariance, weights, names, *, returns=None, dates=None,
                   shock_top_position=-0.20, losses=(0.10, 0.20)) -> dict:
    """The three questions above, run together on one covariance.

    The top position is shocked because that is the scenario a concentrated book
    is actually exposed to; `shock_top_position` is the size of that move and is
    recorded rather than hidden, so a reader can tell a -20% assumption from a
    -50% one.
    """
    vector = _weights(weights)
    names = list(names)
    top = str(names[int(np.argmax(vector))])
    report = {
        'top_position': top,
        'top_position_weight': round(float(vector.max()), 6),
        'correlated_shock': correlated_shock(
            covariance, vector, {top: shock_top_position}, names),
        'reverse_stress': {
            f'loss_{int(loss * 100)}pct': reverse_stress(
                covariance, vector, loss, names)
            for loss in losses
        },
    }
    if returns is not None:
        report['historical'] = historical_worst_windows(
            returns, vector, dates=dates)
    return report
