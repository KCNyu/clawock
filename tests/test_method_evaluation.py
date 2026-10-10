"""A method is judged by what it returned, under an identity it cannot edit (#2844).

The calibrator groups calls by action / driver / condition / regime and reads
wins and losses. Two things followed from that and are pinned here as fixed:

* a method that wins 40% of the time at four units and loses 60% at one was
  described as having no edge, and its mirror image as having one;
* a change of method, a refused proposal and an unexecuted call had no
  identity and no denominator, so "is the new method better" had no answer.
"""
from __future__ import annotations

import json

import pytest

from clawock import costs
from clawock.decision import ledger as dv2
from clawock.decision import method_evaluation as me
from clawock.decision import proposals, receipts


# ── payoff beside hit rate: the issue's counterexample ──────────────────────

def _calibrated(wins, n, win_size, loss_size):
    """`n` settled cuts over 20 dates, `wins` of them at +win_size."""
    row = {"action": "cut", "driven_by": "technical",
           "condition": {"type": "open"}, "regime": "neutral"}
    counts, payoffs = {}, {}
    for index in range(n):
        won = index < wins
        for key in dv2._calibration_keys(row):
            current = counts.setdefault(key, [0, 0])
            current[0] += 1
            current[1] += int(won)
            dv2._payoff_update(payoffs, key, win_size if won else -loss_size)
    dates = {f"2026-01-{day:02d}" for day in range(1, 21)}
    return dv2._calibration_prediction(row, counts, dates, f"audit-{wins}", payoffs)


def test_a_minority_of_large_wins_is_not_described_as_no_edge():
    lopsided = _calibrated(400, 1000, 4.0, 1.0)   # expectancy +1 per call
    assert lopsided["edge_supported"] is False and lopsided["edge_basis"] == "hit_rate"
    assert lopsided["sizing_status"] == "hit_rate_edge_unsupported"
    payoff = lopsided["payoff"]
    assert payoff["reading"] == "positive_expectancy" and payoff["expectancy_supported"]
    assert payoff["mean_benefit_pct"] == 1.0 and payoff["ci95"][0] > 0
    assert payoff["payoff_ratio"] == 4.0 and payoff["n"] == 1000


def test_a_majority_of_small_wins_is_not_an_economic_edge():
    mirror = _calibrated(600, 1000, 1.0, 4.0)     # expectancy −1 per call
    assert mirror["edge_supported"] is True and mirror["signal_size_multiplier"] > 0
    assert mirror["payoff"]["reading"] == "negative_expectancy"
    assert mirror["payoff"]["mean_benefit_pct"] == -1.0
    assert mirror["payoff"]["expectancy_supported"] is False


def test_too_few_episodes_read_insufficient_not_zero():
    thin = _calibrated(4, 8, 4.0, 1.0)
    assert thin["payoff"] == {
        "reading": "insufficient", "level": None, "n": 0, "mean_benefit_pct": None,
        "ci95": None, "payoff_ratio": None, "expectancy_supported": False}
    wide = _calibrated(6, 12, 5.0, 4.9)
    assert wide["payoff"]["reading"] == "inconclusive"


def test_the_stamp_a_decision_keeps_carries_both_readings():
    assert "payoff" in dv2.CALIBRATION_STAMP_FIELDS
    assert "edge_supported" in dv2.CALIBRATION_STAMP_FIELDS


# ── method identity ─────────────────────────────────────────────────────────

def test_two_methods_do_not_share_an_identity_and_one_wording_is_one_method():
    a = proposals.method_version("RKLX/RKLB 比值的 20 日 z 值")
    assert a == proposals.method_version(" RKLX/RKLB  比值的 20 日 z 值。")
    assert a != proposals.method_version("RKLX/RKLB 比值的 60 日 z 值")
    assert a.startswith("mv-") and len(a) == 15
    for absent in (None, "", "  。 ", 7):
        assert proposals.method_version(absent) == "unknown"
    assert proposals.hypothesis_id("RKLX", "x") != proposals.hypothesis_id("SPCH", "x")
    assert proposals.hypothesis_id("RKLX", " ") is None


