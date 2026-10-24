"""Free-source dates, entitlement failures, privacy boundaries and request budgets."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from clawock.market_data import treasury, private_research as private, macro, fundamentals
from clawock.strategies.plugins.morning_scans import Scans

AT = datetime(2026, 10, 24, 8, tzinfo=timezone.utc)


def curve_csv(day='10/23/2026', missing=None):
    columns = list(treasury.MATURITIES)
    values = ['4'] * len(columns)
    values[columns.index('10 Yr')] = '5.1'
    if missing:
        values[columns.index(missing)] = 'N/A'
    return 'Date,' + ','.join(columns) + '\n' + day + ',' + ','.join(values) + '\n'


class Response:
    def __init__(self, data=None, text='', status=200):
        self.data, self.text, self.status_code = data, text, status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError('redacted test error')


def test_curve_has_fourteen_tenors_and_same_date_basis_points():
    row = treasury.parse_curve(curve_csv(), at=AT)
    assert len(row['yields']) == 14
    assert row['spread_10y_2y_bps'] == 110
    assert row['spread_10y_3m_bps'] == 110
    assert row['unit'] == 'percent' and row['as_of'] == '2026-10-23'
    assert row['status'] == 'ok' and row['missing_maturities'] == []


def test_missing_latest_tenor_is_not_backfilled_from_previous_day():
    text = curve_csv('10/22/2026') + curve_csv(missing='10 Yr').split('\n')[1] + '\n'
    row = treasury.parse_curve(text, at=AT)
    assert row['yields']['10y'] is None
    assert row['spread_10y_2y_bps'] is None and row['missing_maturities'] == ['10y']
    assert treasury.parse_curve(curve_csv('10/26/2026'), at=AT) is None
    assert treasury.parse_curve(curve_csv('10/01/2026'), at=AT)['status'] == 'stale'


def test_january_empty_current_year_uses_december(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return Response(text='Date,10 Yr\n' if len(calls) == 1 else curve_csv('12/31/2025'))
    monkeypatch.setattr(treasury.requests, 'get', get)
    row = treasury.fetch_curve(at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    assert row['as_of'] == '2025-12-31' and row['status'] == 'ok'
    assert '/2025/' in calls[-1]


def test_macro_treasury_fallback_does_not_rescale_percent_yield(monkeypatch):
    row = treasury.parse_curve(curve_csv().replace('5.1', '12.1'), at=AT)
    monkeypatch.setattr(treasury, 'fetch_curve', lambda **kw: row)
    monkeypatch.setattr(macro, 'yahoo_quote', lambda symbol: None)
    monkeypatch.setattr(macro.cboe, 'fetch_quote', lambda *a, **kw: None)
    monkeypatch.setattr(macro, 'cnn_fear_greed', lambda: None)
    monkeypatch.setattr(macro, 'fed_press_releases', lambda **kw: [])
    out = macro.collect(at=AT)
    assert out['treasury_10y']['yield_pct'] == 12.1
    assert out['treasury_10y']['source'] == 'us_treasury'
    assert out['treasury_10y']['change_pct'] is None
    assert 'credit_spreads' not in out and 'analysts' not in out


def test_reader_rechecks_curve_date_and_renderer_shows_dated_spread(tmp_path):
    from clawock.harness.brief_render import macro_section
    path = tmp_path / 'assets/data/macro.json'
    path.parent.mkdir(parents=True)
    data = {'generated_at': AT.isoformat(), 'treasury_curve': treasury.parse_curve(curve_csv(), at=AT)}
    path.write_text(json.dumps(data))
    answer = Scans(36).macro(tmp_path, at=AT)
    assert answer['reading']['treasury_curve']['spread_10y_2y_bps'] == 110
    assert '2026-10-23' in macro_section({'macro': answer['reading']}, {})
    data['treasury_curve']['as_of'] = '2026-10-01'
    path.write_text(json.dumps(data))
    answer = Scans(36).macro(tmp_path, at=AT)
    assert answer['reading']['treasury_curve'] is None
    assert answer['reading']['coverage']['treasury_curve'] == 'stale'


def test_analyst_personal_query_uses_two_requests_then_private_cache(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv('FINNHUB_API_KEY', 'test-only-key')
    def get(url, **kwargs):
        calls.append(url)
        assert 'token' not in kwargs['params']
        assert kwargs['headers']['X-Finnhub-Token'] == 'test-only-key'
        if url.endswith('recommendation'):
            return Response([{'symbol': 'AAPL', 'period': '2026-10-01', 'strongBuy': 1, 'buy': 2,
                              'hold': 3, 'sell': 0, 'strongSell': 0}])
        return Response([{'symbol': 'AAPL', 'period': '2026-06-30', 'estimate': 1.5,
                          'actual': 1.6, 'surprise': 0.1, 'surprisePercent': 6.67}])
    monkeypatch.setattr(private.requests, 'get', get)
    first = private.analysts('AAPL', workspace=tmp_path, at=AT)
    again = private.analysts('AAPL', workspace=tmp_path, at=AT + timedelta(hours=1))
    assert first == again and len(calls) == 2
    assert first['status'] == 'ok' and first['visibility'] == 'private_personal_use'
    assert first['not_provided'] == ['forward_eps_consensus', 'price_targets']
    assert not (tmp_path / 'assets').exists()
    cache = tmp_path / '.cache/private-market-data/analysts-AAPL.json'
    assert cache.stat().st_mode & 0o777 == 0o600
    assert 'test-only-key' not in cache.read_text()


@pytest.mark.parametrize('http,status', [(403, 'denied'), (429, 'rate_limited')])
def test_entitlement_failures_are_not_empty_consensus(monkeypatch, tmp_path, http, status):
    monkeypatch.setenv('FINNHUB_API_KEY', 'test-only-key')
    monkeypatch.setattr(private.requests, 'get', lambda *a, **kw: Response(status=http))
    out = private.analysts('AAPL', workspace=tmp_path, at=AT)
    assert out['status'] == 'unavailable'
    assert out['recommendation_trends']['status'] == status
    assert not (tmp_path / '.cache/private-market-data/analysts-AAPL.json').exists()


def test_wrong_symbol_bad_counts_and_future_periods_are_rejected():
    base = {'symbol': 'AAPL', 'period': '2026-10-01', 'buy': 3}
    rows = [dict(base, symbol='MSFT'), dict(base, period='2026-11-01'), dict(base, buy=True),
            dict(base, buy=float('nan')), dict(base, buy=-1), dict(base, buy=1.2)]
    assert private._rows(rows, 'AAPL', ('buy',), AT, counts=True) == []
    with pytest.raises(ValueError):
        private.analysts('../secret')


def test_credit_spread_retains_observation_lag_and_units(monkeypatch, tmp_path):
    monkeypatch.setattr(private.requests, 'get', lambda *a, **kw: Response(text=
        'observation_date,BAA10Y\n2026-10-21,1.5\n2026-10-22,1.6\n2026-10-23,.\n2026-10-26,99\n'))
    out = private.credit_spread(workspace=tmp_path, at=AT)
    assert out['observation'] == {'as_of': '2026-10-22', 'value': 1.6, 'bps': 160, 'age_days': 2}
    assert out['visibility'] == 'private_personal_use'
    assert not (tmp_path / 'assets/data/macro.json').exists()


def test_credit_cli_never_writes_public_snapshot(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(private, 'credit_spread', lambda **kw: {'status': 'ok'})
    assert macro.main(['--workspace', str(tmp_path), '--credit-spreads']) == 0
    assert json.loads(capsys.readouterr().out) == {'status': 'ok'}
    assert not (tmp_path / 'assets').exists()
    with pytest.raises(SystemExit):
        macro.main(['--workspace', str(tmp_path), '--credit-spreads', '--output', 'public.json'])


def test_analyst_cli_does_not_resolve_eastmoney(monkeypatch, capsys):
    monkeypatch.setattr(private, 'analysts', lambda symbol: {'symbol': symbol, 'status': 'ok'})
    monkeypatch.setattr(fundamentals, 'resolve', lambda code: pytest.fail('unrelated provider queried'))
    assert fundamentals.main(['AAPL', '--analysts', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['symbol'] == 'AAPL'
