"""One verdict, and every gate that had to agree to produce it.

The problem with six gates
--------------------------
This repository has accumulated a good set of them, and each is right:
`cscv` prices the ranking of a search, `deflated_sharpe` prices its level,
`bootstrap` widens an interval for serial dependence, `attribution` splits a
return into what the factors explain and what they do not, `drift` says whether
the distributions still look like the ones the thresholds were registered
against. They are also six separate outputs, each with its own sample floor and
its own refusal, and the failure mode of six separate outputs is that a reader
takes the one that agrees with them.

`grade` runs them on one input and reduces them to a single evidence level, with
every gate's contribution attached. The reduction is deliberately harsh in one
direction: **a refusal is not a pass.** A gate that says `insufficient_sample`
caps the grade below `diagnostic`, because "we could not check" and "we checked
and it held" are the two things a summary is most tempting to blur.

The grades
----------
* `insufficient` — the sample cannot support the question. Most results here.
* `diagnostic` — measured, intervals published, nothing pre-registered. The
  ceiling for anything measured after the fact, and the ceiling this module can
  ever award: `validated` requires pre-registration, which is a property of when
  a rule was written and not of any computation.
* `contested` — gates disagree. Named rather than averaged away, because two
  gates disagreeing is information and their mean is not.

Nothing here can promote a result to `validated`. That word belongs to a rule
that survived being written down before the data arrived.
"""
from __future__ import annotations

import statistics

from clawock.evaluation import bootstrap as block_bootstrap
from clawock.evaluation import cscv, deflated_sharpe
from clawock.evaluation.attribution import perf_attrib

#: Below this many sessions no gate here is meaningful, and running them anyway
#: produces a table of refusals that reads like a result.
MIN_SESSIONS = 12


def grade(returns_by_session, *, configurations=None, n_trials=None,
          attribution=None, drift_report=None) -> dict:
    """Reduce every available gate to one evidence level and its reasons.

    `returns_by_session` maps a session to the realised returns attributed to it.
    `configurations`, when supplied, is `{name: {session: return}}` for every
    variant the search considered — the ranking `cscv` prices. `n_trials` is how
    many cells a reader's eye could have landed on; it defaults to the number of
    configurations and must be given explicitly when the search was wider than
    the table shown.
    """
    sessions = sorted(returns_by_session)
    gates, reasons = {}, []
    if len(sessions) < MIN_SESSIONS:
        return {'grade': 'insufficient', 'n_sessions': len(sessions),
                'reasons': [f'{len(sessions)} sessions is below the '
                            f'{MIN_SESSIONS}-session floor'],
                'gates': {}}

    pooled = {day: list(returns_by_session[day]) if isinstance(
        returns_by_session[day], (list, tuple)) else [returns_by_session[day]]
        for day in sessions}
    interval = block_bootstrap.clustered_block_ci(pooled)
    gates['interval'] = interval
    if interval is None:
        reasons.append('interval unavailable')
    else:
        clears = interval['ci95'][0] > 0 or interval['ci95'][1] < 0
        gates['interval_clears_zero'] = clears
        if not clears:
            reasons.append('the interval on the mean covers zero')

    daily = [statistics.fmean(pooled[day]) for day in sessions]
    trials = n_trials or (len(configurations) if configurations else 1)
    trial_sharpes = None
    if configurations:
        trial_sharpes = [deflated_sharpe.sharpe(
            [values[day] for day in sessions if day in values])
            for values in configurations.values()]
        trial_sharpes = [value for value in trial_sharpes if value is not None]
    gates['deflated_sharpe'] = deflated_sharpe.deflated_sharpe_ratio(
        daily, n_trials=trials, trial_sharpes=trial_sharpes)
    if gates['deflated_sharpe'].get('dsr') is None:
        reasons.append('deflated Sharpe: ' + gates['deflated_sharpe'].get('reason', ''))
    elif gates['deflated_sharpe']['dsr'] < 0.9:
        reasons.append('the Sharpe does not survive deflation for the search size')

    if configurations and len(configurations) >= cscv.MIN_CONFIGS:
        names = sorted(configurations)
        common = [day for day in sessions
                  if all(day in configurations[name] for name in names)]
        matrix = [[configurations[name][day] for name in names] for day in common]
        gates['pbo'] = cscv.probability_of_backtest_overfitting(
            matrix, lambda values: statistics.fmean(values) if values else None,
            embargo=1)
        gates['pbo']['configurations'] = names
        if gates['pbo'].get('pbo') is None:
            reasons.append('PBO: ' + gates['pbo'].get('reason', ''))
        elif gates['pbo']['pbo'] > 0.5:
            reasons.append('the in-sample winner is below median out of sample '
                           'more often than not')
    else:
        gates['pbo'] = {'status': 'not_applicable',
                        'reason': 'fewer than three configurations: no selection '
                                  'effect to measure'}

    if attribution is not None:
        gates['attribution'] = {
            key: attribution.get(key) for key in
            ('status', 'common_return_mean', 'specific_return_mean',
             'tilt_return_mean', 'timing_return_mean', 'fit_quality')}
        if attribution.get('status') == 'measured':
            common = attribution.get('common_return_mean') or 0.0
            total = attribution.get('total_return_mean') or 0.0
            if total and abs(common) < 0.3 * abs(total):
                reasons.append('most of the return is specific: the factors on '
                               'record do not explain it')
    if drift_report is not None:
        gates['drift'] = {
            'flagged': drift_report.get('flagged'),
            'flagged_share': drift_report.get('flagged_share'),
            'discriminating': drift_report.get('discriminating'),
        }
        if drift_report.get('discriminating') is False:
            reasons.append('the drift detector cannot discriminate on this '
                           'reference window, so distribution stability is '
                           'unchecked rather than confirmed')

    refused = [name for name, value in gates.items()
               if isinstance(value, dict)
               and value.get('status') in ('insufficient_sample', 'insufficient_search')]
    passed = [
        bool(gates.get('interval_clears_zero')),
        (gates.get('deflated_sharpe') or {}).get('dsr') is not None
        and gates['deflated_sharpe']['dsr'] >= 0.9,
        (gates.get('pbo') or {}).get('pbo') is not None
        and gates['pbo']['pbo'] <= 0.5,
    ]
    if refused:
        level = 'insufficient'
        reasons.append(f'gates that could not run: {", ".join(sorted(refused))}')
    elif all(passed):
        level = 'diagnostic'
    elif any(passed):
        level = 'contested'
    else:
        level = 'insufficient'
    return {
        'grade': level,
        'n_sessions': len(sessions),
        'gates': gates,
        'reasons': reasons,
        'ceiling': ('diagnostic; `validated` requires pre-registration, which is '
                    'a property of when a rule was written and cannot be '
                    'produced by any computation here'),
        'discipline': 'a refused gate caps the grade; "not checked" is not "held"',
    }


def evaluate(sessions, weights_by_session, factors, *, configurations=None,
             n_trials=None, drift_report=None) -> dict:
    """Attribution and the grade, on one input, in one call."""
    attribution = perf_attrib(sessions, weights_by_session, factors)
    returns_by_session = {}
    if attribution.get('status') == 'measured':
        returns_by_session = {
            day: [value] for day, value in
            (attribution.get('per_session') or {}).get('total', {}).items()}
    return {
        'attribution': attribution,
        'grade': grade(returns_by_session, configurations=configurations,
                       n_trials=n_trials, attribution=attribution,
                       drift_report=drift_report),
    }
