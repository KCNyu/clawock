"""Single source of truth for portfolio-level realized P&L.

Walks `holdings[].trades[]` across every portfolio book, sums every entry with a
`realized_pnl` field, and writes back each book's `realized_pnl` plus a
deterministic chronological `realized_note`.

Designed to run after any price/position refresh so the aggregate cannot drift
away from the structured trades[] entries.

CLI usage:
    clawock realized            # rewrite portfolio.json in place
    clawock realized --dry-run  # print + diff, don't write
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

# The CLI operates on the configured workspace. Library callers pass an
# in-memory ledger and remain independent of filesystem layout.
PORTFOLIO_PATH = workspace_root(Path.cwd()) / 'portfolio.json'


def _aggregate(holdings: List[Dict]) -> Tuple[float, str, List[Dict]]:
    """Sum sell trades' realized_pnl + build chronological note."""
    sells: List[Dict] = []
    for h in holdings:
        ticker = h.get('ticker', '?')
        for t in h.get('trades', []) or []:
            r = t.get('realized_pnl')
            if r is None:
                continue
            sells.append({
                'date':         t.get('date', ''),
                'ticker':       ticker,
                'shares':       t.get('shares', 0),
                'price':        t.get('price', 0),
                'realized_pnl': r,
            })

    sells.sort(key=lambda x: (x['date'], x['ticker']))
    total = round(sum(s['realized_pnl'] for s in sells), 2)

    parts = []
    for s in sells:
        # Format: "TICKER Nshares@price(+realized)"
        # Round price/realized to keep notes tidy; price stays as-is unless float oddity.
        price_s = f"{s['price']:g}"
        r = s['realized_pnl']
        r_s = f"{r:+g}".replace('+', '+').replace('-', '-')
        parts.append(f"{s['ticker']} {s['shares']}股@{price_s}({r_s})")

    note = ' + '.join(parts) if parts else ''
    return total, note, sells


def recompute(data: Dict) -> Dict[str, Dict]:
    """Mutate `data` in place. Return per-region {realized_pnl, realized_note}."""
    out = {}
    for region, pf in (data.get('portfolios') or {}).items():
        if not isinstance(pf, dict):
            continue
        total, note, sells = _aggregate(pf.get('holdings', []) or [])
        pf['realized_pnl']  = total
        pf['realized_note'] = note
        out[region] = {
            'realized_pnl':  total,
            'realized_note': note,
            'sell_count':    len(sells),
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='print summary, do not write')
    ap.add_argument('--path', type=Path, default=PORTFOLIO_PATH)
    args = ap.parse_args(argv)

    with open(args.path, encoding='utf-8') as f:
        data = json.load(f)

    before = {
        r: {
            'realized_pnl':  data['portfolios'][r].get('realized_pnl'),
            'realized_note': data['portfolios'][r].get('realized_note', ''),
        }
        for r, portfolio in (data.get('portfolios') or {}).items()
        if isinstance(portfolio, dict)
    }

    after = recompute(data)

    for r in after:
        b = before[r]
        a = after[r]
        changed = (b['realized_pnl'] != a['realized_pnl']) or (b['realized_note'] != a['realized_note'])
        marker = '  ✏️  CHANGED' if changed else '  ✓ unchanged'
        print(f"== {r} =={marker}")
        print(f"  before realized_pnl: {b['realized_pnl']}")
        print(f"  after  realized_pnl: {a['realized_pnl']}  ({a['sell_count']} sell trade(s))")
        if b['realized_note'] != a['realized_note']:
            print(f"  before note: {b['realized_note'][:120]}{'...' if len(b['realized_note']) > 120 else ''}")
            print(f"  after  note: {a['realized_note'][:120]}{'...' if len(a['realized_note']) > 120 else ''}")
        print()

    if args.dry_run:
        print('[dry-run] portfolio.json NOT written.')
        return 0

    safe_write_json(str(args.path), data)
    print(f'✅ Saved → {args.path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