def _decision(ticker="AAA", action="cut", day="2026-07-01", **over):
    row = dv2.legacy_action_to_decision({
        "ticker": ticker, "strategy_id": "tactical_entry", "action": action,
        "condition": {"type": "open"}, "size": {"shares": 10}, "confidence": 0.6,
        "driven_by": "technical", "regime": "neutral", "leg": "US", **over}, day)
    row["episode_id"] = f"ep-{ticker}-{day}-{action}"
    return row


def test_the_plan_cannot_name_its_own_method_version():
    row = _decision(method="20 日 z 值", method_version="mv-000000000000",
                    hypothesis="回踩不破", hypothesis_id="hyp-mine")
    assert row["method_version"] == proposals.method_version("20 日 z 值")
    assert row["hypothesis_id"] == proposals.hypothesis_id("AAA", "回踩不破")
    assert _decision()["method_version"] == "unknown"


def test_a_forecast_the_bars_can_score_keeps_its_level():
    scored = _decision(forecast={"metric": "close_above", "level": 11.5,
                                 "probability": 0.6, "horizon_sessions": 5})["forecast"]
    assert scored == {"event": None, "probability": 0.6, "horizon_sessions": 5,
                      "metric": "close_above", "level": 11.5}
    worded = _decision(forecast={"event": "财报后指引上调", "probability": 0.4,
                                 "horizon_sessions": 3, "metric": "vibes"})["forecast"]
    assert worded == {"event": "财报后指引上调", "probability": 0.4, "horizon_sessions": 3}
    assert _decision(forecast={"metric": "close_above", "probability": 0.5,
                               "horizon_sessions": 5})["forecast"] is None


# ── the immutable proposals log ─────────────────────────────────────────────

def _finding(index, channel, code):
    return receipts.finding(channel, code, "x", index=index, ticker="AAA")


def _plan(*decisions):
    return {"date": "2026-07-01", "context_generation_id": "gen-1",
            "decisions": list(decisions)}


AUTHOR = {"model": "unknown", "prompt": "sha256:abc", "code": "abc1234"}


def test_filed_refused_and_objected_proposals_are_all_recorded(tmp_path):
    plan = _plan(_decision(method="方法甲"), _decision("BBB", method="方法乙"),
                 _decision("CCC", "add_only_on_trigger"))
    findings = [_finding(1, receipts.STRATEGY, "STRAT_SELL_WITHOUT_ESCALATED_EVENT"),
                _finding(2, receipts.FACT, "FACT_UNKNOWN_EVENT")]
    fresh = proposals.record(tmp_path, plan, findings, plan_status="fail", author=AUTHOR)
    assert [(row["ticker"], row["status"], row["agrees_with_policy"]) for row in fresh] == [
        ("AAA", "filed", True), ("BBB", "filed", False), ("CCC", "refused", True)]
    assert fresh[2]["refusals"] == [{"channel": "fact", "code": "FACT_UNKNOWN_EVENT"}]
    assert fresh[1]["objections"] == ["STRAT_SELL_WITHOUT_ESCALATED_EVENT"]
    assert {row["plan_status"] for row in fresh} == {"fail"}
    assert fresh[0]["method_version"] != fresh[1]["method_version"]
    assert fresh[0]["authorship"] == AUTHOR
    assert proposals.load(tmp_path) == fresh


def test_a_rerun_appends_nothing_and_a_revision_appends_beside_the_original(tmp_path):
    original = _plan(_decision(method="方法甲", hypothesis="会跌"))
    first = proposals.record(tmp_path, original, [], plan_status="pass", author=AUTHOR)
    assert proposals.record(tmp_path, original, [], plan_status="pass", author=AUTHOR) == []

    # The outcome is in; the method is rewritten to one that would have won.
    revised = _plan({**original["decisions"][0], "method": "方法丙"})
    second = proposals.record(tmp_path, revised, [], plan_status="pass", author=AUTHOR)
    rows = proposals.load(tmp_path)
    assert len(rows) == 2 and [row["method"] for row in rows] == ["方法甲", "方法丙"]
    assert rows[0] == first[0] and rows[1] == second[0]
    assert rows[0]["decision_id"] == rows[1]["decision_id"]
    assert rows[0]["record_id"] != rows[1]["record_id"]


