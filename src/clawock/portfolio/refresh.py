"""Shared preparation of portfolio snapshots before market quote refreshes."""
from clawock.portfolio.math import active_holdings, ledger_rows, number


def active_and_zero_closed(region):
    active = active_holdings(region['holdings'])

    # Zero out snapshot fields on closed positions — refresh skips shares==0
    # holdings, so without this they keep stale cv/pnl from the pre-close run.
    for h in ledger_rows(region['holdings']):
        if number(h.get('shares', 0)) == 0:
            for k in ('current_value', 'pnl_abs', 'pnl_percent',
                      'today_change', 'today_change_pct'):
                if h.get(k):
                    h[k] = 0

    return active
