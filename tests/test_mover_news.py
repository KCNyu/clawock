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
INSTANCE_HARNESS = ROOT / "instances" / "kcnyu" / "src" / "clawock_kcnyu" / "harness"
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


def test_context_items_keep_one_narrow_slot():
    long_title = "港交所公告：" + "细节" * 200            # unmatched -> context
    rows = [row(f"{long_title} {i}", f"2026-07-24 13:5{i}:00") for i in range(6)]
    result = mn.probe(["00100"], market="hk", now=NOW,
                      http=fake_http({"appstock/news": tencent_payload(rows)}))
    items = result["tickers"]["00100"]["items"]
    assert len(items) == mn.MAX_CONTEXT_ITEMS
    assert all(len(item["title"]) <= mn.TITLE_CHARS for item in items)


def test_interrupts_get_the_slots_and_the_characters():
    long_notice = ("(1) 根据一般授权完成配售35,600,000股新A类股份；"
                   "(2) 根据一般授权完成发行6,500百万港元于2027年到期的可转换债券，"
                   "所得款项净额约为62亿港元，将用于模型训练算力采购与一般营运资金")
    rows = [row(f"{long_notice}{i}", f"2026-07-24 13:5{i}:00") for i in range(5)]
    rows.append(row("董事会会议召开日期", "2026-07-24 13:59:00"))
    def http(url, headers=None, timeout=None):
        return tencent_payload(rows if "type=0" in url else [])

    entry = mn.probe(["00100"], market="hk", now=NOW, http=http)["tickers"]["00100"]
    signals = [item["signal"] for item in entry["items"]]
    assert signals == [mn.INTERRUPT] * mn.MAX_INTERRUPT_ITEMS + [mn.CONTEXT]
    assert entry["more_interrupts"] == 2
    # the placement number survives, which is the whole point of the wider limit
    kept = entry["items"][0]["title"]
    assert "35,600,000" in kept and "6,500百万" in kept
    assert mn.TITLE_CHARS < len(kept) <= mn.INTERRUPT_TITLE_CHARS


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
            return tencent_payload([row("二零二六年中期业绩公告", "2026-07-24 13:00:00")])
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

    from clawock import fetch_us_filings

    monkeypatch.setattr(
        fetch_us_filings, "lookup_cik", lambda ticker: "CIK0001045810"
    )
    monkeypatch.setattr(
        fetch_us_filings, "_load_user_agent", lambda: "clawock test agent"
    )

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
        source = (INSTANCE_HARNESS / name).read_text()
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


# --- filing triage, calibrated on this book's real filings --------------------

@pytest.mark.parametrize("title,market,expected", [
    ("翌日披露报表", "hk", mn.NOISE),
    ("股份发行人的证券变动月报表", "hk", mn.NOISE),
    ("北京市竞天公诚律师事务所关于金风科技的法律意见书", "hk", mn.NOISE),
    ("Form 4 - Statement of Changes in Beneficial Ownership", "us", mn.NOISE),
    ("Form 3 - Initial Statement of Beneficial Ownership", "us", mn.NOISE),
    ("SCHEDULE 13G", "us", mn.NOISE),
    ("144", "us", mn.NOISE),
    ("8-K Results of Operations", "us", mn.INTERRUPT),
    ("10-K/A 10-K/A", "us", mn.INTERRUPT),
    ("424B5 Prospectus Supplement", "us", mn.INTERRUPT),
    ("SC 13D", "us", mn.INTERRUPT),
    ("NT 10-Q Notification of Late Filing", "us", mn.INTERRUPT),
    ("盈利警告", "hk", mn.INTERRUPT),
    ("内幕消息 — 收到监管问询", "hk", mn.INTERRUPT),
    ("(1) 根据一般授权完成配售35,600,000股新A类股份", "hk", mn.INTERRUPT),
    ("短暂停止买卖", "hk", mn.INTERRUPT),
    ("二零二六年中期业绩公告", "hk", mn.INTERRUPT),
    ("董事会会议召开日期", "hk", mn.CONTEXT),
    ("DEF 14A", "us", mn.CONTEXT),
    ("某个从未见过的新公告类型", "hk", mn.CONTEXT),
])
def test_triage_matches_the_filings_this_book_actually_sees(title, market, expected):
    signal, rule = mn.classify(title, market)
    assert signal == expected, (title, rule)


def test_an_unknown_title_is_context_never_dropped():
    assert mn.classify("完全没见过的东西", "hk") == (mn.CONTEXT, None)


