"""
recompute_realized.py — single source of truth for portfolio-level realized P&L.

Walks `holdings[].trades[]` across both portfolios, sums every entry with a
`realized_pnl` field, and writes back:
  portfolios.us_stocks.realized_pnl   (USD)
  portfolios.us_stocks.realized_note  (deterministic chronological breakdown)
  portfolios.hk_stocks.realized_pnl   (HKD)
  portfolios.hk_stocks.realized_note

Hooked into fetch_us_stocks.update_us_portfolio() and analyze_hk_stocks
refresh — runs on every price refresh so the aggregate can never drift away
from the structured trades[] entries again (the 2026-05-20 SOXL+RKLX bug:
2dc7786 appended trades[] but forgot to bump the aggregate).

CLI usage:
    python3 recompute_realized.py            # rewrite portfolio.json in place
    python3 recompute_realized.py --dry-run  # print + diff, don't write
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safe_io import safe_write_json
# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

# The ledger of whichever workspace this file sits in — the same resolution the
# other 42 modules use. It was the live absolute path, which made
# `python3 recompute_realized.py` in a worktree rewrite the operator's real
# portfolio.json: the library callers pass their own dict, so the constant only
# ever served the command line, and the command line was pointed at production
# no matter where it ran from. On the live host this resolves to the same file.
PORTFOLIO_PATH = os.path.join(workspace_root(Path(__file__).resolve().parents[2]),
                              'portfolio.json')


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
    for region in ('us_stocks', 'hk_stocks'):
        pf = data['portfolios'].get(region)
        if not pf:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='print summary, do not write')
    ap.add_argument('--path', default=PORTFOLIO_PATH)
    args = ap.parse_args()

    with open(args.path, encoding='utf-8') as f:
        data = json.load(f)

    before = {
        r: {
            'realized_pnl':  data['portfolios'][r].get('realized_pnl'),
            'realized_note': data['portfolios'][r].get('realized_note', ''),
        }
        for r in ('us_stocks', 'hk_stocks')
        if r in data['portfolios']
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

    safe_write_json(args.path, data)
    print(f'✅ Saved → {args.path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
