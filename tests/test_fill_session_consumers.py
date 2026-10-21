"""Session returns and fill dates must not borrow position-day P&L semantics."""
import pytest

from clawock.portfolio.math import day_pnl, trade_session_date
from clawock.decision.ledger import match_real_executions
from clawock.decision.setups import holding_metrics
from clawock.evidence.news_evidence_graph import apply_confirmation, load_policy


@pytest.mark.parametrize('market,day,note,want', [
    ('us', '2026-08-07', '成交 02:00 HKT', '2026-08-06'),
    ('us', '2026-08-08', '成交 02:03 HKT', '2026-08-07'),
    ('us', '2026-08-12', '微信,2026-08-13 00:41 HKT', '2026-08-12'),
    ('us', '2026-08-07', '成交 22:00 HKT', '2026-08-07'),
    ('us', '2026-01-07', '成交 04:45 HKT', '2026-01-06'),
    ('us', '2026-06-19', '', '2026-06-18'),
    ('hk', '2026-10-16', '成交 09:39 HKT', '2026-10-16'),
    ('hk', '2026-10-19', '', '2026-10-16'),
    ('us', '2026-08-07', '', '2026-08-07'),
    ('us', '2026-08-07', '成交 29:00 HKT', '2026-08-07'),
    ('us', '2026-08-07', '成交 01:00 HKT 或 22:00 HKT', '2026-08-07'),
    ('us', 'invalid', '成交 01:00 HKT', 'invalid'),
    ('us', '2030-08-07', '成交 01:00 HKT', '2030-08-07'),
])
def test_fill_session(market, day, note, want):
    assert trade_session_date(market, {'date': day, 'note': note}) == want


@pytest.mark.parametrize('day,note,session', [
    ('2026-08-07', '成交 02:00 HKT', '2026-08-06'),
    ('2026-08-08', '成交 02:03 HKT', '2026-08-07'),
    ('2026-06-19', '', '2026-06-18'),
])
def test_pnl_and_execution_match_share_fill_session(day, note, session):
    trade = dict(date=day, note=note, action='buy', shares=10, price=12)
    holding = dict(ticker='ABC', shares=10, current_price=11, prev_close=10, trades=[trade])
    assert day_pnl(holding, session, market='us') == (-10, 120)
    assert day_pnl(holding, '2026-08-10', market='us') == (10, 100)
    decision = dict(decision_id='a', ticker='ABC', action='add_only_on_trigger', size={'shares': 10},
                    execution={'status': 'followed'},
                    evaluation={'triggered': True, 'trigger_session': session})
    book = {'portfolios': {'us_stocks': {'holdings': [holding]}}}
    assert match_real_executions([decision], book)['a']['date'] == day
    # Matching remains strict and one-to-one.
    assert match_real_executions([decision, {**decision, 'decision_id': 'b'}], book) == {}
    assert match_real_executions([{**decision, 'size': {'shares': 9}}], book) == {}


@pytest.mark.parametrize('ticker,reported', [('07709', '07709'), ('RKLX', 'RKLB')])
def test_consumers_use_quote_return_even_when_new_position_loses(ticker, reported):
    holding = dict(ticker=ticker, shares=100, current_price=19.19, prev_close=18.68,
                   today_change_pct=-4.24)
    metrics = holding_metrics(holding)
    assert metrics['today_change_pct'] == 2.73
    assert metrics['position_day_pct'] == -4.24
    events = [dict(ticker=reported, reported_ticker=reported, impact_direction=sign)
              for sign in ('positive', 'negative')]
    apply_confirmation(load_policy(), events,
                       {'portfolios': {'hk_stocks': {'holdings': [holding]}}}, {}, {})
    assert events[0]['confirmation']['price_change_pct'] == pytest.approx(2.73019, abs=1e-5)
    assert events[0]['confirmation']['price_change_basis'] == 'session'
    assert events[0]['confirmation']['price_aligned'] is True
    assert events[1]['confirmation']['price_aligned'] is False
    holding['quote_incomplete'] = True
    assert holding_metrics(holding)['today_change_pct'] is None
    apply_confirmation(load_policy(), events,
                       {'portfolios': {'hk_stocks': {'holdings': [holding]}}}, {}, {})
    assert events[0]['confirmation']['price_change_pct'] is None
    assert events[0]['confirmation']['price_aligned'] is False
