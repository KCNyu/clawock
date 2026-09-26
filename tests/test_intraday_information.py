"""Intraday information lane (docs/architecture/intraday-agent.md §6).

The morning files are read, never refetched; each item is labelled with the
time its file was written and `stale` when that was before the session opened;
a source that cannot be read is named, never shown as "no news".
"""
import json
from datetime import datetime

from clawock.evidence import intraday_information as info
from clawock.harness import intraday_postflight as post
from clawock.sessions import HKT


def _workspace(tmp_path, *, drop=()):
    data = tmp_path / 'assets' / 'data'
    data.mkdir(parents=True)
    files = {
        'em_news.json': {'generated_at': '2026-09-25T08:03:45+08:00',
                         'holdings_news': {'00100': {'items': [
                             {'title': '智谱跌超10% MINIMAX-W跌超5%', 'date': '2026-09-23'}]}},
                         'market_724': [{'title': '日经225指数开盘上涨0.19%'}]},
        'us_news_digest.json': {'generated_at': '2026-09-25T17:35:11',
                                'held_via': {'RKLB': ['RKLX']},
                                'raw_news_evidence': {'RKLB': [
                                    {'headline': 'Rocket Lab wins launch contract',
                                     'datetime': 1790330000}]}},
        'sentiment.json': {'generated_at': '2026-09-25T00:05:43+00:00',
                           'tickers': [{'ticker': 'RKLB', 'reddit_mentions_7d': 4,
                                        'google_news_en': [{}, {}]}]},
        'macro.json': {'generated_at': '2026-09-25T00:05:20+00:00',
                       'spx': {'price': 7704.13, 'change_pct': -0.02},
                       'fear_greed': {'score': 36.1, 'rating': 'fear'}},
        'news_evidence_graph.json': {'generated_at': '2026-09-25T00:04:28+00:00', 'events': [
            {'ticker': 'RKLB', 'title': '8-K current report', 'source_type': 'sec_filing',
             'actionable_blockers': []},
            {'ticker': 'RKLB', 'title': 'Rocket Lab stock rallies on backlog', 'source_type':
             'google_news_rss', 'actionable_blockers': ['reliable_primary_or_wire'],
             'impact_direction': 'positive'}]},
    }
    for name, doc in files.items():
        if name not in drop:
            (data / name).write_text(json.dumps(doc, ensure_ascii=False))
    return tmp_path


NOW = datetime(2026, 9, 25, 23, 10, tzinfo=HKT)  # US session opened 21:30 HKT


def test_morning_files_are_read_labelled_and_never_shown_as_live(tmp_path):
    flashes = [{'title': '美股三大指数高开', 'date': '2026-09-25 23:02'},
               {'title': '旧快讯', 'date': '2026-09-25 08:00'}]
    out = info.collect(_workspace(tmp_path), 'us', ['RKLX', 'RKLB'], now=NOW,
                       fast_news=lambda limit: flashes)
    summary = out['summary']
    assert out['degraded'] == []
    graph = summary['sources']['news_evidence_graph']
    assert graph['stale'] is True and graph['as_of'] == '09-25 08:04 HKT'
    # The US digest was written 17:35 HKT, still before this session opened.
    assert summary['sources']['us_news_digest']['stale'] is True
    rows = summary['tickers']['RKLB']
    assert [row['grade'] for row in rows] == ['primary', 'soft', 'soft']
    assert all('截至' in row['cite'] and '开盘前旧闻' in row['cite'] for row in rows)
    # A fund reads its issuer's digest (held_via), labelled the same way.
    assert summary['tickers']['RKLX'][0]['title'] == 'Rocket Lab wins launch contract'
    assert summary['attention']['RKLB'] == {'reddit_mentions_7d': 4, 'reddit_status': None,
                                            'google_news_en': 2, 'google_news_zh': 0}
    # 7x24 is market-level (no mover filter), window-bounded, one request.
    assert [f['title'] for f in summary['market_flashes']] == ['美股三大指数高开']
    assert summary['sources']['em_724_live'] == {'status': 'ok', 'requests': 1}
    assert 'information' not in out['full'] and out['full']['tickers']['RKLB']


def test_an_unreadable_source_is_named_not_silent(tmp_path):
    out = info.collect(_workspace(tmp_path, drop=('news_evidence_graph.json',)), 'us',
                       ['RKLB'], now=NOW, fast_news=lambda limit: [])
    assert out['degraded'] == ['news_evidence_graph（missing）', '东财7×24（empty_or_failed）']




