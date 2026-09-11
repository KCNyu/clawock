"""Advice the book keeps declining may stand; the harness owns evidence and rails.

kcn 2026-09-12:「我们长期不听的模型建议可以考虑有一个自适应机制」— and, asked how
the system would know he does not want to deleverage:「你怎么判断我不想执行」. The
answer these tests pin: from the book (shares unchanged on the targets, trades in
other names, buys INTO the target), never from the model.
"""
import json

from clawock.decision import packet
from clawock.decision import plans
from clawock.decision import risk
from clawock.harness import brief_postflight
from clawock.harness import brief_render


OPENED = "2026-08-01"


def _stop(pnl=-34.5, ticker="07226", leg="HK"):
    return {"breaches": [], "breach_count": 1, "hard_stop_watch": [{
        "type": "leveraged_hard_stop", "ticker": ticker, "leg": leg,
        "pnl_pct": pnl, "severity": "critical",
        "detail": f"{ticker} 浮亏 {pnl}% ≤ 硬止损线 -18%", "action": "cut",
        "required_reduction": {"kind": "full_leveraged_position",
                               "target_tickers": [ticker], "swap_to": "03033"},
    }]}


def _book(target_trades=(), other_trades=({"date": "2026-08-20", "action": "buy"},)):
    return {"portfolios": {
        "hk_stocks": {"holdings": [
            {"ticker": "07226", "shares": 6200, "trades": list(target_trades)},
        ]},
        "us_stocks": {"holdings": [
            {"ticker": "SKHY", "shares": 1, "trades": list(other_trades)},
        ]},
    }}


