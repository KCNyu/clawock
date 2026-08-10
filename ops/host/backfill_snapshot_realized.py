"""
Host maintenance: repair historical snapshots whose
`portfolios.{us,hk}_stocks.realized_pnl` drifted out of sync with the canonical
portfolio.json trades[] ledger (the 2026-05-21 phantom-drawdown bug).

For each memory/snapshots/YYYY-MM-DD.json it recomputes realized_pnl + realized_note
as the point-in-time value reflected in that snapshot's holdings (see
clawock.portfolio.snapshots.realized_as_of), using portfolio.json as the source
of truth.

    python3 ops/host/backfill_snapshot_realized.py --dry-run
    python3 ops/host/backfill_snapshot_realized.py
"""
import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

# Every other ops entry point does this, and this one is documented above as
# `python3 ops/host/...`, which is system python — not the venv the package is
# installed into. Without it the command in the docstring is a ModuleNotFoundError.
_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))

from clawock.safe_io import safe_write_json  # noqa: E402
from clawock.portfolio.snapshots import realized_as_of, snapshot_shares  # noqa: E402
from clawock.workspace import workspace_root  # noqa: E402

# The workspace this file sits in, not the operator's. As an absolute live path
# it made `--portfolio` default to the real ledger *and* pointed SNAP_DIR at the
# real memory/snapshots/, so a backfill run from a review checkout rewrote
# production snapshots in place.
WS = str(workspace_root(Path.cwd()))
SNAP_DIR = os.path.join(WS, 'memory', 'snapshots')
DATE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--portfolio', default=os.path.join(WS, 'portfolio.json'))
    args = ap.parse_args()

    ledger = json.load(open(args.portfolio, encoding='utf-8'))['portfolios']
    regions = {
        'us_stocks': ledger.get('us_stocks', {}).get('holdings', []),
        'hk_stocks': ledger.get('hk_stocks', {}).get('holdings', []),
    }

    paths = sorted(p for p in glob.glob(os.path.join(SNAP_DIR, '*.json'))
                   if DATE_RE.match(os.path.basename(p)))
    changed_files = 0
    for p in paths:
        date = DATE_RE.match(os.path.basename(p)).group(1)
        d = json.load(open(p, encoding='utf-8'))
        pf = d.get('portfolios', {})
        file_changed = False
        for region, ledger_holdings in regions.items():
            rpf = pf.get(region)
            if not rpf:
                continue
            shares = snapshot_shares(rpf)
            new_total, new_note = realized_as_of(ledger_holdings, date, shares)
            old_total = rpf.get('realized_pnl')
            if old_total is None or abs(float(old_total) - new_total) > 0.005:
                print(f'{date} {region}: {old_total} -> {new_total}  (Δ {new_total - (old_total or 0):+.2f})')
                rpf['realized_pnl'] = new_total
                rpf['realized_note'] = new_note
                file_changed = True
        if file_changed:
            changed_files += 1
            if not args.dry_run:
                safe_write_json(p, d)

    verb = 'would change' if args.dry_run else 'changed'
    print(f'\n{verb} {changed_files}/{len(paths)} snapshot(s).')
    if args.dry_run:
        print('[dry-run] nothing written.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