def test_noise_is_suppressed_but_counted():
    rows = [
        row("翌日披露报表", "2026-07-24 13:50:00"),
        row("盈利警告", "2026-07-24 13:40:00"),
        row("月报表", "2026-07-24 13:30:00"),
    ]
    def http(url, headers=None, timeout=None):
        return tencent_payload(rows if "type=0" in url else [])

    entry = mn.probe(["00100"], market="hk", now=NOW, http=http)["tickers"]["00100"]
    assert [item["title"] for item in entry["items"]] == ["盈利警告"]
    assert entry["suppressed_noise"] == 2
    assert entry["items"][0]["signal"] == mn.INTERRUPT


def test_an_interrupt_outranks_a_fresher_context_item():
    def http(url, headers=None, timeout=None):
        if "type=0" in url:
            return tencent_payload([row("盈利警告", "2026-07-24 13:00:00")])
        return tencent_payload([row("董事会会议召开日期", "2026-07-24 13:58:00")])

    items = mn.probe(["00100"], market="hk", now=NOW, http=http)["tickers"]["00100"]["items"]
    assert [item["signal"] for item in items] == [mn.INTERRUPT, mn.CONTEXT]


def test_every_triage_rule_is_valid_and_scoped():
    triage = mn.load_triage()
    assert triage["default_class"] == mn.CONTEXT
    seen = set()
    for rule in triage["rules"]:
        assert rule["id"] not in seen
        seen.add(rule["id"])
        assert rule["class"] in {mn.INTERRUPT, mn.CONTEXT, mn.NOISE}
        assert rule["market"] in {"us", "hk"}
        assert rule["why"]


# --- fund look-through: eight of twelve positions are funds -------------------

@pytest.mark.parametrize("ticker,market,kind,issuer", [
    ("PLTU", "us", "look_through", "PLTR"),
    ("MSFU", "us", "look_through", "MSFT"),
    ("RKLX", "us", "look_through", "RKLB"),
    ("SPCH", "us", "look_through", "SPCX"),
    ("CRCL", "us", "issuer", "CRCL"),
    ("00100", "hk", "issuer", "00100"),
    ("SOXL", "us", "index_fund", None),
    ("TQQQ", "us", "index_fund", None),
    ("07226", "hk", "index_fund", None),
    ("03032", "hk", "index_fund", None),
])
def test_probe_target_matches_the_actual_book(ticker, market, kind, issuer):
    target = mn.probe_targets(ticker, market)
    assert target["kind"] == kind
    assert target["issuer"] == issuer


def test_an_index_fund_is_not_probed_for_issuer_filings():
    calls = []
    result = mn.probe(["07226"], market="hk", now=NOW,
                      http=fake_http({"appstock/news": tencent_payload([])}, calls))
    entry = result["tickers"]["07226"]
    assert entry["status"] == "index_fund_no_issuer"
    assert calls == []
    assert "HSTECH" in entry["notes"][0]


def test_a_leveraged_etf_probes_the_company_it_tracks():
    calls = []
    mn.probe(["MSFU"], market="us", now=NOW,
             http=fake_http({"appstock/news": tencent_payload([])}, calls))
    assert any("usMSFT" in url for url in calls)
    assert not any("usMSFU" in url for url in calls)


# --- halts -------------------------------------------------------------------

HALT_FEED = """<rss><channel>
<item><title>PLTU</title>
<ndaq:HaltDate>07/24/2026</ndaq:HaltDate><ndaq:HaltTime>01:45:00.000</ndaq:HaltTime>
<ndaq:IssueSymbol>PLTU</ndaq:IssueSymbol><ndaq:ReasonCode>LUDP</ndaq:ReasonCode>
<ndaq:ResumptionDate>07/24/2026</ndaq:ResumptionDate><ndaq:ResumptionTradeTime>01:50:00</ndaq:ResumptionTradeTime>
</item>
<item><title>OTHER</title>
<ndaq:HaltDate>07/24/2026</ndaq:HaltDate><ndaq:HaltTime>13:45:00.000</ndaq:HaltTime>
<ndaq:IssueSymbol>OTHER</ndaq:IssueSymbol><ndaq:ReasonCode>T1</ndaq:ReasonCode>
</item>
</channel></rss>"""


def test_halts_are_only_asked_for_when_a_leveraged_fund_moved():
    """A large-cap halt is too rare to spend a request on every slot."""
    calls = []
    def text(url, timeout=None):
        calls.append(url)
        return HALT_FEED

    mn.probe(["CRCL"], market="us", now=NOW,
             http=fake_http({"appstock/news": tencent_payload([])}), http_text=text)
    assert calls == []                       # issuer-only mover: no halt request

    mn.probe(["PLTU"], market="us", now=NOW,
             http=fake_http({"appstock/news": tencent_payload([])}), http_text=text)
    assert len(calls) == 1                   # 2x single-stock ETF: worth asking


