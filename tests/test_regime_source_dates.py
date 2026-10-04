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
