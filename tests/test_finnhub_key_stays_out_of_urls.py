"""A Finnhub key must never be part of a request URL.

`fetch_earnings_for_ticker` reports failures as `f'{type(e).__name__}: {e}'`, and
that string is published in `assets/data/catalysts.json`. A `requests`
connection error's message is the full request URL — so with the key in a
`token=` query parameter, one network blip would have committed it to a public
repository and site. The key goes in the `X-Finnhub-Token` header instead.
"""
import requests

from clawock.market_data import calendar

KEY = 'finnhub-secret-key-123'


def test_a_failed_earnings_call_does_not_publish_the_key(monkeypatch):
    seen = {}

    def fail_like_requests(url, params=None, headers=None, timeout=None):
        prepared = requests.Request('GET', url, params=params).prepare()
        seen['url'] = prepared.url
        seen['headers'] = headers or {}
        raise requests.ConnectionError(
            f"HTTPSConnectionPool(host='finnhub.io', port=443): Max retries "
            f"exceeded with url: {prepared.path_url}")

    monkeypatch.setattr(calendar.requests, 'get', fail_like_requests)
    rows, err = calendar.fetch_earnings_for_ticker('NVDA', '2026-01-01', '2026-01-31', KEY)

    assert rows is None and err.startswith('ConnectionError')
    assert KEY not in err
    assert KEY not in seen['url']
    assert seen['headers'].get('X-Finnhub-Token') == KEY
