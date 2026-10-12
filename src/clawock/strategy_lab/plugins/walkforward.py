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

What it costs
-------------
The rank IC is gross: it says the ordering carried information, not that
anything survives being traded. So each session's scores are also held as a
portfolio — the better half of the names, equal-weighted, against all of them
— and charged the registered cost model (`costs` service) on the names that
enter and leave when the tranche formed `horizon` sessions earlier is replaced.
`net_of_cost` reports that excess before and after the charge and the turnover
behind it. The registered gate does not read it; an alternate may, through
`oos_net_excess_ci95_lower_gt`.

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
from clawock.strategy_lab.plugins.signal_panel import _spearman

name = 'walkforward-optimizer'
inject = ('strategies', 'bars', 'costs')

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
        # Not part of the registered gate. An alternate sets a number here to
        # ask whether the edge is still there after the registered costs.
        'oos_net_excess_ci95_lower_gt': None,
    },
}


#: The least a registered gate may ask. A row may tighten any of these; a row
#: that asks for less is refused at mount, so lowering a bar is a change to
#: this file and not to a config row.
FLOOR = {key: value for key, value in DEFAULTS['gate'].items() if value is not None}


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


#: What an alternate's verdict does. `record`: it is written beside the verdict
#: and nothing reads it. `live`: its refusal is an objection that keeps a
#: candidate from being cleared for prospective registration.
EFFECTS = ('record', 'live')


def _loosens(check: str, registered, value) -> bool:
    """Whether `value` asks less of a proposal than the registered threshold."""
    if check == 'corporate_actions_adjusted':
        return bool(registered) and not value
    if registered is None:
        return False  # a check the registered gate does not make
    if value is None:
        return True
    return value > registered if check.endswith('_lt') else value < registered


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
        effect = row.get('effect', 'record')
        if effect not in EFFECTS:
            raise ValueError(
                f'gate alternate {identifier!r}: effect must be one of {EFFECTS}, got {effect!r}')
        gate = {**registered, **(row.get('gate') or {})}
        # An alternate with live effect may only add or tighten a check. One
        # that dropped the adjustment check, or lowered a bar, would otherwise
        # be a way to clear what the registered gate refuses.
        loosened = sorted(check for check in gate if _loosens(check, registered[check], gate[check]))
        if effect == 'live' and loosened:
            raise ValueError(
                f'gate alternate {identifier!r} has live effect and loosens {loosened}; '
                'a live alternate may only add or tighten a check')
        out.append({'id': identifier, 'rationale': rationale, 'effect': effect, 'gate': gate})
    return out


def configurations(space: dict) -> list[dict]:
    """Every point of the grid, in a stable order."""
    keys = sorted(space)
    return [dict(zip(keys, values))
            for values in itertools.product(*(space[key] for key in keys))]


