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