def test_quoting_a_stale_headline_without_its_time_is_flagged():
    ctx = {'market': 'us', 'should_alert': False, 'raw_wechat_block': '🇺🇸 美股盯盘',
           'information': {'sources': {}, 'tickers': {'RKLB': [
               {'title': 'Rocket Lab wins launch contract',
                'cite': '《Rocket Lab wins launch contract》（us_news_digest，截至 09-25 17:35 HKT，开盘前旧闻）'}]}}}
    base = '▎我的看法\nRKLX 跟随 RKLB 上行，' + '板块情绪偏暖。' * 6
    bare = base + 'Rocket Lab wins launch contract 是今天的催化。\n下一触发：RKLX 站上 1'
    flagged = [i for i in post.validate(bare, ctx, bare) if '旧闻' in i]
    assert flagged and not flagged[0].endswith('(advisory)')
    labelled = base + 'Rocket Lab wins launch contract（截至 09-25 17:35 HKT）仍是背景。\n'
    assert not [i for i in post.validate(labelled, ctx, labelled) if '旧闻' in i]


# ── Tier 2: live free feeds (contract §6) ────────────────────────────────────

HK_NOW = datetime(2026, 9, 28, 11, 33, tzinfo=HKT)  # HK session opened 09:30


def _hk_targets(ticker):
    if ticker in ('03032', '07226'):
        return {'kind': 'index_fund', 'issuer': None, 'theme_terms': ['恒生科技', '恒科']}
    return {'kind': 'issuer', 'issuer': ticker}


def _us_targets(ticker):
    return {'kind': 'look_through', 'issuer': 'RKLB'} if ticker == 'RKLX' else \
        {'kind': 'issuer', 'issuer': ticker}


def _stub_fetchers(calls, **override):
    def record(name, answer):
        def fn(*args):
            calls.append((name, args[0] if args and name != 'hkexnews' else name))
            return answer(*args) if callable(answer) else answer
        return fn
    base = {
        'hkexnews': record('hkexnews', lambda codes, now, suppressed: [
            {'issuer': '02208', 'title': '內幕消息（公告及通告 - [內幕消息]）',
             'published_at': '2026-09-28T11:02:00+08:00', 'signal': 'interrupt'}]),
        'sec_fulltext': record('sec_fulltext', lambda issuers, now, suppressed: [
            {'issuer': 'RKLB', 'title': '8-K（items 7.01）', 'published_at': None,
             'filed_date': '2026-09-28', 'signal': 'interrupt'}]),
        'google_news': record('google_news', lambda query, language: [
            {'title': f'{query} live', 'published_at': '2026-09-28T10:40:00+08:00',
             'publisher': 'Reuters'},
            {'title': f'{query} overnight', 'published_at': '2026-09-28T06:10:00+08:00'},
            {'title': f'{query} last week', 'published_at': '2026-09-20T06:10:00+08:00'}]),
        'yahoo_rss': record('yahoo_rss', []),
        'ths_724': record('ths_724', [{'title': '恒指午间收跌', 'publisher': None,
                                      'published_at': '2026-09-28T11:30:00+08:00'}]),
        'em_724': record('em_724', [{'title': '恒生科技指数跌2%', 'date': '2026-09-28 11:20'}]),
    }
    base.update(override)
    return base


def test_live_feeds_are_asked_per_issuer_and_theme_and_carry_their_own_time(tmp_path):
    calls = []
    live = info.collect_live(
        tmp_path, 'hk', now=HK_NOW, session='2026-09-28',
        tickers=['00100', '02208', '03032', '07226'], targets=_hk_targets,
        names={'00100': 'MINIMAX-W', '02208': '金风科技'},
        fetchers=_stub_fetchers(calls))
    # One HKEXnews request for the book; three HSTECH funds are one theme query;
    # an index fund gets no filing lookup of its own.
    assert sorted(c[1] for c in calls if c[0] == 'google_news') == [
        'MINIMAX when:1d', '恒生科技 when:1d', '金风科技 when:1d']
    assert [c for c in calls if c[0] == 'hkexnews'] == [('hkexnews', 'hkexnews')]
    assert live['degraded'] == []

    out = info.collect(_workspace(tmp_path), 'hk', ['00100', '02208', '03032', '07226'],
                       now=HK_NOW, live=live)
    rows = out['summary']['live']['02208']
    # Live first, primary before soft; the filing is this session's.
    assert rows[0]['grade'] == 'primary' and rows[0]['stale'] is False
    assert rows[0]['cite'] == '《內幕消息（公告及通告 - [內幕消息]）》（HKEXnews披露易，09-28 11:02 HKT 发布，盘中实时）'
    assert [r['stale'] for r in rows] == [False, False, True]
    assert rows[2]['cite'].endswith('（Google新闻，09-28 06:10 HKT 发布，开盘前旧闻）')
    assert all('last week' not in r['title'] for r in out['full']['live']['tickers']['02208'])
    assert out['summary']['live']['07226'] == out['summary']['live']['03032']
    # Morning rows stay where they were and keep their morning labels.
    assert out['summary']['tickers']['00100'][0]['cite'].endswith('开盘前旧闻）')
    # A pre-open live headline is held to the same quoting rule as the morning files.
    assert '金风科技 when:1d overnight' in info.stale_titles(out['summary'])
    assert '金风科技 when:1d live' not in info.stale_titles(out['summary'])
    # The second 7x24 feed adds what the first did not say; 7x24 came from the lane.
    assert [f['title'] for f in out['summary']['market_flashes']] == ['恒指午间收跌', '恒生科技指数跌2%']
    assert out['summary']['sources']['em_724_live'] == {'status': 'ok', 'requests': 1}
    assert out['summary']['sources']['hkexnews']['status'] == 'ok'