def panel(spec, bars, configs, *, horizon: int, min_cross_section: int):
    """(sessions, matrix[session][config], cells[session][config]).

    `matrix` holds the daily rank ICs; `cells` the (ticker, score, forward
    return) triples each one was computed from. Only sessions where every
    configuration could be ranked are kept: a chooser can only choose between
    candidates scored on the same day.
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
                    pairs[series[index]['date']][column].append((ticker, value, forward))
    sessions, matrix, cells = [], [], []
    for day in sorted(pairs):
        row = [_spearman([triple[1:] for triple in cell])
               if len(cell) >= min_cross_section else None
               for cell in pairs[day]]
        if all(value is not None for value in row):
            sessions.append(day)
            matrix.append(row)
            cells.append(pairs[day])
    return sessions, matrix, cells


def ic_matrix(spec, bars, configs, *, horizon: int, min_cross_section: int):
    """(sessions, matrix[session][config]) of daily rank ICs."""
    return panel(spec, bars, configs, horizon=horizon,
                 min_cross_section=min_cross_section)[:2]


def _basket(cell) -> list[str]:
    """The better half by score; ties broken by ticker so a rerun agrees."""
    ranked = sorted(cell, key=lambda triple: (-triple[1], triple[0]))
    return [triple[0] for triple in ranked[:(len(ranked) + 1) // 2]]


def net_excess(cells, picks, positions, *, horizon: int, side_bps) -> dict:
    """Per-session excess of the better-half basket, before and after costs.

    `picks[k]` is the configuration in force at `positions[k]`. A tranche is
    held `horizon` sessions, so the one formed at session i replaces the one
    formed at i - horizon: names that leave are sold and names that enter are
    bought, each at `side_bps(ticker)` on its weight. The first tranches have
    nothing to replace and pay a full entry. The equal-weight comparison is
    charged nothing, which leans against the strategy.
    """
    chosen = dict(zip(positions, picks))
    gross, net, turnover = [], [], []
    for position, pick in zip(positions, picks):
        cell = cells[position][pick]
        forward = {ticker: value for ticker, _, value in cell}
        basket = _basket(cell)
        before = position - horizon
        previous = (_basket(cells[before][chosen.get(before, pick)])
                    if before >= 0 else [])
        bought = [ticker for ticker in basket if ticker not in previous]
        sold = [ticker for ticker in previous if ticker not in basket]
        cost = sum(side_bps(ticker) for ticker in bought) / len(basket)
        if previous:
            cost += sum(side_bps(ticker) for ticker in sold) / len(previous)
        excess = (statistics.fmean(forward[ticker] for ticker in basket)
                  - statistics.fmean(forward.values()))
        gross.append(excess)
        net.append(excess - cost / 10_000)
        turnover.append(len(bought) / len(basket))
    return {'gross': gross, 'net': net, 'turnover': turnover}


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


def mean_ci(values, *, min_block: int, samples: int, seed: int, digits: int = 4):
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
    return [round(draws[int(0.025 * (samples - 1))], digits),
            round(draws[int(0.975 * (samples - 1))], digits)]


def _gate(thresholds: dict, *, oos_sessions, ic_ci, lift_ci, pbo, adjusted,
          net_ci=None) -> list[dict]:
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
    floor = thresholds.get('oos_net_excess_ci95_lower_gt')
    if floor is not None:
        checks.append(check('oos_net_excess_ci95_lower_gt', net_ci and net_ci[0],
                            net_ci is not None and net_ci[0] > floor, f'> {floor}'))
    return checks


class Optimizer:
    def __init__(self, strategies, bars, costs, settings: dict):
        self.strategies, self.bars, self.costs = strategies, bars, costs
        self.settings = settings

    def run(self, strategy: str, registrations=(), sensitivity=True) -> dict:
        """One proposal. `registrations` are earlier cleared parameters of this
        strategy (`ledger.registrations`); each is scored on the sessions after
        the one it was registered on."""
        spec = self.strategies.get(strategy)
        settings = self.settings
        horizon = settings['horizon_sessions']
        configs = configurations(spec.space)
        if spec.params not in configs:
            raise ValueError(
                f'{strategy}: registered params {spec.params} are not a point of '
                'the declared space, so the search has no baseline')
        default = configs.index(spec.params)
        sessions, matrix, cells = panel(
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
        index_of = {day: i for i, day in enumerate(sessions)}
        positions = [index_of[day] for day in walk['days']]
        picks = [fold['chosen'] for fold in walk['folds']
                 for _ in range(fold['test_sessions'])]

        def side_bps(ticker):
            return self.costs.side_bps(self.bars.leg(ticker))

        traded = net_excess(cells, picks, positions, horizon=horizon, side_bps=side_bps)
        baseline = net_excess(cells, [default] * len(positions), positions,
                              horizon=horizon, side_bps=side_bps)
        net_ci = mean_ci(traded['net'], **ci, digits=6)
        pbo = cscv.probability_of_backtest_overfitting(
            matrix, statistics.fmean, n_groups=settings['pbo_groups'],
            embargo=embargo) if matrix else {
                'status': 'insufficient_sample', 'pbo': None,
                'reason': 'no session ranked every configuration'}
        source = self.bars.describe()
        measured = dict(
            oos_sessions=len(walk['days']), ic_ci=ic_ci, lift_ci=lift_ci,
            pbo=pbo.get('pbo'), adjusted=source.get('corporate_actions_adjusted'),
            net_ci=net_ci)
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
        objections = [alternate['id'] for alternate in alternates
                      if alternate['effect'] == 'live' and not alternate['would_pass']]
        prospective = []
        for registered in registrations:
            if registered['params'] not in configs:
                continue  # the space no longer holds it; nothing to score it on
            column = configs.index(registered['params'])
            days = [day for day in sessions if day > registered['after_session']]
            later = [row[column] for day, row in zip(sessions, matrix)
                     if day > registered['after_session']]
            prospective.append({
                'params': registered['params'], 'after_session': registered['after_session'],
                'sessions': len(later),
                'first_session': days[0] if days else None,
                'last_session': days[-1] if days else None,
                'mean_ic': round(statistics.fmean(later), 4) if later else None,
                # Too few sessions to bootstrap reads None, not an interval.
                'ic_ci95': mean_ci(later, **ci)})
        selected = configs[_best(matrix, range(len(matrix)), default)] if matrix else None
        surface = sorted(
            ({'params': configs[c],
              'mean_ic': round(statistics.fmean(row[c] for row in matrix), 4)}
             for c in range(len(configs))),
            key=lambda item: -item['mean_ic']) if matrix else []

        def mean(values, digits=4):
            return round(statistics.fmean(values), digits) if values else None

        report = {
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
            # What the alternates with live effect do: object. A candidate no
            # live alternate objects to is cleared to be registered and scored
            # on the sessions that follow. Not a permission to trade.
            'live_review': {
                'alternates': [a['id'] for a in alternates if a['effect'] == 'live'],
                'objections': objections,
                'cleared': passed and not objections},
            # Earlier cleared parameters, scored only on sessions after their
            # registration.
            'prospective': prospective,
            'objective': (f'mean daily rank IC against the {horizon}-session forward '
                          'return, gross; net_of_cost holds the same picks as a basket'),
            'search': {'space': spec.space, 'configurations': len(configs)},
            'sample': {'sessions': len(sessions),
                       'first': sessions[0] if sessions else None,
                       'last': sessions[-1] if sessions else None,
                       # The latest bar the run was served, scored or not.
                       'last_bar': max((self.bars.series(ticker)[-1]['date']
                                        for ticker in self.bars.tickers()), default=None),
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
            # Per session, in return units over the horizon: the better-half
            # basket less the equal-weight of every scored name.
            'net_of_cost': {
                'portfolio': (f'better half by score, equal-weighted, held {horizon} '
                              'sessions, against the equal-weight of all scored names'),
                'oos_mean_gross_excess': mean(traded['gross'], 6),
                'oos_mean_net_excess': mean(traded['net'], 6),
                'oos_net_excess_ci95': net_ci,
                'oos_mean_net_excess_registered': mean(baseline['net'], 6),
                'mean_turnover_per_tranche': mean(traded['turnover']),
                'costs': self.costs.describe(),
            },
            'pbo': {key: pbo.get(key) for key in
                    ('status', 'pbo', 'n_splits', 'reason',
                     'mean_out_of_sample_degradation') if key in pbo},
            'surface': surface,
            'settings': settings,
            'seed': {'strategy_walkforward_bootstrap': seed},
        }
        report['coverage_sensitivity'] = (
            coverage_sensitivity(self, strategy, report) if sensitivity else None)
        return report


class _Subset:
    """A bars service restricted to some of its names."""

    def __init__(self, bars, tickers):
        self._bars, self._tickers = bars, sorted(tickers)

    def tickers(self):
        return list(self._tickers)

    def series(self, ticker):
        return self._bars.series(ticker)

    def leg(self, ticker):
        return self._bars.leg(ticker)

    def describe(self):
        return {**self._bars.describe(), 'tickers': len(self._tickers)}


def coverage_sensitivity(optimizer: 'Optimizer', strategy: str, report: dict):
    """The same search on the names the source answered adjusted, alone.

    A source may serve two kinds of name: those it answered adjusted, and those
    it answered raw because its own record holds no corporate action for them.
    The second kind rests on one provider's record. This reruns the proposal
    without them and reports whether the verdict survives, so a candidate that
    depends on them says so in its own row. It decides nothing.
    """
    basis = (optimizer.bars.describe().get('basis') or {})
    confirmed, on_record = basis.get('adjusted') or [], basis.get('no_action_on_record') or []
    if not confirmed or not on_record:
        return None
    try:
        narrow = Optimizer(optimizer.strategies, _Subset(optimizer.bars, confirmed),
                           optimizer.costs, optimizer.settings).run(strategy, sensitivity=False)
    except Exception as exc:
        return {'question': 'adjusted names only', 'tickers': len(confirmed),
                'left_out': sorted(on_record), 'error': f'{type(exc).__name__}: {exc}'}
    walk = narrow['walk_forward']
    return {
        'question': 'adjusted names only',
        'tickers': len(confirmed),
        'left_out': sorted(on_record),
        'status': narrow['status'],
        'refused_because': narrow['refused_because'],
        'selected_params': narrow['selected_params'],
        'oos_mean_ic_selected': walk['oos_mean_ic_selected'],
        'oos_ic_ci95': walk['oos_ic_ci95'],
        'pbo': narrow['pbo'].get('pbo'),
        'verdict_survives': narrow['status'] == report['status'],
    }


def apply(ctx, config):
    gate = _thresholds(config.get('gate'), 'gate')
    lowered = sorted(check for check, floor in FLOOR.items() if _loosens(check, floor, gate[check]))
    if lowered:
        raise ValueError(
            f'the registered gate asks less than the floor on {lowered} '
            f'(floor {({check: FLOOR[check] for check in lowered})}); a row may tighten '
            'the gate, and lowering a floor is a change to the optimiser, not to a row')
    settings = {**DEFAULTS, **config, 'gate': gate,
                'gate_alternates': _alternates(config.get('gate_alternates'), gate)}
    ctx.provide('optimizer', Optimizer(
        ctx.get('strategies'), ctx.get('bars'), ctx.get('costs'), settings))
