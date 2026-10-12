"""The `optimizer` service: search a strategy's declared grid, walking forward.

The question this answers
-------------------------
"Can a strategy tune its own parameters?" Mechanically, yes: a strategy plugin
declares a grid, and this service picks from it. Whether the pick means anything
is a separate question, and the one this module is mostly about.

What it measures
----------------
Each session, each configuration's score is ranked across the names against the
forward return that followed — the rank IC `evaluation.signal_panel` uses, with
the same entry rule (the first close the signal could not have seen). The
optimiser then walks forward: at each refit it picks the configuration with the
best mean IC over the sessions whose forward returns had already been realised,
and is scored on the block after it. The registered parameters are carried
through the same blocks as the baseline.

What it may conclude
--------------------
A **proposal**, never a change. `config/factor-universe.json` states the rule
this inherits: never infer live permission from a retrospective backtest. So
the report always carries `live_permission: false`, and the gate decides only
whether the selected parameters are worth pre-registering for prospective
scoring:

* enough out-of-sample sessions;
* the walk-forward IC and its lift over the registered parameters both have a
  block-bootstrap interval above zero;
* the grid as a whole is not a lottery — CSCV's probability of backtest
  overfitting is below one half (`evaluation.cscv`);
* the bars are adjusted for corporate actions.

A refusal lists every check it failed. Changing the registered parameters is
then an edit to the row in `config/strategy-plugins.json`, reviewed like any
other configuration change.

Alternate gates
---------------
The gate itself may be wrong, and the way to find out is not to edit it.
`gate_alternates` in the row names other threshold sets, each with the reason
it exists. Every proposal is judged by all of them beside the registered gate
and the verdicts are reported in `alternate_gates`. An alternate never sets
`status`: it is a second opinion kept on the record, so a threshold can be
argued from what it would have concluded before it is allowed to conclude
anything.
"""
from __future__ import annotations

import itertools
import random
import statistics
from collections import defaultdict

from clawock import seeds
from clawock.evaluation import bootstrap, cscv
from clawock.evaluation.signal_panel import _spearman

name = 'walkforward-optimizer'
inject = ('strategies', 'bars')

DEFAULTS = {
    # Forward horizon in sessions; `signal_panel` scores 1, 5 and 20.
    'horizon_sessions': 5,
    # A rank over fewer names than this is mostly ties and noise.
    'min_cross_section': 6,
    'min_train_sessions': 60,
    'test_sessions': 20,
    'pbo_groups': 8,
    'bootstrap_samples': 2000,
    'gate_alternates': [],
    'gate': {
        'min_oos_sessions': 60,
        'oos_ic_ci95_lower_gt': 0.0,
        'oos_lift_ci95_lower_gt': 0.0,
        'pbo_lt': 0.5,
        'corporate_actions_adjusted': True,
    },
}


def _thresholds(overrides, label: str) -> dict:
    """The registered defaults with `overrides` applied; unknown keys refused.

    A misspelt threshold that fell back to its default would be a gate that
    reads as tightened or loosened and is neither.
    """
    unknown = sorted(set(overrides or {}) - set(DEFAULTS['gate']))
    if unknown:
        raise ValueError(
            f'{label}: unknown gate check(s) {unknown}; known: {sorted(DEFAULTS["gate"])}')
    return {**DEFAULTS['gate'], **(overrides or {})}


def _alternates(rows, registered: dict) -> list[dict]:
    out, seen = [], set()
    for row in rows or []:
        identifier, rationale = row.get('id'), row.get('rationale')
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError(f'gate alternate needs a unique id, got {identifier!r}')
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f'gate alternate {identifier!r} needs a rationale')
        seen.add(identifier)
        # An alternate states only what it changes; the rest is the registered gate.
        _thresholds(row.get('gate'), f'gate alternate {identifier!r}')
        out.append({'id': identifier, 'rationale': rationale,
                    'gate': {**registered, **(row.get('gate') or {})}})
    return out


def configurations(space: dict) -> list[dict]:
    """Every point of the grid, in a stable order."""
    keys = sorted(space)
    return [dict(zip(keys, values))
            for values in itertools.product(*(space[key] for key in keys))]


