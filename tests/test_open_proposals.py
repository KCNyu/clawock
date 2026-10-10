"""A proposal is checked three ways, and only two of them can refuse it (#2842).

kcn's objection to the old validator was that the line sat too far right: code
owned the facts, and also which names could be candidates, which actions were
allowed and what the entry had to be. A plan that chose its own entry price was
refused with the same authority as one that sold shares the book did not hold.

Pinned here:

* a departure from a registered rule — its entry, its tranche, its escalation
  list, its candidate list — is filed as written, with the rule's objection on
  the decision;
* what is false (an invented event, a price nobody observed, a receipt from the
  future) or cannot be done (no cash, no lot, an obligation in force, an
  authorisation not given) is still refused, under a code of its own channel;
* nothing rewrites the proposal to agree with the policy.
"""
from __future__ import annotations

import copy
import json

import pytest

from clawock.context import brief as brief_context
from clawock.decision import ledger as dv2
from clawock.decision import packet as packet_mod
from clawock.decision import receipts
from clawock.harness import brief_postflight, brief_render
from clawock.market_data import compute
from tests.test_brief_decision_packet import _context


def _compile(context=None):
    context = context or _context()
    return packet_mod.compile_packet(context, brief_context.compute_generation_id(context))


def _add(ticker="HK2", shares=20, price=10.5, **over):
    return {"ticker": ticker, "strategy_id": "tactical_entry", "action": "add_only_on_trigger",
            "driven_by": "technical", "evidence_event_id": None,
            "condition": {"type": "price_above", "price": price},
            "invalidation_price": 9.8, "size": {"shares": shares},
            "hypothesis": "回踩 20 日线不破，抛压出清", **over}


def _codes(plan, packet, channel=None):
    return sorted(item["code"] for item in packet_mod.review_plan(plan, packet)
                  if channel is None or item["channel"] == channel)


def _blocked(plan, packet):
    return packet_mod.validate_plan_constraints(plan, packet)


# ── the envelope is not the policy ──────────────────────────────────────────

def test_a_quiet_holding_can_be_sold_or_added_to_and_the_policy_only_objects():
    packet = _compile()
    constraints = packet["tickers"]["HK2"]["constraints"]
    # The registered policy: nothing escalated, no setup, so hold or watch.
    assert constraints["allowed_actions"] == ["hold_and_watch", "watch"]
    assert constraints["open_actions"] == [
        "hold_and_watch", "watch", "trim_on_rebound", "cut", "t_only",
        "add_only_on_trigger", "add_on_breakout"]
    assert constraints["closed_actions"] == {}

    sell = {"decisions": [{
        "ticker": "HK2", "strategy_id": "core_position", "action": "cut",
        "driven_by": "technical", "evidence_event_id": None, "size": {"shares": 100}}]}
    assert _blocked(sell, packet) == []
    assert _codes(sell, packet) == [
        "STRAT_ACTIVE_WITHOUT_CATALYST", "STRAT_SELL_WITHOUT_ESCALATED_EVENT"]


def test_an_add_at_the_plans_own_entry_is_filed_with_the_policys_objections():
    packet = _compile()
    plan = {"decisions": [_add()]}
    assert _blocked(plan, packet) == []
    assert _codes(plan, packet) == [
        "STRAT_ACTIVE_WITHOUT_CATALYST", "STRAT_ADD_OUTSIDE_POLICY",
        "STRAT_NOT_A_REGISTERED_SETUP"]
    # Two lots are inside the cash and concentration room and above the
    # registered tranche of one: an objection, not a refusal.
    two_lots = {"decisions": [_add(shares=40)]}
    assert _blocked(two_lots, packet) == []
    assert "STRAT_SIZE_ABOVE_POLICY_TRANCHE" in _codes(two_lots, packet)

    bound = packet_mod.bind_policy_review(plan, packet)
    review = bound["decisions"][0]["policy_review"]
    assert review["agrees_with_policy"] is False and len(review["objections"]) == 3
    # The proposal is exactly what was written: nothing was resized or re-priced.
    assert {k: v for k, v in bound["decisions"][0].items() if k != "policy_review"} \
        == plan["decisions"][0]
    assert plan["decisions"][0].get("policy_review") is None


def test_an_authored_review_is_replaced_not_trusted():
    packet = _compile()
    plan = {"decisions": [_add(policy_review={"agrees_with_policy": True, "objections": []})]}
    review = packet_mod.bind_policy_review(plan, packet)["decisions"][0]["policy_review"]
    assert review["agrees_with_policy"] is False


