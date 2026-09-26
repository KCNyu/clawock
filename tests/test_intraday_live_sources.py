"""Tier 2 source parsers (docs/architecture/intraday-agent.md §6), network stubbed.

Shapes are the ones the live endpoints returned on 2026-09-26: HKEXnews'
all-issuer JSON (traditional characters, `relTime` in HKT), EDGAR full-text
search hits (date only), Yahoo's per-symbol RSS and 同花顺's 7x24 JSON.
"""
from datetime import datetime

import pytest

from clawock.evidence import intraday_information as info
from clawock.market_data import filings, live_news, primary_disclosures as pd
from clawock.sessions import HKT

NOW = datetime(2026, 9, 28, 11, 33, tzinfo=HKT)


def _hkex(rows, pages=1):
    return {'genDate': '1790352000481', 'maxNumOfFile': pages, 'newsInfoLst': rows}


def _row(code, when, title, category, path='/listedco/x.pdf'):
    return {'relTime': when, 'title': title, 'lTxt': category, 'webPath': path,
            'stock': [{'sc': code, 'sn': 'x'}]}


def test_one_hkexnews_request_serves_the_whole_book_and_triage_reads_its_characters(
    monkeypatch
):
    feed = _hkex([
        _row('02208', '28/09/2026 11:02', '內幕消息', '公告及通告 - [內幕消息]'),
        _row('02208', '28/09/2026 10:15', '翌日披露報表', '翌日披露報表 - [股份購回]'),
        _row('00700', '28/09/2026 10:00', '內幕消息', '公告及通告 - [內幕消息]'),
        _row('00100', '26/09/2026 22:55', '展示文件', '展示文件'),  # outside 24 h
    ])
    asked = []

    def http(url, **_k):
        asked.append(url)
        return feed
    items, note, requests = pd.fetch_hkexnews_latest(
        ['02208', '100'], now=NOW, window_minutes=24 * 60, http=http)
    assert note is None and requests == 1 and len(asked) == 1
    assert [(i['issuer'], i['title']) for i in items] == [
        ('02208', '內幕消息（公告及通告 - [內幕消息]）'), ('02208', '翌日披露報表 - [股份購回]')]
    assert items[0]['published_at'] == '2026-09-28T11:02:00+08:00'
    assert items[0]['source_url'] == 'https://www1.hkexnews.hk/listedco/x.pdf'

    # Through the lane's own fetcher: the daily return is triaged as noise
    # (its rule is written in simplified characters), the inside information kept.
    monkeypatch.setattr(pd, '_http_json', http)
    suppressed = []
    kept = info._default_fetchers(1)['hkexnews'](['02208'], NOW, suppressed)
    assert [(k['title'], k['signal']) for k in kept] == [
        ('內幕消息（公告及通告 - [內幕消息]）', 'interrupt')]
    assert suppressed == ['翌日披露報表 - [股份購回]']


def test_hkexnews_reads_a_second_page_only_when_the_first_ends_inside_the_window():
    pages = {1: _hkex([_row('02208', '28/09/2026 11:00', 'a', 'a')], pages=3),
             2: _hkex([_row('02208', '27/09/2026 09:00', 'b', 'b')], pages=3)}
    asked = []

    def http(url, **_k):
        page = int(url.rsplit('_', 1)[1].split('.')[0])
        asked.append(page)
        return pages[page]
    items, note, requests = pd.fetch_hkexnews_latest(
        ['02208'], now=NOW, window_minutes=24 * 60, http=http)
    assert asked == [1, 2] and requests == 2 and [i['title'] for i in items] == ['a']
    _items, note, _n = pd.fetch_hkexnews_latest(
        ['02208'], now=NOW, window_minutes=24 * 60, http=lambda *_a, **_k: _hkex([]))
    assert note == 'empty feed'  # HKEX never publishes an empty list


