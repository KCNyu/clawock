"""`clawock scorecard-provenance` — resolve a published scorecard to its rows.

The shape of the block, and the digests it carries, live in
`clawock.scorecard_provenance`: `decision.ledger` attaches the block while
computing the metrics, and `decision` must not import `evidence`, which sits
above it (#814). This module is the command on top of that shape — the half that
reads a published payload, reads a ledger (the working copy or any git ref), and
says whether the two still agree.

Two questions it answers, deliberately kept apart:

* **did this slice change** — the digest over the rows inside the published
  window bounds. A mismatch means a row the number was computed from has been
  re-settled or edited, which is a real finding about a published claim;
* **did the ledger grow** — the digest over the whole file. Later sessions
  appending is the normal daily case and is reported as `moved`, never as a
  failure, so the check stays usable on any day rather than only on publish day.

With `--recompute` it goes further and re-derives the headline counts through
`decision.ledger.compute_metrics` at the recorded cutoff, which is the "click a
metric, see its source" half of #1113.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from clawock import scorecard_provenance as prov
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
LEDGER_PATH = prov.LEDGER_PATH
DASHBOARD_PATH = 'assets/data/dashboard.json'


def recompute_headline(provenance: dict, decisions) -> dict:
    """Re-derive the published headline counts at the recorded cutoff.

    The cutoff has to come from the block rather than from the clock: the
    scorecard window is rolling, so "30 days ago" on the day of verification is
    a different population, and comparing against it would report a mismatch
    that is not a change to the published number.
    """
    from clawock.decision import ledger as ledger_module

    window = provenance.get('window') or {}
    metrics = ledger_module.compute_metrics(
        list(decisions),
        window_days=window.get('days') or 30,
        cutoff=window.get('cutoff'),
    )
    counts = provenance.get('counts') or {}
    checks = []
    for name in sorted(counts):
        actual = metrics.get(name)
        checks.append({
            'name': f'counts.{name}',
            'status': 'pass' if actual == counts[name] else 'fail',
            'expected': counts[name],
            'actual': actual,
        })
    return {'ok': all(c['status'] == 'pass' for c in checks),
            'checks': checks, 'metrics': metrics}


def load_ledger(path: Path | str | None = None, ref: str | None = None) -> list[dict]:
    """Read decisions from the working copy, or from any git ref."""
    rel = str(path or LEDGER_PATH)
    if ref:
        out = subprocess.run(['git', 'show', f'{ref}:{rel}'], cwd=WS,
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            raise SystemExit(
                f'cannot read {rel} at {ref}: {out.stderr.strip() or "git show failed"}')
        text = out.stdout
    else:
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = WS / candidate
        text = candidate.read_text(encoding='utf-8')
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_provenance(metrics_path: Path | str | None = None) -> dict:
    """Pull the provenance block out of a published dashboard payload."""
    path = Path(metrics_path or DASHBOARD_PATH)
    if not path.is_absolute():
        path = WS / path
    payload = json.loads(path.read_text(encoding='utf-8'))
    metrics = payload.get('decision_metrics') if isinstance(payload, dict) else None
    if isinstance(metrics, dict) and isinstance(metrics.get('provenance'), dict):
        return metrics['provenance']
    if isinstance(payload, dict) and isinstance(payload.get('provenance'), dict):
        return payload['provenance']
    raise SystemExit(f'no decision_metrics.provenance in {path}')


def _print_checks(title: str, result: dict) -> None:
    print(title)
    for check in result['checks']:
        mark = {'pass': 'ok', 'moved': '~', 'fail': 'FAIL'}[check['status']]
        line = f'  [{mark}] {check["name"]}'
        if check['status'] != 'pass':
            line += f'  expected={check.get("expected")!r} actual={check.get("actual")!r}'
        if check.get('detail'):
            line += f'\n        {check["detail"]}'
        print(line)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='clawock scorecard-provenance',
        description='Show or verify what produced the published scorecard.')
    parser.add_argument('--check', action='store_true',
                        help='recompute the digests and compare with the published block')
    parser.add_argument('--recompute', action='store_true',
                        help='also re-derive the headline counts at the recorded cutoff')
    parser.add_argument('--metrics', default=None,
                        help=f'published payload to read (default {DASHBOARD_PATH})')
    parser.add_argument('--ledger', default=None,
                        help=f'ledger to verify against (default {LEDGER_PATH})')
    parser.add_argument('--ref', default=None,
                        help='read the ledger from this git ref instead of the working copy')
    parser.add_argument('--json', action='store_true', help='print JSON, not text')
    args = parser.parse_args(argv)

    provenance = load_provenance(args.metrics)
    if not args.check:
        print(json.dumps(provenance, indent=2, ensure_ascii=False))
        return 0

    decisions = load_ledger(args.ledger, args.ref)
    result = prov.verify(provenance, decisions)
    if args.recompute:
        headline = recompute_headline(provenance, decisions)
        result = {'ok': result['ok'] and headline['ok'],
                  'checks': result['checks'] + headline['checks']}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        source = args.ref or (args.ledger or LEDGER_PATH)
        _print_checks(
            f'scorecard provenance: generated_at={provenance.get("generated_at")} '
            f'commit={provenance.get("code_commit")} vs {source}', result)
        print('OK' if result['ok'] else 'MISMATCH')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
