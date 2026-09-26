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


# ── Tier 2: live sources folded into the lane (contract §6) ─────────────────

HK_NOW = datetime(2026, 9, 28, 11, 33, tzinfo=HKT)  # HK session opened 09:30


def _hk_targets(ticker):
    if ticker in ('03032', '07226'):
        return {'kind': 'index_fund', 'issuer': None, 'theme_terms': ['恒生科技', '恒科']}
    return {'kind': 'issuer', 'issuer': ticker}


HK_FETCHERS = {
    'hkexnews': lambda codes: [
        {'issuer': '02208', 'title': '內幕消息（公告及通告 - [內幕消息]）',
         'published_at': '2026-09-28T11:02:00+08:00'}],
    'google_news': lambda query, language: [
        {'title': f'{query} live', 'published_at': '2026-09-28T10:40:00+08:00',
         'publisher': 'Reuters'},
        {'title': f'{query} overnight', 'published_at': '2026-09-28T06:10:00+08:00'}],
    'ths_724': lambda: [{'title': '恒指午间收跌', 'published_at': '2026-09-28T11:30:00+08:00'}],
    'em_724': lambda: [{'title': '恒生科技指数跌2%', 'date': '2026-09-28 11:20'}],
}


def test_live_items_reach_the_lane_apart_from_the_morning_rows_with_their_own_time(tmp_path):
    live = info.collect_live(tmp_path, 'hk', now=HK_NOW, session='2026-09-28',
                             tickers=['00100', '02208', '03032', '07226'],
                             targets=_hk_targets,
                             names={'00100': 'MINIMAX-W', '02208': '金风科技'},
                             fetchers=HK_FETCHERS)
    out = info.collect(_workspace(tmp_path), 'hk', ['00100', '02208', '03032', '07226'],
                       now=HK_NOW, live=live)
    summary = out['summary']
    rows = summary['live']['02208']
    assert rows[0]['cite'] == ('《內幕消息（公告及通告 - [內幕消息]）》'
                               '（HKEXnews披露易，09-28 11:02 HKT 发布，盘中实时）')
    assert [r['stale'] for r in rows] == [False, False, True]
    assert summary['live']['07226'] == summary['live']['03032']
    # Morning rows stay where they were, with their morning labels.
    assert summary['tickers']['00100'][0]['cite'].endswith('开盘前旧闻）')
    # A pre-open live headline is held to the same quoting rule as the morning files.
    assert '金风科技 when:1d overnight' in info.stale_titles(summary)
    assert '金风科技 when:1d live' not in info.stale_titles(summary)
    # 同花顺 adds what 东财 did not say; 东财 7×24 came from the same lane.
    assert [f['title'] for f in summary['market_flashes']] == ['恒指午间收跌', '恒生科技指数跌2%']
    assert summary['sources']['em_724_live'] == {'status': 'ok', 'requests': 1}
    assert summary['sources']['hkexnews']['status'] == 'ok'
    assert summary['sources']['hkexnews']['tier'] == 2
    assert out['full']['live']['tickers']['02208'][0]['source'] == 'hkexnews'
    assert out['degraded'] == []


def test_a_live_source_that_did_not_answer_is_on_the_lanes_degraded_list(tmp_path):
    def down(query, language):
        raise TimeoutError('read timed out')
    live = info.collect_live(tmp_path, 'hk', now=HK_NOW, session='2026-09-28',
                             tickers=['02208'], targets=_hk_targets, names={'02208': '金风科技'},
                             fetchers={**HK_FETCHERS, 'google_news': down})
    out = info.collect(_workspace(tmp_path), 'hk', ['02208'], now=HK_NOW, live=live)
    assert out['degraded'] == ['Google新闻（TimeoutError）']
    assert out['summary']['sources']['google_news']['status'] == 'failed'
