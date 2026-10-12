import pytest

from clawock.decision import regime


def test_us_fetch_keeps_its_own_last_valid_bar_date(monkeypatch):
    class Response:
        def json(self):
            return {'data': {'usTEST': {'qfqday': [
                ['2026-09-30', '9', '10'], ['2026-10-01', '10', '11'],
                ['2026-10-02', '10', 'bad']]}}}
    monkeypatch.setattr(regime.requests, 'get', lambda *a, **kw: Response())
    closes = regime.fetch_us('usTEST')
    assert closes == [10, 11] and closes.as_of == '2026-10-01'


def test_short_history_name_keeps_its_date(monkeypatch):
    closes = regime.DatedCloses()
    closes.extend(range(10, 20))
    closes.as_of = '2026-10-01'
    etf = next(iter(regime.US_2X_MAP))
    monkeypatch.setattr(regime, '_held_us_lev_etfs', lambda: [etf])
    monkeypatch.setattr(regime, 'fetch_us', lambda sym: closes)
    result = regime.compute_us()
    assert result['names'][0]['as_of'] == result['as_of'] == '2026-10-01'


def test_radar_uses_each_names_date_without_hk_fallback():
    from clawock.publish.dashboard import compute_reentry_radar
    lev = {'as_of': '2026-09-30', 'hk': {'close': 100, 'ma': 110},
           'us': {'names': [{'etf': 'SPCH', 'underlying': 'SPCX', 'close': 9, 'ma': 10,
                             'as_of': '2026-10-01'},
                            {'etf': 'RKLX', 'underlying': 'RKLB', 'close': 19, 'ma': 20}]}}
    result = compute_reentry_radar(lev, {})
    dates = {r['name']: r['as_of'] for r in result['watches']}
    assert dates == {'HSTECH': '2026-09-30', 'SPCX': '2026-10-01', 'RKLB': None}


@pytest.mark.parametrize('count', [199, 200, 201])
def test_us_full_regime_starts_at_200_bars(monkeypatch, count):
    base = [100 + .25 * i for i in range(198)] + [140., 138., 139.]
    monkeypatch.setattr(regime, '_held_us_lev_etfs', lambda: ['SPCH'])
    monkeypatch.setattr(regime, 'fetch_us', lambda sym: base[:count])
    row = regime.compute_us()['names'][0]
    assert row['regime_basis'] == ('short_ma_5' if count == 199 else 'ma_200_and_20d_realized_vol')
    if count >= 200:
        assert row['state'] == 'ok'
    assert row['vol_annualized'] == round(regime.compute(base[:count])[1], 4)


@pytest.mark.parametrize('count', [20, 21, 83])
def test_short_ma_volatility_has_its_own_sample_requirement(monkeypatch, count):
    from clawock.portfolio.guardrail import compute_breakeven_math, compute_risk_guardrail
    from clawock.harness.brief_render import breakeven_section
    closes = [100 + (i % 3) for i in range(count - 1)] + [95]
    monkeypatch.setattr(regime, '_held_us_lev_etfs', lambda: ['SPCH'])
    monkeypatch.setattr(regime, 'fetch_us', lambda sym: closes)
    us = regime.compute_us()
    row = us['names'][0]
    assert row['state'] == 'cut'  # short-MA policy remains intact, regardless of vol
    assert row['vol_n_returns'] == min(20, count - 1)
    assert (row['vol_annualized'] is None) == (count == 20)
    held = [{'ticker': 'SPCH', 'shares': 1, 'cost_basis': 100,
             'current_price': 95, 'current_value': 95, 'pnl_percent': -5}]
    lev = {'us': us}
    math = compute_breakeven_math([], held, lev)
    text = breakeven_section({'breakeven_math': math})
    if count == 20:
        assert '收益样本不足 20 根（仅 19 根）' in text
    else:
        assert math['rows'][0]['chop_drag_pct_per_month'] > 0
        assert 'vol_unavailable_reason' not in math['rows'][0]
    guard = compute_risk_guardrail([], held, {}, {}, {}, lev)
    breach = next(b for b in guard['breaches'] if b['type'] == 'regime_delever')
    assert 'short_ma_5' in breach['detail']
    assert '过热' not in breach['detail']
    assert '波动>70%' not in breach['action']
