"""The add-side read is a join of answers the packet already had (#755).

kcn's ask was to see, intraday, whether a price/news anomaly amounts to an add
signal. Everything needed was already computed — `anomalies`, `opportunity_radar`,
`early_trend_candidates`, `mover_news` (already triaged), `mover_thesis`,
`plan_context` — and none of it reached the message, because the Mode 7 template
named none of the three lanes.

These tests pin the three rules the join encodes, each of which is a rule the desk
already wrote down somewhere else:

1. discipline outranks opportunity (an open `risk_rule` action ⇒ `reject`);
2. only a primary `interrupt` filing can promote to `candidate`;
3. everything else is `wait`, carrying the level that would settle it.

Plus the two things that make it usable rather than decorative: the numbers are
copied (never derived), and the postflight notices when the prose ignores the rows.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clawock.decision import add_side  # noqa: E402

RADAR = {"rows": [
    {"label": "02208", "state": "near_breakout", "state_zh": "机会·接近",
     "holdings": ["02208"], "prior_20d_high": 11.72, "pct_from_high": -4.01},
    {"label": "HSTECH", "state": "near_breakout", "state_zh": "机会·接近",
     "holdings": ["07226"], "prior_20d_high": 4948.5, "pct_from_high": -3.06},
    {"label": "00700", "state": "mid_range", "holdings": ["00700"],
     "prior_20d_high": 500.0, "pct_from_high": -12.0},
]}
PRIMARY = {"tickers": {"02208": {"status": "ok", "items": [
    {"tier": "primary", "signal": "interrupt", "title": "盈喜:上半年净利预增 60%",
     "age_minutes": 12},
]}}}
SOFT_ONLY = {"tickers": {"02208": {"status": "ok", "items": [
    {"tier": "supporting", "signal": "context", "title": "券商上调目标价"},
]}}}


def _row(out, ticker):
    return next(r for r in out["rows"] if r["ticker"] == ticker)


def test_a_price_anomaly_without_a_primary_filing_waits_and_names_the_level():
    """The common case, and the one that produced nothing before: 02208 +6.4%."""
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=RADAR, mover_news={"tickers": {"02208": {"status": "no_recent_filing",
                                                       "items": []}}})
    row = _row(out, "02208")
    assert row["verdict"] == "wait"
    assert "无一手公告" in row["why"]
    assert "11.72" in row["needs"], "a wait with no falsifier is a shrug"
    assert row["evidence"]["move_pct"] == 6.4
    assert row["triggers"] == ["price_anomaly", "near_breakout"]
    assert row["authorization"] is None


def test_soft_news_alone_cannot_promote_past_wait():
    """The catalyst gate, restated here: sentiment and broker notes are colour.

    This is the half kcn asked for ("情绪消息异动") and the half that must not turn
    into an add authorisation — the rule predates this module.
    """
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=RADAR, mover_news=SOFT_ONLY)
    row = _row(out, "02208")
    assert row["verdict"] == "wait"
    assert "软消息" in row["why"] or "情绪" in row["why"]
    assert "news" in row["triggers"]


def test_a_primary_interrupt_plus_a_breakout_approach_is_a_candidate():
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=RADAR, mover_news=PRIMARY)
    row = _row(out, "02208")
    assert row["verdict"] == "candidate"
    assert "盈喜" in row["why"]
    assert "11.72" in row["needs"]
    assert out["candidate_count"] == 1


def test_a_primary_filing_without_the_technical_state_still_waits():
    """Half the condition is not the condition."""
    radar = {"rows": [r for r in RADAR["rows"] if r["label"] != "02208"]}
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=radar, mover_news=PRIMARY)
    assert _row(out, "02208")["verdict"] == "wait"


def test_an_unfinished_risk_rule_action_rejects_regardless_of_how_good_it_looks():
    """Discipline outranks opportunity — even with a primary catalyst on the tape."""
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=RADAR, mover_news=PRIMARY,
        plan_context={"open": [{"ticker": "02208", "action": "cut", "shares": 1200,
                                "driven_by": "risk_rule"}]})
    row = _row(out, "02208")
    assert row["verdict"] == "reject"
    assert "cut" in row["why"] and "1200" in row["why"]
    assert "纪律" in row["needs"]


def test_a_live_thesis_red_line_rejects_too():
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=RADAR, mover_news=PRIMARY,
        mover_thesis={"02208": {"status": "triggered", "reason": "杠杆敞口 30.5% breach"}})
    assert _row(out, "02208")["verdict"] == "reject"


def test_an_unknown_thesis_is_not_a_red_line():
    """`status: unknown` is the normal state for a name with no baseline (live data
    on 2026-08-17 had exactly that for both anomaly tickers). Treating it as a
    breach would make every read a `reject` and the lane useless."""
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=RADAR, mover_news=SOFT_ONLY,
        mover_thesis={"02208": {"status": "unknown", "reason": "no canonical thesis"}})
    assert _row(out, "02208")["verdict"] == "wait"


def test_a_name_deep_in_its_range_produces_no_row_at_all():
    """Only states the radar calls in-play are add-side reads; 00700 at -12% is not."""
    out = add_side.read_rows(anomalies=[], radar=RADAR)
    assert [r["ticker"] for r in out["rows"]] == ["02208", "07226"], out["rows"]


def test_index_labels_resolve_to_the_tradable_holding():
    """HSTECH has no ticker to add; 07226 is the thing that trades."""
    out = add_side.read_rows(anomalies=[], radar=RADAR)
    assert "HSTECH" not in [r["ticker"] for r in out["rows"]]
    assert _row(out, "07226")["evidence"]["prior_20d_high"] == 4948.5


def test_every_number_in_a_row_came_from_the_inputs():
    """No derived arithmetic: a number in the report must be pointable-at in context."""
    anomalies = [{"ticker": "02208", "move_pct": 6.4, "severity": "high"}]
    out = add_side.read_rows(anomalies=anomalies, radar=RADAR, mover_news=SOFT_ONLY)
    supplied = {6.4, 11.72, -4.01, 4948.5, -3.06}
    for row in out["rows"]:
        for key, value in row["evidence"].items():
            if isinstance(value, (int, float)):
                assert value in supplied, f"{key}={value} is not an input value"


def test_the_live_context_shape_still_feeds_it():
    """Runs the join on the real packet if this host has one — shape, not values.

    The module reads six context keys; a rename in preflight would otherwise show
    up as a quietly empty lane, which is how the three lanes it replaces got lost.
    """
    live = Path("/root/.openclaw/workspace/memory/.tmp/intraday-context-hk-latest.json")
    try:
        # `exists()` is not the question — a CI runner has an unreadable /root that
        # answers True and then raises on read (this test failed exactly that way
        # on its first PR run). Try the read and let any OSError mean "not here".
        raw = live.read_text()
    except OSError:
        pytest.skip("no readable live intraday context on this machine")
    ctx = json.loads(raw)
    for key in ("anomalies", "opportunity_radar", "early_trend_candidates",
                "mover_news", "mover_thesis", "plan_context"):
        assert key in ctx, f"preflight no longer emits {key}"
    out = add_side.read_rows(
        anomalies=ctx["anomalies"], radar=ctx["opportunity_radar"],
        early_trend=ctx["early_trend_candidates"], mover_news=ctx["mover_news"],
        mover_thesis=ctx["mover_thesis"], plan_context=ctx["plan_context"])
    assert set(out) == {"rows", "candidate_count", "wait_count", "reject_count",
                        "policy"}
    assert all(r["verdict"] in add_side.VERDICTS for r in out["rows"])


def test_both_market_skills_require_the_line_in_the_same_words():
    """Two hand-written templates that must not drift (#739's lesson)."""
    texts = [(ROOT / "skills" / f"{market}-stock-analysis" / "SKILL.md").read_text()
             for market in ("hk", "us")]
    for text in texts:
        assert "add_side_reads" in text
        assert "三态都不是下单授权" in text
    hk, us = (t.split("add_side_reads", 1)[1][:400] for t in texts)
    assert hk == us, "the hk and us Mode 7 add-side instructions have drifted"
