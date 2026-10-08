"""Refresh selection matches ledger arithmetic without rewriting share balances."""
from clawock.portfolio.math import active_holdings
from clawock.portfolio.refresh import active_and_zero_closed


def test_refresh_uses_numeric_active_selection_and_only_zeros_known_closed():
    holdings = [{'shares': shares, 'current_value': 99, 'pnl_abs': 5}
                for shares in (100, '100', 0, '0', None, 'invalid', -1)]
    region = {'holdings': holdings + [None]}
    assert active_and_zero_closed(region) == active_holdings(region['holdings']) == holdings[:2]
    assert [h['shares'] for h in holdings] == [100, '100', 0, '0', None, 'invalid', -1]
    assert [h['current_value'] for h in holdings] == [99, 99, 0, 0, 99, 99, 99]
