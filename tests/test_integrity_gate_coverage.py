"""Independent denominators for canonical bars and configured book gates."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clawock.portfolio import integrity

CONFIG = Path(__file__).resolve().parents[1] / 'config/portfolio-derivations.json'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize('market', ['hk', 'us'])
def test_whole_leg_stopped_is_visible_even_when_union_has_no_gaps(tmp_path, market):
    bars = tmp_path / 'bars'
    for ticker in ['A', 'B']:
        write(bars / f'{ticker}.json', {'ticker': ticker, 'leg': market.upper(),
              'bars': {'2026-10-07': {'close': 10}}})
    assert integrity.summarize_bar_gaps(bars) == []
    rows = integrity.summarize_bar_staleness(
        bars, markets=[market], now=datetime(2026, 10, 11, tzinfo=timezone.utc))
    assert rows == [{'market': market, 'newest_bar': '2026-10-07',
                     'last_completed_session': '2026-10-09',
                     'missing_sessions': ['2026-10-08', '2026-10-09'], 'status': 'behind'}]


def test_empty_store_and_retired_only_leg_are_not_healthy(tmp_path):
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    write(tmp_path / 'retired.json', {'leg': 'US', 'retired': True,
          'bars': {'2026-10-09': {'close': 10}}})
    rows = integrity.summarize_bar_staleness(tmp_path, markets=['hk', 'us'], now=now)
    assert len(rows) == 2
    assert all(r['status'] == 'unavailable' and r['newest_bar'] is None for r in rows)


def test_calendar_excludes_holiday_weekend_and_unfinished_session(tmp_path):
    write(tmp_path / 'A.json', {'leg': 'US', 'bars': {'2026-07-02': {'close': 10}}})
    for now in [datetime(2026, 7, 5, tzinfo=timezone.utc),
                datetime(2026, 7, 6, 15, tzinfo=timezone.utc)]:
        assert integrity.summarize_bar_staleness(tmp_path, markets=['us'], now=now) == []


def report(tmp_path, monkeypatch, config, books):
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    cfg = write(tmp_path / 'config/portfolio-derivations.json', config)
    portfolio = write(tmp_path / 'portfolio.json', {'portfolios': books})
    return integrity.check(portfolio, config_path=cfg)


def test_renamed_configured_book_still_checks_cash_and_currency(tmp_path, monkeypatch):
    config = json.loads(CONFIG.read_text())
    config['risk_books']['us']['portfolio_key'] = 'america'
    config['cash_field_by_book']['america'] = config['cash_field_by_book'].pop('us_stocks')
    rep = report(tmp_path, monkeypatch, config, {'america': {
        'currency': 'HKD', 'cash_usd': 600, 'cash_reconciled': 100,
        'cash_reconciled_date': '2026-10-01', 'holdings': []}})
    codes = {f['code'] for f in rep['findings']}
    assert {'CASH_RECON', 'FX_TAG'} <= codes
    assert 'BOOK_GATE_CONFIG' not in codes
    assert not rep['ok']


@pytest.mark.parametrize('mutation', ['unknown_book', 'unknown_market', 'extra_cash',
                                      'missing_cash', 'duplicate', 'wrong_cash'])
def test_unrecognized_book_configuration_fails_closed(tmp_path, monkeypatch, mutation):
    config = copy.deepcopy(json.loads(CONFIG.read_text()))
    books = {'us_stocks': {'currency': 'USD', 'holdings': []}}
    if mutation == 'unknown_book':
        books['new_account'] = {'currency': 'USD', 'holdings': []}
    elif mutation == 'unknown_market':
        config['risk_books']['future_market'] = {'portfolio_key': 'future_book'}
        config['cash_field_by_book']['future_book'] = 'cash_usd'
    elif mutation == 'extra_cash':
        config['cash_field_by_book']['future_book'] = 'cash_usd'
    elif mutation == 'missing_cash':
        del config['cash_field_by_book']['us_stocks']
    elif mutation == 'duplicate':
        config['risk_books']['hk']['portfolio_key'] = 'us_stocks'
    else:
        config['cash_field_by_book']['us_stocks'] = 'cash_hkd'
    rep = report(tmp_path, monkeypatch, config, books)
    assert not rep['ok']
    assert any(f['code'] == 'BOOK_GATE_CONFIG' and f['level'] == 'ERROR' for f in rep['findings'])
    from clawock.publish.artifacts import DASHBOARD_MONEY_INTEGRITY_CODES
    assert 'BOOK_GATE_CONFIG' in DASHBOARD_MONEY_INTEGRITY_CODES


def test_check_exposes_calendar_and_prev_close_coverage(tmp_path, monkeypatch):
    config = json.loads(CONFIG.read_text())
    rep = report(tmp_path, monkeypatch, config, {'us_stocks': {'currency': 'USD',
        'holdings': [{'ticker': 'A', 'shares': 1, 'cost_basis': 10,
                      'prev_close': 10, 'prev_close_date': '2026-10-08'}]}})
    assert {row['market'] for row in rep['bar_staleness']} == {'hk', 'us'}
    assert rep['prev_close_coverage'] == {'checked': 0, 'missing': [
        {'region': 'us_stocks', 'ticker': 'A', 'date': '2026-10-08'}]}
    assert {'BAR_STALENESS', 'PREV_CLOSE_COVERAGE'} <= {f['code'] for f in rep['findings']}


@pytest.mark.parametrize('raw', [None, '{', '[]', '{}'])
def test_missing_or_malformed_gate_config_is_an_error(tmp_path, monkeypatch, raw):
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    path = tmp_path / 'bad-config.json'
    if raw is not None:
        path.write_text(raw)
    portfolio = write(tmp_path / 'portfolio.json', {'portfolios': {'new_account': {}}})
    rep = integrity.check(portfolio, config_path=path)
    assert not rep['ok']
    assert any(f['code'] == 'BOOK_GATE_CONFIG' for f in rep['findings'])
