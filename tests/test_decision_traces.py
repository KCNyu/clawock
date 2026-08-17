"""Behavioral tests for build_decision_traces — the dashboard card mirror of
the DSH plugin's decision-trace view.

Synthetic workspace under a temp dir; WS_ROOT is monkeypatched so no real desk
data, bars or network are touched. Verifies the trace contract: real fills as
the spine, soft-paired decisions (±3 calendar days, same ticker) as the "why"
layer, T+1 verdicts against canonical bars, and no cross-currency mixing in the
realized figures.

The fixture writes `memory/snapshots/` prices that DISAGREE with
`memory/bars/` on purpose. That disagreement is the anti-inert assertion for
#740: if this view ever slides back onto snapshot `current_price`, the deltas
move and `test_t1_marks_against_canonical_bars_not_snapshots` goes red instead
of the regression shipping quietly.
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
    # Canonical bars — the price source this view settles against.
    bars = {
        "PLTU": {"2026-08-14": 49.24, "2026-08-15": 49.0},
        # 08-05 is the T+1 close for the 08-04 HK fill; 00100 keeps trading.
        "00100": {"2026-08-05": 230.0, "2026-08-14": 330.0, "2026-08-15": 329.0},
        # SPCH deliberately has NO close after its 2026-08-15 fill.
        "SPCH": {"2026-08-13": 8.5},
    }
    (tmp_path / "memory" / "bars").mkdir(parents=True)
    for ticker, closes in bars.items():
        (tmp_path / "memory" / "bars" / f"{ticker}.json").write_text(json.dumps({
            "schema_version": 1, "ticker": ticker,
            "bars": {d: {"open": c, "high": c, "low": c, "close": c} for d, c in closes.items()},
        }), encoding="utf-8")
    # Snapshots with contradicting prices. Nothing may read these (#740) — they
    # exist so a silent regression back onto snapshot current_price is visible.
    for day, prices in [("2026-08-14", {"PLTU": 60.0, "SPCH": 20.0, "00100": 500.0}),
                        ("2026-08-15", {"PLTU": 61.0, "SPCH": 21.0, "00100": 501.0})]:
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


def test_no_t1_when_canonical_close_missing(ws):
    """The 08-15 SPCH buy has no close after it → t1 stays absent, not fake."""
    traces = dashboard.build_decision_traces()
    spch = next(t for t in traces if t["ticker"] == "SPCH")
    assert spch["t1"] is None


def test_rationale_truncated_to_payload_budget(ws):
    """Full rationales blew the 200KB dashboard cap (209KB in CI); the trace
    contract truncates them at 140 chars so the payload stays publishable."""
    traces = dashboard.build_decision_traces()
    for t in traces:
        r = (t.get("decision") or {}).get("rationale")
        if r:
            assert len(r) <= 141, f"rationale too long: {len(r)}"


def test_hold_pnl_attached_for_still_held_tickers(ws):
    traces = dashboard.build_decision_traces()
    spch = next(t for t in traces if t["ticker"] == "SPCH")
    assert spch["holdPnl"] == -28.0


def test_t1_marks_against_canonical_bars_not_snapshots(ws):
    """#740: this view settled T+1 against snapshot `current_price`, the field
    settlement had already disowned — 9 of 40 published verdicts were wrong.

    The fixture's snapshots say PLTU closed at 60.0 on 08-14; the canonical bar
    says 49.24. Marking the 50.0 sell against the snapshot would read +20%
    (卖飞); against the bar it is -1.52% (卖对). Asserting the *number* is what
    makes this gate non-inert: it fails if the source ever slides back.
    """
    traces = dashboard.build_decision_traces()
    pltu = next(t for t in traces if t["ticker"] == "PLTU" and t["date"] == "2026-08-13")
    assert pltu["t1"]["price"] == 49.24, "T+1 price must come from memory/bars"
    assert pltu["t1"]["delta"] == -1.52
    assert pltu["t1"]["verdict"] == "卖对"


def test_t1_refuses_a_close_beyond_the_gap_ceiling(ws, tmp_path):
    """A close far after the fill is a different horizon and must not wear the
    T+1 label. Mirrors the plugin's T1_MAX_GAP_DAYS = 4."""
    bars = tmp_path / "memory" / "bars" / "PLTU.json"
    doc = json.loads(bars.read_text())
    # Only close left for the 08-13 sell is 11 days later.
    doc["bars"] = {"2026-08-24": {"open": 60.0, "high": 60.0, "low": 60.0, "close": 60.0}}
    bars.write_text(json.dumps(doc), encoding="utf-8")
    traces = dashboard.build_decision_traces()
    pltu = next(t for t in traces if t["ticker"] == "PLTU" and t["date"] == "2026-08-13")
    assert pltu["t1"] is None, "an 11-day-later close is not T+1"


