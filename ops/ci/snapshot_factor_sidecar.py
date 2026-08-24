#!/usr/bin/env python3
"""Snapshot an overwrite-in-place data sidecar into a date-keyed archive.

factor-snapshots/ gives the factor-research layer a point-in-time record
(#936): sentiment.json / macro.json are overwritten in place by their scan
workflows, so any backtest reading them after the fact sees TODAY's file,
not the one the day's decisions actually saw — the classic look-ahead trap.
Each daily scan now archives a verbatim byte copy under
assets/data/factor-snapshots/<name>/<UTC-date>.json before the overwrite
cycle continues; research reads the dated row, never the live file.

Verbatim bytes, not a re-serialization: the snapshot must be exactly what
the producer wrote, so later schema evolution cannot retroactively rewrite
history. Idempotent per (name, date): an identical re-run (workflow retry)
is a no-op; genuinely different content on the same UTC date wins as the
final version of that day.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_ROOT = _REPO_ROOT / 'assets' / 'data' / 'factor-snapshots'


def snapshot(source: Path, bucket: str, run_date: str, root: Path = SNAPSHOT_ROOT):
    """Copy source verbatim into root/bucket/run_date.json. Returns action."""
    if not source.exists():
        print(f'  ⚠ factor snapshot: source missing: {source}', file=sys.stderr)
        return 'missing'
    target = root / bucket / f'{run_date}.json'
    data = source.read_bytes()
    if target.exists() and target.read_bytes() == data:
        print(f'  factor snapshot: {target} unchanged')
        return 'unchanged'
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    tmp = target.with_suffix('.json.tmp')
    tmp.write_bytes(data)
    os_replace(tmp, target)
    verb = 'updated' if existed else 'created'
    print(f'  factor snapshot: {verb} {target} ({len(data)} bytes)')
    return verb


def os_replace(src: Path, dst: Path):
    import os
    os.replace(src, dst)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--source', required=True, help='sidecar produced this run')
    ap.add_argument('--bucket', default=None,
                    help='snapshot subdirectory (default: source stem)')
    args = ap.parse_args(argv)

    source = Path(args.source)
    bucket = args.bucket or source.stem
    run_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    action = snapshot(source, bucket, run_date)
    # A missing source is a real defect upstream — fail loudly so the job
    # does not green-light a night with no archived data.
    return 1 if action == 'missing' else 0


if __name__ == '__main__':
    sys.exit(main())
