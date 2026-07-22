"""Behavioural tests for the shared peer scanner.

`peer_scan.collect` is the one place that decides what the 板块全景 / 同行扫描
sections are allowed to say, so its two drift guards are pinned here: a peer-map
entry that names a different company than the feed, and a delisted line still
echoing its last-ever quote.

The fetch itself is stubbed — no network, no subprocess.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


WS = Path(__file__).resolve().parents[1]
DATA_SCRIPTS = str(WS / "scripts" / "data")


@pytest.fixture(scope="module")
def ps():
    if DATA_SCRIPTS not in sys.path:
        sys.path.insert(0, DATA_SCRIPTS)
    return pytest.importorskip("peer_scan")


PORTFOLIO = {
    "portfolios": {
        "hk_stocks": {"holdings": [
            {"ticker": "00100", "shares": 100, "today_change_pct": -3.0, "pnl_percent": -65.1},
        ]},
        "us_stocks": {"holdings": [
            {"ticker": "SOLD", "shares": 0, "today_change_pct": 1.0, "pnl_percent": 1.0},
        ]},
    }
}

PEER_MAP = {"holdings": {
    "00100": {
        "name": "MINIMAX-W",
        "theme": "HK AI 大模型",
        "listed_peers": [
            {"ticker": "02513", "region": "hk", "name": "智谱", "rel": "大模型同业"},
            {"ticker": "09999", "region": "hk", "name": "旧名字", "rel": "改过名的"},
            {"ticker": "00001", "region": "hk", "name": "退市了", "rel": "僵尸报价"},
        ],
    },
    "SOLD": {"name": "已清仓", "theme": "无", "listed_peers": [
        {"ticker": "ZZZZ", "region": "us", "name": "Whatever", "rel": "x"},
    ]},
}}

FETCHED = {
    "02513": {"price": 1175.0, "pct_1d": 8.0, "pct_5d": -31.2, "name": "智谱"},
    "09999": {"price": 10.0, "pct_1d": 1.0, "pct_5d": 2.0, "name": "完全不同的公司"},
    "00001": {"price": 86.96, "pct_1d": 0.0, "pct_5d": 5.35, "name": "退市了",
              "stale_quote": "2026-02-06 09:30:00 (163d old)"},
}


@pytest.fixture
def wired(ps, tmp_path, monkeypatch):
    """Points collect() at a synthetic peer-map and a stubbed fetch."""
    peer_map = tmp_path / "peer-map.json"
    peer_map.write_text(json.dumps(PEER_MAP, ensure_ascii=False))
    monkeypatch.setattr(ps, "WS", tmp_path)
    (tmp_path / "memory").mkdir(exist_ok=True)
    (tmp_path / "memory" / "peer-map.json").write_text(json.dumps(PEER_MAP, ensure_ascii=False))

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps({"peers": FETCHED})
        stderr = ""

    monkeypatch.setattr(ps, "_run_fetch", lambda req: FakeCompleted(), raising=False)
    import subprocess as sp
    monkeypatch.setattr(sp, "run", lambda *a, **kw: FakeCompleted())
    return ps


def test_inactive_holdings_are_not_scanned(wired):
    scan = wired.collect(PORTFOLIO, log=lambda m: None)
    assert "00100" in scan
    assert "SOLD" not in scan, "a zero-share holding must not pull peer data"


def test_stale_peer_is_dropped_not_read_as_flat(wired):
    logged = []
    scan = wired.collect(PORTFOLIO, log=logged.append)
    tickers = [p["ticker"] for p in scan["00100"]["listed_peers"]]
    assert "00001" not in tickers
    assert any("stale" in m for m in logged)


def test_feed_name_wins_and_mismatch_is_reported(wired):
    logged = []
    scan = wired.collect(PORTFOLIO, log=logged.append)
    renamed = next(p for p in scan["00100"]["listed_peers"] if p["ticker"] == "09999")
    assert renamed["name"] == "完全不同的公司", "must not relabel with the configured name"
    assert "name_mismatch" in renamed
    assert any("name mismatch" in m for m in logged)


def test_agreeing_name_carries_no_mismatch_flag(wired):
    scan = wired.collect(PORTFOLIO, log=lambda m: None)
    zhipu = next(p for p in scan["00100"]["listed_peers"] if p["ticker"] == "02513")
    assert "name_mismatch" not in zhipu


@pytest.mark.parametrize("skill", ["hk-stock-analysis", "us-stock-analysis"])
def test_skills_only_claim_peer_scan_where_a_preflight_emits_it(skill):
    """Doc-code contract: a SKILL that says "preflight gives you X" must be true.

    The 2026-07-22 cron went red because the SKILL asked for a sector Top 5 while
    no preflight supplied the data, so the agent improvised a fetch. Telling it to
    read a `peer_scan` that a preflight does not write would recreate exactly that
    footgun in a quieter form.
    """
    body = (WS / "skills" / skill / "SKILL.md").read_text()
    if "peer_scan" not in body:
        pytest.skip("skill does not reference peer_scan")
    for name in ("report_preflight", "intraday_preflight"):
        src = (WS / "scripts" / "harness" / f"{name}.py").read_text()
        assert "'peer_scan':" in src, f"{skill} promises peer_scan but {name} never writes it"
        assert "peer_scan.collect" in src


def test_flat_peer_outranks_losers(wired, monkeypatch):
    """`or -999` would bury a genuinely flat peer below every loser."""
    fetched = {
        "02513": {"price": 1.0, "pct_1d": 0.0, "pct_5d": 0.0, "name": "智谱"},
        "09999": {"price": 1.0, "pct_1d": -5.0, "pct_5d": 0.0, "name": "完全不同的公司"},
        "00001": {"price": 1.0, "pct_1d": -1.0, "pct_5d": 0.0, "name": "退市了"},
    }

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps({"peers": fetched})
        stderr = ""

    import subprocess as sp
    monkeypatch.setattr(sp, "run", lambda *a, **kw: FakeCompleted())
    scan = wired.collect(PORTFOLIO, log=lambda m: None)
    order = [p["ticker"] for p in scan["00100"]["listed_peers"]]
    assert order == ["02513", "00001", "09999"], "0.0 must sort above -1.0 and -5.0"


def test_legs_scopes_the_scan_before_fetching(wired):
    """A single-market caller must not pay the cross-market fan-out."""
    portfolio = {
        "portfolios": {
            "hk_stocks": {"holdings": [
                {"ticker": "00100", "shares": 100, "today_change_pct": -3.0, "pnl_percent": -65.1},
            ]},
            "us_stocks": {"holdings": [
                {"ticker": "SOLD", "shares": 5, "today_change_pct": 1.0, "pnl_percent": 1.0},
            ]},
        }
    }
    both = wired.collect(portfolio, log=lambda m: None)
    assert {"00100", "SOLD"} <= set(both)
    hk_only = wired.collect(portfolio, log=lambda m: None, legs=("hk_stocks",))
    assert set(hk_only) == {"00100"}


def test_peers_are_sorted_and_divergence_is_flagged(wired):
    scan = wired.collect(PORTFOLIO, log=lambda m: None)
    entry = scan["00100"]
    pcts = [p["pct_1d"] for p in entry["listed_peers"]]
    assert pcts == sorted(pcts, reverse=True)
    # best peer +8.0 vs holding -3.0 = 11pp gap, well over the 3pp threshold
    assert entry["divergence_signal"] and "02513" in entry["divergence_signal"]
    assert entry["theme"] == "HK AI 大模型"
