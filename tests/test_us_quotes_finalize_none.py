"""`us-quotes` finalize must tolerate a null today_change on an unrefreshed row.

A partial `--tickers` refresh leaves every other holding's stored fields alone;
`aggregates`/the quote writer can legitimately clear a day change to null when
the previous close is unknown. `dict.get(key, 0)` only defaults a missing key,
so the whole refresh crashed before writing back (#3492).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from clawock.market_data import us_quotes


def test_finalize_ignores_a_null_today_change(monkeypatch):
    monkeypatch.setattr(us_quotes, 'fetch_us_indices', lambda: {})
    us = {'holdings': [{
        'ticker': 'CRCL', 'shares': 1, 'current_price': 10.0,
        'cost_basis': 5.0, 'current_value': 10.0,
        'today_change': None, 'pnl_percent': 100.0, 'pnl_abs': 5.0,
    }]}
    data = {'last_updated': ''}

    us_quotes._us_finalize_region(
        data, us, now_et=datetime(2026, 11, 14, 6, 0,
                                  tzinfo=ZoneInfo('America/New_York')),
        et_str='Nov 14, 2026 06:00 ET', hkt_str='2026/11/14 19:00 HKT',
        all_active=True, tickers=['CRCL'], updated=['CRCL'], missing=[],
        source_counts={})

    assert us['today_total_change'] == 0
