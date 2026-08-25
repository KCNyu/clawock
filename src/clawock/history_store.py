"""Rolling storage for the dated JSONL histories under ``assets/data/``.

The four point-in-time histories (news evidence, cross-sectional factors, peer
residuals, quant signals) are **rewritten whole** every day by the jobs that
append to them, and until now none of them had a bound: ``news_evidence_history``
alone went 487KB → 855KB in fourteen days and was accelerating (#951). At that
rate every daily commit carries the whole file again, and every ``fetch-depth: 0``
checkout carries every one of those versions.

The naive fix — truncate the file — is not available, because two readers
legitimately want the entire series:

* ``news_evidence_graph.apply_novelty`` scores a cluster last seen beyond the
  30d lookback as ``cluster_old_but_recurrent`` (0.8) rather than
  ``new_cluster`` (1.0). Cut the tail and「旧事重提」silently reads as brand new.
* ``factors.prospective_walk_forward`` / ``add_alpha_walkforward`` replay from
  the first row. Cut the tail and the evaluation window shortens, which moves
  hit rates and episode counts.

So the decision (2026-08-25) is a **storage split, not a semantic change**:

* the working file keeps the most recent ``HOT_WINDOW_DAYS`` of snapshots — this
  is the file the daily job rewrites, so daily churn is bounded from now on;
* everything older moves once into ``assets/data/archive/<same name>``, which is
  only ever appended to (a row moves in when it ages out and is never rewritten);
* every reader that wants the series calls :func:`load_series`, which returns
  archive + working. **Novelty semantics and the replay window are therefore
  unchanged** — that is the point of doing it this way rather than capping.

The archive is also the seam: moving cold rows off master (to the data branch or
out of the repo) later becomes a change of one path here, instead of a migration
of four writers and three readers.

#951 originally covered only row-level JSONL series. ``memory/snapshots/`` has
the same disease in file form (#1040): one dated file per trading day, readers
that look at at most the last 90 entries, storage that grows forever. Those are
handled by :func:`roll_dated_files`, the file-level analogue of
``split_window``: whole files past the hot window move into a sibling
``_archive/`` directory instead of rows being partitioned across two files.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from clawock.safe_io import safe_write_text

# Six months of hot rows. Every in-run lookback the daily jobs use is far
# shorter (novelty 30d, factor windows ≤ 120d), so this is not a behaviour
# knob — it is how much a single day's rewrite is allowed to carry.
HOT_WINDOW_DAYS = 180

DATE_KEY = 'as_of'

# A file whose entire name is a date — the memory/snapshots/ shape
# (``2026-08-26.json``). Strict full match on purpose: tagged one-offs like
# ``2026-05-16-saturday-baseline.json`` are not daily churn (never rewritten),
# and the dashboard's snapshot filter must keep agreeing with this set, so
# ``publish.dashboard.SNAPSHOT_FNAME_RE`` is aliased to this constant.
DATED_FILE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\.json$')

ARCHIVE_DIR_NAME = '_archive'


def archive_path(path) -> Path:
    """Where the cold half of ``path`` lives."""
    path = Path(path)
    return path.parent / 'archive' / path.name


def _read_jsonl(path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            # A half-written line is a torn write, not a reason to lose the
            # rest of the series. Same tolerance the previous loaders had.
            continue
    return rows


def _dump(rows) -> str:
    return '\n'.join(
        json.dumps(row, ensure_ascii=False, separators=(',', ':'))
        for row in rows
    ) + '\n'


def _day(row) -> str:
    return str((row or {}).get(DATE_KEY) or '')[:10]


def load_series(path) -> list:
    """The whole logical series: archived rows first, then the hot window.

    Readers must use this instead of reading the working file directly —
    reading only the working file is exactly the truncation this module exists
    to avoid.
    """
    rows = _read_jsonl(archive_path(path)) + _read_jsonl(path)
    return sorted(rows, key=_day)


def split_window(rows, *, keep_days=HOT_WINDOW_DAYS, today=None):
    """Partition ``rows`` into (cold, hot) on the ``keep_days`` boundary.

    Rows without a usable ``as_of`` stay hot: an undated row cannot be proven
    old, and silently archiving it would hide it from the readers that still
    scan the working file.
    """
    today = today or datetime.now(timezone.utc).date()
    if isinstance(today, str):
        today = date.fromisoformat(today[:10])
    if isinstance(today, datetime):
        today = today.date()
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    cold, hot = [], []
    for row in rows:
        day = _day(row)
        (cold if (day and day < cutoff) else hot).append(row)
    return cold, hot


def write_series(path, rows, *, keep_days=HOT_WINDOW_DAYS, today=None) -> list:
    """Persist the full series across the working file and its archive.

    Returns the same rows it was given (sorted): callers keep operating on the
    whole series — ``update_history`` returns it to walk-forward evaluators —
    while only the hot half lands in the file the next commit rewrites.
    """
    rows = sorted(rows, key=_day)
    cold, hot = split_window(rows, keep_days=keep_days, today=today)
    if cold:
        archive = archive_path(path)
        archive.parent.mkdir(parents=True, exist_ok=True)
        # Rewriting the archive from `cold` (rather than appending) keeps it
        # identical to "the series minus the hot window" even if a backfill
        # rewrites old rows; the file is stable day to day because the same
        # rows keep producing the same bytes.
        safe_write_text(str(archive), _dump(cold))
    safe_write_text(str(path), _dump(hot) if hot else '')
    return rows


def series_digest(path) -> str:
    """Digest of the whole logical series, not of the working file's bytes.

    Provenance in a run card names the rows the run actually read. After the
    hot/cold split, hashing the working file would describe the last 180 days
    while the count beside it describes the whole series.
    """
    hasher = hashlib.sha256()
    for row in load_series(path):
        hasher.update(
            json.dumps(row, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')).encode('utf-8')
        )
        hasher.update(b'\n')
    return 'sha256:' + hasher.hexdigest()[:16]


def roll_dated_files(directory, *, keep_days=HOT_WINDOW_DAYS, today=None) -> list:
    """Move dated files older than ``keep_days`` into ``directory/_archive/``.

    The file-level analogue of :func:`split_window` (#1040): every consumer of
    ``memory/snapshots/`` looks at a bounded recent window (dashboard embeds 90,
    sparklines take 8, weekly review reads its own week), so keeping 180 days
    flat costs nothing semantic and bounds what every future checkout carries.

    Same conservatism as :func:`split_window`: a file whose name is not a bare
    date cannot be proven old and is never touched — which also keeps this safe
    to point at mixed directories. The archive directory itself is never
    scanned or rewritten; like the JSONL archive it is write-once parking.

    Returns the names moved (empty on nothing-to-do), so the caller can report
    or no-op. Callers must commit from a pathspec that covers the archive dir
    (the morning brief postflight's ``git add memory/`` does; the intraday
    postflights' explicit-file adds do not, which is why only preflight rolls).
    """
    today = today or datetime.now(timezone.utc).date()
    if isinstance(today, str):
        today = date.fromisoformat(today[:10])
    if isinstance(today, datetime):
        today = today.date()
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    directory = Path(directory)
    if not directory.is_dir():
        return []
    archive = directory / ARCHIVE_DIR_NAME
    moved = []
    for p in sorted(directory.iterdir()):
        if not p.is_file() or not DATED_FILE_RE.match(p.name):
            continue
        if p.name[:10] >= cutoff:
            continue
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / p.name
        if not target.exists():
            p.rename(target)
            moved.append(p.name)
    return moved
