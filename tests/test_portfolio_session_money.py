"""Remaining-position day P&L, malformed holding rows and publication regression."""
import copy
import json
import subprocess
from pathlib import Path

import pytest

from clawock import instruments
from clawock.harness import intraday_postflight
from clawock.portfolio import aggregates, cash, integrity, realized, risk
from clawock.portfolio.math import day_pnl, holding_session


def test_partial_add_uses_fill_for_new_shares_and_same_percentage_base():
    row = dict(ticker='X', shares=7200, current_price=2.598, prev_close=2.742,
               cost_basis=2.5, data_source='Tencent Oct 02 11:03 HKT',
               trades=[dict(action='buy', date='2026-10-02', shares=1000, price=2.594)])
    amount, base = day_pnl(row, '2026-10-02')
    assert amount == pytest.approx(-888.8)
    assert base == pytest.approx(19594.4)
    book = dict(last_updated='2026/10/02 11:03 HKT', portfolios={'hk_stocks': {'holdings': [row]}})
    aggregates.recompute(book)
    assert row['today_change'] == -888.8
    assert row['today_change_pct'] == -4.54
    assert book['portfolios']['hk_stocks']['today_total_change'] == -888.8


@pytest.mark.parametrize('trades,shares,base', [
    ([], 10, 1200),
    ([dict(action='buy', shares=10, price=100)], 10, 1000),
    ([dict(action='buy', shares=10, price=100), dict(action='sell', shares=10, price=102),
      dict(action='buy', shares=10, price=104)], 10, 1040),
    ([dict(action='buy', shares=5, price=100), dict(action='sell', shares=7, price=102)], 3, 300),
    ([dict(action='buy', shares=5, price=100), dict(action='buy', shares=5, price=110)], 15, 1650),
])
def test_day_pnl_old_new_reentry_and_partial_sale(trades, shares, base):
    row = dict(shares=shares, current_price=105, prev_close=120,
               trades=[dict(t, date='2026-10-02') for t in trades])
    amount, actual_base = day_pnl(row, '2026-10-02')
    assert actual_base == base
    assert amount == shares * 105 - base


def test_quote_session_does_not_treat_holiday_fetch_as_new_lot_day():
    assert holding_session({'data_source': 'Tencent Oct 01 11:03 HKT'}, '2026-10-01', 'hk') == '2026-09-30'
    assert holding_session({'day_session_date': '2026-10-01'}, '2026-10-02', 'us') == '2026-10-01'


def test_malformed_holdings_produce_findings_without_crashing_money_readers(tmp_path):
    book = json.loads((Path(__file__).parents[1] / 'portfolio.json').read_text())
    book['portfolios']['hk_stocks']['holdings'].extend([None, 'ticker shares cost_basis', 42])
    path = tmp_path / 'portfolio.json'
    path.write_text(json.dumps(book))
    result = integrity.check(path)
    findings = result.get('findings', result.get('issues', []))
    bad = [f for f in findings if f['code'] == 'LEDGER_ROW_INVALID' and 'holdings[' in f['msg']]
    assert len(bad) == 3
    for reader in [aggregates.recompute, cash.recompute, realized.recompute, instruments.compute_lookthrough_exposure]:
        reader(copy.deepcopy(book))
    risk.active_holdings(book, 'hk_stocks')
    assert json.loads(path.read_text()) == book  # integrity never rewrites original rows


def test_reconcile_retires_only_known_obsolete_price_delta():
    row = dict(ticker='X', shares=1, current_price=2, prev_close=1, cost_basis=1,
               today_change_abs=123, user_note='keep')
    data = dict(portfolios={'hk_stocks': {'holdings': [row]}})
    aggregates.recompute(data, dry_run=True)
    assert row['today_change_abs'] == 123
    aggregates.recompute(data)
    assert 'today_change_abs' not in row and row['user_note'] == 'keep'


