"""Freeze the normalized HK writer before policy extraction (#2729).

Expected return values, persisted books and diagnostics were captured from
49797452c before extraction, without network or live portfolio access.
"""
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from clawock.market_data import hk_analysis as hk

CASES = json.loads((Path(__file__).parent / 'fixtures' / 'hk_quote_policies.json').read_text())


def run_case(module, case, monkeypatch, path, capsys):
    instant = datetime.fromisoformat(case['now'])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(module, 'datetime', Clock)
    monkeypatch.setattr(module, 'PORTFOLIO_PATH', str(path))
    monkeypatch.setattr(module, 'fetch_hk_quotes', lambda codes: copy.deepcopy(case['quotes']))

    def indices():
        if case['indices'] == 'failed':
            raise RuntimeError('index provider down')
        return copy.deepcopy(case['indices'])

    monkeypatch.setattr(module, 'fetch_indices', indices)
    path.write_text(json.dumps(case['portfolio']))
    error = None
    try:
        returned = module.update_hk_portfolio(dry_run=case['dry_run'])
    except RuntimeError as exc:
        returned, error = None, str(exc)
    out, err = capsys.readouterr()
    return {'returned': returned, 'written': json.loads(path.read_text()),
            'stdout': out.replace(str(path), '<portfolio>'), 'stderr': err, 'error': error}


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_writer_replays_pre_extraction_results(case, monkeypatch, tmp_path, capsys):
    expected = copy.deepcopy(case['expected'])
    if case['name'] == 'approx-absent':
        # #3023: absence is now explicit and cannot carry yesterday's value.
        for key in ('returned', 'written'):
            row = expected[key]['portfolios']['hk_stocks']['holdings'][0]
            row.update(today_change=None, today_change_pct=None)
    assert run_case(hk, case, monkeypatch, tmp_path / 'portfolio.json', capsys) == expected


def test_numeric_string_shares_refresh_without_rewriting_ledger(monkeypatch, tmp_path, capsys):
    case = copy.deepcopy(CASES[0])
    for h in case['portfolio']['portfolios']['hk_stocks']['holdings']:
        h['shares'] = str(h['shares'])
    actual = run_case(hk, case, monkeypatch, tmp_path / 'portfolio.json', capsys)
    expected = copy.deepcopy(case['expected'])
    for key in ('returned', 'written'):
        for h in expected[key]['portfolios']['hk_stocks']['holdings']:
            h['shares'] = str(h['shares'])
    assert actual == expected


def test_missing_fallback_prior_close_clears_previous_day_change():
    case = next(c for c in CASES if c['name'] == 'approx-absent')
    holding = copy.deepcopy(case['portfolio']['portfolios']['hk_stocks']['holdings'][0])
    holding.update(today_change=999, today_change_pct=99, today_change_abs=999)
    quote = copy.deepcopy(next(iter(case['quotes'].values())))
    hk._hk_apply_quote(holding, quote, datetime.fromisoformat(case['now']), '2026-09-01', [])
    assert holding['quote_incomplete']
    assert holding['today_change'] is None and holding['today_change_pct'] is None
    assert 'today_change_abs' not in holding


def test_divergence_survives_fetch_write_and_clears_on_new_quote(monkeypatch, tmp_path, capsys):
    case = copy.deepcopy(CASES[0])
    code, quote = next(iter(case['quotes'].items()))
    monkeypatch.setattr(hk, '_fetch_tencent_hk', lambda codes: {code: dict(quote)})
    alternate = dict(quote, c=quote['c'] * 1.03)
    monkeypatch.setattr(hk, '_fetch_eastmoney_hk', lambda codes: {code: alternate})
    fetched = hk.fetch_hk_quotes([code])[code]
    assert fetched['_divergence']['c_div_pct'] == 3
    alternate['c'] = quote['c']
    assert '_divergence' not in hk.fetch_hk_quotes([code])[code]
    case['quotes'][code] = fetched
    actual = run_case(hk, case, monkeypatch, tmp_path / 'portfolio.json', capsys)
    row = next(h for h in actual['written']['portfolios']['hk_stocks']['holdings'] if h['ticker'] == code)
    assert row['quote_divergence']['c_div_pct'] == 3
    assert '分歧 c 3' in row['data_source']
    assert row['current_price'] == round(quote['c'], 3)
    hk._hk_apply_quote(row, quote, datetime.fromisoformat(case['now']), '2026-09-01', [])
    assert 'quote_divergence' not in row and '分歧' not in row['data_source']


def test_fallback_quote_on_a_new_session_drops_the_previous_range():
    """#3158: a source without high/low must not carry yesterday's range into today."""
    case = next(c for c in CASES if c['name'] == 'approx-absent')
    holding = copy.deepcopy(case['portfolio']['portfolios']['hk_stocks']['holdings'][0])
    now = datetime.fromisoformat(case['now'])
    session = hk._hk_quote_session(now).isoformat()
    quote = {'name': 'X', 'c': 10.0, 'pc': 10.2, 'o': 10.1, 'dp': -1.96, '_src': 'yfinance'}

    holding.update(day_session_date='2000-01-03', day_low=12.0, day_high=13.0)
    hk._hk_apply_quote(holding, copy.deepcopy(quote), now, '2026-09-01', [])
    assert holding['day_session_date'] == session
    assert 'day_low' not in holding and 'day_high' not in holding
    assert holding['day_open'] == 10.1

    holding.update(day_low=9.8, day_high=10.4)
    hk._hk_apply_quote(holding, copy.deepcopy(quote), now, '2026-09-01', [])
    assert (holding['day_low'], holding['day_high']) == (9.8, 10.4), (
        'within one session the last real range stays')


def test_eastmoney_quote_keeps_the_session_high_and_low(monkeypatch):
    class Reply:
        def json(self):
            return {'data': {'diff': [
                {'f12': '00100', 'f14': 'X', 'f2': 160.7, 'f3': -6.5, 'f15': 172.2,
                 'f16': 158.1, 'f17': 171.0, 'f18': 171.9},
                {'f12': '02208', 'f14': 'Y', 'f2': 9.1, 'f3': 0.0, 'f15': '-',
                 'f16': '-', 'f17': 9.1, 'f18': 9.1},
            ]}}

    monkeypatch.setattr(hk, 'em_get', lambda *a, **k: Reply())
    out = hk._fetch_eastmoney_hk(['00100', '02208'])
    assert (out['00100']['h'], out['00100']['l']) == (172.2, 158.1)
    assert 'h' not in out['02208'] and 'l' not in out['02208']


@pytest.mark.parametrize('value, expected', [(None, 30000), (0, 0), (31000, 31000)])
def test_finalize_carries_unpriced_rows_at_cost(value, expected, monkeypatch):
    data = copy.deepcopy(CASES[0]['portfolio'])
    region = data['portfolios']['hk_stocks']
    row = region['holdings'][0]
    row['current_value'] = value
    monkeypatch.setattr(hk, 'fetch_indices', lambda: {})
    hk._hk_finalize_region(data, 'hk_stocks', copy.deepcopy(region), [row],
                           '2026/10/06 12:00 HKT', [], [], True)
    assert region['total_current_value'] == expected
    assert region['total_pnl'] == expected - 30000
