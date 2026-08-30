"""Regimes as a probability with a duration, not a label that flips.

What is here today
------------------
`lev_regime` classifies the market with two hard rules — close against its
200-day mean, 20-day volatility against a cap — and maps the result to a
leverage multiplier. It is pre-registered, it is legible, and `validate-regime-dial`
has already measured what it is worth: purged CSCV puts its PBO at 0.21 and the
permutation test of its *timing* against the returns comes back p = 0.92. The
dial reduces drawdown because it spends time out of the market, not because it
knows when to.

What it cannot express is anything between the two sides of a threshold. On the
day HSTECH closes 0.1% below its 200-day mean the dial goes from full leverage to
half, and the day it closes 0.1% above it goes back. A regime that is 55% likely
and one that is 99% likely produce the same decision, and "how long has this
state historically lasted" is not a question the dial has a shape for.

What this adds
--------------
A Gaussian hidden Markov model over a small observation vector, fitted by
Baum-Welch. It answers three things the dial cannot:

* `P(state | history up to today)` — a posterior, so a marginal regime reads as
  marginal;
* the transition matrix, and from it `1 / (1 - a_ii)` — the expected remaining
  duration of the state the market is in;
* the state characteristics — each hidden state's mean return and volatility —
  so "risk-off" is a description of the data rather than a name assigned to it.

The look-ahead that this kind of model invites
----------------------------------------------
Almost every published HMM regime chart is drawn with **smoothed** posteriors
`P(state_t | all observations)`, which include the future. A regime series built
that way identifies the crash of March 2020 on the first of March, and any
strategy backtested against it prints a wonderful number that could not have been
traded. This module computes smoothed posteriors — they are the right thing for
*describing* history — and `walk_forward_states` refits on an expanding window
and keeps only the **filtered** posterior `P(state_t | observations up to t)`,
which is the only series that may be scored. The two are returned under names
that cannot be confused, and the evaluation path takes the filtered one.

Nothing here changes a leverage decision. It is a measurement, and the last
function in the file is the one that says whether the measurement earned
anything: the same permutation test the existing dial had to pass.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

#: EM is not convex. Restarts are seeded and fixed so a rerun of the same data
#: gives the same model — a regime model whose states renumber between runs
#: cannot be compared with yesterday's.
RESTART_SEEDS = (11, 29, 47, 83, 101)

MIN_OBSERVATIONS = 250


class GaussianHMM:
    """Diagonal-covariance Gaussian HMM, fitted by Baum-Welch in log space.

    Diagonal rather than full covariance on purpose: a full covariance for `k`
    states over `d` features costs `k·d(d+1)/2` parameters, and with the feature
    vector used here it would spend more of the sample estimating correlations
    between the features than transitions between the states.
    """

    def __init__(self, n_states: int, n_features: int):
        self.n_states = n_states
        self.n_features = n_features
        self.start = np.full(n_states, 1.0 / n_states)
        self.transitions = np.full((n_states, n_states), 1.0 / n_states)
        self.means = np.zeros((n_states, n_features))
        self.variances = np.ones((n_states, n_features))
        self.log_likelihood = -np.inf
        self.n_iterations = 0

    # -- emission ---------------------------------------------------------
    def _log_emission(self, observations: np.ndarray) -> np.ndarray:
        """log N(x_t | mu_k, diag(var_k)) for every t, k."""
        difference = observations[:, None, :] - self.means[None, :, :]
        return -0.5 * (
            np.sum(np.log(2 * np.pi * self.variances)[None, :, :], axis=2)
            + np.sum(difference ** 2 / self.variances[None, :, :], axis=2))

    # -- inference --------------------------------------------------------
    def _forward(self, log_emission: np.ndarray):
        n = len(log_emission)
        log_alpha = np.zeros((n, self.n_states))
        log_alpha[0] = np.log(self.start + 1e-300) + log_emission[0]
        log_transitions = np.log(self.transitions + 1e-300)
        for t in range(1, n):
            log_alpha[t] = log_emission[t] + _logsumexp(
                log_alpha[t - 1][:, None] + log_transitions, axis=0)
        return log_alpha, float(_logsumexp(log_alpha[-1], axis=0))

    def _backward(self, log_emission: np.ndarray) -> np.ndarray:
        n = len(log_emission)
        log_beta = np.zeros((n, self.n_states))
        log_transitions = np.log(self.transitions + 1e-300)
        for t in range(n - 2, -1, -1):
            log_beta[t] = _logsumexp(
                log_transitions + (log_emission[t + 1] + log_beta[t + 1])[None, :],
                axis=1)
        return log_beta

    def filtered(self, observations: np.ndarray) -> np.ndarray:
        """`P(state_t | observations up to and including t)`.

        The only posterior that may be scored against a forward return. Its
        value at `t` uses nothing after `t`.
        """
        log_alpha, _ = self._forward(self._log_emission(observations))
        return np.exp(log_alpha - _logsumexp(log_alpha, axis=1)[:, None])

    def smoothed(self, observations: np.ndarray) -> np.ndarray:
        """`P(state_t | all observations)`. For describing history only.

        Every value in this array contains the future. It is the right series
        for "what was going on in July" and the wrong one for anything that gets
        multiplied by a forward return.
        """
        log_emission = self._log_emission(observations)
        log_alpha, total = self._forward(log_emission)
        log_beta = self._backward(log_emission)
        log_gamma = log_alpha + log_beta - total
        return np.exp(log_gamma - _logsumexp(log_gamma, axis=1)[:, None])

    def viterbi(self, observations: np.ndarray) -> np.ndarray:
        log_emission = self._log_emission(observations)
        n = len(log_emission)
        log_transitions = np.log(self.transitions + 1e-300)
        score = np.log(self.start + 1e-300) + log_emission[0]
        backpointer = np.zeros((n, self.n_states), dtype=int)
        for t in range(1, n):
            candidates = score[:, None] + log_transitions
            backpointer[t] = np.argmax(candidates, axis=0)
            score = np.max(candidates, axis=0) + log_emission[t]
        path = np.zeros(n, dtype=int)
        path[-1] = int(np.argmax(score))
        for t in range(n - 2, -1, -1):
            path[t] = backpointer[t + 1, path[t + 1]]
        return path

    # -- fitting ----------------------------------------------------------
    def fit(self, observations: np.ndarray, *, max_iterations=150, tolerance=1e-5,
            seed=11):
        rng = np.random.default_rng(seed)
        n, d = observations.shape
        # Initialise from a random partition rather than from noise: a state
        # whose mean starts far outside the data never receives responsibility
        # and the model silently fits with fewer states than it claims.
        assignment = rng.integers(0, self.n_states, size=n)
        for state in range(self.n_states):
            rows = observations[assignment == state]
            if len(rows) < 2:
                rows = observations
            self.means[state] = rows.mean(axis=0)
            self.variances[state] = np.maximum(rows.var(axis=0), 1e-8)
        self.start = np.full(self.n_states, 1.0 / self.n_states)
        self.transitions = np.full(
            (self.n_states, self.n_states), 0.1 / max(1, self.n_states - 1))
        np.fill_diagonal(self.transitions, 0.9)

        previous = -np.inf
        for iteration in range(max_iterations):
            log_emission = self._log_emission(observations)
            log_alpha, total = self._forward(log_emission)
            log_beta = self._backward(log_emission)
            log_gamma = log_alpha + log_beta - total
            gamma = np.exp(log_gamma - _logsumexp(log_gamma, axis=1)[:, None])

            log_transitions = np.log(self.transitions + 1e-300)
            xi = np.zeros((self.n_states, self.n_states))
            for t in range(n - 1):
                block = (log_alpha[t][:, None] + log_transitions
                         + (log_emission[t + 1] + log_beta[t + 1])[None, :] - total)
                xi += np.exp(block)

            self.start = gamma[0] / gamma[0].sum()
            row_sums = xi.sum(axis=1, keepdims=True)
            self.transitions = np.where(row_sums > 0, xi / np.maximum(row_sums, 1e-300),
                                        1.0 / self.n_states)
            weights = gamma.sum(axis=0)
            for state in range(self.n_states):
                weight = max(weights[state], 1e-300)
                self.means[state] = (gamma[:, state] @ observations) / weight
                difference = observations - self.means[state]
                self.variances[state] = np.maximum(
                    (gamma[:, state] @ (difference ** 2)) / weight, 1e-10)

            self.n_iterations = iteration + 1
            self.log_likelihood = total
            if abs(total - previous) < tolerance:
                break
            previous = total
        return self

    # -- reporting --------------------------------------------------------
    def n_parameters(self) -> int:
        k, d = self.n_states, self.n_features
        return (k - 1) + k * (k - 1) + 2 * k * d

    def bic(self, observations: np.ndarray) -> float:
        return (self.n_parameters() * math.log(len(observations))
                - 2 * self.log_likelihood)

    def reorder_by_mean_return(self) -> "GaussianHMM":
        """Renumber the states low-to-high by mean of the first feature.

        EM numbers states by whichever random partition it started from, so
        state 2 in today's fit and state 2 in yesterday's are unrelated. Every
        consumer below needs one canonical order — the walk-forward series that
        must not relabel at each refit, the exposure map whose whole meaning is
        "probability in the worst states", the printed table — and mean return
        is a total order over the states that does not depend on the run.
        """
        order = np.argsort(self.means[:, 0])
        self.start = self.start[order]
        self.transitions = self.transitions[np.ix_(order, order)]
        self.means = self.means[order]
        self.variances = self.variances[order]
        return self

    def expected_durations(self) -> list[float]:
        """`1 / (1 - a_ii)`: how long the chain stays put once it arrives."""
        diagonal = np.clip(np.diag(self.transitions), 0.0, 1 - 1e-9)
        return [round(float(1.0 / (1.0 - value)), 2) for value in diagonal]

    def stationary_distribution(self) -> list[float]:
        values, vectors = np.linalg.eig(self.transitions.T)
        index = int(np.argmin(np.abs(values - 1.0)))
        vector = np.real(vectors[:, index])
        vector = np.abs(vector)
        return [round(float(value), 6) for value in vector / vector.sum()]


def _logsumexp(array: np.ndarray, axis: int) -> np.ndarray:
    peak = np.max(array, axis=axis, keepdims=True)
    peak = np.where(np.isfinite(peak), peak, 0.0)
    return (peak + np.log(np.sum(np.exp(array - peak), axis=axis, keepdims=True))
            ).squeeze(axis)


def fit_best(observations, n_states: int, *, seeds=RESTART_SEEDS) -> GaussianHMM:
    """Baum-Welch from several fixed starts; keep the highest likelihood.

    EM on a hidden Markov model is not convex and a single start lands in a
    local optimum often enough that the state count would look like the thing
    that changed. The seeds are fixed so the same data gives the same model.
    """
    observations = np.asarray(observations, dtype=float)
    best = None
    for seed in seeds:
        model = GaussianHMM(n_states, observations.shape[1]).fit(
            observations, seed=seed)
        if best is None or model.log_likelihood > best.log_likelihood:
            best = model
    return best.reorder_by_mean_return()


def select_states(observations, candidates=(2, 3, 4, 5), *,
                  seeds=RESTART_SEEDS) -> dict:
    """Choose the state count by BIC, and publish the whole curve.

    The curve matters more than the winner. A BIC that is nearly flat across two
    and five states means the data does not distinguish them, and reporting only
    the argmin would present a search result as a discovery.
    """
    observations = np.asarray(observations, dtype=float)
    scores = {}
    models = {}
    for count in candidates:
        model = fit_best(observations, count, seeds=seeds)
        models[count] = model
        scores[count] = round(model.bic(observations), 3)
    best = min(scores, key=lambda count: scores[count])
    ordered = sorted(scores.values())
    return {
        'n_states': best,
        'bic': scores,
        'bic_margin': round(ordered[1] - ordered[0], 3) if len(ordered) > 1 else None,
        'model': models[best],
        'reading': ('a small BIC margin means the data does not distinguish the '
                    'state counts; the winner is then a search result, not a '
                    'discovery'),
    }


def observation_matrix(closes, *, volatility_window=20):
    """The feature vector: one-day return and trailing realised volatility.

    Two features, deliberately. Every extra feature is `2k` more parameters and
    this is being fitted to about fourteen hundred daily bars of one index. The
    pair is what the existing dial already uses — direction and volatility —
    which also makes the comparison between them a comparison of *shape*, not of
    inputs.
    """
    closes = [float(value) for value in closes]
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    rows, index = [], []
    for position in range(volatility_window, len(returns)):
        window = returns[position - volatility_window:position]
        rows.append([returns[position], float(np.std(window))])
        index.append(position + 1)
    return np.array(rows, dtype=float), index


def describe_states(model: GaussianHMM, observations: np.ndarray,
                    posteriors: np.ndarray) -> list[dict]:
    """What each hidden state actually is, in the units of the data."""
    assignment = np.argmax(posteriors, axis=1)
    out = []
    for state in range(model.n_states):
        rows = observations[assignment == state]
        out.append({
            'state': state,
            'share_of_sessions': round(float((assignment == state).mean()), 4),
            'mean_daily_return': round(float(rows[:, 0].mean()), 6)
            if len(rows) else None,
            'mean_trailing_volatility': round(float(rows[:, 1].mean()), 6)
            if len(rows) else None,
            'annualised_volatility': round(
                float(rows[:, 0].std() * math.sqrt(252)), 4) if len(rows) > 1 else None,
            'expected_duration_sessions': model.expected_durations()[state],
        })
    out.sort(key=lambda row: (row['mean_daily_return'] or 0.0))
    return out


def walk_forward_states(observations, *, n_states, warmup=250, step=20,
                        seeds=RESTART_SEEDS):
    """Refit on an expanding window; keep only what was knowable at each point.

    Two separate look-aheads are closed here and both are easy to leave open:

    * the model is **refitted** every `step` sessions on data up to that point,
      so a regime definition learned from 2026 is never used to label 2025;
    * only the **filtered** posterior is kept, so no label contains an
      observation later than itself.

    State identity comes from `fit_best`, which returns every model with its
    states sorted low-to-high by mean return. That sort is a total order and
    needs no reference to the previous fit: column `k` means "the k-th
    lowest-return state" in every refit. Without it EM would renumber freely
    and the series would flip labels at each refit for reasons that have nothing
    to do with the market.
    """
    observations = np.asarray(observations, dtype=float)
    n = len(observations)
    if n < warmup + step:
        return None
    out = np.full((n, n_states), np.nan)
    n_refits = 0
    for end in range(warmup, n, step):
        model = fit_best(observations[:end], n_states, seeds=seeds)
        n_refits += 1
        window_end = min(end + step, n)
        # `filtered` over the prefix ending at `window_end`: row t of it uses
        # nothing after t, and the model behind it saw nothing after `end`.
        filtered = model.filtered(observations[:window_end])
        out[end:window_end] = filtered[end:window_end]
    valid = ~np.isnan(out[:, 0])
    return {'posteriors': out, 'valid': valid, 'n_refits': n_refits,
            'warmup': warmup, 'step': step,
            'ordering': 'states sorted by mean daily return, low to high'}


# ---------------------------------------------------------------------------
# Evaluation: the same gate the existing dial had to pass
# ---------------------------------------------------------------------------

def exposure_from_posteriors(posteriors, valid, *, risk_off_states=1,
                             base=2.0, floor=0.5):
    """Map `P(worst states)` to an exposure multiplier, linearly.

    Linear rather than thresholded on purpose: a threshold would reproduce the
    dial's own shape and the comparison would then be between two spellings of
    the same rule. The point of a posterior is that 55% and 99% are different
    numbers, so the exposure is `base` scaled down toward `floor` in proportion
    to how much probability sits in the low-return states.

    `risk_off_states` counts from the bottom of the return ordering that
    `walk_forward_states` imposes, so state 0 is always the worst one.
    """
    exposure = []
    for index in range(len(posteriors)):
        if not valid[index]:
            exposure.append(None)
            continue
        risk_off = float(posteriors[index][:risk_off_states].sum())
        exposure.append(base - (base - floor) * risk_off)
    return exposure


def evaluate_against_dial(closes, dates, *, n_states=None, warmup=250, step=20,
                          permutations=2000, floor=0.5,
                          seeds=RESTART_SEEDS) -> dict:
    """Fit, walk forward, and put the result through the dial's own test.

    This is the part that decides whether the model is worth anything. The
    production dial has already been measured: purged CSCV puts its PBO at 0.21
    and its circular-shift permutation p-value at 0.92 — it reduces drawdown by
    spending time out of the market, not by knowing when to. A richer model has
    to beat that same test on the same data with the same null, or the honest
    conclusion is that a posterior with a duration is a better *description* of
    the market and not better *timing*.

    Only the filtered, walk-forward posteriors reach the exposure path. The
    smoothed ones are returned separately and are for reading history.
    """
    from clawock.evaluation import regime_validation as rv

    observations, index = observation_matrix(closes)
    if len(observations) < MIN_OBSERVATIONS:
        return {'status': 'insufficient_sample', 'n_observations': len(observations)}

    selection = select_states(observations, seeds=seeds) if n_states is None else {
        'n_states': n_states, 'bic': None, 'bic_margin': None,
        'model': fit_best(observations, n_states, seeds=seeds)}
    model = selection['model']
    states = selection['n_states']

    walk = walk_forward_states(observations, n_states=states, warmup=warmup,
                               step=step, seeds=seeds)
    if walk is None:
        return {'status': 'insufficient_sample', 'n_observations': len(observations)}

    returns = [closes[position] / closes[position - 1] - 1 for position in index]
    exposure = exposure_from_posteriors(walk['posteriors'], walk['valid'],
                                        floor=floor)
    aligned = [(ret, exp) for ret, exp in zip(returns, exposure) if exp is not None]
    scored_returns = [row[0] for row in aligned]
    scored_exposure = [row[1] for row in aligned]

    summary = rv.summarize(scored_returns, scored_exposure)
    permutation = rv.permutation_test(
        scored_returns, scored_exposure, permutations=permutations)

    # The production dial on exactly the same scored rows, so the comparison is
    # not between two different samples wearing the same dates.
    #
    # `exposure_path` returns a *triple* `(returns, exposure, tiers)`. Slicing
    # the call directly sliced the tuple, which handed `summarize` an empty
    # exposure and printed a dial with a total return of exactly 0.0 and a
    # maximum drawdown of exactly 0.0 — a comparison arm that looked like a
    # perfect defensive record and was an unpacking bug.
    _, dial_path, _ = rv.exposure_path(closes)
    scored_positions = [position for position, value
                        in zip(index, exposure) if value is not None]
    # `dial_path[k]` is the leverage for `closes[k + 1]`, and `index` holds
    # positions into `closes`.
    dial_exposure = [dial_path[position - 1] for position in scored_positions
                     if 0 < position <= len(dial_path)]
    if len(dial_exposure) == len(scored_returns):
        dial_summary = rv.summarize(scored_returns, dial_exposure)
        dial_permutation = rv.permutation_test(
            scored_returns, dial_exposure, permutations=permutations)
    else:
        dial_summary = {'status': 'unaligned',
                        'reason': f'{len(dial_exposure)} dial rows against '
                                  f'{len(scored_returns)} scored returns'}
        dial_permutation = dial_summary

    smoothed = model.smoothed(observations)
    return {
        'status': 'measured',
        'n_states': states,
        'bic': selection.get('bic'),
        'bic_margin': selection.get('bic_margin'),
        'n_observations': len(observations),
        'n_scored_sessions': len(aligned),
        # The dial's red tier reaches 0.0 and this floor does not, so the two
        # arms do not have the same reachable range unless it is set to 0. It is
        # a parameter rather than a constant precisely so the asymmetry is
        # something a reader can see and change.
        'exposure_floor': floor,
        'walk_forward': {key: walk[key] for key in
                         ('n_refits', 'warmup', 'step', 'ordering')},
        'states': describe_states(model, observations, smoothed),
        'transition_matrix': [[round(float(value), 4) for value in row]
                              for row in model.transitions],
        'expected_durations_sessions': model.expected_durations(),
        'stationary_distribution': model.stationary_distribution(),
        'current_posterior': [round(float(value), 4)
                              for value in model.filtered(observations)[-1]],
        'hmm_exposure': summary,
        'hmm_permutation': permutation,
        'production_dial_exposure': dial_summary,
        'production_dial_permutation': dial_permutation,
        'discipline': (
            'filtered walk-forward posteriors only; the smoothed series contains '
            'the future and is used for describing states, never for scoring'),
        'reading': (
            'a lower p-value than the production dial is the only result that '
            'would justify changing anything; equal or worse means the model is '
            'a better description of the market and not better timing'),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(result: dict) -> None:
    if result.get('status') != 'measured':
        print(f"not measured: {result.get('status')} "
              f"({result.get('n_observations')} observations)", file=sys.stderr)
        return

    print(f"{result['n_observations']} observations, "
          f"{result['n_scored_sessions']} scored sessions, "
          f"{result['n_states']} states\n")

    if result.get('bic'):
        curve = '  '.join(f'{count}:{value:,.0f}'
                          for count, value in sorted(result['bic'].items()))
        print(f'--- state count by BIC (lower is better) ---\n  {curve}')
        margin = result.get('bic_margin')
        if margin is not None:
            print(f'  margin over the runner-up: {margin:,.1f}')
        print()

    print('--- what each state is, in the units of the data ---')
    for row in result['states']:
        print(f"  state {row['state']}  "
              f"{row['share_of_sessions'] * 100:5.1f}% of sessions  "
              f"mean {row['mean_daily_return'] * 100:+.3f}%/session  "
              f"ann.vol {(row['annualised_volatility'] or 0) * 100:5.1f}%  "
              f"stays {row['expected_duration_sessions']:.0f} sessions")

    posterior = '  '.join(f'{index}:{value:.2f}'
                          for index, value in enumerate(result['current_posterior']))
    print(f"\n  today: {posterior}   "
          f"(states low-to-high by mean return)")

    print('\n--- does it time anything the production dial does not? ---')
    for label, summary, permutation in (
            ('hmm posterior', result['hmm_exposure'], result['hmm_permutation']),
            ('production dial', result['production_dial_exposure'],
             result['production_dial_permutation'])):
        if summary.get('status') == 'unaligned':
            print(f"  {label:<16} unaligned: {summary['reason']}")
            continue
        print(f"  {label:<16} "
              f"total {summary['dial_total_return'] * 100:+7.1f}%  "
              f"maxDD {summary['dial_max_drawdown'] * 100:6.1f}%  "
              f"p(drawdown) = {permutation['p_value_drawdown']:.3f}")
    print(f"\n  {result['reading']}")


def main(argv=None) -> int:
    from clawock.evaluation import regime_validation as rv

    ap = argparse.ArgumentParser(prog='clawock validate-regime-hmm',
                                 description=__doc__)
    ap.add_argument('--states', type=int, default=None,
                    help='fix the state count; default selects it by BIC')
    ap.add_argument('--warmup', type=int, default=250,
                    help='sessions before the first walk-forward label')
    ap.add_argument('--step', type=int, default=20,
                    help='sessions between refits')
    ap.add_argument('--permutations', type=int, default=2000)
    ap.add_argument('--restarts', type=int, default=len(RESTART_SEEDS),
                    help='EM restarts per fit; fewer is faster and more likely '
                         'to report a local optimum as the model')
    ap.add_argument('--floor', type=float, default=0.5,
                    help='exposure at full risk-off probability; the production '
                         'dial reaches 0.0, so --floor 0 equalises the range')
    ap.add_argument('--json', action='store_true',
                    help='emit the full result instead of the report')
    ap.add_argument('--no-card', action='store_true',
                    help='skip writing a run card (for ad-hoc exploration)')
    args = ap.parse_args(argv)

    data = rv.fetch_hstech()
    if len(data) < 400:
        print(f'HSTECH fetch returned {len(data)} bars — not enough to fit',
              file=sys.stderr)
        return 1
    dates = [row[0] for row in data]
    closes = [row[1] for row in data]
    print(f'HSTECH {len(closes)} bars  {dates[0]} → {dates[-1]}\n')

    result = evaluate_against_dial(
        closes, dates, n_states=args.states, warmup=args.warmup, step=args.step,
        permutations=args.permutations, floor=args.floor,
        seeds=RESTART_SEEDS[:max(1, args.restarts)])

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=float))
    else:
        _print_report(result)
    if result.get('status') != 'measured':
        return 1

    if not args.no_card:
        from clawock.evidence import run_card
        card = run_card.record(
            'regime_hmm_validation',
            params={'n_states': result['n_states'],
                    'state_selection': 'BIC' if args.states is None else 'fixed',
                    'warmup': args.warmup, 'step': args.step,
                    'permutations': args.permutations,
                    'restart_seeds': list(RESTART_SEEDS[:max(1, args.restarts)]),
                    'features': ['one-day return', 'trailing 20-session volatility'],
                    'exposure_map': 'linear in P(lowest-return state), '
                                    f'2.0 -> {args.floor}'},
            inputs=[{'symbol': 'hkHSTECH',
                     'source': 'tencent kline (day, unadjusted)',
                     'bars': len(closes), 'first_session': dates[0],
                     'last_session': dates[-1],
                     'digest': run_card.series_digest(data)}],
            metrics={key: result[key] for key in (
                'n_observations', 'n_scored_sessions', 'exposure_floor',
                'bic', 'bic_margin',
                'walk_forward', 'states', 'transition_matrix',
                'expected_durations_sessions', 'stationary_distribution',
                'current_posterior', 'hmm_exposure', 'hmm_permutation',
                'production_dial_exposure', 'production_dial_permutation')},
            code_files=[__file__, Path(rv.__file__)],
            notes=['only filtered walk-forward posteriors are scored; the '
                   'smoothed series contains the future and is used to describe '
                   'the states, never to time anything',
                   'the production dial arm is scored on exactly the same rows '
                   'as the HMM arm, so the comparison is not two samples '
                   'wearing the same dates',
                   'nothing here changes a live leverage decision — this is a '
                   'measurement of whether a posterior with a duration times '
                   'better than two thresholds'],
        )
        print(f'\nrun card: {card.relative_to(rv.WS)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
