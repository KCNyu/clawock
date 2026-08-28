"""Unit tests for fail-safe automatic peer suggestions."""

from __future__ import annotations

from pathlib import Path

import requests


WS = Path(__file__).resolve().parents[1]
from clawock.market_data import peer_discovery as sp


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_us_excludes_self_and_curated_then_caps_six(monkeypatch):
    monkeypatch.setattr(sp, "_api_key", lambda name: "test")
    monkeypatch.setattr(
        sp.requests,
        "get",
        lambda *a, **kw: FakeResponse(
            ["NVDA", "AMD", "CURATED", "AVGO", "QCOM", "INTC", "MU", "MRVL", "ARM", "TSM"]
        ),
    )

    peers = sp.suggest_auto_peers("nvda", "us", ["amd", "CURATED"])

    assert [p["ticker"] for p in peers] == ["AVGO", "QCOM", "INTC", "MU", "MRVL", "ARM"]
    assert len(peers) == 6
    assert all(p["region"] == "us" and p["source"] == "finnhub" for p in peers)
    assert all(p["name"] == p["ticker"] for p in peers)


def test_us_outage_returns_empty_and_diagnoses(monkeypatch, capsys):
    monkeypatch.setattr(sp, "_api_key", lambda name: "test")

    def timeout(*args, **kwargs):
        raise requests.Timeout("offline")

    monkeypatch.setattr(sp.requests, "get", timeout)

    assert sp.suggest_auto_peers("NVDA", "us", []) == []
    assert "auto peer source failed" in capsys.readouterr().err


def test_hk_gated_off_by_default_makes_no_em_calls(monkeypatch, capsys):
    # HK auto-peers ship disabled — no longer because the source is unresolved
    # (it works, see the parser test below) but because turning them on
    # re-registers the peer-residual rules against a different peer universe
    # (#1122). The gate must still short-circuit BEFORE any East Money call so a
    # HK-heavy scan is not slowed by requests whose result is discarded.
    calls = []
    monkeypatch.setattr(sp, "em_get", lambda *a, **kw: calls.append(kw) or None)

    assert sp.suggest_auto_peers("00700", "hk", ["09988"]) == []
    assert calls == []
    assert "re-registration" in capsys.readouterr().err


def test_hk_peers_come_from_one_industry_report_call_ranked_by_market_cap(monkeypatch):
    """Guards `_suggest_hk` directly, bypassing the ship gate.

    The board-code chain this replaced took three calls and died on the last
    one: `clist/get?fs=b:HK28` does not accept the `HK\\d+` family that
    `slist/get` returns, and no spelling of the selector fixes it. The F10
    industry report is keyed by the holding itself, so the whole answer —
    industry name, constituents, market cap to rank them — arrives in one call
    with no board code anywhere in the chain.
    """
    calls = []

    def fake_em_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        return FakeResponse({"result": {"count": 176, "data": [
            {"TYPE_NAME": "互联网服务", "CORRE_SECURITY_CODE": code,
             "CORRE_SECURITY_NAME": name}
            for code, name in [
                ("00700", "腾讯控股"),
                ("80700", "腾讯控股-R"),
                ("09988", "阿里巴巴-W"),
                ("03690", "美团-W"),
                ("01024", "快手-W"),
                ("09626", "哔哩哔哩-W"),
                ("09888", "百度集团-SW"),
                ("09999", "网易-S"),
                ("03888", "金山软件"),
                ("00772", "阅文集团"),
            ]
        ]}})

    monkeypatch.setattr(sp, "em_get", fake_em_get)

    peers = sp._suggest_hk("700", ["09988"])

    assert [p["ticker"] for p in peers] == [
        "03690", "01024", "09626", "09888", "09999", "03888"
    ], "self and curated names are excluded, order is the report's market-cap rank"
    assert len(calls) == 1, "the three-call board chain is gone"
    url, params = calls[0]
    assert url == sp.EM_HK_INDUSTRY_URL
    assert params["filter"] == '(SECUCODE="00700.HK")'
    assert params["sortColumns"] == "HKTOTAL_MARKET_CAP" and params["sortTypes"] == "-1", (
        "the report is paged, so ranking after the fetch would rank page one")
    assert all(p["region"] == "hk" and p["source"] == "eastmoney" for p in peers)
    assert all(p["industry"] == "互联网服务" for p in peers)


def test_the_rmb_dual_counter_is_not_offered_as_its_own_peer(monkeypatch):
    """80700 is 00700 in RMB — the same issuer, and as a residual its own FX basis."""
    monkeypatch.setattr(sp, "em_get", lambda *a, **kw: FakeResponse(
        {"result": {"data": [
            {"TYPE_NAME": "互联网服务", "CORRE_SECURITY_CODE": "80700",
             "CORRE_SECURITY_NAME": "腾讯控股-R"},
            {"TYPE_NAME": "互联网服务", "CORRE_SECURITY_CODE": "08083",
             "CORRE_SECURITY_NAME": "中国先锋医药"},
        ]}}))

    peers = sp._suggest_hk("00700", [])

    assert [p["ticker"] for p in peers] == ["08083"], (
        "a GEM code starting 08 is a real listing; only the 8xxxx counter goes")


def test_the_industry_average_row_is_not_a_company(monkeypatch):
    """Measured live: 行业平均 was the sixth "peer" 00100 got back.

    The report ends with aggregate rows that carry a label where the code
    belongs, and every downstream consumer would then try to price a ticker
    called 行业平均.
    """
    monkeypatch.setattr(sp, "em_get", lambda *a, **kw: FakeResponse(
        {"result": {"data": [
            {"TYPE_NAME": "软件服务", "CORRE_SECURITY_CODE": "00700",
             "CORRE_SECURITY_NAME": "腾讯控股"},
            {"TYPE_NAME": "软件服务", "CORRE_SECURITY_CODE": "行业平均",
             "CORRE_SECURITY_NAME": "行业平均"},
        ]}}))

    assert [p["ticker"] for p in sp._suggest_hk("00100", [])] == ["00700"]


def test_an_empty_industry_report_degrades_to_no_peers(monkeypatch, capsys):
    monkeypatch.setattr(sp, "em_get", lambda *a, **kw: FakeResponse(
        {"result": None, "success": True}))

    assert sp._suggest_hk("00700", []) == []
    assert "no HK industry comparison rows" in capsys.readouterr().err


def test_hk_outage_returns_empty_and_diagnoses_when_enabled(monkeypatch, capsys):
    # When HK is enabled, a source outage must still degrade to [] (never raise).
    monkeypatch.setattr(sp, "HK_AUTO_PEERS_ENABLED", True)
    monkeypatch.setattr(sp, "em_get", lambda *a, **kw: None)

    assert sp.suggest_auto_peers("00700", "hk", []) == []
    assert "auto peer source failed" in capsys.readouterr().err
