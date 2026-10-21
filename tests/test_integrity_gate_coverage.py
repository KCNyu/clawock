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
        bars, markets=[market], now=datetime(2026, 10, 12, 1, tzinfo=timezone.utc))
    assert rows == [{'market': market, 'newest_bar': '2026-10-07',
                     'last_completed_session': '2026-10-09',
                     'missing_sessions': ['2026-10-08', '2026-10-09'], 'status': 'behind'}]


def test_empty_store_and_retired_only_leg_are_not_healthy(tmp_path):
    now = datetime(2026, 10, 12, 1, tzinfo=timezone.utc)
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
    assert any(integrity.blocks_money_publication(f) for f in rep['findings'])


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


@pytest.mark.parametrize('cost', [0, None])
def test_dashboard_rejects_invalid_cost_even_when_payload_matches(tmp_path, monkeypatch, cost):
    from clawock.publish.artifacts import _assert_dashboard_money_reconciles

    book = {'currency': 'USD', 'total_pnl': 0, 'holdings': [
        {'ticker': 'TEST', 'shares': 2, 'cost_basis': cost}]}
    rep = report(tmp_path, monkeypatch, json.loads(CONFIG.read_text()),
                 {'us_stocks': book, 'hk_stocks': {'currency': 'HKD', 'holdings': []}})
    code = 'COST_ZERO' if cost == 0 else 'COST_MISSING'
    assert {f['code'] for f in rep['findings'] if f['level'] == 'ERROR'} == {code}
    from clawock.publish.dashboard import trim_holding
    payload = {
        'holdings': {'us': [trim_holding(book['holdings'][0], 'USD')], 'hk': []},
        'totals': {'us': {'pnl_usd': 0}, 'hk': {}},
        'concentration': {leg: {'total': 0, 'hhi': 0, 'top2': 0, 'positions': []}
                          for leg in ('us', 'hk')},
        'fx': {'usdhkd': None},
        'build_status': {'integrity': {'ok': True, 'error_count': 0}},
    }
    with pytest.raises(AssertionError, match='portfolio money integrity failed:.*' + code):
        _assert_dashboard_money_reconciles(payload, tmp_path / 'portfolio.json')


def test_money_publication_covers_new_errors_but_not_freshness_warnings():
    assert integrity.blocks_money_publication({'code': 'FUTURE_ERROR', 'level': 'ERROR'})
    assert integrity.blocks_money_publication({'code': 'PNL_LEG', 'level': 'WARN'})
    assert not integrity.blocks_money_publication({'code': 'STALENESS', 'level': 'WARN'})


def test_market_filter_excludes_unrequested_stale_store(tmp_path):
    write(tmp_path / 'A.json', {'leg': 'HK', 'bars': {'2026-10-09': {'close': 10}}})
    write(tmp_path / 'B.json', {'leg': 'US', 'bars': {'2026-10-07': {'close': 10}}})
    now = datetime(2026, 10, 12, 1, tzinfo=timezone.utc)
    assert integrity.summarize_bar_staleness(tmp_path, markets=['hk'], now=now) == []
    assert [r['market'] for r in integrity.summarize_bar_staleness(tmp_path, now=now)] == ['us']


def test_auxiliary_defaults_use_module_workspace_from_foreign_cwd(tmp_path, monkeypatch):
    from clawock import workspace
    root = tmp_path / 'desk'
    monkeypatch.delenv('CLAWOCK_WORKSPACE', raising=False)
    monkeypatch.setattr(workspace, '__file__', str(root / 'src/clawock/workspace.py'))
    monkeypatch.chdir(tmp_path)
    write(root / 'memory/bars/A.json', {'ticker': 'A', 'leg': 'US',
          'bars': {'2026-10-07': {'close': 10}, '2026-10-09': {'close': 12}}})
    write(root / 'memory/bars/B.json', {'ticker': 'B', 'leg': 'US',
          'bars': {'2026-10-07': {'close': 10}, '2026-10-08': {'close': 11}}})
    log = root / 'memory/bar-conflicts.jsonl'
    log.write_text(json.dumps({'seen_at': '2026-10-10', 'kind': 'impossible_bar',
                              'ticker': 'B', 'date': '2026-10-09', 'fetched': {'close': -1}}) + '\n')
    now = datetime(2026, 10, 12, 1, tzinfo=timezone.utc)
    assert integrity._bar_close('A', '2026-10-09') == 12
    assert integrity.summarize_bar_staleness(markets=['us'], now=now) == []
    assert len(integrity.summarize_bar_gaps()) == 2
    assert integrity._refused_bars()[('B', '2026-10-09')] == {'close': -1}
    assert integrity.summarize_bar_conflicts(now=now)['total'] == 1