def test_t1_accepts_a_weekend_gap(ws, tmp_path):
    """Friday fill settling against Monday is 3 calendar days — still T+1."""
    bars = tmp_path / "memory" / "bars" / "PLTU.json"
    doc = json.loads(bars.read_text())
    doc["bars"] = {"2026-08-16": {"open": 55.0, "high": 55.0, "low": 55.0, "close": 55.0}}
    bars.write_text(json.dumps(doc), encoding="utf-8")
    traces = dashboard.build_decision_traces()
    pltu = next(t for t in traces if t["ticker"] == "PLTU" and t["date"] == "2026-08-13")
    assert pltu["t1"] is not None and pltu["t1"]["date"] == "2026-08-16"


def test_t1_tone_and_verdict_share_one_dead_zone(ws):
    """#739: the card coloured the chip on `delta >= 0` while the words used a
    ±1% dead zone, so a sell at +0.5% rendered a red chip labelled 持平 — three
    such rows were live. Tone ships with the verdict from one rule."""
    assert dashboard._t1_verdict("sell", 0.5) == "持平"
    assert dashboard._t1_tone("sell", 0.5) == "flat", "a 持平 move may not be coloured"
    assert dashboard._t1_verdict("sell", 2.0) == "卖飞"
    assert dashboard._t1_tone("sell", 2.0) == "loss"
    assert dashboard._t1_verdict("buy", 2.0) == "涨"
    assert dashboard._t1_tone("buy", 2.0) == "win"
    # A reducing action other than plain "sell" follows the sell rule too: the
    # old renderer only special-cased `sell` and coloured cut/trim gains green.
    for reducing in ("cut", "trim", "trim_on_rebound"):
        assert dashboard._t1_tone(reducing, 3.0) == "loss", reducing
        assert dashboard._t1_verdict(reducing, 3.0) == "卖飞", reducing


def test_pairing_window_is_calendar_days_across_a_year_boundary():
    """#739: the window used y*400+m*32+d, which puts 2026-12-31 and
    2027-01-01 eighteen "days" apart — a January fill could never pair with a
    late-December plan, and every cross-month window was quietly short."""
    assert dashboard._day_num("2027-01-01") - dashboard._day_num("2026-12-31") == 1
    assert dashboard._day_num("2026-08-01") - dashboard._day_num("2026-07-29") == 3
    assert dashboard._day_num("2026-03-01") - dashboard._day_num("2026-02-27") == 2
    assert dashboard._day_num("not-a-date") is None
    assert dashboard._day_num("2026-02-30") is None, "an impossible date is not a day"