def _history(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text(json.dumps({"date": OPENED, "breaches": [], "hard_stop_watch": [
        {"type": "leveraged_hard_stop", "ticker": "07226", "leg": "HK"}]}) + "\n")
    return path


def _run(tmp_path, now, guardrail=None, book=None):
    return risk.reconcile_guardrail(
        guardrail or _stop(), book or _book(), path=tmp_path / "risk.json",
        history_path=_history(tmp_path), now=now)


def _adaptive(result):
    return result["records"][0]["adaptive"]


# ── evidence: what the book shows, not what the model guesses ───────────────

def test_trading_other_names_while_the_target_sits_untouched_is_a_decision(tmp_path):
    adaptive = _adaptive(_run(tmp_path, "2026-09-11T00:00:00+00:00"))
    assert adaptive["eligible"] and adaptive["may_stand"]
    assert adaptive["stance"]["stance"] == "declined"
    assert adaptive["stance"]["last_trade_elsewhere"] == "2026-08-20"


def test_buying_into_a_name_told_to_cut_is_the_strongest_vote(tmp_path):
    book = _book(target_trades=[{"date": "2026-08-12", "action": "buy"},
                                {"date": "2026-08-19", "action": "buy"}])
    stance = _adaptive(_run(tmp_path, "2026-09-11T00:00:00+00:00", book=book))["stance"]
    assert stance["stance"] == "contrary"
    assert stance["buys_on_target"] == 2 and stance["last_buy_on_target"] == "2026-08-19"


def test_no_recent_trading_at_all_is_not_a_decision(tmp_path):
    """Away is not declining: an old trade elsewhere says nothing about today."""
    book = _book(other_trades=[{"date": "2026-07-01", "action": "buy"}])
    adaptive = _adaptive(_run(tmp_path, "2026-09-11T00:00:00+00:00", book=book))
    assert not adaptive["eligible"]
    assert "stance=silent" in adaptive["not_eligible_because"]


def test_selling_the_target_means_acting_and_the_rule_stays_loud(tmp_path):
    book = _book(target_trades=[{"date": "2026-09-01", "action": "sell", "shares": 100}])
    adaptive = _adaptive(_run(tmp_path, "2026-09-11T00:00:00+00:00", book=book))
    assert not adaptive["eligible"] and "stance=acting" in adaptive["not_eligible_because"]


def test_a_month_without_any_trade_turns_it_loud_again(tmp_path):
    """Declining is judged on recent behaviour; a book gone quiet for 30 days is
    treated as someone away, and the rule goes back to being raised every day."""
    assert _adaptive(_run(tmp_path, "2026-09-11T00:00:00+00:00"))["may_stand"]
    later = _adaptive(_run(tmp_path, "2026-09-25T00:00:00+00:00"))
    assert not later["eligible"] and "stance=silent" in later["not_eligible_because"]


def test_ten_days_first(tmp_path):
    adaptive = _adaptive(_run(tmp_path, "2026-08-08T00:00:00+00:00"))
    assert not adaptive["eligible"]


def test_old_evidence_on_other_tickers_does_not_block_the_current_targets(tmp_path):
    """The US leverage breach carries July MSFU/PLTU sells as `evidence_present`
    while its targets today are RKLX/SPCH. Stance reads the CURRENT targets."""
    result = _run(tmp_path, "2026-09-11T00:00:00+00:00")
    ledger = json.loads((tmp_path / "risk.json").read_text())
    ledger["records"][0]["execution"] = {"status": "evidence_present", "evidence": [
        {"ticker": "MSFU", "date": "2026-07-30", "action": "sell"}]}
    (tmp_path / "risk.json").write_text(json.dumps(ledger))
    assert _adaptive(_run(tmp_path, "2026-09-12T00:00:00+00:00"))["eligible"]
    assert result  # first run only seeded the ledger


# ── rails the model cannot switch off ───────────────────────────────────────

def test_ten_more_points_of_loss_forces_it_back(tmp_path):
    _run(tmp_path, "2026-09-11T00:00:00+00:00", guardrail=_stop(pnl=-34.5))
    near = _adaptive(_run(tmp_path, "2026-09-12T00:00:00+00:00", guardrail=_stop(pnl=-44.0)))
    assert near["may_stand"] and near["rearm_at"] == "浮亏 ≤ -44.5%"
    deep = _adaptive(_run(tmp_path, "2026-09-13T00:00:00+00:00", guardrail=_stop(pnl=-44.6)))
    assert deep["must_reissue"] and not deep["may_stand"]
    assert "-34.5% → -44.6%" in deep["must_reason"]


def test_the_ceiling_forces_it_back_after_28_days_without_a_reissue(tmp_path):
    active = _book(other_trades=[{"date": "2026-08-20", "action": "buy"},
                                 {"date": "2026-10-01", "action": "buy"}])
    _run(tmp_path, "2026-09-11T00:00:00+00:00", book=active)
    assert _adaptive(_run(tmp_path, "2026-10-08T00:00:00+00:00", book=active))["may_stand"]
    late = _adaptive(_run(tmp_path, "2026-10-09T00:00:00+00:00", book=active))
    assert late["must_reissue"] and "28" in late["must_reason"]


# ── the choice is filed by the harness, from the validated plan ─────────────

def test_a_reissue_re_anchors_both_rails_and_a_stand_does_not(tmp_path):
    path = tmp_path / "risk.json"
    _run(tmp_path, "2026-09-11T00:00:00+00:00", guardrail=_stop(pnl=-34.5))
    hold = [{"ticker": "07226", "action": "hold_and_watch", "rationale": "维持"}]
    filed = risk.record_stances(path, "2026-09-11", hold)
    assert [row["choice"] for row in filed] == ["stand"]

    active = _book(other_trades=[{"date": "2026-09-15", "action": "buy"}])
    _run(tmp_path, "2026-09-20T00:00:00+00:00", guardrail=_stop(pnl=-40.0), book=active)
    cut = [{"ticker": "07226", "action": "cut", "rationale": "跌穿 4800，今天不同"}]
    risk.record_stances(path, "2026-09-20", cut)
    risk.record_stances(path, "2026-09-20", cut)  # a postflight re-run replaces, not appends

    record = json.loads(path.read_text())["records"][0]
    assert record["adaptive"]["last_reissued_on"] == "2026-09-20"
    assert record["adaptive"]["anchor"]["value"] == -40.0
    assert [row["date"] for row in record["adaptive"]["stances"]] == ["2026-09-11", "2026-09-20"]
    after = _adaptive(_run(tmp_path, "2026-09-21T00:00:00+00:00",
                           guardrail=_stop(pnl=-45.0), book=active))
    assert after["may_stand"], "re-anchored at -40: -45 is 5pp deeper, not 10"


# ── consumers ───────────────────────────────────────────────────────────────

def test_attach_discipline_puts_the_ledger_state_on_the_rows_the_packet_reads(tmp_path):
    guardrail = risk.attach_breach_ids(_stop())
    discipline = _run(tmp_path, "2026-09-11T00:00:00+00:00", guardrail=guardrail)
    rows = risk.attach_discipline(guardrail, discipline)["hard_stop_watch"]
    assert rows[0]["standing"]["days_open"] >= 10, "standing used to arrive empty (#1075)"
    assert rows[0]["adaptive"]["may_stand"]


def _risk_row(may_stand, kind="hard_stop"):
    return {"kind": kind, "adaptive": {"may_stand": may_stand}}


def test_a_name_whose_breaches_may_all_stand_can_hold_but_still_cannot_add():
    constraints = packet._constraints(
        6200, [_risk_row(True), _risk_row(True, kind="breach")], [], {}, {})
    assert "hold_and_watch" in constraints["allowed_actions"]
    assert "cut" in constraints["allowed_actions"]
    assert constraints["forced_action_one_of"] == []
    assert not {"add_only_on_trigger", "add_on_breakout"} & set(constraints["allowed_actions"])


def test_one_breach_that_may_not_stand_keeps_the_action_forced():
    constraints = packet._constraints(
        6200, [_risk_row(True, kind="breach"), _risk_row(False)], [], {}, {})
    assert constraints["forced_action_one_of"] == ["cut"]


def test_postflight_does_not_call_a_stood_hard_stop_unhandled(tmp_path):
    def unhandled(may_stand):
        context = {"risk_guardrail": {"breach_count": 1, "breaches": [], "hard_stop_watch": [{
            "ticker": "07226", "detail": "x", "breach_id": "risk-x",
            "adaptive": {"may_stand": may_stand}}]}}
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({"decisions": [{
            "ticker": "07226", "action": "hold_and_watch",
            "strategy_id": "risk_rebalance", "driven_by": "risk_rule"}]}))
        issues = brief_postflight.validate_plan_json(plan, context=context, normalized=False)
        return [i for i in issues if "硬止损未处理" in i and "07226" in i]

    assert unhandled(False), "the gate itself must still fire"
    assert not unhandled(True)