# ── what still refuses, each under its own channel ──────────────────────────

@pytest.mark.parametrize("change, code", [
    ({"size": {"shares": 21}}, "FEAS_NOT_A_BOARD_LOT"),
    ({"size": {"shares": 0}}, "FEAS_SIZE_NOT_POSITIVE_INTEGER"),
    ({"size": {"shares": 20.5}}, "FEAS_FRACTIONAL_SHARES"),
    # (0.6 × 2200 − 1100) / 0.4 = 550 of room; 550 // (11 × 20) = 2 lots.
    ({"size": {"shares": 60}}, "AUTH_EXCEEDS_ROOM"),
    ({"invalidation_price": None}, "FEAS_NO_INVALIDATION_PRICE"),
    ({"condition": {"type": "price_above", "price": None}}, "FACT_ENTRY_PRICE_MISSING"),
    ({"technical_setup_id": "made_up_setup"}, "FACT_UNKNOWN_SETUP"),
    # The quote is 11 and the trigger 10.5: 10.9 was observed by nobody.
    ({"simulated_entry_price": 10.9}, "FACT_PRICE_NOT_OBSERVED"),
    ({"driven_by": "catalyst", "evidence_event_id": "evt_fake"}, "FACT_UNKNOWN_EVENT"),
    ({"strategy_id": "risk_rebalance", "driven_by": "risk_rule"}, "AUTH_NO_SWAP_MANDATE"),
])
def test_a_false_or_infeasible_add_is_refused_with_its_code(change, code):
    packet = _compile()
    issues = _blocked({"decisions": [_add(**change)]}, packet)
    assert len(issues) == 1 and issues[0].endswith(f"[{code}]"), issues


def test_a_trigger_is_the_plans_to_choose_and_an_observed_price_is_not():
    packet = _compile()
    for stated in (10.5, 11):  # its own trigger, or the packet's quote
        assert _blocked({"decisions": [_add(simulated_entry_price=stated)]}, packet) == []
    assert _blocked({"decisions": [_add(price=10.5)]}, packet) == []
    assert _blocked({"decisions": [_add(price=12.75)]}, packet) == []


def test_the_legs_adds_together_cannot_spend_more_than_its_cash():
    packet = _compile()
    plan = {"decisions": [_add("HK2", 40), _add("00100", 40)]}
    assert packet["portfolio"]["cash_available"] == {"HK": 2000.0, "US": 0.0}
    assert _blocked(plan, packet) == []
    packet["portfolio"]["cash_available"]["HK"] = 500.0
    issues = _blocked(plan, packet)
    assert len(issues) == 1 and "FEAS_EXCEEDS_CASH" in issues[0] and "840.00" in issues[0]


def test_an_open_breach_freezes_the_add_and_leaves_the_hold_open():
    context = _context()
    context["risk_guardrail"]["breaches"] = [{
        "type": "single_name", "ticker": "HK2", "breach_id": "risk-cap",
        "required_reduction": {"target_tickers": ["HK2"], "minimum_value": 100}}]
    packet = _compile(context)
    constraints = packet["tickers"]["HK2"]["constraints"]
    assert constraints["open_actions"] == ["hold_and_watch", "watch", "trim_on_rebound", "cut"]
    assert constraints["closed_actions"]["add_only_on_trigger"]["code"] == \
        "AUTH_ADD_FROZEN_BY_BREACH"
    issues = _blocked({"decisions": [_add()]}, packet)
    assert len(issues) == 1 and "AUTH_ADD_FROZEN_BY_BREACH" in issues[0]
    assert "adds are frozen while a risk breach is open" in issues[0]


def test_an_obligation_in_force_closes_everything_else():
    packet = _compile()
    constraints = packet["tickers"]["LEVX"]["constraints"]
    assert constraints["open_actions"] == ["cut"]
    hold = {"decisions": [{"ticker": "LEVX", "action": "hold_and_watch",
                           "driven_by": "technical", "evidence_event_id": None}]}
    issues = _blocked(hold, packet)
    assert len(issues) == 1 and "AUTH_OBLIGATION_IN_FORCE" in issues[0]