def test_cited_computations_are_embedded_because_the_receipt_store_is_temporary(tmp_path):
    receipt = {"receipt_id": "cr-0123456789abcdef", "kind": "compute", "value_pct": 4.2}
    plan = _plan(_decision(tool_receipts=["cr-0123456789abcdef", "cr-ffffffffffffffff"]))
    row = proposals.record(
        tmp_path, plan, [], plan_status="pass", author=AUTHOR,
        load_receipt={"cr-0123456789abcdef": receipt}.get)[0]
    assert row["tool_receipts"] == [
        receipt, {"receipt_id": "cr-ffffffffffffffff", "missing": True}]


def test_a_torn_last_line_does_not_hide_the_log(tmp_path):
    proposals.record(tmp_path, _plan(_decision()), [], plan_status="pass", author=AUTHOR)
    with proposals.log_path(tmp_path).open("a") as handle:
        handle.write('{"record_id": "prop-torn", "ticker"')
    assert len(proposals.load(tmp_path)) == 1


def test_authorship_states_what_the_harness_can_see(tmp_path, monkeypatch):
    (tmp_path / "skills" / "daily-deep-brief").mkdir(parents=True)
    (tmp_path / "skills" / "daily-deep-brief" / "SKILL.md").write_text("prompt v1")
    monkeypatch.delenv("CLAWOCK_AUTHOR_MODEL", raising=False)
    seen = proposals.authorship(tmp_path)
    assert seen["model"] == "unknown" and seen["prompt"].startswith("sha256:")
    assert proposals.authorship(tmp_path, model="minimax")["model"] == "minimax"
    monkeypatch.setenv("CLAWOCK_AUTHOR_MODEL", "runner-said")
    assert proposals.authorship(tmp_path)["model"] == "runner-said"
    (tmp_path / "skills" / "daily-deep-brief" / "SKILL.md").write_text("prompt v2")
    assert proposals.authorship(tmp_path)["prompt"] != seen["prompt"]


# ── the evaluation ──────────────────────────────────────────────────────────

FREE = costs.CostModel.free()


def _settled(ticker, day, benefit, *, method=None, agrees=None, action="cut",
             followed=None, **over):
    row = _decision(ticker, action, day, method=method, **over)
    row["evaluation"] = {"status": "settled", "triggered": True, "outcome":
                         "win" if benefit > 0 else "loss" if benefit < 0 else "flat",
                         "benefit_t1_pct": benefit, "mark_t1_session": day}
    if agrees is not None:
        row["policy_review"] = {"agrees_with_policy": agrees, "objections": []}
    if followed is not None:
        row["execution"] = {"status": "followed" if followed else "not_followed"}
    return row


def _days(count):
    return [f"2026-07-{day:02d}" for day in range(1, count + 1)]


def test_arms_separate_what_the_policy_agreed_with_from_what_it_objected_to():
    rows = []
    for index, day in enumerate(_days(14)):
        rows.append(_settled(f"A{index}", day, 2.0 if index % 2 else -1.0, agrees=True))
        rows.append(_settled(f"O{index}", day, 4.0 if index % 5 < 2 else -1.0, agrees=False))
        rows.append(_settled(f"U{index}", day, -0.5))
    report = me.evaluate(rows, [], cost_model=FREE)
    assert set(report["arms"]) == {"policy_agreed", "policy_objected", "unreviewed"}
    agreed, objected = report["arms"]["policy_agreed"], report["arms"]["policy_objected"]
    assert agreed["hit_rate"]["rate"] == 0.5 and agreed["payoff"]["mean_net_benefit_pct"] == 0.5
    # 6 wins of 14 at +4, 8 losses at −1: a minority of wins, a positive mean.
    assert objected["hit_rate"]["wins"] == 6 and objected["hit_rate"]["rate"] < 0.5
    assert objected["payoff"]["mean_net_benefit_pct"] == round((6 * 4 - 8) / 14, 4)
    assert objected["payoff"]["payoff_ratio"] == 4.0
    assert report["arms"]["unreviewed"]["payoff"]["reading"] == "negative_expectancy"
    assert "hold reference is zero by construction" in report["benefit"]
    assert report["overall"]["hit_rate"]["n"] == 42


