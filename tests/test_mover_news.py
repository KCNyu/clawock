"""The intraday catalyst probe: bounded, mover-scoped, and honest about silence.

Every test runs offline through the module's single HTTP seam. A test that needed
the network would be untrustworthy exactly when the endpoints misbehave, which is
the case this code exists to survive.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.data import mover_news as mn


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 24, 6, 0, tzinfo=timezone.utc)          # 14:00 HKT


def tencent_payload(rows):
    return {"code": 0, "data": {"data": rows}}


def row(title, when, url=None):
    return {"title": title, "time": when, "url": url}


def fake_http(mapping, calls=None):
    """Route by URL fragment; anything unmapped raises, like a dead endpoint."""
    def _http(url, headers=None, timeout=None):
        if calls is not None:
            calls.append(url)
        for fragment, payload in mapping.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise OSError(f"unmapped url {url}")
    return _http


@pytest.fixture(autouse=True)
def no_flashes(monkeypatch):
    # The market-flash leg reaches Eastmoney through its own fetcher; silence it
    # unless a test opts in.
    monkeypatch.setattr(mn, "_market_flashes", lambda names, now, window: ([], None))
    monkeypatch.setattr(mn, "holding_names", lambda tickers: {})


# --- scope and budget --------------------------------------------------------

def test_nothing_moved_means_no_requests():
    calls = []
    assert mn.probe([], market="hk", now=NOW, http=fake_http({}, calls)) == {}
    assert mn.probe(None, market="us", now=NOW, http=fake_http({}, calls)) == {}
    assert calls == []


def test_only_the_first_few_movers_are_chased():
    payload = tencent_payload([row("公告 A", "2026-07-24 13:50:00")])
    result = mn.probe(
        ["00100", "02208", "03032", "03033", "07226"], market="hk", now=NOW,
        http=fake_http({"appstock/news": payload}),
    )
    assert len(result["tickers"]) == mn.MAX_MOVERS
    assert result["not_chased"] == ["07226"]


def test_items_are_capped_and_titles_truncated():
    long_title = "港交所公告：" + "细节" * 200
    rows = [row(f"{long_title} {i}", f"2026-07-24 13:5{i}:00") for i in range(6)]
    result = mn.probe(["00100"], market="hk", now=NOW,
                      http=fake_http({"appstock/news": tencent_payload(rows)}))
    items = result["tickers"]["00100"]["items"]
    assert len(items) == mn.MAX_ITEMS_PER_TICKER
    assert all(len(item["title"]) <= mn.TITLE_CHARS for item in items)


def test_the_time_budget_stops_further_calls():
    ticks = iter([0, 0, 999, 999, 999, 999, 999, 999])
    result = mn.probe(["00100", "02208"], market="hk", now=NOW,
                      http=fake_http({"appstock/news": tencent_payload([])}),
                      clock=lambda: next(ticks))
    statuses = {t: e["status"] for t, e in result["tickers"].items()}
    assert "degraded" in statuses.values()
    assert any("time budget" in note
               for entry in result["tickers"].values() for note in entry["notes"])


# --- freshness and tiering ---------------------------------------------------

def test_only_items_inside_the_window_survive():
    rows = [
        row("窗口内公告", "2026-07-24 13:30:00"),     # 30 min old
        row("昨天的公告", "2026-07-23 09:00:00"),     # ~29h old
        row("未来时间戳", "2026-07-24 23:00:00"),     # negative age
    ]
    def http(url, headers=None, timeout=None):
        # only the filing feed answers, so each item appears once
        return tencent_payload(rows if "type=0" in url else [])

    items = mn.probe(["00100"], market="hk", now=NOW, http=http)["tickers"]["00100"]["items"]
    assert [item["title"] for item in items] == ["窗口内公告"]
    assert items[0]["age_minutes"] == 30


def test_exchange_filings_outrank_broker_notes():
    def http(url, headers=None, timeout=None):
        if "type=0" in url:
            return tencent_payload([row("翌日披露报表", "2026-07-24 13:00:00")])
        return tencent_payload([row("券商研报：维持买入", "2026-07-24 13:55:00")])

    items = mn.probe(["00100"], market="hk", now=NOW, http=http)["tickers"]["00100"]["items"]
    assert [item["tier"] for item in items] == [mn.PRIMARY, mn.SUPPORTING]
    # the primary item is older yet still first: tier beats recency
    assert items[0]["age_minutes"] > items[1]["age_minutes"]
    assert items[0]["source_class"] == "exchange_filing"
    assert items[1]["source_class"] == "broker_or_media"


def test_us_leg_prefers_sec_and_does_not_repeat_the_same_filing(monkeypatch):
    sec = {
        "filings": {"recent": {
            "form": ["8-K", "4"],
            "acceptanceDateTime": ["2026-07-24T05:30:00.000Z", "2026-07-20T12:00:00.000Z"],
            "primaryDocDescription": ["Results of Operations", "FORM 4"],
        }}
    }
    monkeypatch.setattr(mn, "_sec_items",
                        lambda ticker, now, window, http: (
                            mn._sec_items.__wrapped__(ticker, now=now, window=window, http=http)
                            if hasattr(mn._sec_items, "__wrapped__") else
                            ([{
                                "published_at": "2026-07-24T05:30:00+00:00",
                                "age_minutes": 30,
                                "title": "8-K Results of Operations",
                                "tier": mn.PRIMARY,
                                "source_class": "sec_filing",
                                "url": None,
                            }], None)))
    calls = []
    result = mn.probe(["NVDA"], market="us", now=NOW,
                      http=fake_http({"appstock/news": tencent_payload(
                          [row("Form 8-K - Results", "2026-07-24 13:30:00")])}, calls))
    items = result["tickers"]["NVDA"]["items"]
    # the SEC filing is kept; Tencent's copy of the same filing is never fetched
    assert items[0]["source_class"] == "sec_filing"
    assert "exchange_filing" not in [item["source_class"] for item in items]
    assert all("type=0" not in url for url in calls)
    assert json.dumps(sec)  # fixture kept readable


def test_sec_cik_is_not_double_prefixed(monkeypatch):
    """`lookup_cik` already returns `CIK##########`; prefixing again 404s."""
    seen = {}

    class FakeFilings:
        @staticmethod
        def lookup_cik(ticker):
            return "CIK0001045810"

        @staticmethod
        def _load_user_agent():
            return "clawock test agent"

    monkeypatch.setitem(__import__("sys").modules, "fetch_us_filings", FakeFilings)

    def http(url, headers=None, timeout=None):
        seen["url"] = url
        return {"filings": {"recent": {"form": [], "acceptanceDateTime": [],
                                       "primaryDocDescription": []}}}

    mn._sec_items("NVDA", now=NOW, window=240, http=http)
    assert seen["url"] == "https://data.sec.gov/submissions/CIK0001045810.json"
    assert "CIKCIK" not in seen["url"]


# --- silence and failure are stated ------------------------------------------

def test_no_items_reads_no_recent_filing_rather_than_an_empty_block():
    result = mn.probe(["00100"], market="hk", now=NOW,
                      http=fake_http({"appstock/news": tencent_payload([])}))
    entry = result["tickers"]["00100"]
    assert entry["status"] == "no_recent_filing"
    assert entry["items"] == []


def test_a_dead_endpoint_degrades_with_a_reason_and_never_raises():
    result = mn.probe(["00100"], market="hk", now=NOW,
                      http=fake_http({"appstock/news": OSError("connection reset")}))
    entry = result["tickers"]["00100"]
    assert entry["status"] == "degraded"
    assert any("OSError" in note for note in entry["notes"])


def test_a_garbage_payload_is_survived():
    for payload in ({}, {"data": None}, {"data": {"data": "nope"}}, []):
        result = mn.probe(["00100"], market="hk", now=NOW,
                          http=fake_http({"appstock/news": payload}))
        assert result["tickers"]["00100"]["status"] in {"no_recent_filing", "degraded"}


def test_market_flashes_only_survive_when_they_name_a_holding(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(mn, "holding_names", lambda tickers: {"00100": "MINIMAX-W"})
    fake_rows = [
        {"title": "MINIMAX-W 港股异动拉升", "date": "2026-07-24 13:40:00"},
        {"title": "某地暴雨预警升级", "date": "2026-07-24 13:41:00"},
    ]
    monkeypatch.setitem(
        __import__("sys").modules, "fetch_em_news",
        type("M", (), {"em_fast_news": staticmethod(lambda limit=20: fake_rows)}),
    )
    result = mn.probe(["00100"], market="hk", now=NOW,
                      http=fake_http({"appstock/news": tencent_payload([])}))
    flashes = result["market_flashes"]
    assert [f["title"] for f in flashes] == ["MINIMAX-W 港股异动拉升"]
    assert flashes[0]["tier"] == mn.SUPPORTING
    assert flashes[0]["matched"] == ["MINIMAX-W"]


def test_symbol_mapping_covers_both_markets():
    assert mn.tencent_symbol("00100", "hk") == "hk00100"
    assert mn.tencent_symbol("2208", "hk") == "hk02208"
    assert mn.tencent_symbol("nvda", "us") == "usNVDA"
    assert mn.tencent_symbol("", "hk") is None


# --- the consumers -----------------------------------------------------------

def test_both_preflights_probe_only_the_flagged_names():
    for name in ("intraday_preflight.py", "report_preflight.py"):
        source = (ROOT / "scripts" / "harness" / name).read_text()
        assert "import mover_news" in source, name
        assert "mover_news.probe(" in source, name
        assert "[a['ticker'] for a in anomalies]" in source, name
        assert "'mover_news'" in source, name


def test_both_skills_bound_how_the_block_may_be_used():
    for name in ("us-stock-analysis", "hk-stock-analysis"):
        skill = (ROOT / "skills" / name / "SKILL.md").read_text()
        assert "mover_news" in skill, name
        assert "no_recent_filing" in skill, name
        assert "primary" in skill and "supporting" in skill, name
        # Tavily must stay out of the intraday catalyst path
        assert "禁止 Tavily" in skill or "禁止Tavily" in skill, name


def test_tavily_is_never_called_from_this_module():
    source = (ROOT / "scripts" / "data" / "mover_news.py").read_text().lower()
    assert "tavily" not in source.replace("禁止 tavily", "")
