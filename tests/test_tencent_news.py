"""One adapter for Tencent's per-symbol news/announcement search.

`primary_disclosures.fetch_exchange` (type 0, primary) and
`mover_evidence._tencent_items` (type 1, supporting) each used to build the
request and apply the window themselves. They share `tencent_news` now; these
pin the request both send and that both keep exactly the same rows.
"""
from datetime import datetime

from clawock.market_data import mover_evidence, primary_disclosures, tencent_news
from clawock.sessions import HKT

NOW = datetime(2026, 9, 26, 11, 0, tzinfo=HKT)
PAYLOAD = {'data': {'data': [
    {'time': '2026-09-26 10:30:00', 'title': 'inside', 'url': 'u1'},
    {'time': '2026-09-26 11:05:00', 'title': 'from the future', 'url': 'u2'},
    {'time': '2026-09-26 06:00:00', 'title': 'older than the window', 'url': 'u3'},
    {'time': None, 'title': 'no time', 'url': 'u4'},
    {'time': '26/09/2026', 'title': 'unreadable time', 'url': 'u5'},
    {'time': '2026-09-26 09:00:00', 'title': 'edge of the window', 'url': 'u6'},
]}}


def _http(seen):
    def http(url):
        seen.append(url)
        return PAYLOAD
    return http


def test_both_feeds_send_the_request_they_always_sent():
    base = 'https://web.ifzq.gtimg.cn/appstock/news/info/search'
    assert tencent_news.url('hk00100', tencent_news.FILINGS) == (
        f'{base}?symbol=hk00100&n=8&page=1&type=0')
    assert tencent_news.url('usRKLB', tencent_news.NEWS) == (
        f'{base}?symbol=usRKLB&n=8&page=1&type=1')


def test_the_window_keeps_only_rows_it_can_date_inside_it():
    rows = tencent_news.recent_rows('hk00100', 0, now=NOW, window_minutes=120,
                                    http=_http([]))
    assert [(row['title'], age) for _, age, row in rows] == [
        ('inside', 30), ('edge of the window', 120)]
    assert rows[0][0] == datetime(2026, 9, 26, 10, 30, tzinfo=HKT)


def test_filings_and_mover_news_keep_the_same_rows_from_the_same_answer():
    filing_urls, news_urls = [], []
    filings, note = primary_disclosures.fetch_exchange(
        'hk00100', now=NOW, window_minutes=120, http=_http(filing_urls))
    news = mover_evidence._tencent_items(
        'hk00100', mover_evidence.TENCENT_NEWS_TYPE, mover_evidence.SUPPORTING,
        'broker_or_media', now=NOW, window=120, http=_http(news_urls))

    assert note is None
    assert [(f['published_at'], f['age_minutes']) for f in filings] == [
        (n['published_at'], n['age_minutes']) for n in news]
    assert [f['evidence_tier'] for f in filings] == ['primary', 'primary']
    assert [n['tier'] for n in news] == ['supporting', 'supporting']
    assert filing_urls[0].endswith('type=0') and news_urls[0].endswith('type=1')
