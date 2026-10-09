"""A reduction with nowhere to go is answered, not obeyed (#2839).

kcn 2026-10-10:「如果早早砍了，然后我们又没提供出新的建议反倒是会亏或者说不赚钱」.
Measured on the ledger through 2026-10-08: 335 risk sells, three with a buy leg;
the three names that were sold on such a row (PLTU / MSFU / ROBN) were not
replaced by their 1x and rose 55–80% afterwards.

Two properties are pinned here:

* a cap that names an amount and no destination (`single_name`,
  `leveraged_exposure`, `factor_concentration`, `beta`) obliges an answer — a
  trim, or a hold with its reason — and never a sell, while a hard stop and a
  regime de-lever, which name their `swap_to`, stay forced;
* a swap target the book does not hold can be written as the buy leg.
"""
from __future__ import annotations

import copy
import json

import pytest

from clawock.context import brief as brief_context
from clawock.decision import packet
from clawock.decision import risk
from clawock.harness import brief_postflight
from clawock.harness import brief_preflight


def _cap(kind="single_name", ticker="00100", **over):
    row = {
        "kind": "breach", "scope": "ticker", "breach_id": f"risk-{kind}",
        "type": kind, "enforcement": "respond", "severity": "high",
        "detail": "over the cap", "adaptive": {"eligible": False},
        "required_reduction": {"kind": "market_value", "minimum_value": 500.0},
    }
    return {**row, **over}


def _hard_stop(**over):
    return {
        "kind": "hard_stop", "scope": "ticker", "breach_id": "risk-stop",
        "type": "leveraged_hard_stop", "enforcement": "forced",
        "severity": "critical", "adaptive": {"eligible": False},
        "required_reduction": {"kind": "full_leveraged_position", "minimum_shares": 10},
        **over,
    }


def _constraints(risks):
    return packet._constraints(
        shares=100, risks=risks, actionable_ids=[],
        technical={"setups": [{"setup_id": "trend_pullback", "remaining_tranches": 1}]},
        execution={"blockers": [], "thesis_gate": "intact", "max_add_shares": 40,
                   "position_room_shares": 40})


# ── which rows oblige a sell ────────────────────────────────────────────────

def test_only_a_rule_that_names_a_destination_obliges_a_sell():
    for kind in ("single_name", "leveraged_exposure", "factor_concentration", "beta"):
        assert not risk.forces_action({"type": kind})
    for kind in ("hard_stop", "leveraged_hard_stop", "regime_delever"):
        assert risk.forces_action({"type": kind})
    # A rule nobody classified is obeyed until someone decides otherwise.
    assert risk.forces_action({"type": "a_rule_added_next_year"})
    assert risk.forces_action({})


@pytest.mark.parametrize(
    "kind", ["single_name", "leveraged_exposure", "factor_concentration", "beta"])
def test_a_cap_opens_the_hold_on_its_first_day_and_keeps_adds_shut(kind):
    constraints = _constraints([_cap(kind)])
    assert constraints["forced_action_one_of"] == []
    assert constraints["allowed_actions"] == [
        "hold_and_watch", "watch", "trim_on_rebound", "cut"]
    assert constraints["respond_to_breach_ids"] == [f"risk-{kind}"]


def test_a_hard_stop_beside_a_cap_still_forces_the_cut():
    constraints = _constraints([_cap("beta"), _hard_stop()])
    assert constraints["allowed_actions"] == ["cut"]
    assert constraints["forced_action_one_of"] == ["cut"]


