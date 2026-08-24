#!/usr/bin/env python3
"""
gc_sessions.py — clean up stale openclaw session/log artifacts.

All 11 cron jobs run with sessionTarget=isolated, so each invocation creates a
fresh session file + trajectory.jsonl that nothing ever deletes. At ~70 files
per day (~25 MB/day) the sessions/ dir grows ~9 GB/year unattended.

This script removes:
  - sessions/*.trajectory.jsonl     older than KEEP_TRAJECTORY_DAYS
  - sessions/*.jsonl (plain)        older than KEEP_SESSION_DAYS
  - sessions/*.json (non-jsonl)     older than KEEP_SESSION_DAYS
  - sessions/bak-* / pre-cleanup-*  older than KEEP_BAK_DAYS
  - gateway-supervisor-restart-handoff.json if expired

Defaults are conservative; tune via env vars if needed.
Designed to run as a daily cron (~03:00 HKT, after overnight monitor ends 02:30
and before US close 04:05 — see openclaw-intraday-cron-no-overlap memory).

Idempotent + dry-run via --dry-run. Failures non-fatal (prints + exits 0).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))
from clawock.providers.openclaw import runtime_paths  # noqa: E402

_OPENCLAW_PATHS = runtime_paths()
SESSIONS_DIR = _OPENCLAW_PATHS.sessions_dir
HANDOFF_FILE = _OPENCLAW_PATHS.supervisor_handoff
WORKSPACE_TMP = _OPENCLAW_PATHS.workspace_memory_tmp

KEEP_TRAJECTORY_DAYS = int(os.environ.get('GC_KEEP_TRAJECTORY_DAYS', '7'))
KEEP_SESSION_DAYS    = int(os.environ.get('GC_KEEP_SESSION_DAYS',    '14'))
KEEP_BAK_DAYS        = int(os.environ.get('GC_KEEP_BAK_DAYS',        '3'))
KEEP_TMP_DAYS        = int(os.environ.get('GC_KEEP_TMP_DAYS',        '14'))

for _name, _days in (('GC_KEEP_TRAJECTORY_DAYS', KEEP_TRAJECTORY_DAYS),
                     ('GC_KEEP_SESSION_DAYS', KEEP_SESSION_DAYS),
                     ('GC_KEEP_BAK_DAYS', KEEP_BAK_DAYS),
                     ('GC_KEEP_TMP_DAYS', KEEP_TMP_DAYS)):
    if _days < 0:
        # A negative retention makes "older than cutoff" true for files that
        # do not exist yet — i.e. delete everything, then keep deleting.
        raise SystemExit(f'gc_sessions: {_name}={_days} is negative; '
                         f'refusing to run (see #930)')


def humansize(n):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


# Every SESSIONS_DIR sweep rule in one place: (report label, name predicate,
# retention days). A file may match several rules (e.g. x.bak-1.jsonl matches
# both the plain-.jsonl and the bak rule); it is deleted iff ANY matching
# rule's cutoff makes it stale — exactly what the old per-rule passes did —
# and is reported under its most permissive match.
SESSION_RULES = [
    ('trajectory.jsonl',
     lambda n: n.endswith('.trajectory.jsonl'),
     KEEP_TRAJECTORY_DAYS),
    ('plain .jsonl',
     lambda n: n.endswith('.jsonl'),
     KEEP_SESSION_DAYS),
    ('.json sidecar',
     lambda n: n.endswith('.json'),
     KEEP_SESSION_DAYS),
    ('bak / pre-cleanup',
     lambda n: '.bak-' in n or '.pre-cleanup-' in n or n.endswith('.bak'),
     KEEP_BAK_DAYS),
    # Stale rename leftovers like *.jsonl.1779044443580 (epoch-ms suffix)
    ('tmp / numeric-suffix',
     lambda n: any(n.endswith(suf) for suf in ('.tmp', '.old')) or
               n.split('.')[-1].isdigit() and len(n.split('.')[-1]) >= 10,
     KEEP_BAK_DAYS),
    # Tombstones like *.jsonl.deleted.2026-06-14T19-00-50.702Z / *.jsonl.reset.<iso>.
    # The suffix is an ISO timestamp ending in "Z", so it matches none of the
    # predicates above (not .jsonl/.json/.bak, and "702Z" is not .isdigit()) —
    # these accumulated unbounded until 2026-07-15 (78 files back to 06-13).
    # The live transcript is already gone by the time one is written, so they
    # age out on the same clock as a plain session.
    ('deleted / reset tombstone',
     lambda n: '.jsonl.deleted.' in n or '.jsonl.reset.' in n,
     KEEP_SESSION_DAYS),
]


def gc_files(pattern_predicate, cutoff_ts, label, dry_run, dirpath=None):
    """Walk dirpath (default SESSIONS_DIR), delete matching files older than cutoff."""
    dirpath = dirpath or SESSIONS_DIR
    if not dirpath.exists():
        return 0, 0
    n_files, n_bytes = 0, 0
    for p in dirpath.iterdir():
        if not p.is_file():
            continue
        if not pattern_predicate(p.name):
            continue
        try:
            mt = p.stat().st_mtime
            sz = p.stat().st_size
        except FileNotFoundError:
            continue
        if mt >= cutoff_ts:
            continue
        n_files += 1
        n_bytes += sz
        if not dry_run:
            try:
                p.unlink()
            except OSError as e:
                print(f'  skip {p.name}: {e}', file=sys.stderr)
    print(f'  {label}: {n_files} files, {humansize(n_bytes)}')
    return n_files, n_bytes


def gc_sessions_dir(now_ts, dry_run, allow_future=False):
    """One traversal for every SESSIONS_DIR rule.

    The sweeps used to be six full iterdir() passes re-stating every candidate
    twice (~18k stats a night); each file is now visited once and statted once.

    A far-future ``now_ts`` makes every file stale by definition — one wrong
    argument deletes the whole tree (the agent-E incident, #930: a review
    simulation passed a synthetic 2027 timestamp against the real default
    SESSIONS_DIR). Refuse such clocks loudly; the CLI passes time.time() and
    never trips this.
    """
    if not allow_future and now_ts > time.time() + 300:
        raise ValueError(
            f'now_ts ({now_ts}) is more than 5 minutes ahead of the wall '
            f'clock — refusing bulk deletion; pass allow_future=True only '
            f'from a test/simulation with an explicit scratch directory')
    if not SESSIONS_DIR.exists():
        return 0, 0
    per_rule = {label: [0, 0] for label, _, _ in SESSION_RULES}
    for p in SESSIONS_DIR.iterdir():
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        matches = [(label, now_ts - days * 86400)
                   for label, pred, days in SESSION_RULES if pred(p.name)]
        if not matches:
            continue
        label, cutoff = max(matches, key=lambda m: m[1])
        if st.st_mtime >= cutoff:
            continue
        per_rule[label][0] += 1
        per_rule[label][1] += st.st_size
        if not dry_run:
            try:
                p.unlink()
            except OSError as e:
                print(f'  skip {p.name}: {e}', file=sys.stderr)
    total_files, total_bytes = 0, 0
    for label, _, _ in SESSION_RULES:
        n, b = per_rule[label]
        if n:
            print(f'  {label}: {n} files, {humansize(b)}')
        total_files += n
        total_bytes += b
    return total_files, total_bytes


def gc_handoff(dry_run):
    if not HANDOFF_FILE.exists():
        return False
    try:
        data = json.loads(HANDOFF_FILE.read_text())
    except Exception as e:
        print(f'  handoff unreadable, leaving in place: {e}')
        return False
    expires = data.get('expiresAt', 0) / 1000
    if expires == 0 or expires >= time.time():
        return False
    age_h = (time.time() - expires) / 3600
    print(f'  handoff: expired {age_h:.1f}h ago, removing')
    if not dry_run:
        try:
            HANDOFF_FILE.unlink()
        except OSError as e:
            print(f'    skip: {e}', file=sys.stderr)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Print but do not delete')
    args = parser.parse_args()

    now = time.time()
    print(f'gc_sessions: dir={SESSIONS_DIR} dry_run={args.dry_run}')
    print(f'  keep trajectory ≤ {KEEP_TRAJECTORY_DAYS}d, session ≤ {KEEP_SESSION_DAYS}d, '
          f'bak ≤ {KEEP_BAK_DAYS}d, workspace .tmp ≤ {KEEP_TMP_DAYS}d')

    total_files, total_bytes = gc_sessions_dir(now, args.dry_run)

    # workspace memory/.tmp — preflight contexts / sidecars / scratch PNGs.
    # Everything here is per-date scratch that builders read by "newest mtime"
    # or with a max-age guard (load_tmp_sidecar), so anything ≥ KEEP_TMP_DAYS
    # old is dead weight. Before 2026-06-10 nothing GC'd this dir (231 stale
    # files incl. ~470KB PNGs after 3 weeks of cron traffic).
    f, b = gc_files(
        lambda n: True,
        now - KEEP_TMP_DAYS * 86400,
        f'workspace .tmp (> {KEEP_TMP_DAYS}d)', args.dry_run,
        dirpath=WORKSPACE_TMP,
    )
    total_files += f
    total_bytes += b

    # Expired gateway-supervisor-restart-handoff
    gc_handoff(args.dry_run)

    action = 'would free' if args.dry_run else 'freed'
    print(f'gc_sessions: {action} {total_files} files / {humansize(total_bytes)}')


if __name__ == '__main__':
    main()
