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
     "holdings": ["02208"], "close": 11.31, "zscore20": 1.4,
     "prior_20d_high": 11.72, "pct_from_high": -4.01},
    {"label": "HSTECH", "state": "near_breakout", "state_zh": "机会·接近",
     "holdings": ["07226"], "close": 4798.0, "zscore20": 1.1,
     "prior_20d_high": 4948.5, "pct_from_high": -3.06},
    {"label": "00700", "state": "mid_range", "holdings": ["00700"],
     "close": 440.0, "zscore20": -1.2,
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
    """HSTECH has no ticker to add; 07226 is the thing that trades.

    #761 changed where the number sits, not whether the hop happens: the row is
    still produced for 07226 and still carries the index's approach, but the
    level is filed under `proxy_*` because 4948.5 is a Hang Seng Tech index
    level and 07226 trades near 3.5 HKD.
    """
    out = add_side.read_rows(anomalies=[], radar=RADAR)
    assert "HSTECH" not in [r["ticker"] for r in out["rows"]]
    row = _row(out, "07226")
    assert row["evidence"]["proxy_label"] == "HSTECH"
    assert row["evidence"]["proxy_prior_20d_high"] == 4948.5
    assert "prior_20d_high" not in row["evidence"], (
        "the bare key is what the SKILL tells the model to copy verbatim")


def test_every_number_in_a_row_came_from_the_inputs():
    """No derived arithmetic: a number in the report must be pointable-at in context."""
    anomalies = [{"ticker": "02208", "move_pct": 6.4, "severity": "high"}]
    out = add_side.read_rows(anomalies=anomalies, radar=RADAR, mover_news=SOFT_ONLY)
    supplied = {6.4, 11.31, 1.4, 11.72, -4.01, 4798.0, 1.1, 4948.5, -3.06}
    for row in out["rows"]:
        for key, value in row["evidence"].items():
            if isinstance(value, (int, float)):
                assert value in supplied, f"{key}={value} is not an input value"


def test_the_technical_basis_of_a_candidate_is_pointable_in_evidence():
    """#819: the new promotion gate rests on close vs prior_20d_high AND z<2
    (未过热). The message writer can only quote evidence numbers, so a breakout
    candidate must carry close and zscore20 verbatim from the radar row."""
    radar = {"rows": [
        {"label": "02208", "state": "breakout", "state_zh": "机会·突破",
         "holdings": ["02208"], "close": 11.31, "zscore20": 1.4,
         "prior_20d_high": 11.72, "pct_from_high": 1.8},
    ]}
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=radar)
    row = _row(out, "02208")
    assert row["verdict"] == "candidate"
    assert row["evidence"]["close"] == 11.31
    assert row["evidence"]["zscore20"] == 1.4
    assert row["evidence"]["prior_20d_high"] == 11.72


def test_the_proxy_renames_close_and_zscore_too():
    """#761's attribution rule covers every number: a proxy row's close and
    zscore belong to the index (HSTECH), not to the tradable holding."""
    out = add_side.read_rows(anomalies=[], radar=RADAR)
    row = _row(out, "07226")
    assert row["evidence"]["proxy_close"] == 4798.0
    assert row["evidence"]["proxy_zscore20"] == 1.1
    assert "close" not in row["evidence"]
    assert "zscore20" not in row["evidence"]


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


# --- #759: the falsifier must survive a selloff ------------------------------
#
# `opportunity_radar` only carries in-play states, so on a red day every row it
# would have carried disappears — and the `wait` rows lost their level exactly
# when "跌到哪才算机会" was the whole question. Live proof (2026-08-18 HK): the
# 10:01 packet had radar=3 and levelled `needs`; from 10:31 radar=0 and all
# three wait rows read "等一手催化或技术面进入突破区". US the same night never
# hit it — its radar stayed 3-4 rows all session.
#
# The two invariants are deliberately opposed: a dropped level must come back
# (1), and coming back must not look like an approach (2).

LEVELS = {"00100": {"prior_20d_high": 336.4, "close": 293.2,
                    "pct_from_high": -12.85},
          "02208": {"prior_20d_high": 11.72, "close": 10.86,
                    "pct_from_high": -7.34}}


def test_a_wait_names_the_level_even_when_the_radar_dropped_the_name():
    """Invariant 1 — 普跌行情下 wait 仍然带位。"""
    out = add_side.read_rows(
        anomalies=[{"ticker": "00100", "move_pct": -12.2, "severity": "high"}],
        radar={"rows": []}, levels=LEVELS,
        mover_news={"tickers": {"00100": {"status": "no_recent_filing",
                                          "items": []}}})
    row = _row(out, "00100")
    assert row["verdict"] == "wait"
    assert "336.4" in row["needs"] and "-12.85" in row["needs"], row["needs"]
    # and the number is pointable-at as data, not only inside the sentence
    assert row["evidence"]["prior_20d_high"] == 336.4
    assert row["evidence"]["pct_from_high"] == -12.85


