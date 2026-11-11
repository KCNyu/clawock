"""Hand-edited ledger rows must not take a consumer down (#3358/#3359/#3360).

`math.ledger_rows` and `safe_io.to_number` are the repository's shared readers
for hand-entered rows and quoted numbers. A bare string in `trades[]`, or a
quoted `cost_basis`, used to raise inside a quote writer or the dashboard build
before the money gate could name the row.
"""
import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from clawock.decision import ledger, risk
from clawock.evidence import research_surface
from clawock.market_data import us_quotes
from clawock.portfolio import realized
from clawock.portfolio import risk as portfolio_risk
from clawock.publish import dashboard


def _book():
    return {'portfolios': {'us_stocks': {'holdings': [{
        'ticker': 'X', 'shares': 2, 'cost_basis': '87', 'current_price': '81',
        'prev_close': 79, 'prev_close_date': '2026-11-10',
        'day_session_date': '2026-11-10',
        'trades': ['not-an-object', {
            'date': '2026-01-01', 'action': 'buy', 'shares': '1',
            'price': '5', 'realized_pnl': '34.8',
        }],
    }]}}}


def test_trade_readers_skip_a_bare_string_row():
    book = _book()
    rows = ledger._portfolio_trades(copy.deepcopy(book))
    assert [row['ticker'] for row in rows] == ['X']
    assert risk._holding_map(copy.deepcopy(book))['X']['cost_basis'] == '87'
    assert research_surface.active_positions(copy.deepcopy(book)) == [
        {'ticker': 'X', 'region': 'us_stocks', 'first_buy': '2026-01-01'}]
    portfolio_risk._shares_on(book['portfolios']['us_stocks']['holdings'][0], '2025-01-01')
    risk._broker_evidence(
        {'ticker': 'X', 'required_reduction': {'target_tickers': ['X']},
         'current_opened_at': '2026-01-01'},
        copy.deepcopy(book))


def test_quoted_numbers_do_not_crash_realized_or_the_dashboard_row():
    book = copy.deepcopy(_book())
    assert realized.recompute(book)['us_stocks']['realized_pnl'] == 34.8

    holding = book['portfolios']['us_stocks']['holdings'][0]
    row = dashboard.trim_holding(holding, 'USD')
    assert row['cost_basis'] == 87.0
    assert row['current_price'] == 81.0


def test_us_quote_writer_reads_a_quoted_cost_basis_as_its_number():
    holding = _book()['portfolios']['us_stocks']['holdings'][0]
    quote = {'c': 81, 'pc': 79, 'h': 82, 'l': 78, 'o': 80, 'dp': 2.53,
             'source': 'test'}
    us_quotes._us_apply_quote(
        holding, quote, {},
        now_et=datetime(2026, 11, 11, 10, 0, tzinfo=ZoneInfo('America/New_York')),
        today_et_date='2026-11-11', expected_prev_session='2026-11-10')
    assert holding['current_price'] == 81
    assert holding['pnl_abs'] == -12.0