def test_a_regime_delever_is_forced_from_the_guardrail_row():
    context = {
        "portfolio": {"portfolios": {"us_stocks": {"holdings": [
            {"ticker": "LEVX", "shares": 10, "current_price": 12}]}}},
        "risk_guardrail": {"breaches": [
            {"type": "regime_delever", "ticker": "LEVX", "breach_id": "risk-regime",
             "required_reduction": {"target_tickers": ["LEVX"], "swap_to": "BASE"}},
            {"type": "beta", "ticker": None, "breach_id": "risk-beta",
             "required_reduction": {"target_tickers": ["LEVX"]}},
        ]},
    }
    rows = packet._risk_map(context, {"LEVX"})["LEVX"]
    assert [(row["type"], row["enforcement"]) for row in rows] == [
        ("regime_delever", "forced"), ("beta", "respond")]
    assert _constraints(rows)["forced_action_one_of"] == ["trim_on_rebound", "cut"]
    assert _constraints(rows[1:])["forced_action_one_of"] == []


def test_the_book_table_does_not_call_a_cap_a_reduction():
    assert packet._status({}, [_cap()])["label"] == "超限"
    assert packet._status({}, [_cap(), _cap("regime_delever", enforcement="forced")])[
        "label"] == "减仓"
    assert packet._status({}, [_hard_stop()])["label"] == "止损/换1x"


# ── the answer is checked and filed ─────────────────────────────────────────

def _guardrail(kind, ticker, leg, targets):
    return risk.attach_breach_ids({"breach_count": 1, "hard_stop_watch": [], "breaches": [{
        "type": kind, "ticker": ticker, "leg": leg, "severity": "high",
        "detail": "over the cap", "action": "trim",
        "required_reduction": {"kind": "market_value", "minimum_value": 500.0,
                               "currency": "USD", "target_tickers": targets},
    }]})


def _plan_issues(tmp_path, guardrail, decisions):
    path = tmp_path / "2026-07-01-plan.json"
    path.write_text(json.dumps(
        {"schema_version": 2, "date": "2026-07-01", "decisions": decisions}))
    context = {"risk_guardrail": guardrail, "risk_discipline": {"records": []},
               "portfolio": {"portfolios": {}}}
    return [issue for issue in brief_postflight.validate_plan_json(path, context)
            if "仓位" in issue or "硬止损" in issue]


def test_a_hold_with_its_reason_answers_a_cap(tmp_path):
    cap = _guardrail("beta", None, "US", ["RKLX", "SPCH"])
    hold = {"ticker": "SPCH", "action": "hold_and_watch", "strategy_id": "risk_rebalance",
            "rationale": "β 超限来自 2x 腿；今天不减，跌破前低再减"}
    assert _plan_issues(tmp_path, cap, [hold]) == []


def test_a_cap_nobody_mentions_is_reported_as_unanswered(tmp_path):
    cap = _guardrail("beta", None, "US", ["RKLX", "SPCH"])
    elsewhere = {"ticker": "CRCL", "action": "hold_and_watch", "rationale": "无关"}
    silent = {"ticker": "SPCH", "action": "hold_and_watch", "rationale": "  "}
    for decisions in ([], [elsewhere], [silent]):
        issues = _plan_issues(tmp_path, cap, decisions)
        assert len(issues) == 1 and issues[0].startswith("仓位超限未回应: beta US")


def test_a_regime_delever_without_a_trim_is_still_unhandled(tmp_path):
    forced = _guardrail("regime_delever", "SPCH", "US", ["SPCH"])
    hold = {"ticker": "SPCH", "action": "hold_and_watch", "strategy_id": "risk_rebalance",
            "rationale": "不减"}
    issues = _plan_issues(tmp_path, forced, [hold])
    assert len(issues) == 1 and issues[0].startswith("仓位硬闸未处理: regime_delever SPCH")


