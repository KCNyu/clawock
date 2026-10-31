"""Synthetic Tencent protocol and degradation checks; no network in tests."""
from datetime import datetime, timezone
import json

import pytest
import requests

from clawock.market_data import hk_discovery as H, hk_discovery_live as L, stock_discovery as D

NOW = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline_sources(monkeypatch):
    from clawock.market_data import hk_discovery_scan as S, hk_discovery_eastmoney as E
    def fail(*args):
        raise ValueError('synthetic unavailable source')
    monkeypatch.setattr(S, 'fetch_roster', fail)
    monkeypatch.setattr(E, 'fetch_quotes', fail)
    monkeypatch.setattr(E, 'fetch_classifications', lambda deadline: ({}, {'missing': []}))


def wire(ticker='01234', stamp='2026/10/30 16:08:14', **fields):
    cells = [''] * 46
    for i, value in {1: 'Synthetic', 2: ticker, 3: '10', 4: '9.9', 30: stamp,
                     32: '1', 37: '30000000', 45: '200', **{int(k): v for k, v in fields.items()}}.items():
        cells[i] = value
    return f'v_r_hk{ticker}="' + '~'.join(cells) + '";'


def install(tmp_path):
    (tmp_path / 'config').mkdir()
    rows = [{'ticker': t, 'sector': s, 'industry': s, 'security_type': 'ordinary_share'}
            for t, s in [('01234', '工业'), ('02345', '金融'), ('03456', '工业')]]
    (tmp_path / 'config/hk-discovery-universe.json').write_text(json.dumps({'schema_version': 1, 'securities': rows}))
    (tmp_path / 'portfolio.json').write_text('{"portfolios": {}}')
    return {r['ticker']: r for r in rows}


def test_units_freshness_and_public_projection(tmp_path, monkeypatch):
    universe = install(tmp_path)
    text = '\n'.join(wire(t) for t in universe)
    rows, _, failed = L.parse_quotes(text, universe, NOW)
    assert not failed
    assert rows[0]['market_cap_hkd'] == 20_000_000_000
    assert rows[0]['turnover_hkd'] == 30_000_000
    monkeypatch.setattr(L, 'fetch_quotes', lambda _: text)
    result = H.collect(tmp_path, now=NOW)
    assert result['status'] == 'partial'
    assert [r['ticker'] for r in result['candidates']] == ['01234', '02345']
    assert all(not r['allowed'] and r['state'] == 'needs_entry_gate' for r in result['candidates'])
    encoded = json.dumps(result)
    assert '30000000' not in encoded and 'price_hkd": 10' not in encoded
    assert 'authorization_sha256' not in encoded
    assert '非全市场' in '\n'.join(D.candidate_lines(result))


@pytest.mark.parametrize('bad', [wire(stamp='2026/10/29 16:08:14'), wire(stamp='2026/10/30 15:00:00'),
                               wire(stamp='2026/10/30 19:00:00'), wire(**{'45': 'nan'}),
                               wire(**{'37': ''}), wire(**{'45': '1e308'}), wire() + '\n' + wire(), 'bad'])
def test_missing_rows_preserve_good_candidates(tmp_path, monkeypatch, bad):
    install(tmp_path)
    monkeypatch.setattr(L, 'fetch_quotes', lambda _: bad + '\n' + wire('02345'))
    result = H.collect(tmp_path, now=NOW)
    assert result['status'] == 'partial'
    assert [r['ticker'] for r in result['candidates']] == ['02345']
    assert set(result['missing']) == {'01234', '03456'}


def test_transport_failure_and_empty_feed_are_explicit(tmp_path, monkeypatch):
    install(tmp_path)
    def fail(_):
        raise requests.Timeout()
    for fetch in (fail, lambda _: ''):
        monkeypatch.setattr(L, 'fetch_quotes', fetch)
        result = H.collect(tmp_path, now=NOW)
        assert result['status'] == 'incomplete' and result['degraded']
        assert '没有符合' not in '\n'.join(D.candidate_lines(result))


def test_exposure_exclusion_and_combined_degradation(tmp_path, monkeypatch):
    install(tmp_path)
    (tmp_path / 'portfolio.json').write_text(json.dumps({'portfolios': {'HK': {'holdings': [
        {'ticker': '09999', 'shares': 10}]}}}))
    import clawock.instruments
    monkeypatch.setattr(clawock.instruments, 'load_registry', lambda *a, **kw: {'09999': {'underlying': '01234'}})
    monkeypatch.setattr(L, 'fetch_quotes', lambda _: '\n'.join(wire(t) for t in ['01234', '02345', '03456']))
    original = H.collect
    monkeypatch.setattr(H, 'collect', lambda workspace: original(workspace, now=NOW))
    result = D.collect(tmp_path, market='all')
    assert result['status'] == 'partial'
    assert '01234' not in [r['ticker'] for r in result['candidates']]
    assert result['markets']['HK']['rejections']['held_or_underlying'] == 1
    assert '非全市场' in '\n'.join(D.candidate_lines(result))