def test_year_boundary_plan_pairs_with_january_fill(tmp_path, monkeypatch):
    """The same defect, end to end: a 12-31 plan and a 01-02 fill are 2 days
    apart and must soft-pair."""
    (tmp_path / "memory").mkdir()
    (tmp_path / "portfolio.json").write_text(json.dumps({"portfolios": {"us_stocks": {
        "currency": "USD", "holdings": [{"ticker": "NVDA", "shares": 1, "trades": [
            {"date": "2027-01-02", "action": "buy", "shares": 1, "price": 100.0}]}]}}}),
        encoding="utf-8")
    (tmp_path / "memory" / "decisions.jsonl").write_text(json.dumps({
        "decision_id": "dec-y", "plan_date": "2026-12-31", "ticker": "NVDA",
        "action": "buy", "confidence": 0.7, "driven_by": "technical"},
        ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(dashboard, "WS_ROOT", tmp_path)
    traces = dashboard.build_decision_traces()
    assert traces[0]["decision"] is not None, "12-31 plan must pair with a 01-02 fill"
    assert traces[0]["decision"]["planDate"] == "2026-12-31"


def test_rationale_strips_internal_breach_ids(ws, tmp_path):
    """#738: the public card printed "(breach risk-66a236e9b7e1 30d)" — an
    internal hash that means nothing to a reader and ate the 140-char budget."""
    line = json.loads((tmp_path / "memory" / "decisions.jsonl").read_text().splitlines()[1])
    line["rationale"] = ("76.69% single_name超限 mandatory cap 35% "
                         "(breach risk-66a236e9b7e1 30d) + 硬止损 -27.23% ≤ -18% "
                         "(breach risk-95ac7f6cd591 30d) 一次性 cut 200 shares")
    lines = (tmp_path / "memory" / "decisions.jsonl").read_text().splitlines()
    lines[1] = json.dumps(line, ensure_ascii=False)
    (tmp_path / "memory" / "decisions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    traces = dashboard.build_decision_traces()
    spch = next(t for t in traces if t["ticker"] == "SPCH")
    rationale = spch["decision"]["rationale"]
    assert "risk-" not in rationale and "breach" not in rationale
    assert "一次性 cut 200 shares" in rationale, "the real sentence must survive"


def test_alignment_states_the_plan_vs_fill_relation(ws):
    """#738: 39 of 40 published rows had a plan action that differed from the
    fill and the card said nothing. The relation ships as data."""
    traces = dashboard.build_decision_traces()
    spch = next(t for t in traces if t["ticker"] == "SPCH")
    assert spch["decision"]["alignment"] == "opposite", "planned cut, actually bought"
    pltu = next(t for t in traces if t["ticker"] == "PLTU" and t["date"] == "2026-08-13")
    assert pltu["decision"]["alignment"] == "same", "planned trim, actually sold"
    hk = next(t for t in traces if t["ticker"] == "00100")
    assert hk["decision"]["alignment"] == "other", "a reject plan points at neither side"


def test_scope_totals_come_from_the_whole_ledger_not_the_window(ws):
    """#737: the card summed its own window and printed the result as an
    unqualified 已实现 total — $926.3 while the ledger held US $2,347.68 +
    HK$7,259.16, and a flat "HK HK$0" while HK realized was HK$7,259.16."""
    traces = dashboard.build_decision_traces(limit=2)
    scope = dashboard.build_decision_trace_scope(traces, limit=2)
    assert scope["fillsShown"] == 2
    assert scope["fillsTotal"] == 4, "the denominator is the whole fill ledger"
    # The window (newest 2 fills) holds no closed HK fill; the ledger holds the
    # HKD leg either way, so a reader can never mistake the window for the total.
    assert scope["realizedShown"] == {"USD": 45.21}
    assert scope["realizedAll"] == {"USD": 45.21}
    assert scope["closedShown"] == 1


def test_scope_keeps_currencies_apart_and_counts_carry_denominators(ws):
    traces = dashboard.build_decision_traces()
    scope = dashboard.build_decision_trace_scope(traces)
    assert scope["fillsShown"] == scope["fillsTotal"] == 4
    assert scope["pairedShown"] == 4, "all four fills fall inside a plan window"
    # The 08-08 PLTU buy also lands in the 08-10 trim plan's window, so it
    # counts as a reversal too: planned to reduce, actually added.
    assert scope["alignment"] == {"same": 1, "opposite": 2, "other": 1}
    # Mind/emotion coverage is published even when it is bad news: production
    # ran 0/40 while the card advertised an emotion layer (#738).
    assert scope["emotionShown"] == 1 and scope["mindShown"] == 1
    assert set(scope["t1Verdicts"]) <= {"reduce", "add"}
    assert sum(scope["t1Verdicts"]["reduce"].values()) == 1