def test_edgar_full_text_search_asks_once_for_every_issuer_and_keeps_the_date_only(
    monkeypatch
):
    monkeypatch.setattr(filings, 'lookup_cik', lambda t: {
        'CRCL': 'CIK0001876042', 'RKLB': 'CIK0001819994'}.get(t))
    asked = []

    def http(url, **kwargs):
        asked.append((url, kwargs.get('headers', {}).get('User-Agent')))
        return {'hits': {'hits': [
            {'_id': '0001876042-26-000279:crcl-20260925.htm', '_source': {
                'ciks': ['0001876042'], 'file_date': '2026-09-25', 'form': '8-K',
                'file_description': '8-K', 'items': ['5.02', '7.01'],
                'adsh': '0001876042-26-000279'}},
            {'_id': '0002060511-26-000002:wk-form4_1790367093.xml', '_source': {
                'ciks': ['0002060511', '0001876042'], 'file_date': '2026-09-25',
                'form': '4', 'file_description': 'FORM 4', 'items': [],
                'adsh': '0002060511-26-000002'}}]}}
    items, note = pd.fetch_sec_fulltext(['CRCL', 'RKLB'], now=NOW, http=http)
    assert note is None and len(asked) == 1
    assert 'ciks=0001819994%2C0001876042' in asked[0][0] and asked[0][1]
    assert items[0] == {
        'issuer': 'CRCL', 'published_at': None, 'filed_date': '2026-09-25',
        'time_precision': 'date', 'title': '8-K（items 5.02, 7.01）',
        'source_class': 'sec_fulltext', 'evidence_tier': 'primary',
        'source_url': 'https://www.sec.gov/Archives/edgar/data/1876042/'
                      '000187604226000279/crcl-20260925.htm',
        'accession': '0001876042-26-000279', 'form': '8-K', 'filing_items': '5.02,7.01'}
    assert items[1]['title'] == '4 FORM 4'
    assert pd.fetch_sec_fulltext(['NOPE'], now=NOW, http=http) == ([], 'no CIK for NOPE')


YAHOO = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>MISSION SUCCESS: Rocket Lab Launches 97th Electron Mission</title>
<link>https://finance.yahoo.com/x</link><pubDate>Sat, 26 Sep 2026 01:43:00 +0000</pubDate></item>
</channel></rss>"""


def test_feed_parsers_keep_the_publishers_time_and_refuse_a_throttle_page():
    rows = live_news.yahoo_headlines('RKLB', http_text=lambda *_a, **_k: YAHOO)
    assert rows == [{'title': 'MISSION SUCCESS: Rocket Lab Launches 97th Electron Mission',
                     'published_at': '2026-09-26T01:43:00+00:00',
                     'url': 'https://finance.yahoo.com/x', 'publisher': None}]
    with pytest.raises(live_news.SourceError):
        live_news.yahoo_headlines('RKLB', http_text=lambda *_a, **_k: 'Edge: Too Many Requests')

    ths = ('{"code":"200","data":{"list":[{"title":"滴滴与杭州余杭达成战略合作",'
           '"ctime":"1790400263","url":"https://news.10jqka.com.cn/x","source":"人民财讯"}]}}')
    assert live_news.ths_flashes(http_text=lambda *_a, **_k: ths) == [
        {'title': '滴滴与杭州余杭达成战略合作', 'published_at': '2026-09-26T13:24:23+08:00',
         'url': 'https://news.10jqka.com.cn/x', 'publisher': '人民财讯'}]
    with pytest.raises(live_news.SourceError):
        live_news.ths_flashes(http_text=lambda *_a, **_k: '{"code":"-1"}')

    def google(query, **kwargs):
        assert kwargs['ceid'] == 'CN:zh-Hans' and kwargs['timeout'] == 3
        return [{'title': '金风科技中标', 'published': 'Fri, 25 Sep 2026 09:24:21 GMT',
                 'source': '中金在线', 'url': 'u'}], 'ok'
    assert live_news.google_news('金风科技 when:1d', language='zh', timeout=3, fetch=google) == [
        {'title': '金风科技中标', 'published_at': '2026-09-25T09:24:21+00:00',
         'url': 'u', 'publisher': '中金在线'}]
    with pytest.raises(live_news.SourceError):
        live_news.google_news('x', language='en', fetch=lambda *_a, **_k: ([], 'failed'))
