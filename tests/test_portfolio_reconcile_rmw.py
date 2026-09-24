"""Reconciliation must preserve another writer's fields committed before its lock."""
import json
import sys

from clawock.safe_io import mutate_json
from clawock.portfolio import aggregates, realized
from clawock.market_data.gold import update as gold_update


def _write(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _inject_before_lock(monkeypatch, module, edit):
    def wrapped(path, callback):
        mutate_json(path, edit)
        return mutate_json(path, callback)
    monkeypatch.setattr(module, 'mutate_json', wrapped)


def test_aggregates_uses_latest_quote_before_deriving(tmp_path, monkeypatch):
    path = tmp_path / 'portfolio.json'
    _write(path, {'portfolios': {'us_stocks': {'holdings': [
        {'ticker': 'X', 'shares': 10, 'cost_basis': 90, 'prev_close': 99,
         'current_price': 100, 'current_value': 1000}]}}})
    def quote(data):
        data['portfolios']['us_stocks']['holdings'][0]['current_price'] = 110
        return data
    _inject_before_lock(monkeypatch, aggregates, quote)
    assert aggregates.main(['--path', str(path)]) == 0
    row = _read(path)['portfolios']['us_stocks']['holdings'][0]
    assert row['current_price'] == 110
    assert row['current_value'] == 1100
    assert row['today_change'] == 110


def test_realized_preserves_quote_committed_before_reconcile(tmp_path, monkeypatch):
    path = tmp_path / 'portfolio.json'
    _write(path, {'portfolios': {'us_stocks': {'holdings': [
        {'ticker': 'X', 'current_price': 100, 'trades': [
            {'date': '2026-09-01', 'shares': 1, 'price': 10, 'realized_pnl': 2}]}]}}})
    def quote(data):
        data['portfolios']['us_stocks']['holdings'][0]['current_price'] = 110
        return data
    _inject_before_lock(monkeypatch, realized, quote)
    assert realized.main(['--path', str(path)]) == 0
    book = _read(path)['portfolios']['us_stocks']
    assert book['holdings'][0]['current_price'] == 110
    assert book['realized_pnl'] == 2


def test_gold_update_preserves_other_writer_fields(tmp_path, monkeypatch):
    path = tmp_path / 'portfolio.json'
    _write(path, {'gold_dca': {'fund_code': 'A', 'principal_invested': 100,
                              'units_held': 10, 'reconciled_date': '2026-09-01'},
                  'portfolios': {'us_stocks': {'current_price': 100}}})
    monkeypatch.setattr(gold_update, 'PORTFOLIO', str(path))
    monkeypatch.setattr(sys, 'argv', ['clawock-gold-update', '--principal', '200',
                                     '--units', '20', '--no-refresh'])
    def quote(data):
        data['portfolios']['us_stocks']['current_price'] = 110
        return data
    _inject_before_lock(monkeypatch, gold_update, quote)
    assert gold_update.main() == 0
    data = _read(path)
    assert data['portfolios']['us_stocks']['current_price'] == 110
    assert data['gold_dca']['principal_invested'] == 200


def test_aggregates_dry_run_does_not_write(tmp_path):
    path = tmp_path / 'portfolio.json'
    _write(path, {'portfolios': {'us_stocks': {'holdings': [
        {'ticker': 'X', 'shares': 1, 'cost_basis': 1, 'current_price': 2}]}}})
    before = path.read_bytes()
    assert aggregates.main(['--path', str(path), '--dry-run']) == 0
    assert path.read_bytes() == before
