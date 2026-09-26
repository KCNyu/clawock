"""The harness-neutral live sources module (docs/architecture/harness.md
§ Live information sources): plan, adapters through one `http` seam,
normalisation, budgets, cache. No network: every answer is a stub.
"""
import json
import threading
from datetime import datetime

from clawock.evidence import live_sources as live
from clawock.market_data import filings
from clawock.sessions import HKT

NOW = datetime(2026, 9, 28, 11, 33, tzinfo=HKT)  # HK session opened 09:30

HKEX = {'maxNumOfFile': 1, 'newsInfoLst': [
    {'relTime': '28/09/2026 11:02', 'title': '內幕消息', 'lTxt': '公告及通告 - [內幕消息]',
     'webPath': '/a.pdf', 'stock': [{'sc': '02208'}]},
    {'relTime': '28/09/2026 10:15', 'title': '翌日披露報表', 'lTxt': '翌日披露報表 - [股份購回]',
     'webPath': '/b.pdf', 'stock': [{'sc': '02208'}]}]}
GOOGLE = """<rss><channel>
<item><title>金风科技中标海上风电 - 新浪财经</title><link>u1</link>
<pubDate>Mon, 28 Sep 2026 02:40:00 GMT</pubDate><source>新浪财经</source></item>
<item><title>金风科技昨夜公告 - 证券时报</title><link>u2</link>
<pubDate>Sun, 27 Sep 2026 22:10:00 GMT</pubDate><source>证券时报</source></item>
</channel></rss>"""


def _targets(ticker):
    if ticker in ('03032', '07226'):
        return {'kind': 'index_fund', 'issuer': None, 'theme_terms': ['恒生科技', '恒科']}
    if ticker == 'RKLX':
        return {'kind': 'look_through', 'issuer': 'RKLB'}
    return {'kind': 'issuer', 'issuer': ticker}


def _http(asked):
    def http(url, *, headers=None, timeout):
        asked.append(url)
        if 'hkexnews' in url:
            return json.dumps(HKEX)
        if 'news.google.com' in url:
            return GOOGLE
        raise AssertionError(url)
    return http


def test_one_http_seam_serves_every_adapter_and_items_come_out_normalised():
    asked = []
    out = live.collect('hk', ['02208', '03032', '07226'], targets=_targets,
                       names={'02208': '金风科技'}, now=NOW, http=_http(asked),
                       sources=('hkexnews', 'google_news'))
    # One filing request for the book, one Google query per issuer and one per
    # index theme — three HSTECH funds do not ask three times.
    assert len(asked) == 3 and sum('hkexnews' in u for u in asked) == 1
    rows = out['tickers']['02208']
    # Daily returns are routine noise (triage rules are simplified; HKEX is not).
    assert [r['title'] for r in rows] == [
        '內幕消息（公告及通告 - [內幕消息]）', '金风科技中标海上风电', '金风科技昨夜公告']
    assert rows[0] == {
        'source': 'hkexnews', 'grade': 'primary', 'title': '內幕消息（公告及通告 - [內幕消息]）',
        'published_at': '2026-09-28T11:02:00+08:00', 'url': 'https://www1.hkexnews.hk/a.pdf',
        'signal': 'interrupt', 'stale': False,
        'cite': '《內幕消息（公告及通告 - [內幕消息]）》（HKEXnews披露易，09-28 11:02 HKT 发布，盘中实时）'}
    assert rows[2]['stale'] is True and rows[2]['cite'].endswith(
        '（Google新闻·证券时报，09-28 06:10 HKT 发布，开盘前旧闻）')
    assert out['tickers']['03032'] == out['tickers']['07226']
    assert out['sources']['hkexnews'] == {'status': 'ok', 'as_of': '09-28 11:33 HKT',
                                          'stale': False, 'requests': 1, 'cached': 0,
                                          'items': 1}
    assert [r['suppressed_noise'] for r in out['requests'] if r['source'] == 'hkexnews'] == [1]
    assert out['degraded'] == []
    assert live.summarize(out['tickers'], per_ticker=1)['02208'][0]['grade'] == 'primary'


def test_the_caller_chooses_what_fresh_means():
    """The brief measures against the last close, not a session that has not
    opened yet: a 06:10 headline is news since the close, not pre-open news."""
    out = live.collect('hk', ['02208'], targets=_targets, names={'02208': '金风科技'},
                       now=datetime(2026, 9, 28, 8, 5, tzinfo=HKT), http=_http([]),
                       sources=('google_news',), labels=live.BRIEF_LABELS,
                       fresh_since=datetime(2026, 9, 25, 16, 0, tzinfo=HKT))
    [row] = out['tickers']['02208']
    assert row['stale'] is False
    assert row['cite'].endswith('（Google新闻·证券时报，09-28 06:10 HKT 发布，上次收盘后）')


def test_an_edgar_filing_with_no_minute_is_neither_fresh_nor_old(monkeypatch):
    monkeypatch.setattr(filings, 'lookup_cik', lambda t: {'RKLB': 'CIK0001819994'}.get(t))
    now = datetime(2026, 9, 28, 23, 10, tzinfo=HKT)

    def http(url, *, headers=None, timeout):
        return json.dumps({'hits': {'hits': [{'_id': 'x:rklb.htm', '_source': {
            'ciks': ['0001819994'], 'file_date': '2026-09-28', 'form': '8-K',
            'file_description': '8-K', 'items': ['7.01'], 'adsh': '0001819994-26-000001'}}]}})
    out = live.collect('us', ['RKLX'], targets=_targets, names={}, now=now, http=http,
                       sources=('sec_fulltext',))
    row = out['tickers']['RKLX'][0]
    assert row['stale'] is None and row['signal'] == 'interrupt'
    assert row['cite'] == '《8-K（items 7.01）》（SEC全文检索，2026-09-28 提交，今日提交、时刻未知）'
    assert out['tickers']['RKLB'] == out['tickers']['RKLX']


