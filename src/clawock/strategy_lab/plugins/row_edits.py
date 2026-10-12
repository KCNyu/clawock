"""The `promoter` service: when a registration has earned a proposed row edit.

A registration is a cleared candidate's parameters, scored since on sessions
that did not exist when they were chosen. This plugin reads those scores and
says when they are enough to put a change of the strategy's registered
parameters in front of a reviewer. It writes nothing: the lab records what it
answers through `ledger.propose_row_edit`, which applies
`boundaries.check_row_edit` whoever produced the proposal.

Config, all optional, each of which may only be stricter than
`boundaries.PROMOTION_FLOOR`:

* `min_prospective_sessions` — sessions scored since registration;
* `prospective_ic_ci95_lower_gt` — the lower end of the bootstrap interval of
  the mean rank IC over those sessions.

One check is not configurable: when the bars source serves names that rest on
one provider's empty action record, the latest run's verdict must survive
without them (`coverage_sensitivity`).

A proposal names the parameters to move from and to and carries
`live_permission: false`. Applying it is an edit to
`config/strategy-plugins.json` that someone reviews; nothing here opens it.
"""
from __future__ import annotations

from clawock.strategy_lab import boundaries

name = 'row-edit-promoter'


def _check(check, observed, required, passed):
    return {'check': check, 'observed': observed, 'required': required, 'passed': bool(passed)}


class Promoter:
    def __init__(self, thresholds: dict):
        self.thresholds = thresholds

    def judge(self, report: dict, trial: dict) -> list[dict]:
        """Every promotion check for one registration's prospective score."""
        sessions, interval = trial.get('sessions') or 0, trial.get('ic_ci95')
        narrow = report.get('coverage_sensitivity')
        need_sessions = self.thresholds['min_prospective_sessions']
        need_lower = self.thresholds['prospective_ic_ci95_lower_gt']
        return [
            _check('min_prospective_sessions', sessions, f'>= {need_sessions}',
                   sessions >= need_sessions),
            _check('prospective_ic_ci95_lower_gt', interval and interval[0], f'> {need_lower}',
                   bool(interval) and interval[0] > need_lower),
            _check('survives_adjusted_only',
                   'one basis served' if narrow is None else narrow.get('verdict_survives'),
                   'true when measured',
                   narrow is None or narrow.get('verdict_survives') is True),
        ]

    def review(self, report: dict) -> list[dict]:
        """The row edits this run's prospective scores have earned; usually none."""
        current = report['registered_params']
        out = []
        for trial in report.get('prospective') or []:
            if trial['params'] == current:
                continue  # the row already runs these
            checks = self.judge(report, trial)
            if not all(item['passed'] for item in checks):
                continue
            out.append({
                'kind': 'row-edit-proposal',
                'strategy': report['strategy'],
                'from_params': current,
                'to_params': trial['params'],
                'after_session': trial['after_session'],
                'evidence': {key: trial.get(key) for key in
                             ('sessions', 'first_session', 'last_session', 'mean_ic', 'ic_ci95')},
                'coverage_sensitivity': report.get('coverage_sensitivity'),
                'checks': checks,
                'status': 'proposed',
                'live_permission': False,
                'applies_by': 'a reviewed edit to the strategy\'s row in config/strategy-plugins.json',
            })
        return out

    def describe(self) -> dict:
        return dict(self.thresholds)


def apply(ctx, config):
    ctx.provide('promoter', Promoter(boundaries.promotion_thresholds(config)))
