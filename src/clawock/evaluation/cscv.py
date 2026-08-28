"""Combinatorially symmetric cross-validation: how much of a fit is selection.

The gap this closes
-------------------
`regime_validation` already refuses the weakest form of evidence — it walks the
dial forward, permutes its timing against the returns, and prints the threshold
surface so a knife-edge fit is visible. What none of those answer is the
question that actually decides whether a chosen threshold means anything:
**16 configurations were searched, so how often does the one that looks best
in-sample turn out to be below-median out-of-sample?**

That is the probability of backtest overfitting (Bailey, Borwein, López de Prado
and Zhu, *The Probability of Backtest Overfitting*, 2015). Its estimator is CSCV:
split the sample into `S` contiguous groups, take every way of choosing `S/2` of
them as the out-of-sample half, pick the best configuration on the in-sample
half, and record where that configuration lands among the out-of-sample scores.
PBO is the share of splits where it lands in the bottom half. A single
walk-forward pass reports one such draw; CSCV reports the distribution, which is
why a strategy with a real edge and one that was merely selected can produce the
same walk-forward table and different PBO.

Two properties of the estimator matter for reading its output:

* it is **symmetric** — every group serves in both halves across the splits, so
  the result does not depend on which end of the sample the test window fell on;
* it measures **selection**, not skill. A single pre-registered configuration
  has nothing to overfit, and this module refuses to report a PBO for one rather
  than printing 0.0 as though that were evidence.

Purging and the embargo
-----------------------
Plain CSCV assumes observations are independent across the split boundary. They
are not here: a trailing 200-day mean at the first bar of a test group is built
from bars sitting in a training group, and a forward-looking label spans the
boundary in the other direction. `purge` drops the training observations within
`embargo` bars on either side of every test block — López de Prado's purging and
embargo, applied in both directions because these features look back and these
labels look forward.

The estimator is separated from the thing being estimated on purpose: it takes a
matrix of per-observation values and a scoring function, so the regime dial, an
add-side rule, or any future evaluator can be measured by the same code rather
than by a second copy of the arithmetic.
"""
from __future__ import annotations

import math
from itertools import combinations

#: Below this, the estimate is noise about noise. With four groups there are six
#: splits and the rank of the selected configuration can take too few values for
#: the share below the median to mean anything.
MIN_GROUPS = 6

#: A configuration set this small cannot express a selection effect: with one
#: configuration there is no choice to overfit, and with two the out-of-sample
#: rank is a coin flip by construction.
MIN_CONFIGS = 3


def contiguous_groups(n_observations: int, n_groups: int) -> list[list[int]]:
    """Split observation indices into `n_groups` contiguous, near-equal blocks.

    Contiguous rather than interleaved: the leakage this design fights lives in
    time-adjacent bars, and interleaving would put a training bar next to every
    test bar by construction.
    """
    if n_groups <= 0 or n_observations <= 0:
        return []
    edges = [round(n_observations * k / n_groups) for k in range(n_groups + 1)]
    return [list(range(edges[k], edges[k + 1])) for k in range(n_groups)]


def purge(train: list[int], test: list[int], embargo: int) -> list[int]:
    """Drop training observations within `embargo` bars of any test observation.

    Both directions, because both leaks are real: a trailing feature window
    reaches backwards out of the test block into training bars, and a forward
    label reaches forwards out of it. An embargo on one side only would leave
    the other one open while looking rigorous.
    """
    if embargo <= 0 or not test:
        return list(train)
    blocked = set()
    start, previous = test[0], test[0]
    for index in test[1:] + [None]:
        if index is not None and index == previous + 1:
            previous = index
            continue
        blocked.update(range(start - embargo, previous + embargo + 1))
        if index is None:
            break
        start = previous = index
    return [index for index in train if index not in blocked]


def splits(n_groups: int, n_test_groups: int | None = None):
    """Every combinatorially symmetric (train, test) partition of the groups."""
    if n_test_groups is None:
        n_test_groups = n_groups // 2
    for test in combinations(range(n_groups), n_test_groups):
        chosen = set(test)
        yield [g for g in range(n_groups) if g not in chosen], list(test)