def test_a_fallback_level_never_reads_as_an_approach():
    """Invariant 2 — 补位不得渗进 candidate 闸。

    The opposite failure of the one above: if a level implied "near the
    breakout", a name 12.85% below its high would collect the `near_breakout`
    trigger, a technical `state`, and — with a primary filing on the tape —
    promotion to `candidate`. Only the radar decides that.
    """
    out = add_side.read_rows(
        anomalies=[{"ticker": "00100", "move_pct": -12.2, "severity": "high"}],
        radar={"rows": []}, levels=LEVELS, mover_news={"tickers": {"00100": {
            "status": "ok", "items": [{"tier": "primary", "signal": "interrupt",
                                       "title": "盈喜"}]}}})
    row = _row(out, "00100")
    assert row["verdict"] == "wait", "a level is not a technical state"
    assert "near_breakout" not in row["triggers"]
    assert row["evidence"].get("state") is None
    assert out["candidate_count"] == 0


def test_no_level_anywhere_keeps_the_generic_sentence():
    """Fail-soft: a name with no computable 20d level (fresh listing, dead feed)
    must still produce its row, not raise."""
    out = add_side.read_rows(
        anomalies=[{"ticker": "09999", "move_pct": -8.0, "severity": "medium"}],
        radar={"rows": []}, levels=LEVELS)
    row = _row(out, "09999")
    assert row["needs"] == "等一手催化或技术面进入突破区"
    assert "prior_20d_high" not in row["evidence"]


def test_discipline_still_owns_the_needs_line_of_a_reject():
    """A level must not overwrite 「先把纪律动作走完」 — reject is not a price question."""
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": -3.0, "severity": "medium"}],
        radar={"rows": []}, levels=LEVELS,
        plan_context={"open": [{"ticker": "02208", "action": "cut", "shares": 6200,
                                "driven_by": "risk_rule"}]})
    row = _row(out, "02208")
    assert row["verdict"] == "reject"
    assert row["needs"] == "先把纪律动作走完,再谈加仓"


def test_the_radar_publishes_the_levels_the_fallback_needs():
    """The two halves must stay wired: preflight emits `levels`, and it covers
    the names the radar itself dropped (that is the entire point)."""
    ctx_path = Path("/root/.openclaw/workspace/memory/.tmp/"
                    "intraday-context-hk-latest.json")
    try:
        ctx = json.loads(ctx_path.read_text())
    except OSError:
        pytest.skip("no readable live intraday context on this machine")
    radar = ctx.get("opportunity_radar") or {}
    if "levels" not in radar:
        pytest.skip("live packet predates #759")
    for row in (ctx.get("add_side_reads") or {}).get("rows", []):
        if row["verdict"] == "wait" and row["ticker"] in radar["levels"]:
            assert "站上" in row["needs"], row


def test_a_proxy_never_donates_its_level_to_the_name_it_stands_for():
    """#759 review catch: the fallback must not put an index level on a warrant.

    The universe carries proxies — `HSTECH` (source_holdings ['07226']), `SPCX`
    (['SPCX', 'SPCH']), `RKLB` (['RKLX']) — and 07226 has no entry of its own.
    Keying `levels` by holdings too would have made a 3.5 HKD warrant read
    「站上 4948.5」, a Hang Seng Tech index point count. A radar row may still
    carry a proxy (that row names the index it is about); a bare level carries
    no such label, so it must stay with the ticker it was computed from, and a
    name with no level of its own keeps the generic sentence.
    """
    out = add_side.read_rows(
        anomalies=[{"ticker": "07226", "move_pct": -4.0, "severity": "medium"}],
        radar={"rows": []},
        levels={"HSTECH": {"prior_20d_high": 4948.5, "close": 4797.0,
                           "pct_from_high": -3.06}})
    row = _row(out, "07226")
    assert "4948.5" not in row["needs"], row["needs"]
    assert row["needs"] == "等一手催化或技术面进入突破区"
    assert "prior_20d_high" not in row["evidence"]


