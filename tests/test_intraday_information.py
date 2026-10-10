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
    if 'sentiment_snapshot' not in drop:
        snapshot = data / 'factor-snapshots' / 'sentiment'
        snapshot.mkdir(parents=True)
        for day in ('2026-09-25', '2026-09-28'):
            (snapshot / f'{day}.json').write_text(json.dumps({
                'generated_at': f'{day}T05:30:00+08:00'}))
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
    assert all('开盘前旧闻' in row['cite'] for row in rows)
    assert '条目时间未知' in rows[0]['cite']  # graph event lacks publication_time
    assert '截至' in rows[1]['cite'] and '17:35' not in rows[1]['cite']
    # A fund reads its issuer's digest (held_via), labelled the same way.
    assert summary['tickers']['RKLX'][0]['title'] == 'Rocket Lab wins launch contract'
    assert summary['attention']['RKLB'] == {'reddit_mentions_7d': 4, 'reddit_status': None,
                                            'google_news_en': 2, 'google_news_zh': 0}
    # 7x24 is market-level (no mover filter), window-bounded, one request.
    assert [f['title'] for f in summary['market_flashes']] == ['美股三大指数高开']
    assert summary['sources']['em_724_live'] == {'status': 'ok', 'requests': 1}
    assert 'information' not in out['full'] and out['full']['tickers']['RKLB']


def test_a_morning_item_uses_its_own_date_not_the_file_write_time(tmp_path):
    out = info.collect(_workspace(tmp_path), 'hk', ['00100'],
                       now=datetime(2026, 9, 28, 11, 33, tzinfo=HKT),
                       fast_news=lambda limit: [])
    cite = out['summary']['tickers']['00100'][0]['cite']
    assert '发布日期 09-23（时刻未知）' in cite
    assert '09-25 08:03' not in cite


def test_graph_date_precision_never_claims_a_publication_minute(tmp_path):
    root = _workspace(tmp_path)
    path = root / 'assets/data/news_evidence_graph.json'
    doc = json.loads(path.read_text())
    doc['events'] = [
        {'ticker': 'RKLB', 'title': 'Dated filing', 'source_type': 'sec_filing',
         'publication_time': {'iso': '2026-09-25T00:00:00+00:00', 'precision': 'date'}},
        {'ticker': 'RKLB', 'title': 'Timed release', 'source_type': 'sec_filing',
         'publication_time': {'iso': '2026-09-25T14:30:00+00:00', 'precision': 'minute'}},
    ]
    path.write_text(json.dumps(doc))
    out = info.collect(root, 'us', ['RKLB'], now=NOW, fast_news=lambda limit: [])
    cites = {row['title']: row['cite'] for row in out['summary']['tickers']['RKLB']}
    assert '发布日期 09-25（时刻未知）' in cites['Dated filing']
    assert '08:00 HKT' not in cites['Dated filing']
    assert '截至 09-25 22:30 HKT' in cites['Timed release']


def test_an_unreadable_source_is_named_not_silent(tmp_path):
    out = info.collect(_workspace(tmp_path, drop=('news_evidence_graph.json',)), 'us',
                       ['RKLB'], now=NOW, fast_news=lambda limit: [])
    assert out['degraded'] == ['news_evidence_graph（missing）', '东财7×24（empty_or_failed）']


def test_missing_archive_is_not_a_source_gap_and_future_source_is_not_fresh(tmp_path):
    missing = info.collect(_workspace(tmp_path, drop=('sentiment_snapshot',)), 'us',
                           [], now=NOW, fast_news=lambda limit: [])
    assert not any('sentiment_snapshot' in label for label in missing['degraded'])
    future = datetime(2026, 9, 26, 7, 57, tzinfo=HKT)
    assert info.freshness(future, 'us', NOW)['stale'] is True




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


def test_a_live_timestamped_title_does_not_collide_with_old_same_ticker_title():
    old = 'MINIMAX-W (00100.HK) Stock Price, Quote & News'
    live = '港股大模型板块走低 MINIMAX-W跌超10%'
    ctx = {'information': {'tickers': {'00100': [
        {'title': old, 'cite': f'《{old}》（旧源，截至 09-11 08:03 HKT，开盘前旧闻）'}]},
        'live': {'00100': [{'title': live, 'stale': False,
                            'cite': f'《{live}》（Google新闻，09-28 10:36 HKT 发布，盘中实时）'}]}}}
    prose = f'《{live}》（Google新闻，09-28 10:36 HKT 发布，盘中实时）'
    assert post.check_stale_citation(prose, ctx) == []
    assert post.check_stale_citation(f'《{old}》是今天催化。', ctx)


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
    # The reference layer carries the same cite, so there is a time to copy (#2217).
    full_rows = [row for rows in out['full']['tickers'].values() for row in rows]
    assert full_rows and all(row['cite'].startswith('《') for row in full_rows)
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