def test_the_answer_to_a_cap_is_filed_from_its_first_day(tmp_path):
    cap = _guardrail("single_name", "SPCH", "US", ["SPCH"])
    book = {"portfolios": {"us_stocks": {"holdings": [{"ticker": "SPCH", "shares": 300}]}}}
    path = tmp_path / "risk.json"
    summary = risk.reconcile_guardrail(cap, book, path=path,
                                       history_path=tmp_path / "history.jsonl",
                                       now="2026-07-01T00:00:00+00:00")
    assert summary["records"][0]["adaptive"]["eligible"] is False

    hold = [{"ticker": "SPCH", "action": "hold_and_watch", "rationale": "卖了没有去处"}]
    filed = risk.record_stances(path, "2026-07-01", hold)
    assert [(row["choice"], row["why"]) for row in filed] == [("stand", "卖了没有去处")]
    trim = [{"ticker": "SPCH", "action": "trim_on_rebound", "rationale": "站上前高减"}]
    assert risk.record_stances(path, "2026-07-02", trim)[0]["choice"] == "reissue"

    # The next reconcile keeps what was filed, and the packet shows it.
    again = risk.reconcile_guardrail(cap, book, path=path,
                                     history_path=tmp_path / "history.jsonl",
                                     now="2026-07-03T00:00:00+00:00")
    view = packet._adaptive_view(again["records"][0]["adaptive"])
    assert [row["choice"] for row in view["recent_choices"]] == ["stand", "reissue"]


def test_a_forced_breach_that_is_not_eligible_files_nothing(tmp_path):
    stop = risk.attach_breach_ids({"breaches": [], "breach_count": 1, "hard_stop_watch": [{
        "type": "leveraged_hard_stop", "ticker": "RKLX", "leg": "US", "pnl_pct": -30,
        "severity": "critical", "detail": "stop", "action": "cut",
        "required_reduction": {"target_tickers": ["RKLX"], "swap_to": "RKLB"}}]})
    book = {"portfolios": {"us_stocks": {"holdings": [{"ticker": "RKLX", "shares": 10}]}}}
    path = tmp_path / "risk.json"
    risk.reconcile_guardrail(stop, book, path=path, history_path=tmp_path / "history.jsonl",
                             now="2026-07-01T00:00:00+00:00")
    hold = [{"ticker": "RKLX", "action": "hold_and_watch", "rationale": "不砍"}]
    assert risk.record_stances(path, "2026-07-01", hold) == []


# ── a target the book does not hold ─────────────────────────────────────────

def _unheld_target_context(**over):
    """LEVX is under a hard stop that prescribes BASE; the book holds no BASE."""
    return {
        "generated_at": "2026-07-28T08:00:00+08:00", "date": "2026-07-28",
        "portfolio": {"portfolios": {"us_stocks": {"holdings": [{
            "ticker": "LEVX", "shares": 10, "cost_basis": 20, "current_price": 12,
            "current_value": 120}]}}},
        "risk_guardrail": {"breaches": [], "hard_stop_watch": [{
            "ticker": "LEVX", "breach_id": "risk-hard", "detail": "hard stop",
            "action": "swap to BASE",
            "required_reduction": {"kind": "full_leveraged_position", "minimum_shares": 10,
                                   "minimum_value": 120.0, "currency": "USD",
                                   "target_tickers": ["LEVX"], "swap_to": "BASE"}}]},
        "quant_signals": {"rows": {"BASE": {
            "status": "fresh", "row_as_of": "2026-07-27", "close": 30.0}}},
        **over,
    }


def _compile(context):
    return packet.compile_packet(context, brief_context.compute_generation_id(context))


def _swap(buy_shares=4, *, group="swap-1", price=None, target="BASE", source="LEVX"):
    cut = {"ticker": source, "action": "cut", "strategy_id": "risk_rebalance",
           "driven_by": "risk_rule", "size": {"shares": 10}, "decision_group_id": "swap-1"}
    buy = {"ticker": target, "action": "add_only_on_trigger",
           "strategy_id": "risk_rebalance", "driven_by": "risk_rule",
           "size": {"shares": buy_shares}, "decision_group_id": group,
           "condition": {"type": "price_above", "price": price}}
    return {"decisions": [cut, buy]}