def ic_matrix(spec, bars, configs, *, horizon: int, min_cross_section: int):
    """(sessions, matrix[session][config]) of daily rank ICs.

    Only sessions where every configuration could be ranked are kept: a chooser
    can only choose between candidates scored on the same day.
    """
    pairs = defaultdict(lambda: [[] for _ in configs])
    for ticker in bars.tickers():
        series = bars.series(ticker)
        # Entry is the close after the signal session, exit `horizon` later.
        for index in range(len(series) - horizon - 1):
            entry, exit_ = series[index + 1]['close'], series[index + 1 + horizon]['close']
            forward = exit_ / entry - 1
            history = series[:index + 1]
            for column, params in enumerate(configs):
                value = spec.score(history, params)
                if value is not None:
                    pairs[series[index]['date']][column].append((value, forward))
    sessions, matrix = [], []
    for day in sorted(pairs):
        row = [_spearman(cell) if len(cell) >= min_cross_section else None
               for cell in pairs[day]]
        if all(value is not None for value in row):
            sessions.append(day)
            matrix.append(row)
    return sessions, matrix


def _best(matrix, rows, default: int) -> int:
    means = [statistics.fmean(matrix[i][c] for i in rows)
             for c in range(len(matrix[0]))]
    top = max(means)
    # A tie keeps the registered parameters: a move needs a reason.
    return default if means[default] == top else means.index(top)


def walk_forward(sessions, matrix, default: int, *, min_train: int,
                 test_len: int, embargo: int) -> dict:
    """Refit on what was realised, score the next block, repeat."""
    folds, chosen_ics, default_ics, days = [], [], [], []
    start = min_train + embargo
    while start < len(sessions):
        # A training session's forward return closes `embargo` sessions later,
        # so the last ones before the test block were not yet known at refit.
        train = range(0, start - embargo)
        test = range(start, min(start + test_len, len(sessions)))
        pick = _best(matrix, train, default)
        folds.append({'refit_before': sessions[start], 'train_sessions': len(train),
                      'test_sessions': len(test), 'chosen': pick})
        for i in test:
            days.append(sessions[i])
            chosen_ics.append(matrix[i][pick])
            default_ics.append(matrix[i][default])
        start += test_len
    return {'folds': folds, 'days': days, 'chosen': chosen_ics,
            'default': default_ics}


def mean_ci(values, *, min_block: int, samples: int, seed: int):
    """95% stationary-bootstrap interval for the mean of a dependent series.

    Forward returns over `horizon` sessions overlap, so adjacent daily ICs
    share most of their label; the block is never shorter than that overlap.
    """
    if len(values) < 3:
        return None
    block = max(min_block, bootstrap.optimal_block_length(values)['stationary'])
    rnd = random.Random(seed)
    draws = sorted(
        statistics.fmean(values[i] for i in
                         bootstrap.stationary_bootstrap_indices(len(values), block, rnd))
        for _ in range(samples))
    return [round(draws[int(0.025 * (samples - 1))], 4),
            round(draws[int(0.975 * (samples - 1))], 4)]


def _gate(thresholds: dict, *, oos_sessions, ic_ci, lift_ci, pbo, adjusted) -> list[dict]:
    def check(key, observed, passed, required):
        return {'check': key, 'observed': observed, 'required': required,
                'passed': bool(passed)}

    checks = [
        check('min_oos_sessions', oos_sessions,
              oos_sessions >= thresholds['min_oos_sessions'],
              f">= {thresholds['min_oos_sessions']}"),
        check('oos_ic_ci95_lower_gt', ic_ci and ic_ci[0],
              ic_ci is not None and ic_ci[0] > thresholds['oos_ic_ci95_lower_gt'],
              f"> {thresholds['oos_ic_ci95_lower_gt']}"),
        check('oos_lift_ci95_lower_gt', lift_ci and lift_ci[0],
              lift_ci is not None and lift_ci[0] > thresholds['oos_lift_ci95_lower_gt'],
              f"> {thresholds['oos_lift_ci95_lower_gt']}"),
        # An unmeasured PBO fails: "could not check" is not "passed".
        check('pbo_lt', pbo, pbo is not None and pbo < thresholds['pbo_lt'],
              f"< {thresholds['pbo_lt']}"),
    ]
    if thresholds.get('corporate_actions_adjusted'):
        checks.append(check('corporate_actions_adjusted', adjusted, adjusted is True, True))
    return checks