def probability_of_backtest_overfitting(
        matrix, score, *, n_groups: int = 8, n_test_groups: int | None = None,
        embargo: int = 0, higher_is_better: bool = True) -> dict:
    """PBO over a per-observation value matrix.

    ``matrix`` is indexed ``matrix[observation][configuration]`` and its cells
    may be any value the scorer understands (a return, a tuple of strategy and
    benchmark returns, …). ``score`` maps the selected cells of one
    configuration to a scalar.

    Returns the estimate plus the material to argue with it: the logit
    distribution, the out-of-sample scores of each in-sample winner, and how
    much performance the selection lost between the halves. When the sample
    cannot support the estimator it returns ``status: insufficient_sample`` and
    no number — a PBO computed from four splits would be a decoration with a
    citation attached.
    """
    n_observations = len(matrix)
    n_configs = len(matrix[0]) if n_observations else 0
    if n_test_groups is None:
        n_test_groups = n_groups // 2
    reasons = []
    if n_groups < MIN_GROUPS:
        reasons.append(f'{n_groups} groups is below the {MIN_GROUPS}-group floor')
    if n_configs < MIN_CONFIGS:
        reasons.append(
            f'{n_configs} configuration(s) cannot express a selection effect '
            f'(floor {MIN_CONFIGS})')
    if n_observations < n_groups * 2:
        reasons.append(
            f'{n_observations} observations cannot fill {n_groups} groups')
    if reasons:
        return {'status': 'insufficient_sample', 'reason': '; '.join(reasons),
                'n_observations': n_observations, 'n_configs': n_configs,
                'n_groups': n_groups, 'pbo': None}

    groups = contiguous_groups(n_observations, n_groups)
    records = []
    for train_groups, test_groups in splits(n_groups, n_test_groups):
        train = sorted(index for g in train_groups for index in groups[g])
        test = sorted(index for g in test_groups for index in groups[g])
        kept = purge(train, test, embargo)
        if not kept or not test:
            continue
        in_sample = [score([matrix[i][c] for i in kept]) for c in range(n_configs)]
        out_sample = [score([matrix[i][c] for i in test]) for c in range(n_configs)]
        if any(value is None for value in in_sample + out_sample):
            continue
        chosen = (max(range(n_configs), key=lambda c: in_sample[c])
                  if higher_is_better
                  else min(range(n_configs), key=lambda c: in_sample[c]))
        # Relative rank of the chosen configuration among the out-of-sample
        # scores, in (0, 1) — 1 is best. Ties share the mid-rank so a flat
        # surface does not resolve into a spurious win or loss.
        worse = sum(1 for value in out_sample if value < out_sample[chosen])
        equal = sum(1 for value in out_sample if value == out_sample[chosen])
        rank = (worse + (equal - 1) / 2) / (n_configs - 1) if n_configs > 1 else 0.5
        if not higher_is_better:
            rank = 1 - rank
        # Bounded away from the ends so a clean sweep still yields a finite
        # logit; with 16 configurations the shift is one twentieth of a rank.
        bounded = min(max(rank, 1 / (2 * n_configs)), 1 - 1 / (2 * n_configs))
        records.append({
            'chosen': chosen,
            'in_sample_train_size': len(kept),
            'purged': len(train) - len(kept),
            'rank': round(rank, 4),
            'logit': round(math.log(bounded / (1 - bounded)), 6),
            'in_sample_score': round(in_sample[chosen], 6),
            'out_of_sample_score': round(out_sample[chosen], 6),
            'out_of_sample_median': round(sorted(out_sample)[n_configs // 2], 6),
        })
    if not records:
        return {'status': 'insufficient_sample',
                'reason': 'every split scored to None after purging',
                'n_observations': n_observations, 'n_configs': n_configs,
                'n_groups': n_groups, 'pbo': None}

    logits = [record['logit'] for record in records]
    degradation = [record['out_of_sample_score'] - record['in_sample_score']
                   for record in records]
    return {
        'status': 'measured',
        'method': ('combinatorially symmetric cross-validation; contiguous '
                   'groups; purged with a two-sided embargo'),
        'n_observations': n_observations,
        'n_configs': n_configs,
        'n_groups': n_groups,
        'n_test_groups': n_test_groups,
        'n_splits': len(records),
        'embargo': embargo,
        'purged_per_split': round(
            sum(record['purged'] for record in records) / len(records), 1),
        # The estimate: how often the in-sample winner lands in the bottom half
        # out of sample. 0.5 is what a pure selection effect looks like.
        'pbo': round(sum(1 for value in logits if value <= 0) / len(logits), 4),
        'logit_median': round(sorted(logits)[len(logits) // 2], 4),
        'mean_out_of_sample_degradation': round(
            sum(degradation) / len(degradation), 6),
        'splits_where_the_winner_stayed_above_median': sum(
            1 for value in logits if value > 0),
        # Which configurations the search actually picked, and how often. A
        # PBO near 0.5 with one config winning every split says something
        # different from the same number with the winner rotating: the first is
        # a stable rule the estimator cannot separate from noise, the second is
        # the search chasing the window.
        'selection_counts': {
            str(config): sum(1 for record in records if record['chosen'] == config)
            for config in sorted({record['chosen'] for record in records})},
        'selected_configs': sorted({record['chosen'] for record in records}),
    }