def test_an_unheld_swap_target_has_a_row_of_its_own():
    compiled = _compile(_unheld_target_context())
    assert "BASE" not in compiled["tickers"]
    row = compiled["swap_targets"]["BASE"]
    assert row["held"] is False
    assert row["facts"] == {"shares": 0, "current_price": 30.0,
                            "price_basis": "last_close", "price_as_of": "2026-07-27"}
    assert row["constraints"]["allowed_actions"] == ["add_only_on_trigger"]
    assert row["constraints"]["lot_size"] == 1
    assert row["constraints"]["swap_mandate"]["from_ticker"] == "LEVX"
    assert row["constraints"]["swap_mandate"]["max_value"] == 120.0
    assert [m["target_held"] for m in compiled["swap_mandates"]] == [False]
    # The model reads the summary, and a row it cannot see it cannot write.
    assert packet.summary_view(compiled)["swap_targets"] == compiled["swap_targets"]
    # Not a holding: no judgment slot is asked of it.
    assert [row["ticker"] for row in packet.judgment_template(compiled)[
        "ticker_judgments"]] == ["LEVX"]


def test_the_buy_leg_into_an_unheld_target_is_judged_by_its_mandate():
    compiled = _compile(_unheld_target_context())
    assert packet.validate_plan_constraints(_swap(4), compiled) == []
    # 5 x 30 = 150 is more exposure than the 120 the stop takes out.
    assert any("exceeds mandate max_value 120" in issue
               for issue in packet.validate_plan_constraints(_swap(5), compiled))
    assert any("must share decision_group_id" in issue
               for issue in packet.validate_plan_constraints(_swap(4, group="other"), compiled))
    hold = copy.deepcopy(_swap(4))
    hold["decisions"][1]["action"] = "hold_and_watch"
    assert any("outside harness allowed_actions" in issue
               for issue in packet.validate_plan_constraints(hold, compiled))
    stranger = _swap(4, target="NVDA")
    assert any("NVDA: ticker is outside current decision packet" in issue
               for issue in packet.validate_plan_constraints(stranger, compiled))


def test_a_stale_bar_is_not_a_price_and_the_leg_must_state_its_own():
    context = _unheld_target_context()
    context["quant_signals"]["rows"]["BASE"]["status"] = "stale"
    compiled = _compile(context)
    assert compiled["swap_targets"]["BASE"]["facts"] == {
        "shares": 0, "current_price": None, "price_basis": None, "price_as_of": None}
    assert any("has no price to hold to max_value" in issue
               for issue in packet.validate_plan_constraints(_swap(4), compiled))
    assert packet.validate_plan_constraints(_swap(4, price=29.5), compiled) == []


def _hk_context(quotes):
    context = _unheld_target_context(swap_target_quotes=quotes)
    context["portfolio"] = {"portfolios": {"hk_stocks": {"holdings": [{
        "ticker": "07226", "shares": 1000, "lot_size": 100, "current_price": 4.0,
        "current_value": 4000}]}}}
    stop = context["risk_guardrail"]["hard_stop_watch"][0]
    stop["ticker"] = "07226"
    stop["required_reduction"].update(
        minimum_shares=1000, minimum_value=4000.0, currency="HKD",
        target_tickers=["07226"], swap_to="03033")
    context["quant_signals"] = {"rows": {"03033": {
        "status": "fresh", "row_as_of": "2026-07-27", "close": 3.9}}}
    return context


def _hk_swap(buy_shares):
    plan = _swap(buy_shares, target="03033", source="07226")
    plan["decisions"][0]["size"] = {"shares": 1000}
    return plan


def test_an_unheld_hk_target_is_sized_in_the_board_lot_its_quote_carried():
    quoted = _compile(_hk_context({"03033": {
        "price": 4.0, "lot_size": 100, "name": "南方恒生科技", "as_of": "2026-07-28"}}))
    row = quoted["swap_targets"]["03033"]
    assert row["facts"]["current_price"] == 4.0 and row["facts"]["price_basis"] == "quote"
    assert row["constraints"]["lot_size"] == 100
    assert packet.validate_plan_constraints(_hk_swap(1000), quoted) == []
    assert any("not a board-lot multiple of 100" in issue
               for issue in packet.validate_plan_constraints(_hk_swap(950), quoted))