def test_a_source_that_did_not_answer_is_named_and_the_rest_still_land():
    def http(url, *, headers=None, timeout):
        if 'hkexnews' in url:
            raise TimeoutError('read timed out')
        return GOOGLE
    out = live.collect('hk', ['02208', '00100'], targets=_targets,
                       names={'02208': '金风科技', '00100': 'MINIMAX-W'}, now=NOW, http=http,
                       sources=('hkexnews', 'google_news'),
                       limits=live.Limits(request_budget={'hkexnews': 1, 'google_news': 1}))
    assert out['degraded'] == ['HKEXnews披露易（TimeoutError）', 'Google新闻（1/2 超出请求预算）']
    assert out['sources']['hkexnews']['status'] == 'failed'
    assert out['sources']['google_news']['status'] == 'partial'
    assert out['tickers']['02208']


def test_nothing_waits_past_the_budget():
    release = threading.Event()

    def http(url, *, headers=None, timeout):
        if 'hkexnews' in url:
            release.wait(5)
        return GOOGLE
    try:
        out = live.collect('hk', ['02208'], targets=_targets, names={'02208': '金风科技'},
                           now=NOW, http=http, sources=('hkexnews', 'google_news'),
                           limits=live.Limits(budget_s=0.3))
    finally:
        release.set()
    assert out['elapsed_s'] < 2
    assert out['degraded'] == ['HKEXnews披露易（超时）']
    assert out['tickers']['02208'][0]['source'] == 'google_news'


def test_a_rerun_inside_the_ttl_reuses_and_keeps_what_the_session_saw(tmp_path):
    cache, asked = tmp_path / 'live.json', []
    kwargs = dict(targets=_targets, names={'02208': '金风科技'}, cache_path=cache,
                  session='2026-09-28', sources=('hkexnews', 'google_news'))
    live.collect('hk', ['02208'], now=NOW, http=_http(asked), **kwargs)
    live.collect('hk', ['02208'], now=NOW.replace(minute=45), http=_http(asked), **kwargs)
    assert len(asked) == 2  # the second call was served from the cache

    def quiet(url, *, headers=None, timeout):
        asked.append(url)
        return json.dumps({'maxNumOfFile': 1, 'newsInfoLst': [
            {'relTime': '28/09/2026 12:00', 'title': 'x', 'lTxt': 'x', 'stock': [{'sc': '00001'}]}]}) \
            if 'hkexnews' in url else '<rss><channel></channel></rss>'
    later = live.collect('hk', ['02208'], now=NOW.replace(hour=12, minute=3), http=quiet,
                         **kwargs)
    assert len(asked) == 4  # the next slot asks again
    # The feeds no longer list them; the session's earlier items remain.
    assert [r['source'] for r in later['tickers']['02208']] == [
        'hkexnews', 'google_news', 'google_news']
    assert later['sources']['google_news']['items'] == 0


def test_intraday_brief_and_report_all_go_through_the_one_collect(monkeypatch, capsys):
    """kcn 2026-09-26: the live sources serve every entry and live in one
    place. Each entry picks sources, limits and labels; none fetches itself."""
    from clawock.evidence import intraday_information
    from clawock.harness import brief_preflight, report_preflight

    calls = []

    def fake(market, tickers, **kwargs):
        calls.append((market, tuple(tickers), kwargs.get('sources'), kwargs.get('labels'),
                      kwargs.get('fresh_since') is not None))
        return {'as_of': 'x', 'elapsed_s': 0.0, 'sources': {}, 'tickers': {}, 'flashes': [],
                'requests': [], 'raw': {}, 'degraded': []}
    monkeypatch.setattr(live, 'collect', fake)
    monkeypatch.setattr(live, 'book_tickers', lambda _ws, market: ['T-' + market])
    monkeypatch.setattr(live, 'last_close', lambda market, now: NOW)

    intraday_information.collect_live('ws', 'hk', now=NOW)
    report_preflight.live_information('us', now=NOW)
    # The brief's node runs this command (`clawock live-sources`) as its subprocess.
    assert live.main(['--market', 'both', '--sources',
                      ','.join(brief_preflight.BRIEF_LIVE_SOURCES),
                      '--fresh-since', 'last_close']) == 0
    assert set(json.loads(capsys.readouterr().out)) == {'hk', 'us'}

    assert calls[0] == ('hk', ('T-hk',), None, live.INTRADAY_LABELS, False)
    assert calls[1] == ('us', ('T-us',), report_preflight.REPORT_LIVE_SOURCES, None, False)
    assert sorted(calls[2:]) == [
        ('hk', ('T-hk',), brief_preflight.BRIEF_LIVE_SOURCES, live.BRIEF_LABELS, True),
        ('us', ('T-us',), brief_preflight.BRIEF_LIVE_SOURCES, live.BRIEF_LABELS, True)]
