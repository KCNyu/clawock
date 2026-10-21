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
from clawock.code_identity import git_commit, file_digest as _file_digest
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
    'regime',
    'execution_status',
    'override_status',
    'signal_provenance_schema_version',
    'sizing_active',
    'sizing_contributors',
    'information_usable_for_decisions',
    'information_activation_progress',
    'information_activation_blockers',
    'evaluation',
)


def _projection(row: dict, fields=CONSUMED_FIELDS) -> dict:
    """The part of one decision the scorecard can see, over `fields`.

    `regime` keys the confidence calibrator and `information.*` feeds the
    overlay's reachability counts; both were read but left out until #2188.
    A block published before that lists the older `ledger.fields`, and is
    verified over exactly those.
    """
    evaluation = row.get('evaluation') or {}
    provenance = row.get('signal_provenance') or {}
    sizing = provenance.get('sizing') or {}
    contributors = sizing.get('contributors') or []
    information = provenance.get('information') or {}
    full = {
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
        'regime': row.get('regime'),
        'information_usable_for_decisions': information.get('usable_for_decisions'),
        'information_activation_progress': information.get('activation_progress'),
        'information_activation_blockers': sorted(
            str(b) for b in information.get('activation_blockers') or []),
        'evaluation': {k: evaluation.get(k) for k in EVALUATION_FIELDS},
    }
    return {field: full.get(field) for field in fields}


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'))


def rows_digest(rows, fields=CONSUMED_FIELDS) -> str:
    """Digest of a set of decisions over the fields the scorecard consumes.

    Order-independent on purpose: the ledger is append-only, but a rewrite that
    only reorders rows produces the same metrics, so it must produce the same
    digest. Two ledgers agreeing here produce the same scorecard under the same
    code; disagreeing means some number on the page can move.
    """
    projections = sorted(
        (_canonical(_projection(row, fields)) for row in rows))
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
    return git_commit(WS)


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


def settlement_source_digest(rows):
    """Settlement inputs, including complete conditions/shares, excluding re-derived evaluation."""
    projected = [json.dumps({k: v for k, v in row.items() if k != 'evaluation'},
                            sort_keys=True, ensure_ascii=False, separators=(',', ':'))
                 for row in rows]
    return hashlib.sha256('\n'.join(sorted(projected)).encode()).hexdigest()


def committed_ref(workspace, ref):
    """Resolve a ref once, shared by source reads and the input fingerprint."""
    return subprocess.run(
        ['git', 'rev-parse', '--verify', '--end-of-options', f'{ref}^{{commit}}'], cwd=workspace,
        capture_output=True, text=True, timeout=15, check=True).stdout.strip()


def committed_source(workspace, ref='HEAD'):
    """Read one immutable ledger generation; never consume uncommitted execution edits."""
    commit = committed_ref(workspace, ref)
    raw = subprocess.run(
        ['git', 'show', f'{commit}:{LEDGER_PATH}'], cwd=workspace,
        capture_output=True, text=True, timeout=15, check=True).stdout
    return [json.loads(line) for line in raw.splitlines() if line.strip()], commit


def dashboard_source(workspace):
    """Publish only a ledger generation already fetched from the public master.

    A local runtime HEAD can still be unpushed, or disappear in a rebase. The
    remote-tracking ref is immutable once resolved by committed_source; a stale
    fetch merely delays new ledger rows. A Git checkout without that ref fails
    closed. Portable desks without Git remain explicitly unversioned.
    """
    if git_commit(workspace) is not None:
        return committed_source(workspace, ref='refs/remotes/origin/master')
    path = Path(workspace) / LEDGER_PATH
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    return [json.loads(line) for line in text.splitlines() if line.strip()], None


def record_live_snapshot(provenance, rows, workspace, *, writeback_input=None):
    """Pin brief scores after execution writeback to a content-addressed input.

    Store complete settled rows: later execution edits or bar corrections must
    not destroy the evidence used for this brief. This is local runtime data.
    """
    from clawock.safe_io import safe_write_text

    def persist(source):
        raw = ''.join(_canonical(row) + '\n' for row in source)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        ref = f'memory/scorecard-inputs/{digest}.jsonl'
        safe_write_text(str(Path(workspace) / ref), raw)
        return ref, digest

    ref, digest = persist(rows)
    ledger = provenance['ledger']
    ledger.update(source_kind='live_snapshot', source_ref=ref,
                  view='snapshot_settled', source_digest=digest,
                  source_projection='complete_settled_rows',
                  source_slice_digest=rows_digest(slice_rows(
                      rows, provenance['window']['cutoff'],
                      provenance['window'].get('last_plan_date'))))
    if writeback_input is not None:
        before_ref, before_digest = persist(writeback_input)
        ledger['writeback_input'] = {
            'source_ref': before_ref, 'source_digest': before_digest,
            'settlement_source_digest': settlement_source_digest(writeback_input),
        }
    provenance['note'] = (
        'Brief execution detection and settlement have been written back. '
        'source_ref preserves the exact settled input locally; source_digest is '
        'the SHA-256 of that snapshot. Verification does not re-settle newer bars.')
    return provenance