def test_a_halt_on_a_held_leveraged_etf_surfaces_with_its_reason_code():
    result = mn.halts(["PLTU", "CRCL"], now=NOW, window=240,
                      http_text=lambda url, timeout=None: HALT_FEED)
    assert result["status"] == "checked"
    assert len(result["halted"]) == 1
    halt = result["halted"][0]
    assert halt["ticker"] == "PLTU"
    assert halt["reason_code"] == "LUDP"          # the LULD pause that bites a 2x ETF
    assert halt["age_minutes"] == 15
    assert halt["resumption_trade_time"] == "01:50:00"


def test_halts_ignore_names_we_do_not_hold():
    result = mn.halts(["CRCL"], now=NOW, window=240,
                      http_text=lambda url, timeout=None: HALT_FEED)
    assert result["halted"] == []


def test_no_symbols_means_no_halt_request():
    calls = []
    def text(url, timeout=None):
        calls.append(url)
        return HALT_FEED

    assert mn.halts([], now=NOW, window=240, http_text=text)["status"] == "not_checked"
    assert calls == []


def test_a_dead_halt_feed_degrades_quietly():
    def text(url, timeout=None):
        raise OSError("connection reset")

    result = mn.halts(["PLTU"], now=NOW, window=240, http_text=text)
    assert result["status"] == "degraded"
    assert result["halted"] == []


def test_hk_slots_do_not_call_the_us_halt_feed():
    calls = []
    mn.probe(["00100"], market="hk", now=NOW,
             http=fake_http({"appstock/news": tencent_payload([])}),
             http_text=lambda url, timeout=None: calls.append(url) or HALT_FEED)
    assert calls == []


# --- the report actually consumes it -----------------------------------------

def test_mode_7_requires_attribution_in_the_view_section():
    for name in ("us-stock-analysis", "hk-stock-analysis"):
        skill = (ROOT / "skills" / name / "SKILL.md").read_text()
        view = skill.split("▎我的看法", 1)[1].split("#### Step 2.5", 1)[0]
        assert "异动归因" in view, name
        assert "signal=interrupt" in view, name
        # every honest-failure state has a prescribed sentence
        for state in ("no_recent_filing", "index_fund_no_issuer", "degraded"):
            assert state in view, (name, state)
        # counters stay out of the report
        assert "suppressed_noise" in view and "不要写进报告" in view, name


def test_the_movers_sidecar_quotes_the_same_evidence():
    spec = (ROOT / "skills" / "_shared" / "intraday-status-sidecar.md").read_text()
    assert "mover_news" in spec
    assert "signal=interrupt" in spec
    assert "no_recent_filing" in spec


# --- Mode 6 (open / mid / pm / close, both markets) consumes it too ----------

def _mode_6_prose_section(skill_name):
    skill = (ROOT / "skills" / skill_name / "SKILL.md").read_text()
    return skill.split("#### Step 2: 只写分析散文", 1)[1].split("#### Step 3", 1)[0]


@pytest.mark.parametrize("skill_name", ["us-stock-analysis", "hk-stock-analysis"])
def test_mode_6_reports_must_attribute_their_anomalies(skill_name):
    """Six reports a day (HK open/mid/pm/close, US open/close) had the catalyst
    context and no instruction to use it — dead context in the reports that
    matter most."""
    prose = _mode_6_prose_section(skill_name)
    assert "mover_news" in prose
    assert "异动归因" in prose
    assert "signal=interrupt" in prose
    for state in ("no_recent_filing", "index_fund_no_issuer", "degraded"):
        assert state in prose, state
    # a red line is context for the move, never permission to act
    assert "mover_thesis" in prose and "catalyst-gate" in prose
    # and when space runs out, the attribution is not what gets cut
    assert "先砍板块全景" in prose


def test_mover_attribution_has_room_under_the_ceiling():
    """Attribution is ~1 line per mover; the measured worst case was a US close
    body at 2,898 chars. That used to sit just under a 3,000 soft warn, which is
    why this test existed. #334 lifted the ceiling to 5,000/6,000 and removed the
    pre-write target, so the worst case now clears it with room to spare — the
    remaining risk is the opposite one, a ceiling quietly lowered back onto it."""
    from clawock_kcnyu.harness import report_postflight

    worst_case_measured = 2_898
    assert report_postflight.CHAR_LIMITS["soft"] > worst_case_measured
    assert [i for i in report_postflight.validate("填" * worst_case_measured,
                                                  {"market": "us"})
            if "报告长度" in i] == []
