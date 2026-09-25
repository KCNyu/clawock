"""Tier 3 of the information lane: a web search per mover, once per session.

The intraday Tavily bucket is 120 credits a month; one query a slot would be
~400. The harness searches only when something moved, once per ticker per
session, and a search that could not run or found nothing is stated.
"""
from clawock.evidence import anomaly_search as search

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


def test_output_is_parsed_graded_and_unavailable_is_distinct():
    status, reason, items = search.parse_output(SAMPLE)
    assert status == 'ok' and reason is None
    assert [(i['title'][:6], i['grade']) for i in items] == [('恒生科技指数', 'authoritative'),
                                                           ('Why Ho', 'soft')]
    assert items[0]['url'] == 'https://www.cls.cn/detail/123'
    status, reason, items = search.parse_output(
        '## Web search unavailable\n\nTavily budget guardrail: bucket intraday exhausted. Skip…')
    assert status == 'unavailable' and 'exhausted' in reason and items == []
    assert search.parse_output('## Sources\n')[0] == 'empty'


def test_one_query_per_mover_per_session(tmp_path):
    asked = []

    def run(query):
        asked.append(query)
        return search.parse_output(SAMPLE)

    anomalies = [{'ticker': '07226', 'move_pct': -4.7}]
    targets = {'07226': {'kind': 'index_fund', 'via': 'HSTECH', 'theme_terms': ['恒生科技']}}
    cache = tmp_path / 'cache.json'
    first = search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-25', anomalies,
                                    targets=targets, run=run, cache_path=cache)
    again = search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-25', anomalies,
                                     targets=targets, run=run, cache_path=cache)
    assert asked == ['恒生科技指数 今日 走势 原因']
    assert first['07226']['cached'] is False and again['07226']['cached'] is True
    assert again['07226']['items'] == first['07226']['items']
    # A new session asks again; a search that could not run is retried.
    search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-26', anomalies,
                            targets=targets, run=lambda q: ('unavailable', 'no key', []),
                            cache_path=cache)
    search.search_anomalies(tmp_path, 'hk', 'hk:2026-09-26', anomalies,
                            targets=targets, run=run, cache_path=cache)
    assert len(asked) == 2
    # A look-through fund asks about its issuer.
    assert search.query_for('RKLX', 'us', 'Defiance 2X RKLB',
                            {'kind': 'look_through', 'issuer': 'RKLB'}).startswith('RKLB ')
    assert search.monthly_estimate(1) == 44 <= search.MONTHLY_CAP