def load_live_snapshot(provenance, workspace):
    ledger = provenance['ledger']
    ref = ledger['source_ref']
    digest = ledger['source_digest']
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in '0123456789abcdef' for c in digest)
            or ref != f'memory/scorecard-inputs/{digest}.jsonl'):
        raise ValueError('invalid scorecard snapshot reference')
    raw = (Path(workspace) / ref).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('scorecard snapshot digest mismatch')
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def verify_committed_source(provenance, workspace, *, fetch_missing=False):
    """The artifact gate checks source identity without re-grading against newer bars."""
    ledger = provenance.get('ledger') or {}
    if ledger.get('source_kind') == 'live_snapshot':
        load_live_snapshot(provenance, workspace)
        return
    if not ledger.get('source_ref'):
        return  # Legacy generations predate the pinned-source contract.
    ref = ledger['source_ref']
    if fetch_missing:
        # Fetch only missing commit objects, never on a digest mismatch. Accept
        # full SHA identities, not arbitrary refs/options from a public payload.
        if not isinstance(ref, str) or len(ref) != 40 or any(c not in '0123456789abcdef' for c in ref):
            raise ValueError('ledger.source_ref must be a full commit SHA')
        exists = subprocess.run(['git', 'cat-file', '-e', f'{ref}^{{commit}}'],
                                cwd=workspace, capture_output=True, timeout=15)
        if exists.returncode:
            subprocess.run(['git', 'fetch', '--no-tags', 'origin', ref], cwd=workspace,
                           capture_output=True, text=True, timeout=30, check=True)
    rows, _ = committed_source(workspace, ref)
    if settlement_source_digest(rows) != ledger.get('source_digest'):
        raise ValueError('ledger.source_digest does not match source_ref')
    window = provenance['window']
    sliced = slice_rows(rows, window['cutoff'], window.get('last_plan_date'))
    if settlement_source_digest(sliced) != ledger.get('source_slice_digest'):
        raise ValueError('ledger.source_slice_digest does not match source_ref')


def verify_public_source(provenance, workspace):
    """Publish a public-source promise only after both identity and ancestry pass."""
    verify_committed_source(provenance, workspace)
    ledger = provenance.get('ledger') or {}
    ledger['public_source_verified'] = False
    if ledger.get('source_kind') != 'committed' or not ledger.get('source_ref'):
        return
    subprocess.run(['git', 'merge-base', '--is-ancestor', ledger['source_ref'],
                    'refs/remotes/origin/master'], cwd=workspace,
                   capture_output=True, text=True, timeout=15, check=True)
    ledger['public_source_verified'] = True


def record_settlement_view(provenance, source_rows, *, settlement_day=None, source_ref=None):
    """Bind the effective in-memory scorecard to its unmodified public source."""
    ledger = provenance['ledger']
    window = provenance['window']
    ledger['source_kind'] = 'committed' if source_ref else 'unversioned_working_copy'
    if source_ref:
        ledger['source_ref'] = source_ref
    ledger['view'] = 'in_memory_settled'
    ledger['settlement_day'] = settlement_day or provenance['generated_at'][:10]
    ledger['source_projection'] = 'all_non_evaluation_fields'
    ledger['source_digest'] = settlement_source_digest(source_rows)
    ledger['source_slice_digest'] = settlement_source_digest(slice_rows(
        source_rows, window['cutoff'], window.get('last_plan_date')))
    provenance['note'] = (
        'The source is the committed decision ledger at source_ref when present; '
        'uncommitted execution edits await their runtime commit. Metrics use an in-memory '
        'settled view, not a committed re-grade. Verification checks the source '
        'input identity (all non-evaluation fields; evaluation is re-derived), '
        'replays settlement from canonical bars, then checks the '
        'effective digests and counts; changed bars can change that view.')
    return provenance


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
    # Hash what the block says it covered, so a card published before a field
    # joined the contract still verifies against its own digest (#2188).
    fields = tuple(ledger.get('fields') or CONSUMED_FIELDS)

    recomputed_slice = rows_digest(window_rows, fields)
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

    recomputed_all = rows_digest(rows, fields)
    published_all = ledger.get('digest')
    # Growth is the only change this check waves through, so it has to be
    # growth: with the row count unchanged, a different digest means rows that
    # were already there read differently now (#2346).
    grew = len(rows) != ledger.get('rows_total')
    checks.append({
        'name': 'ledger.digest',
        'status': ('pass' if recomputed_all == published_all
                   else 'moved' if grew else 'fail'),
        'expected': published_all,
        'actual': recomputed_all,
        'detail': (
            f'{len(rows)} rows now vs {ledger.get("rows_total")} when published'
            + (' — unchanged' if recomputed_all == published_all else
               ' — later sessions appending is expected' if grew else
               ' — the row count is unchanged, so existing rows were rewritten')),
    })
    return {'ok': all(c['status'] in ('pass', 'moved') for c in checks),
            'checks': checks}
