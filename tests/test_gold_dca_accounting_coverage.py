"""Fund accounting must outlive the rolling chart window and fail safely on short reads."""
import json
from datetime import date, timedelta

import pytest

from clawock.market_data.gold import fetch as gold


def rows(count=500):
    start = date(2026, 1, 1)
    return [((start + timedelta(days=i)).isoformat(), 2.0, 0.0) for i in range(count)]


def seed():
    return {'principal_invested': 1000, 'units_held': 500, 'daily_amount': 200,
            'start_date': '2026-01-01', 'reconciled_date': '2026-01-02'}


def test_paging_continues_past_chart_limit_to_accounting_basis(monkeypatch):
    history = rows()
    calls = []
    def response(_url, _referer, *, params, **kwargs):
        page = params['pageIndex']
        calls.append(page)
        batch = list(reversed(history))[(page-1)*20:page*20]
        return json.dumps({'Data': {'LSJZList': [
            {'FSRQ': d, 'DWJZ': str(n), 'JZZZL': str(c)} for d, n, c in batch]}})
    monkeypatch.setattr(gold, '_em_text', response)
    fetched = gold.fetch_nav_history('000217', until='2026-01-01')
    assert fetched == history and len(calls) > gold.HISTORY_PAGES
    result = gold.compute(seed(), fetched, None)
    assert result['days_invested'] == 500
    assert result['auto_added_days'] == 498
    assert result['principal_effective'] == 1000 + 498*200
    assert len(result['nav_history']) == gold.HISTORY_KEEP
    assert gold.GROUND_TRUTH_FIELDS.isdisjoint(result)


def test_repeated_page_stops_and_incomplete_accounting_is_refused(monkeypatch):
    batch = {'Data': {'LSJZList': [{'FSRQ': '2026-10-01', 'DWJZ': '2'}]}}
    calls = []
    def response(*args, **kwargs):
        calls.append(kwargs['params']['pageIndex'])
        return json.dumps(batch)
    monkeypatch.setattr(gold, '_em_text', response)
    fetched = gold.fetch_nav_history('000217', until='2026-01-01')
    assert len(calls) == 2
    with pytest.raises(ValueError, match='未覆盖'):
        gold.compute(seed(), fetched, None)


def test_main_preserves_file_bytes_on_partial_nonempty_history(monkeypatch, tmp_path):
    portfolio = tmp_path / 'portfolio.json'
    original = json.dumps({'gold_dca': dict(seed(), fund_code='000217', nav=2,
                                           principal_effective=2000)})
    portfolio.write_text(original)
    monkeypatch.setattr(gold, 'PORTFOLIO', str(portfolio))
    monkeypatch.setattr(gold, 'fetch_nav_history', lambda *a, **k: rows()[-160:])
    monkeypatch.setattr(gold, 'fetch_realtime', lambda *a: None)
    assert gold.main() == 0
    assert portfolio.read_text() == original