def test_intraday_commits_the_book_and_its_snapshot_together(tmp_path, monkeypatch):
    def git(*args):
        p = subprocess.run(['git', '-C', str(tmp_path), *args], text=True, capture_output=True)
        return p.returncode == 0, p.stdout + p.stderr
    assert git('init')[0]
    assert git('config', 'user.name', 'test')[0]
    assert git('config', 'user.email', 'test@example.invalid')[0]
    assert git('config', 'core.hooksPath', '/dev/null')[0]
    for name in ['portfolio.json', 'memory/snapshots/2026-10-02.json', 'logs/dashboard_build_status.json']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"generation": 2}')
    monkeypatch.setattr(intraday_postflight, 'git_cmd', git)
    monkeypatch.setattr(intraday_postflight, 'WS', tmp_path)
    monkeypatch.setattr(intraday_postflight, 'rebuild_dashboard', lambda: (True, ''))
    monkeypatch.setattr(intraday_postflight, 'dashboard_publication_state', lambda _: 'current')
    monkeypatch.setattr(intraday_postflight, 'snapshot_date_for_now', lambda: '2026-10-02')
    monkeypatch.setattr(intraday_postflight, 'push_with_rebase_retry', lambda: (True, ''))
    assert intraday_postflight.publish_data_plane('hk') == ('published', True)
    assert git('show', 'HEAD:portfolio.json')[1] == git('show', 'HEAD:memory/snapshots/2026-10-02.json')[1]


@pytest.mark.parametrize('session,shares,fill,current,prev,amount,base', [
    ('2026-08-14', 260, 8.77, 9.0, 9.21, -50.2, 2390.2),
    ('2026-06-12', 10, 52.3, 48.3, 61.67, -40.0, 523.0),
])
def test_weekend_us_fill_uses_its_trading_session(session, shares, fill, current, prev, amount, base):
    from datetime import date, timedelta
    ledger_day = (date.fromisoformat(session) + timedelta(days=1)).isoformat()
    row = dict(shares=shares, current_price=current, prev_close=prev,
               trades=[dict(action='buy', date=ledger_day, shares=10, price=fill)])
    actual, capital = day_pnl(row, session, market='us')
    assert actual == pytest.approx(amount)
    assert capital == pytest.approx(base)


def test_us_asof_reads_session_even_when_fetch_dates_match(tmp_path):
    book = json.loads((Path(__file__).parents[1] / 'portfolio.json').read_text())
    rows = [h for h in book['portfolios']['us_stocks']['holdings'] if h['shares'] > 0]
    for h in rows:
        h['data_source'] = 'Finnhub Oct 05, 2026 09:35 ET'
        h['day_session_date'] = '2026-10-05'
    rows[0]['day_session_date'] = '2026-10-02'
    path = tmp_path / 'portfolio.json'
    path.write_text(json.dumps(book))
    result = integrity.check(path)
    assert any(f['code'] == 'US_ASOF' and f['level'] == 'ERROR' for f in result['findings'])
    assert not result['ok']


def test_us_missing_quote_preserves_entire_book(tmp_path, monkeypatch):
    from clawock.market_data import us_quotes
    book = dict(portfolios={'us_stocks': {'holdings': [
        dict(ticker='CRCL', shares=10, cost_basis=1), dict(ticker='RKLX', shares=10, cost_basis=1)]}})
    path = tmp_path / 'portfolio.json'
    path.write_text(json.dumps(book))
    before = path.read_bytes()
    monkeypatch.setattr(us_quotes, 'load_api_keys', lambda: {})
    monkeypatch.setattr(us_quotes, 'fetch_us_quotes', lambda *a: {'CRCL': {'c': 2}})
    with pytest.raises(RuntimeError, match='US quote refresh incomplete: RKLX'):
        us_quotes.update_us_portfolio(str(path))
    assert path.read_bytes() == before


def test_session_anchor_malformed_or_missing_is_unknown():
    h = {'data_source': 'Tencent Oct 02 16:10 HKT'}
    for stamp in (None, '', '10/03/2026', '2026/99/03', 1234):
        assert holding_session(h, stamp, 'hk') is None
    assert holding_session(h, '2026/10/03 04:03 HKT', 'hk') == '2026-10-02'
    assert holding_session({'data_source': 'Tencent Oct 02, 2026'}, None, 'hk') == '2026-10-02'

@pytest.mark.parametrize('stamp', [None, '10/03/2026'])
def test_unknown_quote_session_is_a_named_money_error(tmp_path, stamp):
    book = json.loads((Path(__file__).parents[1] / 'portfolio.json').read_text())
    book['last_updated'] = stamp
    h = next(h for h in book['portfolios']['hk_stocks']['holdings'] if h['shares'] > 0)
    h.pop('day_session_date', None)
    h['data_source'] = 'Tencent Oct 02 16:10 HKT'
    path = tmp_path / 'portfolio.json'
    path.write_text(json.dumps(book))
    report = integrity.check(path)
    assert not report['ok']
    assert any(f['code'] == 'SESSION_STAMP_INVALID' and f.get('ticker') == h['ticker']
               for f in report['findings'])
