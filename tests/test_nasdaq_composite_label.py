"""`macro.nasdaq` is the Nasdaq Composite (^IXIC) on every source, and says so (#1548).

The Signals card labelled it `NDX` while Tencent/Yahoo served the Composite
(~11% below the Nasdaq-100 the Market Snapshot card shows as NDX), and the
Stooq source mapped ^IXIC to Stooq's `^ndx` — so the same field could carry
either index depending on which provider answered.
"""
from pathlib import Path

from clawock.market_data import macro
from test_dashboard_security import _function_body

ROOT = Path(__file__).resolve().parents[1]


class _Resp:
    status_code = 200
    encoding = None
    text = 'Symbol,Date,Time,Open,High,Low,Close,Volume\n^X,2026-09-17,16:00,100,101,99,100.5,0'

    def json(self):
        return {}


def test_ixic_is_never_fetched_as_the_nasdaq_100(monkeypatch):
    urls = []

    def fake_get(url, **_kwargs):
        urls.append(url)
        return _Resp()

    monkeypatch.setattr(macro.requests, 'get', fake_get)
    macro.yahoo_quote('^IXIC')
    assert urls, 'yahoo_quote made no request'
    assert not any('^ndx' in url.lower() for url in urls), urls


def test_signals_card_does_not_label_the_composite_ndx():
    body = _function_body('renderMacro')
    cell = next(line for line in body.splitlines() if 'm.nasdaq.price' in line)
    assert "lbl: 'NDX'" not in cell
    assert "lbl: 'IXIC'" in cell
