"""The combined-book evaluation must use the shipped HK tier, including cash."""
import pytest
from clawock.decision import regime
from clawock.evaluation import combined_regime


@pytest.mark.parametrize('close,ma,vol,expected', [
    (110, 100, 0.1, 2), (110, 100, 0.9, 1),
    (90, 100, 0.1, 1), (90, 100, 0.9, 0),
    (90, None, None, 0), (110, 100, None, 1),
])
def test_hk_evaluation_matches_production(close, ma, vol, expected):
    actual = combined_regime.hk_effective_leverage(close, ma, vol)
    assert actual == expected == 2 * regime.classify(close, ma, vol)[3]


@pytest.mark.parametrize('kind,sym', [('hk', 'hkHSTECH'), ('hk', 'hk02208'), ('us', 'usMSFT.OQ')])
def test_fetch_skips_bad_closes_without_losing_good_bars(monkeypatch, kind, sym):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return type('Response', (), {'json': lambda self: {'data': {sym: {'day': [
            ['2026-10-06', '1', '123.5'], [], None, ['bad', 1, None],
            ['bad', 1, 'invalid'], ['2026-10-07', 1, '124'],
        ]}}}})()

    monkeypatch.setattr(combined_regime.requests, 'get', get)
    assert combined_regime.fetch(kind, sym, cnt=2) == {'2026-10-06': 123.5, '2026-10-07': 124.0}
    assert len(calls) == 1
    if kind == 'hk':
        assert f'param={sym},day,2020-01-01,' in calls[0]
        assert calls[0].endswith(',2')


def test_combined_hstech_uses_shared_owner(monkeypatch):
    calls = []
    monkeypatch.setattr(combined_regime, 'fetch_hstech', lambda **kw: calls.append(kw) or [('2026-10-07', 124)])
    assert combined_regime.fetch('hk', 'hkHSTECH', 42) == {'2026-10-07': 124}
    assert calls == [{'start': '2020-01-01', 'lim': 42}]
