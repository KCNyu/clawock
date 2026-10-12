"""The strategy-lab ledger: every proposal's verdicts, kept across runs.

A proposal file holds one run. Whether a gate is too tight, or an alternate
would have been right, is a question about many runs, so each `optimize`
appends one row here: the registered verdict, every alternate's verdict, and
the identity of what was measured.

It lives at `memory/strategy-lab/ledger.jsonl`, beside `memory/backtests`: both
are evidence that a research run happened, written at run time and never part
of a development change. It is not `memory/proposals.jsonl`, which records the
book's decision proposals and is read by the brief; nothing on the brief,
report or intraday path reads this file.

Rerunning the same question is not new evidence. A row carries `input_digest`
— strategy, registered parameters, search space, settings and the digest of the
bars served — and the statistics count each distinct input once, by its latest
row.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from clawock import code_identity
from clawock.safe_io import file_lock, jsonl_line
from clawock.strategy_lab import boundaries
from clawock.workspace import workspace_root

LEDGER = Path('memory') / 'strategy-lab' / 'ledger.jsonl'
REGISTRATIONS = Path('memory') / 'strategy-lab' / 'registrations.jsonl'
ROW_EDITS = Path('memory') / 'strategy-lab' / 'row-edits.jsonl'
SCHEMA_VERSION = 1


def ledger_path() -> Path:
    return workspace_root() / LEDGER


def registrations_path() -> Path:
    return workspace_root() / REGISTRATIONS


def row_edits_path() -> Path:
    return workspace_root() / ROW_EDITS


def row_edits(path: Path | None = None) -> list[dict]:
    """Row edits the lab has proposed. Proposed is all they ever are here."""
    return load(path or row_edits_path())


def propose_row_edit(proposal: dict, path: Path | None = None) -> dict | None:
    """Write a proposed row edit down, once per registration.

    The proposal is evidence for whoever reviews the row. It changes no row.
    """
    path = path or row_edits_path()
    record = {'schema_version': SCHEMA_VERSION,
              'proposed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              **proposal}
    boundaries.check_row_edit(record, registrations())
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(str(path)):
        if any(known['strategy'] == record['strategy'] and known['to_params'] == record['to_params']
               and known['after_session'] == record['after_session'] for known in row_edits(path)):
            return None
        with path.open('a', encoding='utf-8') as handle:
            handle.write(jsonl_line(record, label='strategy-lab row edits'))
    return record


def input_digest(report: dict) -> str:
    identity = {
        'strategy': report['strategy'],
        'registered_params': report['registered_params'],
        'space': report['search']['space'],
        'settings': report['settings'],
        'bars': report['sample']['bars'].get('digest'),
    }
    canonical = json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]


def row(report: dict) -> dict:
    """What of a proposal is worth keeping after the file is gone."""
    walk, bars = report['walk_forward'], report['sample']['bars']
    return {
        'schema_version': SCHEMA_VERSION,
        'recorded_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'code': code_identity.git_commit(workspace_root()),
        'input_digest': input_digest(report),
        'strategy': report['strategy'],
        'status': report['status'],
        'live_permission': False,
        'refused_because': report['refused_because'],
        'registered_params': report['registered_params'],
        'selected_params': report['selected_params'],
        'bars': {key: bars.get(key) for key in
                 ('source', 'adjustment', 'corporate_actions_adjusted', 'tickers', 'digest',
                  'basis')},
        'measured': {
            'oos_sessions': walk['oos_sessions'],
            'oos_ic_ci95': walk['oos_ic_ci95'],
            'oos_lift_ci95': walk['oos_lift_ci95'],
            'pbo': report['pbo'].get('pbo'),
            'oos_mean_net_excess': report['net_of_cost']['oos_mean_net_excess'],
            'oos_net_excess_ci95': report['net_of_cost']['oos_net_excess_ci95'],
        },
        'alternate_gates': [
            {'id': alternate['id'], 'binding': False,
             'would_pass': alternate['would_pass'],
             'agrees_with_registered': alternate['agrees_with_registered'],
             'would_refuse_because': alternate['would_refuse_because']}
            for alternate in report['alternate_gates']],
        'live_review': report.get('live_review'),
        'prospective': report.get('prospective', []),
        # The same search without the names the provider only has no action on
        # record for; null when the source does not split them.
        'coverage_sensitivity': report.get('coverage_sensitivity'),
        'gate_requires_adjusted': bool(
            report['settings']['gate'].get('corporate_actions_adjusted')),
    }


def registrations(path: Path | None = None) -> list[dict]:
    """Cleared parameters, each with the last session its run was served."""
    return load(path or registrations_path())


def register(report: dict, path: Path | None = None) -> dict | None:
    """Write a cleared candidate's selected parameters down, once.

    Registering starts prospective scoring: later runs score these parameters
    on the sessions after `after_session` only. It grants nothing else; the
    row says `live_permission: false` like the proposal it came from.
    """
    review = report.get('live_review') or {}
    if not review.get('cleared') or not report.get('selected_params'):
        return None
    path = path or registrations_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        'schema_version': SCHEMA_VERSION,
        'registered_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'strategy': report['strategy'],
        'params': report['selected_params'],
        'after_session': report['sample']['last_bar'],
        'input_digest': input_digest(report),
        'cleared_by': {'gate': 'registered', 'live_alternates': review['alternates']},
        'live_permission': False,
    }
    boundaries.check_registration(record, report)
    with file_lock(str(path)):
        if any(known['strategy'] == record['strategy'] and known['params'] == record['params']
               for known in registrations(path)):
            return None
        with path.open('a', encoding='utf-8') as handle:
            handle.write(jsonl_line(record, label='strategy-lab registrations'))
    return record


def append(report: dict, path: Path | None = None) -> dict:
    path = path or ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    boundaries.check_proposal(report)
    record = row(report)
    with file_lock(str(path)):
        with path.open('a', encoding='utf-8') as handle:
            handle.write(jsonl_line(record, label='strategy-lab ledger'))
    return record


def load(path: Path | None = None) -> list[dict]:
    path = path or ledger_path()
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            # A torn row is a missing run, and a yield computed around it would
            # be a rate over an unknown denominator.
            raise ValueError(f'{path}:{number}: unreadable ledger row') from exc
    return rows


def statistics(rows: list[dict]) -> dict:
    """Yield per strategy over distinct inputs; alternates beside the gate."""
    latest: dict[tuple, dict] = {}
    runs: dict[str, int] = {}
    for record in rows:
        runs[record['strategy']] = runs.get(record['strategy'], 0) + 1
        latest[(record['strategy'], record['input_digest'])] = record
    out = {}
    for (strategy, _), record in latest.items():
        entry = out.setdefault(strategy, {
            'runs': runs[strategy], 'distinct_inputs': 0, 'candidates': 0, 'cleared': 0,
            'refused': 0, 'refused_by_check': {}, 'objections': {}, 'alternate_gates': {}})
        entry['distinct_inputs'] += 1
        entry['candidates' if record['status'] == 'candidate' else 'refused'] += 1
        # Rows written before alternates had live effect carry no review.
        review = record.get('live_review') or {}
        entry['cleared'] += bool(review.get('cleared'))
        if record['status'] == 'candidate':
            for identifier in review.get('objections', []):
                entry['objections'][identifier] = entry['objections'].get(identifier, 0) + 1
        for check in record['refused_because']:
            entry['refused_by_check'][check] = entry['refused_by_check'].get(check, 0) + 1
        for alternate in record['alternate_gates']:
            tally = entry['alternate_gates'].setdefault(alternate['id'], {
                'binding': False, 'judged': 0, 'would_pass': 0,
                'disagrees_with_registered': 0})
            tally['judged'] += 1
            tally['would_pass'] += bool(alternate['would_pass'])
            tally['disagrees_with_registered'] += not alternate['agrees_with_registered']
    for entry in out.values():
        entry['candidate_rate'] = round(entry['candidates'] / entry['distinct_inputs'], 4)
    return {'schema_version': SCHEMA_VERSION, 'rows': len(rows),
            'strategies': dict(sorted(out.items()))}