def test_one_share_is_not_assumed_to_be_a_lot():
    unquoted = _compile(_hk_context({}))
    assert unquoted["swap_targets"]["03033"]["constraints"]["lot_size"] is None
    assert any("board lot of unheld swap target is unknown" in issue
               for issue in packet.validate_plan_constraints(_hk_swap(1000), unquoted))


def test_preflight_quotes_only_the_hk_targets_the_book_does_not_hold():
    guardrail = {"breaches": [
        {"required_reduction": {"swap_to": "RKLB"}},
        {"required_reduction": {"swap_to": "02800"}},
    ], "hard_stop_watch": [{"required_reduction": {"swap_to": "03033"}},
                           {"required_reduction": {}}]}
    book = {"portfolios": {"hk_stocks": {"holdings": [
        {"ticker": "02800", "shares": 500}, {"ticker": "03033", "shares": 0}, "junk"]}}}
    asked = []

    def fetch(codes):
        asked.append(list(codes))
        return {"03033": {"c": 4.0, "lot_size": 100, "name": "南方恒生科技"}}

    assert brief_preflight.swap_target_quotes(
        guardrail, book, today="2026-07-28", fetch_hk=fetch) == {"03033": {
            "price": 4.0, "lot_size": 100, "name": "南方恒生科技", "as_of": "2026-07-28"}}
    assert asked == [["03033"]]

    def broken(codes):
        raise OSError("no route")

    assert brief_preflight.swap_target_quotes(
        guardrail, book, today="2026-07-28", fetch_hk=broken) == {}
    # Nothing to ask for: the fetcher is never reached.
    assert brief_preflight.swap_target_quotes(
        {"breaches": [], "hard_stop_watch": []}, book, today="2026-07-28",
        fetch_hk=broken) == {}


def test_a_swap_into_an_unheld_target_is_not_frozen_as_a_naked_add(tmp_path):
    stop = risk.attach_breach_ids({"breaches": [], "breach_count": 1, "hard_stop_watch": [{
        "type": "leveraged_hard_stop", "ticker": "PLTU", "leg": "US", "pnl_pct": -30,
        "severity": "critical", "detail": "stop", "action": "cut",
        "required_reduction": {"target_tickers": ["PLTU"], "swap_to": "PLTR"}}]})
    # PLTR was sold out months ago; its closed row still carries that day's price.
    book = {"portfolios": {"us_stocks": {"holdings": [
        {"ticker": "PLTU", "shares": 10, "current_price": 20.0},
        {"ticker": "PLTR", "shares": 0, "current_price": 1.0}]}}}
    summary = risk.reconcile_guardrail(stop, book, path=tmp_path / "risk.json",
                                       history_path=tmp_path / "history.jsonl",
                                       now="2026-07-01T00:00:00+00:00")
    cut = {"ticker": "PLTU", "action": "cut", "strategy_id": "risk_rebalance",
           "size": {"shares": 10}}

    def buy(shares, price):
        return {"ticker": "PLTR", "action": "add_only_on_trigger", "leg": "US",
                "size": {"shares": shares}, "condition": {"type": "price_above", "price": price}}

    # 10 x 20 x 2 = 400 of factor exposure out, 3 x 130 = 390 in.
    assert risk.validate_exposure_increases([cut, buy(3, 130.0)], summary, book) == []
    # Priced from the stale closed row, 300 shares would have passed as 300.
    assert len(risk.validate_exposure_increases([cut, buy(300, 130.0)], summary, book)) == 1
    assert len(risk.validate_exposure_increases([cut, buy(3, None)], summary, book)) == 1
