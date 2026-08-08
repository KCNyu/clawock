#!/usr/bin/env python3
"""recompute_aggregates.py — rebuild every DERIVED portfolio field from the leaves.

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

This automates the "手工卖出必须重算聚合" 铁律 (the phantom-peak bug, 3a68822): a
manual T+0 edit to shares/cash no longer needs a full price fetch — run this and the
book is internally consistent again, so the pre-push money-conservation gate passes.
Formulas + `_num`/`_active` are imported from preflight_integrity so this can never
drift from the gate that verifies them.

    python3 recompute_aggregates.py            # rewrite portfolio.json in place
    python3 recompute_aggregates.py --dry-run  # print diffs, write nothing
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from preflight_integrity import _num, _active, PORTFOLIO  # noqa: E402
from clawock.safe_io import safe_write_json  # noqa: E402

# total_pnl_percent precision differs per region's fetcher (fetch_us_stocks rounds
# to 4dp, analyze_hk_stocks to 2dp) — match each so this stays a no-op after a fetch.
_PCT_ROUND = {'us_stocks': 4, 'hk_stocks': 2}


def _r(x):
    return round(x, 2)


def recompute(data, dry_run=False):
    """Mutate `data` in place. Return per-region dict of {field: (old, new)} diffs."""
    changes = {}
    for region in ('us_stocks', 'hk_stocks'):
        pf = data.get('portfolios', {}).get(region)
        if not pf:
            continue
        diffs = {}

        # ── per-holding derived leaves (active only, mirrors the gate's _active) ──
        sum_cv = sum_cost = sum_tc = 0.0
        for h in _active(pf.get('holdings', [])):
            sh = _num(h.get('shares'))
            cp = _num(h.get('current_price'))
            cb = _num(h.get('cost_basis'))
            if sh is None or cp is None:
                continue  # missing a required leaf → can't derive; leave untouched
            cv = _r(sh * cp)
            sum_cv += cv
            if cb is not None:
                sum_cost += sh * cb
                pnl = _r(sh * (cp - cb))
                if _num(h.get('pnl_abs')) != pnl:
                    diffs.setdefault('holdings.pnl_abs', []).append((h.get('ticker'), h.get('pnl_abs'), pnl))
                if not dry_run:
                    h['pnl_abs'] = pnl
            if _num(h.get('current_value')) != cv:
                diffs.setdefault('holdings.current_value', []).append((h.get('ticker'), h.get('current_value'), cv))
            if not dry_run:
                h['current_value'] = cv
            pc = _num(h.get('prev_close'))
            if pc is not None:
                tc = _r(sh * (cp - pc))
                sum_tc += tc
                if not dry_run:
                    h['today_change'] = tc

        # ── region aggregates ──
        pct_nd = _PCT_ROUND.get(region, 2)
        want = {
            'total_current_value': _r(sum_cv),
            'total_cost': _r(sum_cost),
            'total_pnl': _r(sum_cv - sum_cost),
            'total_pnl_percent': (round((sum_cv - sum_cost) / sum_cost * 100, pct_nd) if sum_cost else None),
            'today_total_change': _r(sum_tc),
        }
        for k, v in want.items():
            old = pf.get(k)
            if _num(old) != v and not (old is None and v is None):
                diffs[k] = (old, v)
            if not dry_run:
                pf[k] = v

        if diffs:
            changes[region] = diffs
    return changes


def main(argv):
    dry = '--dry-run' in argv
    path = Path(PORTFOLIO)
    data = json.loads(path.read_text())
    changes = recompute(data, dry_run=dry)

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