class Optimizer:
    def __init__(self, strategies, bars, settings: dict):
        self.strategies, self.bars, self.settings = strategies, bars, settings

    def run(self, strategy: str) -> dict:
        spec = self.strategies.get(strategy)
        settings = self.settings
        horizon = settings['horizon_sessions']
        configs = configurations(spec.space)
        if spec.params not in configs:
            raise ValueError(
                f'{strategy}: registered params {spec.params} are not a point of '
                'the declared space, so the search has no baseline')
        default = configs.index(spec.params)
        sessions, matrix = ic_matrix(
            spec, self.bars, configs, horizon=horizon,
            min_cross_section=settings['min_cross_section'])
        embargo = horizon + 1
        walk = walk_forward(
            sessions, matrix, default, min_train=settings['min_train_sessions'],
            test_len=settings['test_sessions'], embargo=embargo)
        seed = seeds.seed('strategy_walkforward_bootstrap')
        ci = dict(min_block=horizon, samples=settings['bootstrap_samples'], seed=seed)
        lift = [a - b for a, b in zip(walk['chosen'], walk['default'])]
        ic_ci, lift_ci = mean_ci(walk['chosen'], **ci), mean_ci(lift, **ci)
        pbo = cscv.probability_of_backtest_overfitting(
            matrix, statistics.fmean, n_groups=settings['pbo_groups'],
            embargo=embargo) if matrix else {
                'status': 'insufficient_sample', 'pbo': None,
                'reason': 'no session ranked every configuration'}
        source = self.bars.describe()
        measured = dict(
            oos_sessions=len(walk['days']), ic_ci=ic_ci, lift_ci=lift_ci,
            pbo=pbo.get('pbo'), adjusted=source.get('corporate_actions_adjusted'))
        checks = _gate(settings['gate'], **measured)
        passed = all(item['passed'] for item in checks)
        alternates = []
        for alternate in settings['gate_alternates']:
            verdict = _gate(alternate['gate'], **measured)
            would_pass = all(item['passed'] for item in verdict)
            alternates.append({
                **alternate, 'binding': False, 'would_pass': would_pass,
                'agrees_with_registered': would_pass == passed,
                'would_refuse_because': [
                    item['check'] for item in verdict if not item['passed']],
                'checks': verdict})
        selected = configs[_best(matrix, range(len(matrix)), default)] if matrix else None
        surface = sorted(
            ({'params': configs[c],
              'mean_ic': round(statistics.fmean(row[c] for row in matrix), 4)}
             for c in range(len(configs))),
            key=lambda item: -item['mean_ic']) if matrix else []

        def mean(values):
            return round(statistics.fmean(values), 4) if values else None

        return {
            'schema_version': 1,
            'kind': 'strategy-parameter-proposal',
            'strategy': strategy,
            'status': 'candidate' if passed else 'refused',
            'live_permission': False,
            'evidence_grade': 'retrospective',
            'registered_params': dict(sorted(spec.params.items())),
            # What a refit over every scored session picks. Only a `candidate`
            # is worth registering, and registering starts prospective scoring;
            # it does not start trading.
            'selected_params': selected,
            'gate': checks,
            'refused_because': [item['check'] for item in checks if not item['passed']],
            # Second opinions. None of them feeds `status` above.
            'alternate_gates': alternates,
            'objective': (f'mean daily rank IC against the {horizon}-session forward '
                          'return; gross, no trades are simulated'),
            'search': {'space': spec.space, 'configurations': len(configs)},
            'sample': {'sessions': len(sessions),
                       'first': sessions[0] if sessions else None,
                       'last': sessions[-1] if sessions else None,
                       'bars': source},
            'walk_forward': {
                'embargo_sessions': embargo,
                'oos_sessions': len(walk['days']),
                'oos_mean_ic_selected': mean(walk['chosen']),
                'oos_mean_ic_registered': mean(walk['default']),
                'oos_mean_lift': mean(lift),
                'oos_ic_ci95': ic_ci,
                'oos_lift_ci95': lift_ci,
                'folds': [dict(fold, chosen=configs[fold['chosen']])
                          for fold in walk['folds']],
            },
            'pbo': {key: pbo.get(key) for key in
                    ('status', 'pbo', 'n_splits', 'reason',
                     'mean_out_of_sample_degradation') if key in pbo},
            'surface': surface,
            'settings': settings,
            'seed': {'strategy_walkforward_bootstrap': seed},
        }


def apply(ctx, config):
    gate = _thresholds(config.get('gate'), 'gate')
    settings = {**DEFAULTS, **config, 'gate': gate,
                'gate_alternates': _alternates(config.get('gate_alternates'), gate)}
    ctx.provide('optimizer', Optimizer(ctx.get('strategies'), ctx.get('bars'), settings))
