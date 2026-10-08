"""One HSTECH request/parser with explicit live vs research error policy."""
import pytest

from clawock.decision import regime
from clawock.evaluation import hstech_regime, regime_validation
from clawock.market_data import hstech


@pytest.mark.parametrize('series_key', ['day', 'qfqday'])
def test_shared_fetch_handles_bad_rows_and_explicit_window(monkeypatch, series_key):
    calls = []

    class Response:
        def json(self):
            return {'data': {'hkHSTECH': {series_key: [
                ['2026-10-06', '1', '123.5'], [], ['bad', 1, None],
                ['bad', 1, 'invalid'], ['2026-10-07', 1, '124'],
            ]}}}

    def get(url, timeout):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr(hstech.requests, 'get', get)
    expected = [('2026-10-06', 123.5), ('2026-10-07', 124.0)]
    for fetch in (hstech.fetch_hstech, hstech_regime.fetch_hstech,
                  regime_validation.fetch_hstech, regime.fetch_hstech):
        assert fetch(start='2026-10-06', end='2026-10-07', lim=2) == expected
    assert len(calls) == 4
    assert all(url.endswith('param=hkHSTECH,day,2026-10-06,2026-10-07,2')
               and timeout == 20 for url, timeout in calls)


def test_live_fetch_degrades_while_research_fails(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError('network unavailable')

    monkeypatch.setattr(hstech.requests, 'get', fail)
    assert regime.fetch_hstech() == []
    assert 'HSTECH fetch failed' in capsys.readouterr().err
    for fetch in (hstech_regime.fetch_hstech, regime_validation.fetch_hstech):
        with pytest.raises(RuntimeError, match='network unavailable'):
            fetch()
