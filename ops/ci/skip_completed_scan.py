#!/usr/bin/env python3
"""Skip scheduled pre-open fallback scans with a valid current-cycle artifact.

Dispatch remains an explicit refresh. The health card's first daily fire defines
one cycle for both fallback cron legs. Read the latest master checkout under the
existing data-write lock, not the SHA captured when a queued event was created.
This is artifact-based: failed/unpublished runs cannot suppress a later retry.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))


def should_skip(source, event, now):
    if event != 'schedule':
        return False, 'dispatch requests a refresh'
    from clawock.publish.dashboard import latest_scheduled_fire
    from clawock.publish.artifacts import validate_macro, validate_sentiment

    cycle = latest_scheduled_fire(source.name, now)
    try:
        doc = json.loads(source.read_text())
        stamp = datetime.fromisoformat(str(doc.get('generated_at')).replace('Z', '+00:00'))
        if stamp.tzinfo is None or cycle is None or not cycle <= stamp <= now:
            return False, 'no current-cycle timestamp'
        if source.name == 'macro.json':
            validate_macro(source, now=now)
        else:
            validate_sentiment(source)
    except (OSError, ValueError, AttributeError, AssertionError, TypeError, KeyError) as exc:
        return False, f'no valid current-cycle artifact: {exc}'
    return True, f'current cycle already published at {stamp.isoformat()}'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--source', required=True, choices=(
        'assets/data/macro.json', 'assets/data/sentiment.json'))
    args = ap.parse_args(argv)
    skip, reason = should_skip(Path(args.source), os.environ.get('GITHUB_EVENT_NAME', ''),
                               datetime.now(timezone.utc))
    print(f'{args.source}: skip={str(skip).lower()} — {reason}')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'skip={str(skip).lower()}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