def test_the_radar_keys_levels_by_its_own_label_only():
    """The producing half of the invariant above, at the source."""
    from clawock.harness import intraday_preflight as P

    universe = [{"label": "HSTECH", "code": "hkHSTECH", "region": "HK",
                 "source_holdings": ["07226"]}]
    sigs = [{"close": 4797.0, "prior_20d_high": 4948.5, "zscore20": 0.5}]
    import pytest as _pytest  # noqa: F401  (monkeypatch needs a fixture-free path)
    monkey = _pytest.MonkeyPatch()
    try:
        monkey.setattr(P, "WS", ROOT)
        monkey.setattr(P.quant_signals, "universe_details",
                       lambda errors=None: universe)
        monkey.setattr(P.quant_signals, "compute_signals",
                       lambda bars: sigs.pop(0) if sigs else None)
        monkey.setattr(P.quant_signals, "fetch_bars", lambda code, cnt: [])
        out = P.collect_opportunity_radar("hk")
    finally:
        monkey.undo()
    assert set(out["levels"]) == {"HSTECH"}, out["levels"]
    assert "07226" not in out["levels"]


# --- #761: an index may inform a holding, but its level is not the holding's ---
#
# 07226 *is* the 2x HSTECH product, so the index approaching its 20-day high is
# real information about it and the hop must stay. What could not stay is the
# attribution: `needs: 站上 4948.5` for a name trading near 3.5 HKD reads as an
# executable condition and is off by three orders of magnitude. These tests pin
# both halves — the relationship kept, the numbers re-attributed.

PROXY_RADAR = {"rows": [
    {"label": "HSTECH", "state": "near_breakout", "state_zh": "机会·接近",
     "holdings": ["07226"], "prior_20d_high": 4948.5, "pct_from_high": -4.83},
]}


def test_a_proxy_row_names_the_index_in_its_needs_line():
    out = add_side.read_rows(
        anomalies=[{"ticker": "07226", "move_pct": -4.0, "severity": "medium"}],
        radar=PROXY_RADAR)
    row = _row(out, "07226")
    assert row["needs"].startswith("HSTECH 站上 4948.5"), row["needs"]


def test_a_proxy_candidate_also_names_the_index():
    """The promotion path renders its own sentence and needs the same guard."""
    out = add_side.read_rows(
        anomalies=[{"ticker": "07226", "move_pct": -4.0, "severity": "medium"}],
        radar=PROXY_RADAR, mover_news={"tickers": {"07226": {"status": "ok", "items": [
            {"tier": "primary", "signal": "interrupt", "title": "盈喜"}]}}})
    row = _row(out, "07226")
    assert row["verdict"] == "candidate"
    assert row["needs"].startswith("HSTECH 站上 4948.5"), row["needs"]


def test_the_index_to_holding_relationship_is_not_severed():
    """The half that must NOT change: the hop, the state, and promotion by proxy.

    A fix that simply dropped proxy rows would 'solve' the wrong problem — it
    would take a real signal away from the only tradable name it applies to.
    """
    out = add_side.read_rows(
        anomalies=[{"ticker": "07226", "move_pct": -4.0, "severity": "medium"}],
        radar=PROXY_RADAR, mover_news={"tickers": {"07226": {"status": "ok", "items": [
            {"tier": "primary", "signal": "interrupt", "title": "盈喜"}]}}})
    row = _row(out, "07226")
    assert row["ticker"] == "07226"
    assert row["evidence"]["state"] == "near_breakout", "the index state still applies"
    assert "near_breakout" in row["triggers"]
    assert row["verdict"] == "candidate", "a proxy approach can still promote"
    assert out["candidate_count"] == 1


def test_a_name_with_its_own_radar_row_is_untouched_by_the_proxy_rule():
    """02208 covers itself, so nothing is re-attributed and the wording is bare."""
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=RADAR, mover_news=SOFT_ONLY)
    row = _row(out, "02208")
    assert row["needs"] == "站上 11.72(现距高 -4.01%)"
    assert row["evidence"]["prior_20d_high"] == 11.72
    assert "proxy_label" not in row["evidence"]


def test_the_private_proxy_marker_never_leaks_into_a_row():
    """`_proxy_label` is plumbing; `proxy_label` is the published field."""
    out = add_side.read_rows(anomalies=[], radar=PROXY_RADAR)
    for row in out["rows"]:
        assert add_side.PROXY_KEY not in row
        assert add_side.PROXY_KEY not in row["evidence"]


