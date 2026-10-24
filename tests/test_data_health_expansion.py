"""Provider failures, observation dates and newly connected macro surfaces."""
import json
from datetime import datetime, timezone

import pytest

from clawock.market_data import cboe, macro, fund_flows, fundamentals
from clawock.portfolio import fx
from clawock.strategies.plugins.morning_scans import Scans

AT = datetime(2026, 10, 24, 8, tzinfo=timezone.utc)
CSV = 'DATE,OPEN,HIGH,LOW,CLOSE\n10/22/2026,19,20,18,19.03\n10/23/2026,19,20,18,19.45\n'


class Response:
    status_code = 200

    def __init__(self, text='', payload=None):
        self.text, self.payload = text, payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


def test_cboe_prior_close_dates_and_no_future_or_invalid_observations():
    row = cboe.parse_history(CSV + '10/26/2026,0,0,0,999\n10/23/2026,0,0,0,NaN\n', 'VIX', at=AT)
    assert row['price'] == 19.45 and row['prev'] == 19.03
    assert row['as_of'] == '2026-10-23' and row['previous_as_of'] == '2026-10-22'
    assert row['change_pct'] == 2.21
    assert cboe.parse_history(CSV.splitlines()[0] + '\n' + CSV.splitlines()[1], 'VIX', at=AT) is None
    assert cboe.parse_history('DATE,SKEW\n10/23/2026,151.8\n', 'SKEW', at=AT)['price'] == 151.8


def test_cboe_missing_previous_session_is_not_multiday_change():
    row = cboe.parse_history(CSV.replace('10/22/2026', '10/21/2026'), 'VIX', at=AT)
    assert row['prev'] is None and row['change_pct'] is None
    assert cboe.term_structure(row, dict(row, as_of='2026-10-22')) is None


def test_scan_falls_back_to_official_vix_and_connects_new_surfaces(monkeypatch):
    monkeypatch.setattr(macro, 'yahoo_quote', lambda symbol: None)
    monkeypatch.setattr(macro, 'cnn_fear_greed', lambda: None)
    monkeypatch.setattr(macro, 'fed_press_releases', lambda days: [])
    monkeypatch.setattr(cboe, 'fetch_quote', lambda symbol, at: cboe.parse_history(
        'DATE,SKEW\n10/23/2026,151.8\n' if symbol == 'SKEW' else CSV, symbol, at=at))
    out = macro.collect(at=AT)
    assert out['vix']['source'] == 'cboe'
    assert out['coverage']['vix'] == 'ok'
    assert out['coverage']['spx'] == 'unavailable'
    assert out['volatility_term_structure']['vix_to_vix3m'] == 1
    assert out['volatility']['skew']['price'] == 151.8


def test_fresh_index_cannot_hide_stale_vix_from_brief(tmp_path):
    current = {'price': 20, 'as_of': '2026-10-23', 'source': 'cboe'}
    stale = dict(current, as_of='2026-10-22')
    data = {'generated_at': AT.isoformat(), 'spx': current, 'vix': stale,
            'coverage': {'vix': 'ok'},  # even a stale producer verdict is rechecked
            'volatility': {'vix': stale, 'vix3m': current, 'skew': current}}
    folder = tmp_path / 'assets/data'
    folder.mkdir(parents=True)
    (folder / 'macro.json').write_text(json.dumps(data))
    reading = Scans(36).macro(tmp_path, at=AT)['reading']
    assert reading['vix'] is None and reading['spx']['price'] == 20
    assert reading['coverage']['vix'] == 'stale'
    assert reading['volatility_term_structure'] is None
    assert reading['volatility']['skew']['as_of'] == '2026-10-23'
    assert reading['regime'] is None


def test_tencent_spx_is_inx_not_nasdaq_and_hk_compact_dates(monkeypatch):
    parts = [''] * 33
    parts[3], parts[4], parts[30], parts[32] = '7623.68', '7663.43', '2026-10-23 16:38:21', '-0.52'
    urls = []

    def get(url, **kwargs):
        urls.append(url)
        return Response('N/D' if 'stooq' in url else 'v_r_usINX="' + '~'.join(parts) + '";')

    monkeypatch.setattr(macro.requests, 'get', get)
    row = macro.yahoo_quote('^GSPC')
    assert row['source'] == 'tencent' and row['price'] == 7623.68
    assert urls[-1].endswith('r_usINX')
    assert macro._quote('^HSI', 10, 9, 11.11, 'tencent', '20261023160000')['as_of'] == '2026-10-23'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, True])
def test_bad_price_never_becomes_a_quote(value):
    assert macro._quote('X', value, 1, None, 'yahoo', 1) is None


def test_open_fx_rejects_error_stale_future_and_wrong_base(monkeypatch):
    monkeypatch.setattr(fx.time, 'time', lambda: AT.timestamp())
    payload = {'result': 'success', 'base_code': 'USD', 'rates': {'HKD': 7.84},
               'time_last_update_unix': AT.timestamp() - 3600}
    monkeypatch.setattr(fx.SESSION, 'get', lambda *a, **kw: Response(payload=payload))
    assert fx._get_open_er_api() == 7.84
    for update in ({'result': 'error'}, {'base_code': 'EUR'},
                   {'time_last_update_unix': AT.timestamp() - 97 * 3600},
                   {'time_last_update_unix': AT.timestamp() + 3600}):
        old = dict(payload)
        payload.update(update)
        assert fx._get_open_er_api() is None
        payload.clear()
        payload.update(old)


def test_empty_fundflow_and_fundamentals_are_unavailable_not_zero(monkeypatch, capsys):
    sym = {'secid': '116.00700', 'secucode': '00700.HK', 'mkt_num': 116}
    monkeypatch.setattr(fund_flows, 'resolve', lambda code: sym)
    monkeypatch.setattr(fund_flows, 'get_fund_flow', lambda *a: [])
    fund_flows.main(['00700', '--json'])
    assert json.loads(capsys.readouterr().out)['status'] == 'unavailable'
    monkeypatch.setattr(fundamentals, 'resolve', lambda code: sym)
    monkeypatch.setattr(fundamentals, 'get_indicators', lambda *a: [])
    fundamentals.main(['00700', '--json'])
    assert json.loads(capsys.readouterr().out)['status'] == 'unavailable'


def test_new_snapshot_cannot_publish_only_stale_quotes(tmp_path):
    from clawock.publish.artifacts import validate_macro
    path = tmp_path / 'macro.json'
    data = {'generated_at': AT.isoformat(), 'coverage': {'vix': 'ok'},
            'vix': {'price': 20, 'source': 'cboe', 'as_of': '2026-10-22'}}
    path.write_text(json.dumps(data))
    with pytest.raises(AssertionError, match='zero successful'):
        validate_macro(path, now=AT)
    data['vix']['as_of'] = '2026-10-23'
    path.write_text(json.dumps(data))
    validate_macro(path, now=AT)


def test_new_volatility_values_reach_brief_with_observation_dates():
    from clawock.harness.brief_render import macro_section
    result = macro_section({'macro': {'volatility': {
        'vix9d': {'price': 18.7, 'as_of': '2026-10-23'},
        'skew': {'price': 151.8, 'as_of': '2026-10-23'}},
        'coverage': {'dxy': 'unavailable'}}}, {})
    assert 'VIX9D' in result and 'SKEW' in result
    assert '2026-10-23 收盘' in result and '数据缺失或过期：DXY' in result