def test_a_finding_cannot_be_filed_under_another_channel():
    with pytest.raises(ValueError, match="does not belong"):
        receipts.finding(receipts.STRATEGY, "FACT_UNKNOWN_EVENT", "x")
    with pytest.raises(ValueError, match="does not belong"):
        receipts.finding(receipts.FACT, "STRAT_ADD_OUTSIDE_POLICY", "x")
    with pytest.raises(ValueError, match="unknown receipt channel"):
        receipts.finding("taste", "STRAT_X", "x")
    obligation = receipts.finding(receipts.FEASIBILITY, "AUTH_OBLIGATION_IN_FORCE", "x")
    objection = receipts.finding(receipts.STRATEGY, "STRAT_ADD_OUTSIDE_POLICY", "y")
    assert receipts.blocking([obligation, objection]) == [obligation]
    assert receipts.objections([obligation, objection]) == [objection]


# ── a name the book does not hold ───────────────────────────────────────────

def _universe_context():
    context = _context()
    context["portfolio"]["portfolios"]["us_stocks"]["cash_usd"] = 500
    context["proposal_universe"] = {
        "NVDA": {"leg": "US", "close": 120.0, "session": "2026-07-27"},
        "02513": {"leg": "HK", "close": 40.0, "session": "2026-07-28"},
        "03317": {"leg": "HK", "close": 8.0, "session": "2026-07-28"},
        "OLD": {"leg": "US", "close": 5.0, "session": "2026-06-01"},
        "00100": {"leg": "HK", "close": 11.0, "session": "2026-07-28"},
    }
    context["unheld_quotes"] = {"02513": {
        "price": 41.0, "lot_size": 100, "name": "智谱", "as_of": "2026-07-28"}}
    return context


def test_an_unheld_name_with_stored_bars_can_be_proposed():
    packet = _compile(_universe_context())
    universe = packet["proposal_universe"]
    # A held name is a holding; a bar from June prices nothing today.
    assert sorted(universe) == ["02513", "03317", "NVDA"]
    assert universe["NVDA"]["facts"] == {
        "shares": 0, "current_price": 120.0, "price_basis": "last_close",
        "price_as_of": "2026-07-27"}
    assert universe["02513"]["facts"]["price_basis"] == "quote"
    assert universe["02513"]["constraints"]["lot_size"] == 100

    plan = {"decisions": [_add("NVDA", 2, 121.0, invalidation_price=112.0)]}
    assert _blocked(plan, packet) == []
    review = packet_mod.bind_policy_review(plan, packet)["decisions"][0]["policy_review"]
    # Proposable is not authorised: the entry gate is still owed, and said so.
    assert review["authorization"] == "entry_gate_required"
    assert "STRAT_ADD_OUTSIDE_POLICY" in [item["code"] for item in review["objections"]]
    assert "持仓外标的，尚未过建仓前研究闸" in receipts.review_words(review)

    summary = packet_mod.summary_view(packet)["proposal_universe"]
    assert summary["columns"] == "ticker leg price price_as_of price_basis lot_size"
    assert summary["rows"] == [
        "02513 HK 41.0 2026-07-28 quote 100",
        "03317 HK 8.0 2026-07-28 last_close unknown",
        "NVDA US 120.0 2026-07-27 last_close 1"]
    closed = packet_mod.summary_view(packet)["tickers"][0]["constraints"]["closed_actions"]
    assert all(isinstance(code, str) for code in closed.values())
    # Not a holding: no judgment row is asked of it.
    assert "NVDA" not in [row["ticker"] for row in packet_mod.judgment_template(packet)[
        "ticker_judgments"]]


def test_an_unheld_proposal_is_held_to_cash_lots_and_a_real_price():
    packet = _compile(_universe_context())
    over = _blocked({"decisions": [_add("NVDA", 5, 121.0, invalidation_price=112.0)]}, packet)
    assert len(over) == 1 and "FEAS_EXCEEDS_CASH" in over[0]
    unknown_lot = _blocked({"decisions": [_add("03317", 1000, 8.1, invalidation_price=7.5)]},
                           packet)
    assert len(unknown_lot) == 1 and "FEAS_BOARD_LOT_UNKNOWN" in unknown_lot[0]
    odd = _blocked({"decisions": [_add("02513", 30, 41.5, invalidation_price=38.0)]}, packet)
    assert len(odd) == 1 and "FEAS_NOT_A_BOARD_LOT" in odd[0]
    for nowhere in ("OLD", "ZZZZ"):
        issues = _blocked({"decisions": [_add(nowhere, 1, 5.0, invalidation_price=4.0)]}, packet)
        assert len(issues) == 1 and "FACT_TICKER_NOT_PRICEABLE" in issues[0]


