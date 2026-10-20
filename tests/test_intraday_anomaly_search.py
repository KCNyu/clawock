"""Tier 3 of the information lane: web search per mover, two providers.

DeepSeek and Tavily are asked side by side (kcn 2026-10-18: parallel sources,
neither the other's backup). Each keeps its own call policy — DeepSeek every
slot once its answer is old, Tavily once per ticker per session because the
intraday bucket is 120 credits a month — and each provider's gap is stated as
that provider's, never as "no news" and never as the other's.
"""
from datetime import datetime, timedelta, timezone

from clawock.evidence import anomaly_search as search
from clawock.evidence import web_search

SAMPLE = """## Answer

Hang Seng Tech fell as chip names slid.

---

## Sources

- **恒生科技指数午后跌幅扩大，芯片股领跌** (relevance: 81%)
  https://www.cls.cn/detail/123
  恒生科技指数跌2.1%，中芯国际跌超5%……

- **Why Hong Kong tech stocks are falling** (relevance: 70%)
  https://example-blog.com/hk-tech
  Some commentary.
"""
NOW = datetime(2026, 9, 25, 3, 0, tzinfo=timezone.utc)
DS_ROWS = [{'title': '恒生科技指数跌2%，芯片股领跌', 'url': 'https://www.stcn.com/a/1',
            'one_liner': '…', 'grade': 'authoritative', 'filed_date': '2026-09-25'},
           # The same story Tavily found: listed once, under both providers.
           {'title': 'Why Hong Kong tech stocks are falling', 'url': 'https://example-blog.com/hk-tech',
            'one_liner': '…', 'grade': 'soft'}]


def test_tavily_output_is_parsed_graded_and_unavailable_is_distinct():
    status, reason, items = search.parse_output(SAMPLE)
    assert status == 'ok' and reason is None
    assert [(i['title'][:6], i['grade']) for i in items] == [('恒生科技指数', 'authoritative'),
                                                           ('Why Ho', 'soft')]
    assert items[0]['url'] == 'https://www.cls.cn/detail/123'
    status, reason, items = search.parse_output(
        '## Web search unavailable\n\nTavily budget guardrail: bucket intraday exhausted. Skip…')
    assert status == 'unavailable' and 'exhausted' in reason and items == []
    assert search.parse_output('## Sources\n')[0] == 'empty'


def _runners(asked, deepseek=None, tavily=None):
    def ds(query, question=None):
        asked.append(('deepseek', query, question))
        return deepseek or ('ok', None, DS_ROWS)

    def tv(query):
        asked.append(('tavily', query))
        return tavily or search.parse_output(SAMPLE)
    return {'deepseek': ds, 'tavily': tv}


def test_both_providers_are_asked_and_every_row_says_whose_it_is(tmp_path):
    asked = []
    anomalies = [{'ticker': '07226', 'move_pct': -4.7}]
    targets = {'07226': {'kind': 'index_fund', 'via': 'HSTECH', 'theme_terms': ['恒生科技']}}
    out = search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-25', anomalies, targets=targets,
                                  names={'07226': '南方两倍做多恒科'}, runners=_runners(asked),
                                  now=NOW, cache_path=tmp_path / 'c.json')
    assert sorted(a[0] for a in asked) == ['deepseek', 'tavily']
    assert ('deepseek', '恒生科技指数 今日 走势 原因', '为什么南方两倍做多恒科今天跌了4.7%') in asked
    result = out['07226']
    assert result['status'] == 'ok'
    assert {p: s['status'] for p, s in result['providers'].items()} == {
        'deepseek': 'ok', 'tavily': 'ok'}
    assert result['providers']['deepseek']['item_count'] == 2
    by_url = {i['url']: i for i in result['items']}
    assert by_url['https://www.stcn.com/a/1']['provider'] == 'deepseek'
    assert by_url['https://www.cls.cn/detail/123']['provider'] == 'tavily'
    assert by_url['https://example-blog.com/hk-tech']['providers'] == ['deepseek', 'tavily']
    assert len(result['items']) == 3
    assert search.degraded_lines(out) == []


def test_each_provider_keeps_its_own_call_policy(tmp_path):
    asked = []
    anomalies = [{'ticker': '07226', 'move_pct': -4.7}]
    kwargs = dict(cache_path=tmp_path / 'c.json', runners=_runners(asked))
    search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-25', anomalies, now=NOW, **kwargs)
    # The next slot, 30 minutes on: DeepSeek is asked again, Tavily is not
    # (its intraday bucket allows one query per ticker per session).
    later = search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-25', anomalies,
                                    now=NOW + timedelta(minutes=30), **kwargs)
    assert [a[0] for a in asked].count('tavily') == 1
    assert [a[0] for a in asked].count('deepseek') == 2
    assert later['07226']['providers']['tavily']['cached'] is True
    assert later['07226']['providers']['deepseek']['cached'] is False
    # A re-run of the same slot asks nobody.
    search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-25', anomalies,
                            now=NOW + timedelta(minutes=31), **kwargs)
    assert len(asked) == 3
    # A new session asks both again.
    search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-26', anomalies,
                            now=NOW + timedelta(days=1), **kwargs)
    assert len(asked) == 5
    assert search.monthly_estimate(1) == 44 <= search.MONTHLY_CAP


