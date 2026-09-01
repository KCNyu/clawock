"""Provenance for the published scorecard: which rows produced this number.

The gap this closes
-------------------
`evidence/run_card.py` gives a *backtest* an input identity, a parameter set,
code digests and its metrics, and `evidence/claim_provenance.py` makes CI refuse
a backtest claim that no longer matches its card. The daily scorecard — the win
rate, the Brier score, the follow-through rate the dashboard actually shows —
had no equivalent. A reader looking at "win rate 0.48 (30d)" could not get from
that number to the rows that produced it, and could not tell whether the ledger
had been re-settled since.

Tamper-evidence is not the missing piece and this module does not pretend to add
it: `memory/decisions.jsonl` lives in a public repository, so every re-grade is
already a commit with an author, a timestamp and a readable diff, and a digest
the publisher computes beside the number it describes proves nothing the git
history does not (that reasoning closed #1119). What was missing is
**traversal**: naming the exact slice consumed, so a third party can recompute
the headline from the public ledger and see whether it still holds.

What a scorecard provenance block records
-----------------------------------------
* **window** — the rolling cutoff the metrics were computed at, plus the first
  and last plan date actually present in the slice, so the slice is defined by
  recorded bounds instead of by whatever "30 days ago" means when you read it;
* **ledger identity** — a digest of the whole ledger as consumed, and a digest
  of the in-window slice, both over the fields the scorecard reads and nothing
  else. Editing a `rationale` does not move them; re-settling an outcome does,
  which is exactly the change a reader wants to see;
* **counts** — rows, episodes and settled episodes, so a digest mismatch can
  say whether rows were added or existing rows changed;
* **code identity** — the commit and a digest of `decision/ledger.py`, because
  the same rows under a changed metric definition are a different number.

Verification (`clawock scorecard-provenance --check`) recomputes the slice
digest from a ledger — the working copy, or any git ref via `--ref` — and, with
`--recompute`, re-derives the headline numbers at the recorded cutoff and
compares them to the published ones. That command lives in
`evidence.scorecard_verify`; this module holds only the shape and the
digests, because `decision.ledger` attaches the block and must not import a
package that sits above it.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from clawock.workspace import workspace_root

WS = workspace_root()
SCHEMA_VERSION = 1
LEDGER_PATH = 'memory/decisions.jsonl'
DASHBOARD_PATH = 'assets/data/dashboard.json'

#: Evaluation fields the scorecard reads. Kept explicit rather than digesting the
#: whole evaluation object: settlement writes bookkeeping into it (pending
#: reasons, session labels) that no published metric consumes, and a digest that
#: moves on those would cry wolf on every rerun.
EVALUATION_FIELDS = (
    'outcome',
    'status',
    'triggered',
    'not_evaluable_reason',
    'benefit_t1_pct',
    'benefit_t5_pct',
    'benefit_t20_pct',
    'capital',
    'episode_mean_money',
    'mark_t1_session',
)

#: Row-level fields the scorecard reads, in the order the projection emits them.
#: This tuple is the published contract for what the digest covers.
CONSUMED_FIELDS = (
    'decision_id',
    'plan_date',
    'created_at',
    'ticker',
    'leg',
    'action',
    'episode_id',
    'strategy_id',
    'driven_by',
    'condition_type',
    'technical_setup_id',
    'confidence',
    'execution_status',
    'override_status',
    'signal_provenance_schema_version',
    'sizing_active',
    'sizing_contributors',
    'evaluation',
)


def _projection(row: dict) -> dict:
    """The part of one decision the scorecard can see."""
    evaluation = row.get('evaluation') or {}
    provenance = row.get('signal_provenance') or {}
    sizing = provenance.get('sizing') or {}
    contributors = sizing.get('contributors') or []
    return {
        'decision_id': row.get('decision_id'),
        'plan_date': row.get('plan_date'),
        'created_at': row.get('created_at'),
        'ticker': row.get('ticker'),
        'leg': row.get('leg'),
        'action': row.get('action'),
        'episode_id': row.get('episode_id'),
        'strategy_id': row.get('strategy_id'),
        'driven_by': row.get('driven_by'),
        'condition_type': (row.get('condition') or {}).get('type'),
        'technical_setup_id': row.get('technical_setup_id'),
        'confidence': row.get('confidence'),
        'execution_status': (row.get('execution') or {}).get('status'),
        'override_status': (row.get('override') or {}).get('status'),
        'signal_provenance_schema_version': provenance.get('schema_version'),
        'sizing_active': sizing.get('sizing_active'),
        'sizing_contributors': sorted(str(c) for c in contributors),
        'evaluation': {k: evaluation.get(k) for k in EVALUATION_FIELDS},
    }


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'))


def rows_digest(rows) -> str:
    """Digest of a set of decisions over the fields the scorecard consumes.

    Order-independent on purpose: the ledger is append-only, but a rewrite that
    only reorders rows produces the same metrics, so it must produce the same
    digest. Two ledgers agreeing here produce the same scorecard under the same
    code; disagreeing means some number on the page can move.
    """
    projections = sorted(
        (_canonical(_projection(row)) for row in rows))
    hasher = hashlib.sha256()
    for line in projections:
        hasher.update(line.encode())
        hasher.update(b'\n')
    return f'sha256:{hasher.hexdigest()[:16]}'


def slice_rows(rows, cutoff: str, last_plan_date: str | None = None) -> list[dict]:
    """The rows a windowed scorecard saw, by recorded bounds rather than by clock.

    ``cutoff`` alone would keep matching a ledger that has since grown: rows
    added after publication carry later plan dates and would silently join the
    slice, so a later verification would hash a different population and report
    a mismatch that is not a change to the published number. Bounding the top at
    the last plan date present when the card was written keeps the slice fixed.
    """
    out = []
    for row in rows:
        plan_date = row.get('plan_date') or ''
        if plan_date < cutoff:
            continue
        if last_plan_date is not None and plan_date > last_plan_date:
            continue
        out.append(row)
    return out


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=WS,
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _file_digest(path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    return f'sha256:{hashlib.sha256(path.read_bytes()).hexdigest()[:16]}'


def build(decisions, *, window_days: int, cutoff: str, counts: dict,
          generated_at: str | None = None,
          code_files=(), ledger_path: str = LEDGER_PATH) -> dict:
    """Assemble the block. Pure apart from the git commit and code digests."""
    in_window = [d for d in decisions if (d.get('plan_date') or '') >= cutoff]
    plan_dates = sorted(d.get('plan_date') for d in in_window if d.get('plan_date'))
    last_plan_date = plan_dates[-1] if plan_dates else None
    window_rows = slice_rows(decisions, cutoff, last_plan_date)
    code = []
    for path in code_files:
        path = Path(path)
        code.append({'file': path.name, 'digest': _file_digest(path)})
    return {
        'schema_version': SCHEMA_VERSION,
        # `generated_at`, not `computed_at`: it is run_card's name for the same
        # thing, and CI's rebuild-determinism gate strips exactly this key set
        # ({generated_at, generation_id, as_of, age_hours}) before diffing two
        # builds. A second name for a timestamp would make every rebuild look
        # like a changed payload.
        'generated_at': generated_at or datetime.now(timezone.utc).isoformat(
            timespec='seconds'),
        'code_commit': _git_commit(),
        'code': code,
        'ledger': {
            'path': ledger_path,
            'rows_total': len(decisions),
            'digest': rows_digest(decisions),
            'slice_rows': len(window_rows),
            'slice_digest': rows_digest(window_rows),
            'fields': list(CONSUMED_FIELDS),
        },
        'window': {
            'days': window_days,
            'cutoff': cutoff,
            'first_plan_date': plan_dates[0] if plan_dates else None,
            'last_plan_date': last_plan_date,
        },
        'counts': dict(counts),
        'verify': 'clawock scorecard-provenance --check',
        'note': (
            'Digests cover the fields listed under ledger.fields and nothing '
            'else, so prose edits do not move them and a re-settled outcome '
            'does. They identify the slice; the public git history of '
            f'{ledger_path} is what makes a change to it visible.'),
    }


def verify(provenance: dict, decisions) -> dict:
    """Recompute the digests from `decisions` and compare with a published block.

    Returns a result with one entry per check. A changed slice digest is a real
    finding — the published number no longer follows from the ledger — while a
    changed full-ledger digest with an intact slice is normal daily growth and
    is reported as `moved`, not as a failure.
    """
    checks = []
    ledger = provenance.get('ledger') or {}
    window = provenance.get('window') or {}
    cutoff = window.get('cutoff')
    if not cutoff:
        return {'ok': False, 'checks': [
            {'name': 'window.cutoff', 'status': 'fail',
             'detail': 'provenance block has no window cutoff to verify against'}]}
    rows = list(decisions)
    window_rows = slice_rows(rows, cutoff, window.get('last_plan_date'))

    recomputed_slice = rows_digest(window_rows)
    published_slice = ledger.get('slice_digest')
    checks.append({
        'name': 'ledger.slice_digest',
        'status': 'pass' if recomputed_slice == published_slice else 'fail',
        'expected': published_slice,
        'actual': recomputed_slice,
        'detail': (
            f'{len(window_rows)} rows in [{cutoff}, {window.get("last_plan_date")}]'),
    })
    checks.append({
        'name': 'ledger.slice_rows',
        'status': 'pass' if len(window_rows) == ledger.get('slice_rows') else 'fail',
        'expected': ledger.get('slice_rows'),
        'actual': len(window_rows),
    })

    recomputed_all = rows_digest(rows)
    published_all = ledger.get('digest')
    checks.append({
        'name': 'ledger.digest',
        'status': 'pass' if recomputed_all == published_all else 'moved',
        'expected': published_all,
        'actual': recomputed_all,
        'detail': (
            f'{len(rows)} rows now vs {ledger.get("rows_total")} when published'
            ' — later sessions appending is expected'),
    })
    return {'ok': all(c['status'] in ('pass', 'moved') for c in checks),
            'checks': checks}