def test_methods_are_separate_groups_with_their_own_denominators():
    rows = []
    for index, day in enumerate(_days(13)):
        rows.append(_settled(f"A{index}", day, 3.0, method="方法甲",
                             followed=True if index < 4 else None))
        rows.append(_settled(f"B{index}", day, -2.0, method="方法乙"))
    pending = _decision("ZZZ", "cut", "2026-07-20", method="方法甲")
    proposed = [
        {"action": "cut", "method_version": proposals.method_version("方法甲"),
         "status": "refused", "plan_status": "fail", "objections": []},
        {"action": "cut", "method_version": proposals.method_version("方法甲"),
         "status": "filed", "plan_status": "pass", "objections": []},
        {"action": "hold_and_watch", "method_version": "unknown", "status": "filed"},
    ]
    report = me.evaluate([*rows, pending], proposed, cost_model=FREE)
    by = {row["method"]: row for row in report["methods"]}
    assert by["方法甲"]["payoff"]["reading"] == "positive_expectancy"
    assert by["方法乙"]["payoff"]["reading"] == "negative_expectancy"
    assert by["方法甲"]["denominators"] == {
        "proposed": 2, "refused": 1, "in_unpublished_plan": 0, "filed": 14,
        "triggered": 13, "not_triggered": 0, "awaiting_trigger_or_evidence": 1,
        "settled": 13, "followed": 4, "not_followed": 0, "execution_unknown": 10}
    assert report["protocol"]["groups_compared"] == 1 + 2
    assert "promotes, demotes and sizes nothing" in report["protocol"]["note"]


def test_a_thin_group_reads_insufficient_whatever_its_mean():
    rows = [_settled(f"A{i}", day, 9.0, method="新方法") for i, day in enumerate(_days(6))]
    payoff = me.evaluate(rows, [], cost_model=FREE)["methods"][0]["payoff"]
    assert payoff["reading"] == "insufficient" and payoff["mean_net_benefit_pct"] == 9.0
    # Twelve episodes on two dates are still one or two events.
    crowded = [_settled(f"A{i}", _days(2)[i % 2], 9.0) for i in range(12)]
    assert me.evaluate(crowded, [], cost_model=FREE)["overall"]["payoff"]["reading"] \
        == "insufficient"


def test_costs_come_off_every_acted_leg():
    model = costs.CostModel(assumed_commission_bps={"us": 1.0, "hk": 3.0},
                            assumed_minimum_commission={"us": 1.0},
                            spread_bps_by_leg={"us": 4.0, "hk": 12.0}, spread_share=0.5)
    cut = _settled("AAA", "2026-07-01", 1.0)
    assert me.cost_pct(cut, model) == 0.03            # 1 bp + half of 4 bp
    assert me.cost_pct({**cut, "action": "t_only"}, model) == 0.06
    assert me.cost_pct({**cut, "leg": "HK"}, model) == 0.09
    small = {**cut, "evaluation": {**cut["evaluation"], "capital": 200.0}}
    assert me.cost_pct(small, model) == 0.52          # the 1.00 minimum on 200
    rows = [_settled(f"A{i}", day, 0.02) for i, day in enumerate(_days(13))]
    payoff = me.evaluate(rows, [], cost_model=model)["overall"]["payoff"]
    assert payoff["mean_gross_benefit_pct"] == 0.02 and payoff["mean_cost_pct"] == 0.03
    assert payoff["mean_net_benefit_pct"] == -0.01 and payoff["reading"] == "negative_expectancy"


