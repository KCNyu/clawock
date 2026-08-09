#!/usr/bin/env python3
"""Rebuild every derived portfolio field from ledger leaves.

Part of the ledger-derivation work (#3): the only hand-/fetcher-anchored leaves are
`shares`, `cost_basis`, `current_price`, `prev_close`. EVERYTHING above them is a
pure function of those and must never be edited by hand:

  per holding (active, shares>0):
    current_value = shares × current_price
    pnl_abs       = shares × (current_price − cost_basis)
    today_change  = shares × (current_price − prev_close)      [only if prev_close]

  per region (Σ over active holdings):
    total_current_value = Σ current_value
    total_cost          = Σ shares × cost_basis
    total_pnl           = total_current_value − total_cost
    total_pnl_percent   = total_pnl / total_cost × 100
    today_total_change  = Σ today_change

This lets a caller reconcile a position edit without fetching prices again.
Arithmetic primitives are shared with the integrity gate so derivation and
validation cannot drift.

    clawock aggregates            # rewrite portfolio.json in place
    clawock aggregates --dry-run  # print diffs, write nothing
"""
import argparse
import json
import sys
from pathlib import Path

from clawock.portfolio.math import active_holdings, number
from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
PORTFOLIO = WS / 'portfolio.json'
POLICY = WS / 'config' / 'portfolio-derivations.json'


def _r(x):
    return round(x, 2)


def load_policy(path=POLICY):
    """Load workspace-specific precision without embedding book names in core."""
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    configured = payload.get('percent_rounding_by_book', {})
    if not isinstance(configured, dict):
        return {}
    return {
        str(book): int(digits)
        for book, digits in configured.items()
        if isinstance(digits, int) and not isinstance(digits, bool)
        and 0 <= digits <= 8
    }


def recompute(data, dry_run=False, percent_rounding=None):
    """Mutate `data` in place. Return per-region dict of {field: (old, new)} diffs."""
    changes = {}
    precision = percent_rounding or {}
    for region, pf in (data.get('portfolios') or {}).items():
        if not isinstance(pf, dict):
            continue
        diffs = {}

        # ── per-holding derived leaves (active only, mirrors the gate's _active) ──
        sum_cv = sum_cost = sum_tc = 0.0
        for h in active_holdings(pf.get('holdings', [])):
            sh = number(h.get('shares'))
            cp = number(h.get('current_price'))
            cb = number(h.get('cost_basis'))
            if sh is None or cp is None:
                continue  # missing a required leaf → can't derive; leave untouched
            cv = _r(sh * cp)
            sum_cv += cv
            if cb is not None:
                sum_cost += sh * cb
                pnl = _r(sh * (cp - cb))
                if number(h.get('pnl_abs')) != pnl:
                    diffs.setdefault('holdings.pnl_abs', []).append((h.get('ticker'), h.get('pnl_abs'), pnl))
                if not dry_run:
                    h['pnl_abs'] = pnl
            if number(h.get('current_value')) != cv:
                diffs.setdefault('holdings.current_value', []).append((h.get('ticker'), h.get('current_value'), cv))
            if not dry_run:
                h['current_value'] = cv
            pc = number(h.get('prev_close'))
            if pc is not None:
                tc = _r(sh * (cp - pc))
                sum_tc += tc
                if not dry_run:
                    h['today_change'] = tc

        # ── region aggregates ──
        pct_nd = precision.get(region, 2)
        want = {
            'total_current_value': _r(sum_cv),
            'total_cost': _r(sum_cost),
            'total_pnl': _r(sum_cv - sum_cost),
            'total_pnl_percent': (round((sum_cv - sum_cost) / sum_cost * 100, pct_nd) if sum_cost else None),
            'today_total_change': _r(sum_tc),
        }
        for k, v in want.items():
            old = pf.get(k)
            if number(old) != v and not (old is None and v is None):
                diffs[k] = (old, v)
            if not dry_run:
                pf[k] = v

        if diffs:
            changes[region] = diffs
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--path', type=Path, default=PORTFOLIO)
    parser.add_argument('--config', type=Path, default=POLICY)
    args = parser.parse_args(argv)
    dry = args.dry_run
    path = args.path
    data = json.loads(path.read_text())
    changes = recompute(
        data, dry_run=dry, percent_rounding=load_policy(args.config))

    if not changes:
        print('recompute_aggregates: ✓ all derived fields already consistent')
    else:
        for region, diffs in changes.items():
            print(f'== {region} ==')
            for k, v in diffs.items():
                if k.startswith('holdings.'):
                    for tkr, old, new in v:
                        print(f'  {k} [{tkr}]: {old} → {new}')
                else:
                    print(f'  {k}: {v[0]} → {v[1]}')
        if dry:
            print('[dry-run] portfolio.json NOT written.')
        else:
            safe_write_json(str(path), data)
            print(f'✓ 已写回 {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