def test_the_session_cache_is_written_whole_and_a_bad_one_is_said(tmp_path, capsys):
    """#3111: a truncated cache silently re-searched every mover (Tavily billed
    again), and a failed write said nothing."""
    asked = []
    anomalies = [{'ticker': '07226', 'move_pct': -4.7}]
    cache = tmp_path / 'c.json'
    kwargs = dict(cache_path=cache, runners=_runners(asked))
    search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-25', anomalies, now=NOW, **kwargs)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['c.json']  # no temp file left
    assert capsys.readouterr().err == ''

    cache.write_text(cache.read_text()[:40], encoding='utf-8')  # killed mid-write
    search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-25', anomalies,
                            now=NOW + timedelta(minutes=30), **kwargs)
    assert 'anomaly-search cache unreadable' in capsys.readouterr().err

    blocked = tmp_path / 'not-a-dir'
    blocked.write_text('', encoding='utf-8')
    out = search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-25', anomalies, now=NOW,
                                  cache_path=blocked / 'c.json', runners=_runners([]))
    assert out['07226']['status'] == 'ok'
    assert 'anomaly-search cache not written' in capsys.readouterr().err


def test_one_provider_failing_is_its_own_gap_and_not_the_others(tmp_path):
    asked = []
    anomalies = [{'ticker': 'RKLB', 'move_pct': 6.0}]
    out = search.search_anomalies(
        tmp_path, 'us', 'us:2026-09-25', anomalies, now=NOW, cache_path=tmp_path / 'c.json',
        runners=_runners(asked, deepseek=('unavailable', '超出QPS', [])))
    result = out['RKLB']
    # Tavily's rows still stand, and the card names DeepSeek as the gap.
    assert result['status'] == 'ok'
    assert {i['provider'] for i in result['items']} == {'tavily'}
    assert search.degraded_lines(out) == ['RKLB（DeepSeek未取到（超出QPS））']
    # Tavily out of credits while DeepSeek answers: the reverse.
    out = search.search_anomalies(
        tmp_path, 'us', 'us:2026-09-26', anomalies, now=NOW, cache_path=tmp_path / 'c.json',
        runners=_runners(asked, tavily=search.parse_output(
            '## Web search unavailable\n\nTavily budget guardrail: bucket intraday exhausted.')))
    assert {i['provider'] for i in out['RKLB']['items']} == {'deepseek'}
    assert search.degraded_lines(out) == [
        'RKLB（Tavily未取到（Tavily budget guardrail: bucket intraday exhausted））']
    # A Tavily search that could not run is retried next slot.
    search.search_anomalies(tmp_path, 'us', 'us:2026-09-26', anomalies,
                            now=NOW + timedelta(minutes=1), cache_path=tmp_path / 'c.json',
                            runners=_runners(asked))
    assert [a[0] for a in asked].count('tavily') == 3


def test_a_failed_deepseek_refresh_keeps_the_sessions_rows_and_says_so(tmp_path):
    asked = []
    anomalies = [{'ticker': 'RKLB', 'move_pct': 6.0}]
    cache = tmp_path / 'c.json'
    search.search_anomalies(tmp_path, 'us', 'us:2026-09-25', anomalies, now=NOW,
                            cache_path=cache, runners=_runners(asked))
    out = search.search_anomalies(
        tmp_path, 'us', 'us:2026-09-25', anomalies, now=NOW + timedelta(minutes=30),
        cache_path=cache, runners=_runners(asked, deepseek=('unavailable', '超时', [])))
    deepseek = out['RKLB']['providers']['deepseek']
    assert deepseek['status'] == 'unavailable' and deepseek['item_count'] == 2
    assert search.degraded_lines(out) == ['RKLB（DeepSeek未取到（超时））']


def test_nothing_from_either_is_stated_per_provider(tmp_path):
    out = search.search_anomalies(
        tmp_path, 'hk', 'hk:2026-09-25', [{'ticker': '00100', 'move_pct': -5.0}], now=NOW,
        cache_path=tmp_path / 'c.json',
        runners=_runners([], deepseek=('empty', None, []), tavily=('unavailable', 'no key', [])))
    assert out['00100']['status'] == 'empty'
    assert search.degraded_lines(out) == ['00100（DeepSeek无结果、Tavily未取到（no key））']
    # A lane that crashed before either provider answered keeps the old shape.
    assert search.degraded_lines({'SPCH': {'status': 'unavailable', 'items': []}}) == [
        'SPCH（未取到）']


def test_queries_follow_the_issuer_a_fund_looks_through_to():
    assert search.query_for('RKLX', 'us', 'Defiance 2X RKLB',
                            {'kind': 'look_through', 'issuer': 'RKLB'}).startswith('RKLB ')


def test_a_provider_that_raises_does_not_sink_the_other():
    def boom(_query, **_k):
        raise RuntimeError('x')
    answers = web_search.search_all('q', runners={
        'deepseek': boom, 'tavily': lambda _q, **_k: ('ok', None, [{'title': 't', 'url': 'u'}])})
    assert answers['deepseek']['status'] == 'unavailable'
    assert answers['tavily']['items'] == [{'title': 't', 'url': 'u', 'provider': 'tavily'}]