def test_preflight_lists_the_unheld_names_it_can_score(tmp_path):
    from clawock.harness import brief_preflight

    def bars(ticker, closes, **extra):
        (tmp_path / f"{ticker}.json").write_text(json.dumps({
            "ticker": ticker, **extra,
            "bars": {f"2026-07-{20 + i}": {"close": c} for i, c in enumerate(closes)}}))

    bars("NVDA", [118.0, 120.0], leg="US")
    bars("00100", [10.0, 11.0], leg="HK")
    bars("GONE", [1.0], leg="US", retired=True)
    bars("EMPTY", [])
    (tmp_path / "BROKEN.json").write_text("{not json")
    book = {"portfolios": {"hk_stocks": {"holdings": [{"ticker": "00100", "shares": 100}]}}}
    assert brief_preflight.proposal_universe(book, bars_dir=tmp_path) == {
        "NVDA": {"leg": "US", "close": 120.0, "session": "2026-07-21"}}


# ── the proposal's own fields ───────────────────────────────────────────────

def test_a_proposal_keeps_its_hypothesis_method_forecast_and_alternatives():
    row = dv2.legacy_action_to_decision({
        **_add(), "method": "RKLX/RKLB 比值 20 日 z 值 + 同业相对强弱",
        "forecast": {"event": "5 个交易日内收在 11.5 上方", "probability": 0.55,
                     "horizon_sessions": 5},
        "alternatives": [{"option": "hold_and_watch", "why_not": "回踩已完成，等待无新增信息"},
                         {"option": "", "why_not": "x"}, "junk"],
        "tool_receipts": ["cr-0123456789abcdef", "cr-0123456789abcdef", "../x", 7],
    }, "2026-07-28")
    assert row["hypothesis"] == "回踩 20 日线不破，抛压出清"
    assert row["method"].startswith("RKLX/RKLB")
    assert row["forecast"] == {"event": "5 个交易日内收在 11.5 上方", "probability": 0.55,
                               "horizon_sessions": 5}
    assert row["alternatives"] == [
        {"option": "hold_and_watch", "why_not": "回踩已完成，等待无新增信息"}]
    assert row["tool_receipts"] == ["cr-0123456789abcdef"]

    bare = dv2.legacy_action_to_decision({
        "ticker": "HK2", "action": "hold_and_watch", "forecast": {"probability": 2},
        "hypothesis": "   ", "alternatives": "none"}, "2026-07-28")
    assert [bare[key] for key in ("hypothesis", "method", "forecast", "alternatives",
                                  "tool_receipts", "policy_review")] == [None] * 6


def test_a_plan_cannot_report_its_own_fill(tmp_path):
    plan = {"schema_version": 2, "date": "2026-07-28", "decisions": [
        {**_add(), "execution": {"status": "followed", "note": "已成交"}}]}
    normalized = dv2.normalize_authored_plan(plan, tmp_path / "decisions.jsonl")
    assert normalized["decisions"][0]["execution"]["status"] == "unknown"
    assert normalized["decisions"][0]["hypothesis"] == "回踩 20 日线不破，抛压出清"


# ── a cited computation has to be real, replayable and not from the future ──

def test_a_cited_receipt_must_exist_replay_and_predate_the_plan(tmp_path, monkeypatch):
    from clawock.market_data import bars as bars_store

    store = {"AAA": {"source": "fixture", "adjustment": "raw", "bars": {
        f"2026-07-{20 + i}": {"close": 10 + i} for i in range(9)}}}
    monkeypatch.setattr(bars_store, "load_bars", lambda ticker: store.get(ticker, {}))
    known = compute.evaluate('ret(close("AAA"), 3)', as_of="2026-07-27")
    later = compute.evaluate('ret(close("AAA"), 3)', as_of="2026-07-28")
    forged = {**compute.evaluate('last(close("AAA"))', as_of="2026-07-27"), "value": 99.0}
    for receipt in (known, later, forged):
        compute.save_receipt(tmp_path, receipt)

    def issues(*ids):
        return brief_postflight.tool_receipt_issues(
            [{"ticker": "AAA", "tool_receipts": list(ids)}], "2026-07-27", workspace=tmp_path)

    assert issues(known["receipt_id"]) == []
    assert issues() == []
    assert "FACT_UNKNOWN_RECEIPT" in issues("cr-ffffffffffffffff")[0]
    assert "FACT_RECEIPT_FROM_THE_FUTURE" in issues(later["receipt_id"])[0]
    assert "FACT_RECEIPT_DOES_NOT_REPLAY" in issues(forged["receipt_id"])[0]


# ── the reader sees the departure next to the call ──────────────────────────

