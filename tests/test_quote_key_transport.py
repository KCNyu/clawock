"""API credentials must never reach request URLs or failure diagnostics."""
from clawock.market_data import us_quotes


def test_polygon_prev_key_is_header_only_even_on_failure(monkeypatch, capsys):
    key = 'fake-secret-for-test'

    def fail(url, **kwargs):
        assert key not in url
        assert kwargs['params'] == {'adjusted': 'true'}
        assert kwargs['headers'] == {'Authorization': f'Bearer {key}'}
        raise RuntimeError(f'failed https://example.test/?apiKey={key}')

    monkeypatch.setattr(us_quotes.SESSION, 'get', fail)
    assert us_quotes.get_prev_close_polygon('ABC', key) is None
    output = capsys.readouterr().err
    assert 'RuntimeError' in output
    assert key not in output and 'apiKey=' not in output


def test_other_polygon_paths_use_the_same_header_contract(monkeypatch, tmp_path):
    from clawock.market_data import us_analysis
    from clawock.portfolio import risk
    key = 'fake-secret-for-test'
    calls = []

    class Response:
        status_code = 200
        content = b'{}'

        def json(self):
            return {'results': [{'T': 'ABC', 'o': 9, 'h': 11, 'l': 8, 'c': 10, 't': 1788000000000}]}

    def get(url, **kwargs):
        assert key not in url
        assert 'apiKey' not in kwargs.get('params', {})
        assert kwargs['headers'] == {'Authorization': f'Bearer {key}'}
        calls.append(url)
        return Response()

    monkeypatch.setattr(us_quotes.SESSION, 'get', get)
    monkeypatch.setattr(risk.requests, 'get', get)
    monkeypatch.setattr(risk, 'API_KEYS', {'POLYGON_API_KEY': key})
    assert us_quotes.get_polygon_quote('ABC', key)['c'] == 10
    assert us_quotes.get_prev_close_polygon('ABC', key)[0] == 10
    assert us_quotes.get_prev_closes_polygon_grouped(['ABC'], key, '2026-08-28', cache_dir=tmp_path)[2]
    assert us_analysis.get_daily_closes_polygon('ABC', key) == [10]
    assert risk._fetch_polygon_history('ABC')
    assert len(calls) == 5
