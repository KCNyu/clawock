"""DeepSeek Search/Fetch access (`market_data.deepseek_search`) and its use as a
live source. No network: every answer is a stub, the gate is a temp file."""
import io
import json
import urllib.error
from datetime import datetime

import pytest

from clawock.evidence import live_sources as live
from clawock.evidence import web_search
from clawock.market_data import deepseek_search as ds
from clawock.sessions import HKT

HIT = {'rerank_score': 2.3, 'title': 'Rocket Lab falls on Neutron delay', 'url': 'https://www.reuters.com/x',
       'snippet': 'Rocket Lab shares fell…', 'summary': 'Long summary', 'content': '',
       'site_name': 'Reuters', 'site_icon': None, 'date': '2026-10-16T16:00:00+00:00',
       'authority': 4}


def _http_error(code):
    return urllib.error.HTTPError('u', code, 'x', {}, io.BytesIO(b'{}'))


def test_the_key_comes_from_env_then_the_dsh_seam(tmp_path, monkeypatch):
    creds = tmp_path / 'creds.yaml'
    monkeypatch.setattr(ds, 'DSH_CREDENTIALS', creds)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    assert ds.api_key() is None
    creds.write_text('other:\n  X: 1\nrefs:\n  MINIMAX_API_KEY: m\n  DEEPSEEK_API_KEY: "from-dsh"\n'
                     'next:\n  DEEPSEEK_API_KEY: wrong\n')
    assert ds.api_key() == 'from-dsh'
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'from-env')
    assert ds.api_key() == 'from-env'


def test_only_408_429_and_5xx_are_retried():
    calls = []

    def post(status_sequence):
        def run(endpoint, body, key, timeout):
            calls.append(endpoint)
            status = status_sequence.pop(0)
            if status != 200:
                raise _http_error(status)
            return {'results': [HIT]}
        return run

    rows = ds.search('RKLB', key='k', gate=False, sleep=lambda _s: None,
                     post=post([429, 503, 200]), budget_s=30)
    assert len(calls) == 3 and rows[0]['title'].startswith('Rocket Lab')
    for code, reason in ((402, '余额不足'), (401, 'key无效'), (400, '请求参数无效')):
        calls.clear()
        with pytest.raises(ds.SearchError) as error:
            ds.search('RKLB', key='k', gate=False, sleep=lambda _s: None, post=post([code, 200]))
        assert calls == ['search'] and error.value.status == code and error.value.reason == reason
    with pytest.raises(ds.SearchError, match='缺少DEEPSEEK_API_KEY'):
        ds.call('search', {'query': 'x'}, key='', post=post([200]))


def test_rows_keep_deepseeks_scores_and_a_day_only_date_is_a_day():
    row = ds.normalize(HIT)
    # 16:00Z is 00:00 Beijing: DeepSeek knows the day, not the minute.
    assert row['filed_date'] == '2026-10-17' and 'published_at' not in row
    assert (row['authority'], row['rerank_score'], row['publisher']) == (4, 2.3, 'Reuters')
    assert 'content' not in row
    timed = ds.normalize({**HIT, 'date': '2026-10-17T13:05:00Z', 'authority': -1})
    assert timed['published_at'] == '2026-10-17T13:05:00+00:00' and timed['authority'] == -1
    assert 'filed_date' not in ds.normalize({**HIT, 'date': None})
    assert ds.normalize({**HIT, 'title': ''}) is None
    assert ds.is_quote_page({'title': 'Rocket Lab (RKLB.US) Stock Price, Quote & News | Longbridge'})
    assert ds.is_quote_page({'title': '金风科技(002202)'})
    assert not ds.is_quote_page({'title': HIT['title']})


