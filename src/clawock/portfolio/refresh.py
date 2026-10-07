"""Shared preparation of portfolio snapshots before market quote refreshes."""
from clawock.portfolio.math import ledger_rows


def active_and_zero_closed(region):
    active = [h for h in ledger_rows(region['holdings']) if h.get('shares', 0) > 0]

    # Zero out snapshot fields on closed positions — refresh skips shares==0
    # holdings, so without this they keep stale cv/pnl from the pre-close run.
    for h in ledger_rows(region['holdings']):
        if h.get('shares', 0) == 0:
            for k in ('current_value', 'pnl_abs', 'pnl_percent',
                      'today_change', 'today_change_pct'):
                if h.get(k):
                    h[k] = 0

    return active
