#!/usr/bin/env python3
"""Keep the committed sidecar when a re-scan differs from it only in generated_at.

Every scan stamps `generated_at` with the moment it ran, so the bytes it writes
always differ from the committed file and the commit helper's "no change" exit
could never fire: a same-cycle retry that found nothing new still committed,
and the commit still started a Pages deploy (2026-10-12 and 2026-10-14
sentiment). Run after validation and before the factor snapshot: when the new
file equals the committed one apart from `generated_at`, the committed bytes
are written back, the snapshot sees them unchanged and the commit step exits
"no change".

Only within one cycle. The file is held only when the committed copy was
written after the newest scheduled fire the dashboard health card judges this
sidecar against (`dashboard.latest_scheduled_fire`). The first scan after each
fire always commits, so identical readings across days (a holiday) still move
the file and its `generated_at`, and neither the health card's mtime check nor
the brief's 36-hour age read starts calling a confirmed sidecar stale.

Any other difference — a price tick, a rotated headline — is a fresher sample
and is committed as before.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run by path with system python, which has no clawock install.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

CLOCK_FIELDS = ('generated_at',)


def committed_bytes(path: Path):
    """The file as HEAD has it, or None when HEAD has no such file."""
    result = subprocess.run(['git', 'show', f'HEAD:{path.as_posix()}'],
                            capture_output=True)
    return result.stdout if result.returncode == 0 else None


def _parse_time(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else None


def _without_clocks(payload):
    if not isinstance(payload, dict):
        return payload
    return {k: v for k, v in payload.items() if k not in CLOCK_FIELDS}


def decide(new: bytes, old, cycle_start):
    """('hold' | 'commit', reason) for one fresh scan against HEAD's copy."""
    if old is None:
        return 'commit', 'not committed yet'
    if new == old:
        return 'commit', 'byte-identical; the commit step will skip it'
    try:
        new_doc, old_doc = json.loads(new), json.loads(old)
    except ValueError:
        return 'commit', 'not comparable as JSON'
    if _without_clocks(new_doc) != _without_clocks(old_doc):
        return 'commit', 'content changed'
    written = _parse_time(old_doc.get('generated_at')) if isinstance(old_doc, dict) else None
    if written is None:
        return 'commit', 'committed copy has no usable generated_at'
    if cycle_start is None or written < cycle_start:
        return 'commit', 'committed copy predates the current scheduled fire'
    return 'hold', f'only generated_at differs; keeping {old_doc["generated_at"]}'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--source', required=True, type=Path,
                    help='sidecar this run just wrote, relative to the repo root')
    args = ap.parse_args(argv)

    from clawock.publish.dashboard import latest_scheduled_fire

    cycle_start = latest_scheduled_fire(args.source.name, datetime.now(timezone.utc))
    old = committed_bytes(args.source)
    verdict, reason = decide(args.source.read_bytes(), old, cycle_start)
    if verdict == 'hold':
        args.source.write_bytes(old)
    print(f'  {args.source}: {verdict} — {reason}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
