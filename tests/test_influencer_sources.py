"""The 2026-09 source additions to the influence radar.

Three properties matter and none of them is visible from the workflow contract:

1. ARK's daily trades are aggregated per ticker for the LATEST session only
   (a fund that last traded last week must not smuggle an older date in), dust
   below the percent threshold is dropped, and a total interface failure is
   `failed` (→ the producer retains the previous run) while a quiet session is
   `success_empty` (→ nothing is resurrected).
2. Persona news items are second-hand headlines, so they must pass the same
   48h window as everything else even though Google News' own `when:2d`
   operator is already in the query.
3. A chatty source cannot eat the whole candidate batch: before per-source
   budgets existed, Trump alone could fill MAX_CANDIDATES and every newly
   added source would never reach the LLM call.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from clawock.automation import influencer as inf


class _Resp:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload


def _trade(fund, day, ticker, direction, shares, percent, company='Co'):
    return {'fund': fund, 'date': day, 'ticker': ticker, 'company': company,
            'direction': direction, 'shares': shares, 'etf_percent': percent}


def test_ark_keeps_only_the_latest_session_per_ticker(monkeypatch):
    today = datetime.now(timezone.utc).date()
    latest = (today - timedelta(days=1)).isoformat()
    older = (today - timedelta(days=4)).isoformat()
    payloads = {
        'ARKK': [_trade('ARKK', latest, 'COIN', 'Buy', 4200, 0.031, 'Coinbase'),
                 _trade('ARKK', latest, 'SLMT', 'Sell', 7035, 0.0004),
                 _trade('ARKK', older, 'TSLA', 'Sell', 900, 0.4)],
        'ARKW': [_trade('ARKW', latest, 'COIN', 'Buy', 700, 0.012, 'Coinbase')],
    }

    def fake_get(url, params=None, **kwargs):
        return _Resp({'trades': payloads.get(params['symbol'], [])})

    monkeypatch.setattr(inf.requests, 'get', fake_get)

    items, status = inf.fetch_ark()

    assert status == 'success'
    assert len(items) == 1                      # 一只票一条，多只 ETF 合并
    item = items[0]
    assert '(COIN)' in item['text'] and '买入' in item['text']
    assert 'ARKK 4,200 股' in item['text'] and 'ARKW 700 股' in item['text']
    assert 'TSLA' not in item['text']           # 上一交易日的动作被丢掉
    assert 'SLMT' not in item['text']           # 0.5bp 以下的碎单不进雷达
    assert item['published'] == f'{latest}T20:00:00+00:00'   # 交易日，不是抓取时刻
    assert item['origin'] == 'ark-funds'


def test_ark_interface_outage_is_failed_but_quiet_session_is_empty(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('network unavailable')

    monkeypatch.setattr(inf.requests, 'get', boom)
    assert inf.fetch_ark() == ([], 'failed')

    monkeypatch.setattr(inf.requests, 'get',
                        lambda *args, **kwargs: _Resp({'trades': []}))
    assert inf.fetch_ark() == ([], 'success_empty')


def test_ark_treats_a_http_error_as_failure_not_as_a_quiet_day(monkeypatch):
    monkeypatch.setattr(inf.requests, 'get',
                        lambda *args, **kwargs: _Resp({}, status_code=503))
    assert inf.fetch_ark() == ([], 'failed')


def test_persona_news_respects_the_shared_lookback(monkeypatch):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=inf.LOOKBACK_HOURS)
    fresh = (datetime.now(timezone.utc) - timedelta(hours=3))
    stale = (datetime.now(timezone.utc) - timedelta(days=6))
    spec = inf.PERSONA_SOURCES[0]
    monkeypatch.setattr(inf, 'fetch_google_news', lambda *a, **kw: ([
        {'title': 'fresh headline', 'published': fresh.strftime(
            '%a, %d %b %Y %H:%M:%S GMT'), 'source': 'HKET', 'url': 'u1'},
        {'title': 'week-old headline', 'published': stale.strftime(
            '%a, %d %b %Y %H:%M:%S GMT'), 'source': 'HKET', 'url': 'u2'},
    ], 'ok'))

    items, status = inf.fetch_persona(spec, cutoff)

    assert status == 'success'
    assert [it['text'] for it in items] == ['fresh headline']
    assert items[0]['author'] == spec['author']
    assert items[0]['origin'] == 'gnews-rss'


def test_persona_source_failure_is_reported_as_failed(monkeypatch):
    monkeypatch.setattr(inf, 'fetch_google_news',
                        lambda *a, **kw: ([], 'failed'))
    assert inf.fetch_persona(inf.PERSONA_SOURCES[0],
                             datetime.now(timezone.utc)) == ([], 'failed')


def _item(author, text):
    return {'author': author, 'text': text, 'published': '', 'url': ''}


def test_chatty_source_cannot_crowd_the_others_out(tmp_path, monkeypatch):
    """The reason per-source caps exist: one loud source used to fill the batch."""
    monkeypatch.setattr(inf, 'OUT_FILE', str(tmp_path / 'influencer.json'))
    monkeypatch.setattr(inf, 'load_holdings', lambda: [])
    flood = [_item('Trump', f'trump statement {i}') for i in range(60)]
    monkeypatch.setattr(inf, 'fetch_trump', lambda _cutoff: (flood, 'success'))
    monkeypatch.setattr(inf, 'fetch_musk', lambda: ([], 'success_empty'))
    monkeypatch.setattr(inf, 'fetch_ark', lambda _cutoff=None: (
        [_item('Cathie Wood', 'ark trade')], 'success'))
    monkeypatch.setattr(inf, 'fetch_serenity', lambda _cutoff: ([], 'success_empty'))
    monkeypatch.setattr(inf, 'fetch_persona', lambda spec, _cutoff: (
        [_item(spec['author'], f"{spec['key']} headline")], 'success'))
    seen = {}

    def fake_filter(candidates, _held):
        seen['candidates'] = candidates
        return {}

    monkeypatch.setattr(inf, 'llm_filter', fake_filter)
    inf.main()

    candidates = seen['candidates']
    assert len(candidates) <= inf.MAX_CANDIDATES
    authors = {c['author'] for c in candidates}
    assert authors == {'Trump', 'Cathie Wood', '段永平', '洪灏', 'Burry', 'Pelosi'}
    trump_cap = next(s['cap'] for s in inf._sources() if s['key'] == 'trump')
    assert sum(1 for c in candidates if c['author'] == 'Trump') == trump_cap

    payload = json.loads((tmp_path / 'influencer.json').read_text(encoding='utf-8'))
    # Every source reports a status, and the two maps share one key set: the
    # frontend/validator read them positionally, so a source added to one and
    # not the other is a silent lie about coverage.
    assert set(payload['sources']) == set(payload['source_status'])
    assert set(payload['source_status']) == {s['key'] for s in inf._sources()}


def test_ark_origin_gets_its_own_non_primary_source_tier():
    """ARK daily trades are a genuine primary record, but promoting them into
    the evidence graph's PRIMARY_SOURCE_TYPES would let them satisfy the
    primary gate for entries/early-trend decisions — a trading-behaviour change
    this source addition is not asking for. Lock the conservative choice in."""
    from clawock.evidence.news_evidence_graph import (
        PRIMARY_SOURCE_TYPES, source_type)

    assert source_type('ark-funds') == 'ark_daily_trade'
    assert 'ark_daily_trade' not in PRIMARY_SOURCE_TYPES
