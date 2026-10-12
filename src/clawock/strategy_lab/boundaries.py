"""What the strategy lab may never write down, checked where it writes.

The lab searches parameters and keeps a record. These are the limits on that
record, as code rather than as a sentence in a document. They are not a plugin
and no row can turn them off: `ledger.append` and `ledger.register` call them
on every write, and `verify` reads the files back and applies them again, so a
row that reached the ledger some other way is found on the next scheduled run.

* A proposal and a registration say `live_permission: false`. Nothing here can
  write `true`.
* A proposal's `status` is the registered gate's verdict and nothing else:
  `candidate` exactly when every registered check passed.
* An alternate gate is never binding. One with live effect may object; a
  proposal is cleared only when the registered gate passed and nothing objects.
* A candidate was measured on bars that say they are adjusted whenever the
  registered gate asks for that.
* A registration exists only for a cleared candidate, carries the parameters
  that run selected and the last session it was served, and its prospective
  score counts sessions after that one only.
* A row edit is proposed only for a registration, on at least
  `PROMOTION_FLOOR` of prospective evidence, and only when the verdict survives
  without the names one provider vouches for. It says `proposed` and
  `live_permission: false`; the lab has no code that applies one.

What the lab cannot do at all is outside this file because there is no code for
it to guard: no module outside `strategy_lab` imports the ledger
(`tests/package_edges.txt` has no edge into this package), and the registered
parameters of a strategy are a row in `config/strategy-plugins.json` that the
lab reads and never writes.
"""
from __future__ import annotations

STATUSES = ('candidate', 'refused')

#: The least a proposed row edit must rest on. A row may ask for more.
PROMOTION_FLOOR = {'min_prospective_sessions': 60, 'prospective_ic_ci95_lower_gt': 0.0}


def promotion_thresholds(config: dict | None) -> dict:
    """`PROMOTION_FLOOR` with a row's overrides; unknown or lower values refused."""
    config = dict(config or {})
    unknown = sorted(set(config) - set(PROMOTION_FLOOR))
    if unknown:
        raise ValueError(f'unknown promotion check(s) {unknown}; known: {sorted(PROMOTION_FLOOR)}')
    merged = {**PROMOTION_FLOOR, **config}
    lowered = sorted(key for key, floor in PROMOTION_FLOOR.items()
                     if isinstance(merged[key], bool) or not isinstance(merged[key], (int, float))
                     or merged[key] < floor)
    if lowered:
        raise ValueError(
            f'a row edit may not be proposed on less than the floor: {lowered} '
            f'(floor {({key: PROMOTION_FLOOR[key] for key in lowered})})')
    return merged


class BoundaryError(ValueError):
    """A lab record that claims more than the lab is allowed to conclude."""


def proposal_violations(report: dict) -> list[str]:
    found = []
    if report.get('live_permission') is not False:
        found.append(f"live_permission is {report.get('live_permission')!r}, must be false")
    status = report.get('status')
    if status not in STATUSES:
        found.append(f'status {status!r} is not one of {STATUSES}')
    checks = report.get('gate') or []
    failed = [item['check'] for item in checks if not item['passed']]
    if not checks:
        found.append('no registered gate checks were recorded')
    if (status == 'candidate') != (bool(checks) and not failed):
        found.append(f'status {status!r} is not the registered gate\'s verdict (failed: {failed})')
    if sorted(report.get('refused_because') or []) != sorted(failed):
        found.append('refused_because does not list the failed registered checks')
    alternates = report.get('alternate_gates') or []
    for alternate in alternates:
        if alternate.get('binding') is not False:
            found.append(f"alternate gate {alternate.get('id')!r} is marked binding")
    review = report.get('live_review') or {}
    objections = sorted(a['id'] for a in alternates
                        if a.get('effect') == 'live' and not a.get('would_pass'))
    if sorted(review.get('objections') or []) != objections:
        found.append(f'live_review.objections is not the refusing live alternates {objections}')
    if bool(review.get('cleared')) != (status == 'candidate' and not objections):
        found.append('live_review.cleared is not "registered gate passed and nothing objects"')
    required = (report.get('settings') or {}).get('gate', {}).get('corporate_actions_adjusted')
    adjusted = ((report.get('sample') or {}).get('bars') or {}).get('corporate_actions_adjusted')
    if status == 'candidate' and required and adjusted is not True:
        found.append('a candidate was measured on bars that do not say they are adjusted')
    for trial in report.get('prospective') or []:
        first = trial.get('first_session')
        if trial.get('sessions') and not (first and first > trial['after_session']):
            found.append(f"prospective score for {trial.get('params')} counts a session "
                         f"not after {trial.get('after_session')}")
    return found