def test_an_edgar_filing_with_no_minute_is_neither_live_nor_old(tmp_path):
    now = datetime(2026, 9, 28, 23, 10, tzinfo=HKT)
    live = info.collect_live(tmp_path, 'us', now=now, session='2026-09-28',
                             tickers=['RKLX'], targets=_us_targets, names={},
                             fetchers=_stub_fetchers([]))
    out = info.collect(_workspace(tmp_path), 'us', ['RKLX', 'RKLB'], now=now, live=live)
    filing = [r for r in out['summary']['live']['RKLX'] if r['source'] == 'sec_fulltext'][0]
    assert filing['stale'] is None
    assert filing['cite'] == '《8-K（items 7.01）》（SEC全文检索，2026-09-28 提交，今日提交、时刻未知）'
    assert out['summary']['live']['RKLB'] == out['summary']['live']['RKLX']


def test_a_live_source_that_did_not_answer_is_named_not_silent(tmp_path):
    def down(query, language):
        if query.startswith('MINIMAX'):
            raise TimeoutError('read timed out')
        return []
    live = info.collect_live(
        tmp_path, 'hk', now=HK_NOW, session='2026-09-28', tickers=['00100', '02208'],
        targets=_hk_targets, names={'00100': 'MINIMAX-W', '02208': '金风科技'},
        fetchers=_stub_fetchers([], google_news=down,
                                hkexnews=lambda *_a: (_ for _ in ()).throw(ValueError('empty feed'))))
    assert live['degraded'] == ['HKEXnews披露易（ValueError）', 'Google新闻（1/2 TimeoutError）']
    out = info.collect(_workspace(tmp_path), 'hk', ['00100', '02208'], now=HK_NOW, live=live)
    assert out['summary']['sources']['google_news']['status'] == 'partial'
    assert out['summary']['sources']['hkexnews']['status'] == 'failed'
    assert 'Google新闻（1/2 TimeoutError）' in out['degraded']


def test_the_lane_never_waits_past_its_budget(tmp_path):
    import threading
    release = threading.Event()

    def hang(*_a):
        release.wait(5)
        return []
    try:
        live = info.collect_live(
            tmp_path, 'hk', now=HK_NOW, session='2026-09-28', tickers=['02208'],
            targets=_hk_targets, names={'02208': '金风科技'}, budget_s=0.3,
            fetchers=_stub_fetchers([], ths_724=hang))
    finally:
        release.set()
    assert live['elapsed_s'] < 2
    assert live['degraded'] == ['同花顺7×24（超时）']
    assert [r['status'] for r in live['requests'] if r['source'] == 'hkexnews'] == ['ok']


def test_a_rerun_of_the_slot_reuses_its_answers_and_the_next_slot_asks_again(tmp_path):
    cache = tmp_path / 'live.json'
    calls = []
    kwargs = dict(session='2026-09-28', tickers=['02208'], targets=_hk_targets,
                  names={'02208': '金风科技'}, cache_path=cache)
    info.collect_live(tmp_path, 'hk', now=HK_NOW, fetchers=_stub_fetchers(calls), **kwargs)
    first = len(calls)
    info.collect_live(tmp_path, 'hk', now=HK_NOW.replace(minute=40),
                      fetchers=_stub_fetchers(calls), **kwargs)
    # Only the market 7x24 (tier 1, never cached) is asked again inside the TTL.
    assert [c[0] for c in calls[first:]] == ['em_724']
    asked = []
    later = info.collect_live(tmp_path, 'hk', now=HK_NOW.replace(hour=12, minute=3),
                              fetchers=_stub_fetchers(calls, google_news=lambda q, _l: (
                                  asked.append(q), [])[1]), **kwargs)
    assert asked == ['金风科技 when:1d']
    assert {c[0] for c in calls[first + 1:]} == {'hkexnews', 'ths_724', 'em_724'}
    # What the session already saw is kept when a feed stops listing it.
    kept = later['entries']['google_news:金风科技']['items']
    assert [r['title'] for r in kept][:1] == ['金风科技 when:1d live']