def test_an_own_row_beats_a_proxy_row_regardless_of_radar_order():
    """Raised by the deepseek review of #761, verified here.

    `setdefault` in one pass meant "first row wins", and the radar sorts its
    rows by `pct_from_high` — so if a ticker ever had both a row of its own and
    a proxy covering it, whose numbers it got would depend on which was nearer
    its high that minute. No universe entry hits this today (07226 and SPCH
    have no rows of their own), but attribution must not be decided by a sort
    order. Both orderings must give 07226 its own 3.9, never HSTECH's 4948.5.
    """
    own = {"label": "07226", "state": "near_breakout", "holdings": ["07226"],
           "prior_20d_high": 3.9, "pct_from_high": -6.92}
    proxy = {"label": "HSTECH", "state": "near_breakout", "holdings": ["07226"],
             "prior_20d_high": 4948.5, "pct_from_high": -4.83}
    for order in ([proxy, own], [own, proxy]):
        out = add_side.read_rows(
            anomalies=[{"ticker": "07226", "move_pct": -4.0, "severity": "medium"}],
            radar={"rows": order})
        row = _row(out, "07226")
        assert row["evidence"]["prior_20d_high"] == 3.9, order
        assert "proxy_label" not in row["evidence"], order
        assert row["needs"] == "站上 3.9(现距高 -6.92%)", order


def test_a_wait_rebreak_pullback_produces_a_logged_wait_row_not_a_drop():
    """#819: wait_rebreak (uptrend pullback) used to be dropped wholesale, so
    the desk never collected a single sample. It must now produce a `wait` row
    whose evidence carries the state — but it must NOT promote (no primary is
    even required: the promotion gate stays IN_PLAY_STATES-only)."""
    radar = {"rows": [
        {"label": "02208", "state": "wait_rebreak", "state_zh": "机会·等回踩",
         "holdings": ["02208"], "prior_20d_high": 11.72, "pct_from_high": -6.4},
    ]}
    out = add_side.read_rows(anomalies=[{"ticker": "02208", "move_pct": -6.4,
                                         "severity": "high"}], radar=radar)
    row = _row(out, "02208")
    assert row["verdict"] == "wait", "a pullback is a logged wait, never a drop"
    assert row["evidence"]["state"] == "wait_rebreak", "the state must be logged"
    assert "等回踩" in row["why"], row["why"]


def test_wait_rebreak_cannot_promote_even_with_a_primary_filing():
    """The promotion gate is IN_PLAY_STATES; a primary filing next to a
    wait_rebreak row must stay `wait` (measure first, unlock later)."""
    radar = {"rows": [
        {"label": "02208", "state": "wait_rebreak", "state_zh": "机会·等回踩",
         "holdings": ["02208"], "prior_20d_high": 11.72, "pct_from_high": -6.4},
    ]}
    out = add_side.read_rows(anomalies=[{"ticker": "02208", "move_pct": -6.4,
                                         "severity": "high"}],
                             radar=radar, mover_news=PRIMARY)
    row = _row(out, "02208")
    assert row["verdict"] == "wait"
    assert out["candidate_count"] == 0



def test_a_technical_breakout_alone_is_a_candidate():
    """#819: the 8-month bars backtest measured a positive edge for the
    breakout state alone (close > prior 20-day high, not overheated) at every
    horizon. A primary filing is no longer the promotion key for this state:
    it upgrades the wording, it is not required."""
    radar = {"rows": [
        {"label": "02208", "state": "breakout", "state_zh": "机会·突破",
         "holdings": ["02208"], "prior_20d_high": 11.72, "pct_from_high": 1.8},
    ]}
    out = add_side.read_rows(anomalies=[{"ticker": "02208", "move_pct": 6.4,
                                         "severity": "high"}], radar=radar)
    row = _row(out, "02208")
    assert row["verdict"] == "candidate"
    assert "突破" in row["why"], row["why"]
    assert row["needs"].startswith("守住 11.72"), row["needs"]
    assert out["candidate_count"] == 1


def test_a_technical_breakout_with_a_primary_filing_upgrades_the_wording():
    """Primary + breakout: same candidate, 一手公告 wording on top."""
    radar = {"rows": [
        {"label": "02208", "state": "breakout", "state_zh": "机会·突破",
         "holdings": ["02208"], "prior_20d_high": 11.72, "pct_from_high": 1.8},
    ]}
    out = add_side.read_rows(anomalies=[{"ticker": "02208", "move_pct": 6.4,
                                         "severity": "high"}],
                             radar=radar, mover_news=PRIMARY)
    row = _row(out, "02208")
    assert row["verdict"] == "candidate"
    assert "一手公告" in row["why"], row["why"]
    assert row["needs"].startswith("守住 11.72"), row["needs"]


def test_near_breakout_without_a_primary_filing_still_waits():
    """#819: only the confirmed breakout state carries the measured edge;
    near_breakout alone (no primary) must stay wait - no standalone edge."""
    out = add_side.read_rows(
        anomalies=[{"ticker": "02208", "move_pct": 6.4, "severity": "high"}],
        radar=RADAR, mover_news={"tickers": {"02208": {"status": "no_recent_filing",
                                                       "items": []}}})
    row = _row(out, "02208")
    assert row["verdict"] == "wait"
    assert out["candidate_count"] == 0