def test_episode_costs_average_the_calls_not_their_capital():
    model = costs.CostModel(assumed_commission_bps={"us": 0},
                            assumed_minimum_commission={"us": 1},
                            spread_bps_by_leg={"us": 0})
    small = _settled("AAA", "2026-07-01", 0.3, method="A")
    large = _settled("AAA", "2026-07-01", 0.3, method="A")
    small["evaluation"]["capital"] = 100
    large["evaluation"]["capital"] = 1000
    payoff = me.evaluate([small, large], cost_model=model)["overall"]["payoff"]
    # The minimum costs 1% and 0.1%, not 1 / average(100, 1000).
    assert payoff["n"] == 1
    assert payoff["mean_cost_pct"] == 0.55
    assert payoff["mean_net_benefit_pct"] == -0.25


def test_forecasts_are_scored_on_the_close_at_their_horizon():
    closes = {("AAA", "2026-07-07"): 12.0, ("BBB", "2026-07-07"): 9.0}

    def scorer(row):
        return me.score_forecast(
            row, bar=lambda ticker, day: ({"close": closes[(ticker, day)]}
                                          if (ticker, day) in closes else None),
            sessions_from=lambda leg, day, count: [
                "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07"][:count])

    def forecast(metric, level, probability, horizon=5, **more):
        return {"metric": metric, "level": level, "probability": probability,
                "horizon_sessions": horizon, **more}

    right = _decision("AAA", forecast=forecast("close_above", 11.5, 0.8))
    wrong = _decision("BBB", forecast=forecast("close_above", 11.5, 0.8))
    assert scorer(right) == {"status": "scored", "session": "2026-07-07", "close": 12.0,
                             "outcome": 1, "brier": 0.04}
    assert scorer(wrong)["brier"] == 0.64
    worded = _decision("CCC", forecast={"event": "指引上调", "probability": 0.5,
                                        "horizon_sessions": 5})
    not_due = _decision("DDD", forecast=forecast("close_below", 5.0, 0.3))
    assert scorer(worded) == {"status": "unscoreable"} and scorer(not_due) == {"status": "pending"}
    assert scorer(_decision("EEE")) is None

    report = me.evaluate([right, wrong, worded, not_due, _decision("EEE")], [],
                         cost_model=FREE, scorer=scorer)
    assert report["overall"]["forecasts"] == {
        "stated": 4, "scored": 2, "pending": 1, "unscoreable": 1,
        "brier": 0.34, "coin_brier": 0.25, "event_rate": 0.5}


def test_the_plan_date_is_session_one_when_the_market_trades(monkeypatch):
    monkeypatch.setattr(dv2, "is_session", lambda leg, day: day != "2026-07-04")
    monkeypatch.setattr(dv2, "next_sessions", lambda leg, after, count: [
        "2026-07-02", "2026-07-03", "2026-07-06"][:count])
    assert me._sessions_from("US", "2026-07-01", 3) == [
        "2026-07-01", "2026-07-02", "2026-07-03"]
    monkeypatch.setattr(dv2, "next_sessions", lambda leg, after, count: [
        "2026-07-06", "2026-07-07"][:count])
    assert me._sessions_from("US", "2026-07-04", 2) == ["2026-07-06", "2026-07-07"]


def test_the_brief_view_keeps_readings_and_denominators():
    rows = [_settled(f"A{i}", day, 1.0, method="方法甲", agrees=True)
            for i, day in enumerate(_days(13))]
    view = me.brief_view(me.evaluate(rows, [], cost_model=FREE))
    assert set(view) == {"protocol", "overall", "arms", "methods"}
    assert view["arms"]["policy_agreed"]["payoff"]["reading"] == "positive_expectancy"
    assert view["methods"][0]["method"] == "方法甲"
    assert len(json.dumps(view, ensure_ascii=False)) < 6000


# ── postflight writes the log, including what it refused ────────────────────