def registration_violations(record: dict, report: dict) -> list[str]:
    found = []
    if record.get('live_permission') is not False:
        found.append(f"live_permission is {record.get('live_permission')!r}, must be false")
    if not (report.get('live_review') or {}).get('cleared'):
        found.append('the proposal it comes from was not cleared')
    if record.get('params') != report.get('selected_params'):
        found.append('params are not the ones the proposal selected')
    if record.get('after_session') != (report.get('sample') or {}).get('last_bar'):
        found.append('after_session is not the last bar the run was served')
    return found


def row_edit_violations(record: dict, registrations: list[dict]) -> list[str]:
    """What is wrong with a proposed row edit, against the floor and the registrations."""
    found = []
    if record.get('live_permission') is not False:
        found.append(f"live_permission is {record.get('live_permission')!r}, must be false")
    if record.get('status') != 'proposed':
        found.append(f"status {record.get('status')!r}: the lab proposes a row edit and never applies one")
    if record.get('to_params') == record.get('from_params'):
        found.append('it changes nothing')
    if not any(known.get('strategy') == record.get('strategy')
               and known.get('params') == record.get('to_params')
               and known.get('after_session') == record.get('after_session')
               for known in registrations):
        found.append('no registration carries these parameters from that session')
    evidence = record.get('evidence') or {}
    sessions, interval = evidence.get('sessions') or 0, evidence.get('ic_ci95')
    if sessions < PROMOTION_FLOOR['min_prospective_sessions']:
        found.append(f'{sessions} prospective sessions is under the floor')
    if not interval or not interval[0] > PROMOTION_FLOOR['prospective_ic_ci95_lower_gt']:
        found.append(f'prospective interval {interval} does not sit above the floor')
    first = evidence.get('first_session')
    if not (first and record.get('after_session') and first > record['after_session']):
        found.append('its evidence counts a session not after the registration')
    narrow = record.get('coverage_sensitivity')
    if narrow is not None and narrow.get('verdict_survives') is not True:
        found.append('the verdict does not survive without the single-source names')
    return found


def check_row_edit(record: dict, registrations: list[dict]) -> None:
    found = row_edit_violations(record, registrations)
    if found:
        raise BoundaryError(
            f"{record.get('strategy')}: row edit not proposed: " + '; '.join(found))


def check_proposal(report: dict) -> None:
    found = proposal_violations(report)
    if found:
        raise BoundaryError(f"{report.get('strategy')}: proposal not recorded: " + '; '.join(found))


def check_registration(record: dict, report: dict) -> None:
    found = registration_violations(record, report) + proposal_violations(report)
    if found:
        raise BoundaryError(
            f"{record.get('strategy')}: registration not written: " + '; '.join(found))


def verify(rows: list[dict], registrations: list[dict], row_edits: list[dict] = ()) -> list[str]:
    """Every violation in a ledger, its registrations and row edits as they are on disk."""
    found = []
    for number, record in enumerate(row_edits, 1):
        found.extend(f"row edit {number} ({record.get('strategy')}): {line}"
                     for line in row_edit_violations(record, registrations))
    for number, row in enumerate(rows, 1):
        where = f"ledger row {number} ({row.get('strategy')})"
        if row.get('live_permission') is not False:
            found.append(f'{where}: live_permission is not false')
        if row.get('status') not in STATUSES:
            found.append(f"{where}: status {row.get('status')!r}")
        if (row.get('status') == 'candidate') != (not row.get('refused_because')):
            found.append(f'{where}: status disagrees with refused_because')
        for alternate in row.get('alternate_gates') or []:
            if alternate.get('binding') is not False:
                found.append(f"{where}: alternate gate {alternate.get('id')!r} is binding")
        review = row.get('live_review')
        if review and review.get('cleared') and (
                row.get('status') != 'candidate' or review.get('objections')):
            found.append(f'{where}: cleared without a passing registered gate, or over an objection')
        # Rows written before this field existed were all judged by a gate
        # that required adjustment.
        if row.get('status') == 'candidate' and row.get('gate_requires_adjusted', True) and \
                (row.get('bars') or {}).get('corporate_actions_adjusted') is not True:
            found.append(f'{where}: candidate on bars that do not say they are adjusted')
        for trial in row.get('prospective') or []:
            first = trial.get('first_session')
            if trial.get('sessions') and first is not None and not first > trial['after_session']:
                found.append(f'{where}: prospective score counts a session not after '
                             f"{trial['after_session']}")
    cleared = {(row.get('strategy'), row.get('input_digest'))
               for row in rows if (row.get('live_review') or {}).get('cleared')}
    selected = {(row.get('strategy'), row.get('input_digest')): row.get('selected_params')
                for row in rows}
    for number, record in enumerate(registrations, 1):
        where = f"registration {number} ({record.get('strategy')})"
        key = (record.get('strategy'), record.get('input_digest'))
        if record.get('live_permission') is not False:
            found.append(f'{where}: live_permission is not false')
        if key not in cleared:
            found.append(f'{where}: no cleared ledger row with its input digest')
        elif selected[key] != record.get('params'):
            found.append(f'{where}: params are not the ones that run selected')
    return found
