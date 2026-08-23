"""Contract tests for the previously uncovered market-data leaf modules (#850).

benchmarks / fund_flows / eastmoney_symbols / credentials had zero direct
coverage — their parsing, retry and format contracts were only ever exercised
indirectly through monkeypatched stand-ins. These pin the pure seams.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clawock import credentials  # noqa: E402
from clawock.market_data import benchmarks, eastmoney_symbols, fund_flows  # noqa: E402


# ---------------------------------------------------------------------------
# credentials.parse_api_keys — the one format every .api_keys reader shares.
# ---------------------------------------------------------------------------

def test_parse_api_keys_format_contract():
    text = "\n".join([
        "# comment line",
        "",
        "FINNHUB_API_KEY=abc123",
        "SEC_USER_AGENT=Name email@example.com",
        "KEY_WITH_EQUALS=a=b=c",   # first '=' wins
        "  PADDED  =  value  ",
        "no_equals_line",
    ])
    keys = credentials.parse_api_keys(text)
    assert keys["FINNHUB_API_KEY"] == "abc123"
    assert keys["SEC_USER_AGENT"] == "Name email@example.com"
    assert keys["KEY_WITH_EQUALS"] == "a=b=c"
    assert keys["PADDED"] == "value"
    assert "no_equals_line" not in keys
    assert "# comment line" not in keys


def test_load_api_keys_absent_file_is_empty_not_an_error(tmp_path):
    assert credentials.load_api_keys(tmp_path / ".api_keys") == {}


def test_load_api_keys_round_trips(tmp_path):
    p = tmp_path / ".api_keys"
    p.write_text("A=1\nB=2\n")
    assert credentials.load_api_keys(p) == {"A": "1", "B": "2"}


# ---------------------------------------------------------------------------
# benchmarks — HTTP-seam parsing: mock requests, assert the row contract.
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_polygon_daily_parses_rows_and_skips_bad_close(monkeypatch):
    def fake_get(url, **kwargs):
        from urllib.parse import urlsplit
        assert urlsplit(url).netloc == "api.polygon.io", url
        return _Resp({"results": [
            {"t": 1724112000000, "c": 100.5},
            {"t": 1724198400000, "c": None},   # missing close → skipped
            {"t": 1724284800000, "c": "101.25"},  # string close → parsed
        ]})
    monkeypatch.setattr(benchmarks.requests, "get", fake_get)
    out = benchmarks.fetch_polygon_daily("SPY", 7, "key")
    assert len(out) == 2
    assert out[0] == {"date": "2024-08-20", "close": 100.5}
    assert out[1]["close"] == 101.25


def test_fetch_polygon_daily_without_key_never_calls_the_network(monkeypatch):
    called = []
    monkeypatch.setattr(benchmarks.requests, "get",
                        lambda *a, **k: called.append(1))
    assert benchmarks.fetch_polygon_daily("SPY", 7, "") == []
    assert called == []


def test_fetch_tencent_hk_daily_takes_day_or_qfqday(monkeypatch):
    def fake_get(url, **kwargs):
        return _Resp({"data": {"hkHSI": {
            "qfqday": [["2024-08-19", "100", "101.5", "102", "99", "1000"],
                       ["2024-08-20", "101", "bad", "102", "99", "1000"]],
        }}})
    monkeypatch.setattr(benchmarks.requests, "get", fake_get)
    out = benchmarks.fetch_tencent_hk_daily("hkHSI", 7)
    assert [r["close"] for r in out] == [101.5]
    assert out[0]["date"] == "2024-08-19"


# ---------------------------------------------------------------------------
# fund_flows — em_get seam: parse contract and the never-raise rule.
# ---------------------------------------------------------------------------

class _EM:
    def __init__(self, payload=None, raise_json=False):
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


def test_get_fund_flow_parses_klines_and_skips_short_rows(monkeypatch):
    def fake_em_get(url, **kwargs):
        return _EM({"data": {"klines": [
            "2024-08-19,1,2,3,4,5,6,7",
            "2024-08-20,8,9,10,11,12,13,14",
            "short",                      # < 6 fields → skipped
        ]}})
    monkeypatch.setattr(fund_flows, "em_get", fake_em_get)
    rows = fund_flows.get_fund_flow("116.00700", days=5)
    assert len(rows) == 2
    assert rows[0]["date"] == "2024-08-19"


def test_get_fund_flow_degrades_to_empty_on_none_or_bad_json(monkeypatch):
    monkeypatch.setattr(fund_flows, "em_get", lambda *a, **k: None)
    assert fund_flows.get_fund_flow("116.00700") == []
    monkeypatch.setattr(fund_flows, "em_get",
                        lambda *a, **k: _EM(raise_json=True))
    assert fund_flows.get_fund_flow("116.00700") == []


# ---------------------------------------------------------------------------
# eastmoney_symbols — the pure shape functions search/resolve build on.
# ---------------------------------------------------------------------------

def test_make_derives_market_and_secid():
    row = eastmoney_symbols._make("00700", "116", "Tencent")
    assert row["market"] == "HK"
    assert row["secid"] == "116.00700"
    assert row["secucode"] == "00700.HK"


def test_search_filters_to_known_markets(monkeypatch):
    def fake_em_get(url, **kwargs):
        return _EM({"QuotationCodeTable": {"Data": [
            {"Code": "AAPL", "MktNum": "105", "Name": "Apple"},
            {"Code": "XYZ", "MktNum": "999", "Name": "Unknown"},  # dropped
        ]}})
    monkeypatch.setattr(eastmoney_symbols, "em_get", fake_em_get)
    rows = eastmoney_symbols.search("appl")
    assert [r["code"] for r in rows] == ["AAPL"]


def test_resolve_exact_code_match_wins_over_prefer(monkeypatch):
    """The exact-match pool is authoritative: a query that equals one row's code
    returns that row whatever prefer says (prefer only orders non-exact pools)."""
    def fake_em_get(url, **kwargs):
        return _EM({"QuotationCodeTable": {"Data": [
            {"Code": "00700", "MktNum": "116", "Name": "Tencent"},
            {"Code": "TCEHY", "MktNum": "106", "Name": "Tencent ADR"},
        ]}})
    monkeypatch.setattr(eastmoney_symbols, "em_get", fake_em_get)
    got = eastmoney_symbols.resolve("00700", prefer="us")
    assert got is not None
    assert got["code"] == "00700", "exact match wins even with prefer=us"


def test_resolve_prefer_orders_a_non_exact_pool(monkeypatch):
    """No exact match -> the pool is all candidates, and prefer picks the market."""
    def fake_em_get(url, **kwargs):
        return _EM({"QuotationCodeTable": {"Data": [
            {"Code": "00700", "MktNum": "116", "Name": "Tencent"},
            {"Code": "TCEHY", "MktNum": "106", "Name": "Tencent ADR"},
        ]}})
    monkeypatch.setattr(eastmoney_symbols, "em_get", fake_em_get)
    got = eastmoney_symbols.resolve("TENC", prefer="us")
    assert got is not None
    assert got["code"] == "TCEHY", "prefer=us must pick the NYSE row first"
    got = eastmoney_symbols.resolve("TENC", prefer="hk")
    assert got is not None and got["code"] == "00700"



# ---------------------------------------------------------------------------
# eastmoney_http — the shared throttle/retry/session client every Eastmoney
# caller goes through. #850: its serial-throttle, retry-count and session-reuse
# semantics were never asserted directly.
# ---------------------------------------------------------------------------

class _FakeSession:
    """A requests.Session stand-in that records calls and can fail N times."""

    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers, timeout))
        if len(self.calls) <= self.fail_times:
            import requests
            raise requests.RequestException("transient failure")
        class _R:
            def raise_for_status(self):
                pass
        return _R()


def test_em_get_serial_throttle_spaces_calls(monkeypatch):
    """The client is a process-wide serializer: a caller arriving sooner than
    MIN_INTERVAL after the previous one must sleep the remainder (+ jitter)."""
    import clawock.market_data.eastmoney_http as eh
    slept = []
    monkeypatch.setattr(eh, "MIN_INTERVAL", 0.05)
    monkeypatch.setattr(eh, "JITTER", 0.0)
    monkeypatch.setattr(eh.time, "sleep", slept.append)
    monkeypatch.setattr(eh, "_get_session", lambda: _FakeSession())
    t0 = [100.0]
    eh._last_call = 100.0  # a call just happened
    monkeypatch.setattr(eh.time, "time", lambda: t0[0])
    for _ in range(2):
        eh.em_get("http://example.com/api", label="t")
        t0[0] += 0.02  # next caller arrives 20ms later (< MIN_INTERVAL)
    assert len(slept) == 2, "each early caller must sleep the remainder"
    assert all(0.02 <= s <= 0.05 for s in slept), slept


def test_em_get_retries_transient_failures_then_returns_response(monkeypatch):
    import clawock.market_data.eastmoney_http as eh
    monkeypatch.setattr(eh, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(eh, "JITTER", 0.0)
    monkeypatch.setattr(eh, "_get_session", lambda: _FakeSession(fail_times=2))
    monkeypatch.setattr(eh.time, "sleep", lambda *a: None)
    r = eh.em_get("http://example.com/api", retries=5, label="t")
    assert r is not None, "must survive 2 transient failures within 5 retries"


def test_em_get_returns_none_after_retries_exhausted(monkeypatch):
    """All retries failing returns None (never raises) — the caller-degrades rule."""
    import clawock.market_data.eastmoney_http as eh
    monkeypatch.setattr(eh, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(eh, "JITTER", 0.0)
    sessions = []
    monkeypatch.setattr(
        eh, "_get_session",
        lambda: sessions.append(_FakeSession(fail_times=99)) or sessions[-1])
    monkeypatch.setattr(eh.time, "sleep", lambda *a: None)
    r = eh.em_get("http://example.com/api", retries=3, label="t")
    assert r is None
    # and the retry count must be exactly the configured retries
    assert len(sessions[0].calls) == 3


def test_em_get_reuses_one_session_across_calls(monkeypatch):
    import clawock.market_data.eastmoney_http as eh
    monkeypatch.setattr(eh, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(eh, "JITTER", 0.0)
    monkeypatch.setattr(eh.time, "sleep", lambda *a: None)
    sessions = []
    def factory():
        s = _FakeSession()
        sessions.append(s)
        return s
    # Patch the requests.Session class, not _get_session itself: the module
    # caches the session in its global, and that cache is what must be proven.
    monkeypatch.setattr(eh, "_session", None)
    monkeypatch.setattr(eh.requests, "Session", factory)
    eh.em_get("http://a", label="a")
    eh.em_get("http://b", label="b")
    assert len(sessions) == 1, "session must be created once and reused"
    assert sessions[0].calls[0][0] == "http://a"
    assert sessions[0].calls[1][0] == "http://b"


def test_em_get_sends_ua_header_and_extra_headers(monkeypatch):
    import clawock.market_data.eastmoney_http as eh
    monkeypatch.setattr(eh, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(eh, "JITTER", 0.0)
    monkeypatch.setattr(eh.time, "sleep", lambda *a: None)
    sess = _FakeSession()
    monkeypatch.setattr(eh, "_get_session", lambda: sess)
    eh.em_get("http://a", headers={"X-Extra": "1"}, label="a")
    url, params, headers, timeout = sess.calls[0]
    assert headers["User-Agent"] == eh.UA
    assert headers["X-Extra"] == "1"