def test_intraday_slots_say_a_stood_cut_instead_of_re_reading_it(tmp_path):
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "risk_breaches.json").write_text(json.dumps({"schema_version": 1, "records": [{
        "status": "open", "ticker": "07226", "required_reduction": {},
        "adaptive": {"may_stand": True, "stances": [{"date": "2026-09-14", "choice": "stand"}]},
    }]}))
    ledger = tmp_path / "decisions.jsonl"
    ledger.write_text(json.dumps({
        "decision_id": "d1", "plan_date": "2026-09-11", "ticker": "07226", "leg": "HK",
        "action": "cut", "driven_by": "risk_rule", "strategy_id": "risk_rebalance",
        "execution": {"status": plans.OPEN_EXECUTION}, "evaluation": {"status": "pending"},
    }) + "\n")
    context = plans.open_decisions_context(
        today="2026-09-14", ledger=ledger, memory_dir=memory)
    assert context.get("standing_by_choice") == ["07226"]
    assert not context.get("open")


def test_the_brief_shows_evidence_choice_and_rails(tmp_path):
    guardrail = risk.attach_breach_ids(_stop())
    discipline = _run(tmp_path, "2026-09-11T00:00:00+00:00", guardrail=guardrail)
    context = {"risk_guardrail": risk.attach_discipline(guardrail, discipline),
               "risk_discipline": discipline}
    plan = {"decisions": [{"ticker": "07226", "action": "hold_and_watch"}]}
    section = brief_render.risk_section(context, plan)
    assert "长期未执行 · 自适应" in section
    assert "同期在别的票有成交（最近 2026-08-20）" in section
    assert "模型判断今天维持" in section
    assert "浮亏 ≤ -44.5%" in section and "2026-10-09" in section
