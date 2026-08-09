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
    # HK auto-peers ship disabled (East Money HK constituent endpoint unresolved).
    # The gate must short-circuit BEFORE any East Money call so a HK-heavy scan
    # is not slowed by wasted/failing requests every cycle.
    calls = []
    monkeypatch.setattr(sp, "em_get", lambda *a, **kw: calls.append(kw) or None)

    assert sp.suggest_auto_peers("00700", "hk", ["09988"]) == []
    assert calls == []
    assert "not wired yet" in capsys.readouterr().err


def test_hk_parser_resolves_industry_excludes_and_caps_six(monkeypatch):
    # Guards `_suggest_hk` (called directly, bypassing the ship gate) so the parser
    # is correct for when HK is enabled — using a realistic HK\d+ board code.
    calls = []

    def fake_em_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        if url == sp.EM_STOCK_INFO_URL:
            return FakeResponse({"data": {"f57": "00700", "f58": "腾讯控股", "f127": "互联网服务"}})
        if url == sp.EM_STOCK_BOARDS_URL:
            return FakeResponse({"data": {"diff": [
                {"f12": "HK9999", "f14": "腾讯概念"},
                {"f12": "HK28", "f14": "互联网服务"},
            ]}})
        assert url == sp.EM_BOARD_CONSTITUENTS_URL
        return FakeResponse({"data": {"diff": [
            {"f12": "00700", "f13": 116, "f14": "腾讯控股"},
            {"f12": "09988", "f13": 116, "f14": "阿里巴巴-W"},
            {"f12": "03690", "f13": 116, "f14": "美团-W"},
            {"f12": "01024", "f13": 116, "f14": "快手-W"},
            {"f12": "09626", "f13": 116, "f14": "哔哩哔哩-W"},
            {"f12": "09888", "f13": 116, "f14": "百度集团-SW"},
            {"f12": "09999", "f13": 116, "f14": "网易-S"},
            {"f12": "03888", "f13": 116, "f14": "金山软件"},
            {"f12": "00772", "f13": 116, "f14": "阅文集团"},
            {"f12": "600519", "f13": 1, "f14": "贵州茅台"},
        ]}})

    monkeypatch.setattr(sp, "em_get", fake_em_get)

    peers = sp._suggest_hk("700", ["09988"])

    assert [p["ticker"] for p in peers] == [
        "03690", "01024", "09626", "09888", "09999", "03888"
    ]
    assert len(peers) == 6
    assert all(p["region"] == "hk" and p["source"] == "eastmoney" for p in peers)
    assert calls[0][0] == sp.EM_STOCK_INFO_URL
    assert calls[1][0] == sp.EM_STOCK_BOARDS_URL
    assert calls[2][1]["fs"] == "b:HK28"


def test_hk_outage_returns_empty_and_diagnoses_when_enabled(monkeypatch, capsys):
    # When HK is enabled, a source outage must still degrade to [] (never raise).
    monkeypatch.setattr(sp, "HK_AUTO_PEERS_ENABLED", True)
    monkeypatch.setattr(sp, "em_get", lambda *a, **kw: None)

    assert sp.suggest_auto_peers("00700", "hk", []) == []
    assert "auto peer source failed" in capsys.readouterr().err
