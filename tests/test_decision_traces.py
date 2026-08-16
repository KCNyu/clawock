"""Behavioral tests for build_decision_traces — the dashboard card mirror of
the DSH plugin's decision-trace view.

Synthetic workspace under a temp dir; WS_ROOT is monkeypatched so no real desk
data, snapshots or network are touched. Verifies the trace contract: real fills
as the spine, soft-paired decisions (±3 days, same ticker) as the "why" layer,
T+1 close verdicts, and no cross-currency mixing in the realized figures.
"""
import json
import os
from pathlib import Path

import pytest

from clawock.publish import dashboard


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """A minimal desk: portfolio.json + decisions.jsonl + two snapshots."""
    (tmp_path / "memory" / "snapshots").mkdir(parents=True)
    portfolio = {
        "portfolios": {
            "us_stocks": {"currency": "USD", "holdings": [
                {"ticker": "PLTU", "shares": 5, "current_price": 49.24,
                 "pnl_percent": -1.5, "trades": [
                     {"date": "2026-08-13", "action": "sell", "shares": 5,
                      "price": 50.0, "realized_pnl": 45.21,
                      "note": "PLTU 清仓"},
                     {"date": "2026-08-08", "action": "buy", "shares": 5,
                      "price": 45.0, "note": "建仓"},
                 ]},
                {"ticker": "SPCH", "shares": 10, "current_price": 8.77,
                 "pnl_percent": -28.0, "trades": [
                     {"date": "2026-08-15", "action": "buy", "shares": 10,
                      "price": 8.77, "note": "无限子弹流摊本"},
                 ]},
            ]},
            "hk_stocks": {"currency": "HKD", "holdings": [
                {"ticker": "00100", "shares": 120, "current_price": 329.0,
                 "pnl_percent": -40.5, "trades": [
                     {"date": "2026-08-04", "action": "buy", "shares": 20,
                      "price": 230.0, "note": "微信成交"},
                 ]},
            ]},
        },
    }
    (tmp_path / "portfolio.json").write_text(json.dumps(portfolio), encoding="utf-8")
    decisions = [
        # PLTU: plan on 08-10 (within ±3 of the 08-13 sell) — soft pair.
        {"decision_id": "dec-pltu1", "plan_date": "2026-08-10", "ticker": "PLTU",
         "action": "trim_on_rebound", "confidence": 0.6, "driven_by": "technical",
         "rationale": "浮盈保护", "size": {"shares": 5},
         "execution": {"status": "followed"},
         "condition": {"description": "反弹至 50 减仓"}},
        # SPCH: plan on 08-14, trade on 08-15 — direction conflict.
        {"decision_id": "dec-spch1", "plan_date": "2026-08-14", "ticker": "SPCH",
         "action": "cut", "confidence": 0.82, "driven_by": "risk_rule",
         "rationale": "超限硬止损", "size": {"shares": 200, "pct": 0.8},
         "evaluation": {"execution_price": 9.21},
         "execution": {"status": "unknown"}},
        # Conversation mind record (schema_version=0) with full mind fields.
        {"schema_version": 0, "decision_id": "dec-00100a", "ticker": "00100",
         "decided_at": "2026-08-04T13:45:00+08:00", "action": "reject",
         "confidence": 0.65, "driven_by": "fundamental", "source": "conversation",
         "subject": {"ticker": "00100", "market": "HK", "currency": "HKD"},
         "mind": {"bull": {"summary": "营收 +159%"}, "bear": {"summary": "资不抵债"},
                  "thesis": "先活下来", "invalidation": ["站回 340"]},
         "emotion": {"pressure": "averaging_down", "note": "忍住没加"},
         "execution": {"status": "followed"}},
    ]
    (tmp_path / "memory" / "decisions.jsonl").write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in decisions),
        encoding="utf-8")
    # Snapshots: 08-14 (T+1 for the 08-13 sell) and 08-15.
    for day, prices in [("2026-08-14", {"PLTU": 49.24, "SPCH": 9.0, "00100": 330.0}),
                        ("2026-08-15", {"PLTU": 49.0, "SPCH": 9.1, "00100": 329.0})]:
        snap = {"portfolios": {"us_stocks": {"holdings": [
            {"ticker": k, "current_price": v} for k, v in prices.items()]}}}
        (tmp_path / "memory" / "snapshots" / f"{day}.json").write_text(
            json.dumps(snap), encoding="utf-8")
    monkeypatch.setattr(dashboard, "WS_ROOT", tmp_path)
    return tmp_path


def test_traces_spine_is_real_fills_newest_first(ws):
    traces = dashboard.build_decision_traces()
    assert len(traces) == 4
    dates = [t["date"] for t in traces]
    assert dates == sorted(dates, reverse=True), "newest first"


def test_soft_pair_attaches_decision_within_window(ws):
    traces = dashboard.build_decision_traces()
    pltu = next(t for t in traces if t["ticker"] == "PLTU" and t["date"] == "2026-08-13")
    assert pltu["decision"] is not None
    assert pltu["decision"]["action"] == "trim_on_rebound"
    assert pltu["decision"]["planDate"] == "2026-08-10"
    assert pltu["decision"]["condition"] == "反弹至 50 减仓"
    assert pltu["decision"]["sizeShares"] == 5
    assert pltu["decision"]["execution"] == "followed"


def test_t1_verdict_on_sell(ws):
    traces = dashboard.build_decision_traces()
    pltu = next(t for t in traces if t["ticker"] == "PLTU" and t["date"] == "2026-08-13")
    # T+1 close 49.24 vs sell 50.0 → -1.52% → 卖对.
    assert pltu["t1"] is not None
    assert pltu["t1"]["verdict"] == "卖对"
    assert pltu["t1"]["delta"] < 0


def test_direction_conflict_is_visible(ws):
    """SPCH planned cut on 08-14 but bought on 08-15: the trace must carry
    both sides — this is the product's core signal."""
    traces = dashboard.build_decision_traces()
    spch = next(t for t in traces if t["ticker"] == "SPCH")
    assert spch["decision"]["action"] == "cut"
    assert spch["action"] == "buy"
    assert spch["decision"]["plannedPrice"] == 9.21


def test_conversation_mind_record_pairs_with_its_trade(ws):
    traces = dashboard.build_decision_traces()
    hk = next(t for t in traces if t["ticker"] == "00100")
    assert hk["currency"] == "HKD"
    assert hk["decision"]["action"] == "reject"
    assert hk["decision"]["source"] == "conversation"
    assert hk["decision"]["thesis"] == "先活下来"
    assert hk["decision"]["emotion"] == "averaging_down"
    assert hk["decision"]["bull"] == "营收 +159%"


def test_no_t1_when_snapshot_missing(ws):
    """The 08-15 SPCH buy has no close after it → t1 stays absent, not fake."""
    traces = dashboard.build_decision_traces()
    spch = next(t for t in traces if t["ticker"] == "SPCH")
    assert spch["t1"] is None


def test_hold_pnl_attached_for_still_held_tickers(ws):
    traces = dashboard.build_decision_traces()
    spch = next(t for t in traces if t["ticker"] == "SPCH")
    assert spch["holdPnl"] == -28.0