def test_the_page_and_the_card_print_the_departure_beside_the_call():
    packet = _compile()
    plan = packet_mod.bind_policy_review({"decisions": [
        {**_add(), "confidence": 0.6, "rationale": "回踩完成"},
        {"ticker": "00100", "action": "hold_and_watch", "strategy_id": "core_position",
         "driven_by": "technical", "confidence": 0.5, "rationale": "不动"},
    ]}, packet)
    page = brief_render.judge_section(plan)
    assert "与登记策略不同" in page and "入场位由本计划自定，不对应登记形态" in page
    assert "假设" in page and "回踩 20 日线不破，抛压出清" in page
    # A call that agrees with the policy carries no such line.
    assert page.count("与登记策略不同") == 1

    card = brief_render.render_card(
        {"date": "2026-07-28", "book_totals": {}, "fx": {}, "concentration": {}},
        {"portfolio_assessment": "x"}, plan)
    lines = card.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("1. HK2"))
    assert lines[at + 1].startswith("   ↳ 与登记策略不同：")
    assert "加仓不在登记的加仓策略之内" in lines[at + 1]
    assert receipts.review_words(None) == []


def test_the_page_shows_the_judgments_disposition_as_written():
    packet = _compile()
    overlay = {"ticker_judgments": [
        {"ticker": "HK2", "disposition": "candidate", "verdict": "bullish"}]}
    row = next(row for row in packet_mod.compile_pages_projection(packet, overlay)["tickers"]
               if row["ticker"] == "HK2")
    assert row["candidate_disposition"]["deterministic_candidate"] is False
    assert row["candidate_disposition"]["effective"] == "candidate"
    assert row["candidate_disposition"]["departs_from_policy"] is True


# ── postflight: a strategy departure is not an issue ────────────────────────

def _plan_issues(tmp_path, decisions, packet):
    path = tmp_path / "2026-07-28-plan.json"
    plan = dv2.normalize_authored_plan(
        {"schema_version": 2, "date": "2026-07-28", "decisions": copy.deepcopy(decisions)},
        tmp_path / "decisions.jsonl")
    path.write_text(json.dumps(plan))
    return brief_postflight.validate_plan_json(path, _context(), packet)


def test_postflight_files_a_departing_plan_and_still_fails_a_false_one(tmp_path):
    packet = _compile()
    departing = [{**_add(), "confidence": 0.6, "regime": "neutral", "rationale": "回踩完成"}]
    issues = _plan_issues(tmp_path, departing, packet)
    assert not [issue for issue in issues if "harness" in issue or "gate" in issue], issues
    # Without a packet the pre-packet catalyst gate is the only bound there is.
    assert any("catalyst-gate" in issue
               for issue in _plan_issues(tmp_path, departing, None))

    false = [{**departing[0], "driven_by": "catalyst", "evidence_event_id": "evt_fake"}]
    issues = _plan_issues(tmp_path, false, packet)
    assert any(issue.startswith("plan.json harness:") and "FACT_UNKNOWN_EVENT" in issue
               for issue in issues)
    assert brief_postflight.categorize(issues) == "fail"


# ── the authorisations are a named, versioned set ───────────────────────────

def test_a_decision_records_the_authorisation_version_it_was_reviewed_under():
    packet = _compile()
    authorization = packet["authorization"]
    assert authorization["version"].startswith("auth-")
    assert {rule["code"] for rule in authorization["rules"]} == {
        code for code, _, _ in receipts.AUTHORIZATIONS}
    assert authorization["respond_only_breach_types"] == [
        "beta", "factor_concentration", "leveraged_exposure", "single_name"]
    review = packet_mod.bind_policy_review({"decisions": [_add()]}, packet)[
        "decisions"][0]["policy_review"]
    assert review["authorization_version"] == authorization["version"]

    # Changing a cap is a new version, not a silent edit.
    loosened = _context()
    loosened["risk_guardrail"]["caps"] = {"lev_etf_stop_pct": -25}
    assert _compile(loosened)["authorization"]["version"] != authorization["version"]
    # Every code the review can refuse an authorisation under is in the set.
    emitted = {"AUTH_OBLIGATION_IN_FORCE", "AUTH_ADD_FROZEN_BY_BREACH", "AUTH_LEVERAGED_ADD",
               "AUTH_EXCEEDS_ROOM", "AUTH_SWAP_MANDATE", "AUTH_NO_SWAP_MANDATE",
               "AUTH_OBLIGATION_SHORTFALL"}
    assert emitted == {code for code, _, _ in receipts.AUTHORIZATIONS}