def test_market_level_reference_rows_carry_a_cite_and_reach_the_label_gate(tmp_path):
    # The gate listed the per-ticker families only; the three market-level
    # families of information_full had no cite and were never matched (#2568).
    root = _workspace(tmp_path)
    graph_path = root / 'assets' / 'data' / 'news_evidence_graph.json'
    graph = json.loads(graph_path.read_text())
    graph['events'] += [
        {'ticker': 'MARKET', 'title': '美联储10月维持利率不变的概率升至75.1%',
         'publication_time': {'iso': '2026-09-25T07:57:00+08:00', 'precision': 'minute'}},
        {'ticker': 'MARKET', 'event_type': 'macro_schedule',
         'title': 'Sep jobs report (Non-Farm Payrolls); BLS 8:30 ET',
         'publication_time': {'iso': '2026-09-25T08:03:00+08:00', 'precision': 'minute'}}]
    graph_path.write_text(json.dumps(graph, ensure_ascii=False))
    flashes = [{'title': '美股三大指数集体高开，纳指涨0.5%', 'date': '2026-09-25 23:02'},
               {'title': '日本东京9月份整体消费物价同比增长2.7%', 'date': '2026-09-25 07:30'}]
    out = info.collect(root, 'us', ['RKLB'], now=NOW, fast_news=lambda limit: flashes)
    full = out['full']

    for family in ('graph_market_events', 'market_flashes_raw'):
        assert full[family] and all(row['cite'].startswith('《') for row in full[family]), family
    # em_news is the HK leg's file; its 7×24 rows have no clock in this fixture.
    hk = info.collect(root, 'hk', ['00100'], now=HK_NOW, fast_news=lambda limit: [])
    assert [row['cite'] for row in hk['full']['em_market_724']] == [
        '《日经225指数开盘上涨0.19%》（em_news 7×24，条目时间未知（文件写于 09-25 08:03 HKT），开盘前旧闻）']
    assert '日经225指数开盘上涨0.19%' in info.stale_titles(hk['summary'], hk['full'])
    stale = info.stale_titles(out['summary'], full)
    assert '美联储10月维持利率不变的概率升至75.1%' in stale
    assert '日本东京9月份整体消费物价同比增长2.7%' in stale
    # A headline from after the open is live; a schedule entry is not a headline.
    assert '美股三大指数集体高开，纳指涨0.5%' not in stale
    assert 'Sep jobs report (Non-Farm Payrolls); BLS 8:30 ET' not in stale

    ctx = {'information': out['summary'], 'information_full': full}
    title = '美联储10月维持利率不变的概率升至75.1%'
    assert post.check_stale_citation(f'{title}，风险偏好回升。', ctx)
    assert post.check_stale_citation(f'{title}（截至 09-25 07:57，开盘前旧闻），风险偏好回升。', ctx) == []


def test_a_pre_open_headline_from_the_live_lanes_flash_feed_reaches_the_label_gate():
    # 同花顺 7×24 lands in information_full.live.flashes, the one market-level
    # family the gate still did not list (#2593).
    title = '美国9月CPI同比2.4% 低于预期'
    full = {'live': {'tickers': {}, 'flashes': [
        {'title': title, 'cite': f'《{title}》（同花顺7×24，10-05 08:22 HKT 发布，开盘前旧闻）'},
        {'title': '港股午后拉升，恒指涨超1%', 'cite': '《港股午后拉升，恒指涨超1%》（同花顺7×24，10-05 13:40 HKT 发布，盘中实时）'}]}}
    assert info.stale_titles({}, full) == [title]
    ctx = {'information': {}, 'information_full': full}
    assert post.check_stale_citation(f'{title}，降息预期升温。', ctx)
    assert post.check_stale_citation(f'{title}（10-05 08:22 HKT 发布，开盘前旧闻），降息预期升温。', ctx) == []


def test_the_flash_tiers_keep_their_own_rules_when_called_directly():
    """`collect` was one 210-line body; its two flash tiers are now separate
    functions (#2683), and these are the three rules that lived only inline."""
    from datetime import datetime, timedelta, timezone

    from clawock.evidence import intraday_information as lane

    now = datetime(2026, 10, 6, 6, 0, tzinfo=timezone.utc)
    hkt = lambda minutes: (now + timedelta(minutes=minutes)).astimezone(  # noqa: E731
        lane.HKT).strftime('%Y-%m-%d %H:%M:%S')

    assert lane._market_flashes(now, lambda limit=20: [], None) == ([], [], 'empty_or_failed')
    flashes, rows, status = lane._market_flashes(now, lambda limit=20: [
        {'title': '十分钟后的快讯', 'date': hkt(10)}, {'title': '刚才的快讯', 'date': hkt(-2)}], None)
    assert status == 'ok' and len(rows) == 2
    assert [f['title'] for f in flashes] == ['刚才的快讯'], 'a flash stamped in the future is dropped'

    live = {'flashes': [
        {'title': '刚才的快讯', 'published_at': now.isoformat(), 'source': 'ths_724', 'cite': 'a'},
        {'title': '另一件完全不同的事情发生了', 'published_at': now.isoformat(),
         'source': 'ths_724', 'cite': 'b'}]}
    _, merged, _, _ = lane._apply_live_layer(live, {}, flashes, now)
    assert sorted(f['title'] for f in merged) == ['刚才的快讯', '另一件完全不同的事情发生了'], (
        'a live flash repeating a tier-1 title is not added twice')
    assert lane._apply_live_layer(None, {}, flashes, now) == (None, flashes, {}, [])