def test_the_gate_spaces_requests_across_callers(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, 'GATE_DIR', tmp_path)
    clock = {'t': 1000.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock['t'] += seconds

    def gate():  # a new object per call: another process reading the same file
        return ds._Gate('search', qps=2, clock=lambda: clock['t'], sleep=sleep)
    for _ in range(3):
        gate().wait(deadline=ds.time.monotonic() + 10)
    assert slept == [pytest.approx(1.0)]
    gate().wait(deadline=ds.time.monotonic() + 10)
    assert len(slept) == 1
    # A wait that would pass the caller's deadline is refused, not slept.
    with pytest.raises(ds.SearchError):
        gate().wait(deadline=ds.time.monotonic() + 0.1)


def test_deepseek_is_a_live_source_graded_by_host_with_an_honest_date():
    now = datetime(2026, 10, 17, 11, 0, tzinfo=HKT)
    asked = []

    def fake(query, language):
        asked.append((query, language))
        return [ds.normalize(HIT), ds.normalize({**HIT, 'url': 'https://blog.example.com/y',
                                                  'title': 'A blog on RKLB moves today'})]
    out = live.collect('us', ['RKLX'], targets=lambda _t: {'kind': 'look_through', 'issuer': 'RKLB'},
                       names={}, now=now, sources=('deepseek_search',),
                       fetchers={'deepseek_search': fake})
    assert asked == [('RKLB stock news', 'en')]
    rows = out['tickers']['RKLX']
    assert [r['grade'] for r in rows] == ['authoritative', 'soft']
    assert rows[0]['cite'] == ('《Rocket Lab falls on Neutron delay》（DeepSeek搜索·Reuters，'
                               '2026-10-17 发布，开盘前旧闻）')
    assert rows[0]['authority'] == 4 and out['degraded'] == []


def test_a_deepseek_gap_is_named_and_the_other_sources_still_land():
    now = datetime(2026, 10, 17, 11, 0, tzinfo=HKT)

    def down(_query, _language):
        raise RuntimeError('超出QPS')
    out = live.collect('us', ['RKLB'], targets=lambda _t: {'kind': 'issuer', 'issuer': 'RKLB'},
                       names={}, now=now, sources=('deepseek_search', 'yahoo_rss'),
                       fetchers={'deepseek_search': down, 'yahoo_rss': lambda _s: [
                           {'title': 'Rocket Lab news', 'published_at': now.isoformat()}]})
    assert out['degraded'] == ['DeepSeek搜索（RuntimeError）']
    assert [r['source'] for r in out['tickers']['RKLB']] == ['yahoo_rss']


def test_the_adapter_asks_inside_the_window_and_drops_undated_and_quote_pages(monkeypatch):
    seen = {}

    def fake_search(query, **kwargs):
        seen['query'] = query
        return [ds.normalize(HIT), ds.normalize({**HIT, 'date': None, 'url': 'https://a/1'}),
                ds.normalize({**HIT, 'date': '2026-10-10T16:00:00Z', 'url': 'https://a/2'}),
                ds.normalize({**HIT, 'title': 'RKLB Stock Price, Quote & News', 'url': 'https://a/3'})]
    monkeypatch.setattr(ds, 'search', fake_search)
    rows = live._deepseek_search({'args': ('RKLB stock news', 'en')}, timeout=6,
                                 now=datetime(2026, 10, 17, 11, 0, tzinfo=HKT),
                                 window_minutes=24 * 60)
    assert seen['query'] == 'RKLB stock news lang:en after:2026-10-16'
    assert [r['url'] for r in rows] == ['https://www.reuters.com/x']


def test_the_cli_prints_each_provider_under_its_own_heading(monkeypatch, capsys):
    monkeypatch.setattr(web_search, 'RUNNERS', {
        'deepseek': lambda q, **k: ('ok', None, [{'title': 'T', 'url': 'https://reuters.com/t',
                                                  'one_liner': 's', 'grade': 'authoritative'}]),
        'tavily': lambda q, **k: ('unavailable', 'Tavily budget guardrail: bucket research exhausted', [])})
    assert web_search.main(['RKLB news', '--days', '2']) == 0
    text = capsys.readouterr().out
    assert '## DeepSeek — ok' in text and '**T**' in text
    assert '## Tavily — unavailable' in text and 'this is not "no news"' in text
    assert web_search.main(['RKLB', '--providers', 'deepseek', '--json']) == 0
    assert set(json.loads(capsys.readouterr().out)['providers']) == {'deepseek'}