def test_postflight_records_the_plan_it_reviewed(tmp_path):
    from clawock.harness import brief_postflight
    from tests.test_open_proposals import _add, _compile

    packet = _compile()
    plan = dv2.normalize_authored_plan({"schema_version": 2, "date": "2026-07-28", "decisions": [
        {**_add(), "confidence": 0.6, "method": "回踩 20 日线"},
        {**_add("00100", driven_by="catalyst", evidence_event_id="evt_fake"), "confidence": 0.6},
    ]}, tmp_path / "decisions.jsonl")
    fresh = brief_postflight.record_proposals(plan, packet, {}, "fail", workspace=tmp_path)
    assert [(row["ticker"], row["status"]) for row in fresh] == [
        ("HK2", "filed"), ("00100", "refused")]
    assert fresh[0]["agrees_with_policy"] is False and fresh[0]["objections"]
    assert fresh[1]["refusals"] == [{"channel": "fact", "code": "FACT_UNKNOWN_EVENT"}]
    assert fresh[0]["method_version"] == proposals.method_version("回踩 20 日线")
    assert brief_postflight.record_proposals(plan, packet, {}, "fail", workspace=tmp_path) == []
    assert brief_postflight.record_proposals(None, packet, {}, "fail", workspace=tmp_path) == []


def test_method_identity_preserves_math_signs():
    assert proposals.method_version("return > -1") != proposals.method_version("return > 1")
    assert proposals.method_version("A/B") != proposals.method_version("AB")


def test_changing_method_inside_one_episode_does_not_blend_returns():
    a = _settled("AAA", "2026-07-01", 5, method="A")
    b = _settled("AAA", "2026-07-01", -3, method="B")
    assert a["episode_id"] == b["episode_id"]
    result = me.evaluate([a, b], cost_model=FREE)
    assert {r["method"]: r["payoff"]["mean_net_benefit_pct"] for r in result["methods"]} == {
        "A": 5, "B": -3}
    assert result["overall"]["payoff"]["n"] == 1
    assert result["overall"]["payoff"]["mean_net_benefit_pct"] == 1
    assert result["arms"]["unreviewed"]["payoff"]["n"] == 1


def test_policy_change_does_not_duplicate_an_episode_inside_one_method():
    rows = [_settled("AAA", "2026-07-01", 5, method="A", agrees=True),
            _settled("AAA", "2026-07-01", -3, method="A", agrees=False)]
    result = me.evaluate(rows, cost_model=FREE)
    assert result["methods"][0]["payoff"]["n"] == 1
    assert result["methods"][0]["payoff"]["mean_net_benefit_pct"] == 1
    assert result["arms"]["policy_agreed"]["payoff"]["mean_net_benefit_pct"] == 5
    assert result["arms"]["policy_objected"]["payoff"]["mean_net_benefit_pct"] == -3


def test_torn_log_cannot_consume_the_next_proposal(tmp_path):
    proposals.record(tmp_path, _plan(_decision()), [], plan_status="pass", author=AUTHOR)
    path = proposals.log_path(tmp_path)
    with path.open("a") as handle:
        handle.write('{"unfinished":')
    before = path.read_bytes()
    with pytest.raises(ValueError, match="unterminated"):
        proposals.record(tmp_path, _plan(_decision("BBB")), [], plan_status="pass", author=AUTHOR)
    assert path.read_bytes() == before


def test_corrupt_interior_log_is_not_reported_as_a_smaller_denominator(tmp_path):
    proposals.record(tmp_path, _plan(_decision()), [], plan_status="pass", author=AUTHOR)
    path = proposals.log_path(tmp_path)
    path.write_text("broken record\n" + path.read_text())
    with pytest.raises(ValueError, match="corrupt proposal log"):
        proposals.load(tmp_path)


def test_absent_packet_is_unreviewed_not_policy_agreement(tmp_path):
    row = proposals.record(tmp_path, _plan(_decision()), [], plan_status="fail",
                           author=AUTHOR, reviewed=False)[0]
    assert row["agrees_with_policy"] is None
    assert me.arm_of(row) == "unreviewed"
