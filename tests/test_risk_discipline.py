import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
from clawock.decision import ledger as decision_v2
from clawock.decision import risk as discipline
from clawock.harness import brief_postflight  # noqa: E402


def _guardrail(kind="hard_stop", ticker="PLTU", leg="US"):
    row = {
        "ticker": ticker,
        "leg": leg,
        "severity": "critical" if kind == "hard_stop" else "high",
        "detail": f"{ticker or leg} is over limit",
        "action": "reduce risk",
        "required_reduction": {
            "kind": "full_leveraged_position",
            "target_tickers": (
                [ticker] if ticker
                else ["PLTU"] if kind == "leveraged_exposure"
                else []
            ),
        },
    }
    if kind == "hard_stop":
        return {"breaches": [], "hard_stop_watch": [row], "breach_count": 1}
    row["type"] = kind
    return {"breaches": [row], "hard_stop_watch": [], "breach_count": 1}


def _portfolio(trades=None):
    return {
        "portfolios": {
            "hk_stocks": {"holdings": []},
            "us_stocks": {"holdings": [{
                "ticker": "PLTU", "shares": 10, "current_price": 20,
                "trades": trades or [],
            }, {
                "ticker": "PLTR", "shares": 2, "current_price": 180,
                "trades": [],
            }]},
        }
    }


def _reconcile(tmp_path, guardrail=None, now="2026-07-01T00:00:00+00:00",
               portfolio=None):
    return discipline.reconcile_guardrail(
        guardrail if guardrail is not None else _guardrail(),
        portfolio or _portfolio(),
        path=tmp_path / "risk.json",
        history_path=tmp_path / "history.jsonl",
        now=now,
    )


def test_breach_age_change_resolution_and_recurrence_are_durable(tmp_path):
    first = _reconcile(tmp_path)
    record = first["records"][0]
    breach_id = record["breach_id"]
    assert record["age_days"] == 0
    assert record["recurrence_count"] == 1

    changed = _guardrail()
    changed["hard_stop_watch"][0]["detail"] = "PLTU loss worsened"
    later = _reconcile(
        tmp_path, changed, "2026-07-03T00:00:00+00:00")
    record = later["records"][0]
    assert record["breach_id"] == breach_id
    assert record["age_days"] == 2
    assert record["last_changed_at"].startswith("2026-07-03")

    _reconcile(
        tmp_path, {"breaches": [], "hard_stop_watch": [], "breach_count": 0},
        "2026-07-04T00:00:00+00:00",
    )
    saved = discipline.load_ledger(tmp_path / "risk.json")
    assert saved["records"][0]["status"] == "resolved"

    recurrent = _reconcile(
        tmp_path, _guardrail(), "2026-07-05T00:00:00+00:00")
    record = recurrent["records"][0]
    assert record["status"] == "open"
    assert record["recurrence_count"] == 2
    assert record["age_days"] == 0


def test_acknowledgement_and_override_expiry_persist(tmp_path):
    summary = _reconcile(tmp_path, now=datetime.now(timezone.utc))
    breach_id = summary["records"][0]["breach_id"]
    path = tmp_path / "risk.json"

    discipline.acknowledge(path, breach_id, "reviewed with broker")
    overridden = discipline.grant_override(
        path, breach_id, "market closed", ttl_hours=1)
    assert overridden["status"] == "overridden"
    assert overridden["override"]["reason"] == "market closed"

    expires = datetime.fromisoformat(
        overridden["override"]["expires_at"]) + timedelta(seconds=1)
    reconciled = discipline.reconcile_guardrail(
        _guardrail(), _portfolio(), path=path,
        history_path=tmp_path / "history.jsonl", now=expires,
    )
    record = reconciled["records"][0]
    assert record["status"] == "open"
    assert record["override"]["status"] == "expired"
    assert record["acknowledgement"]["status"] == "acknowledged"


def test_broker_execution_evidence_is_reconciled_without_auto_trading(tmp_path):
    _reconcile(tmp_path)
    portfolio = _portfolio([{
        "date": "2026-07-02", "action": "sell",
        "shares": 5, "price": 21, "note": "broker fill",
    }])
    open_summary = _reconcile(
        tmp_path, now="2026-07-03T00:00:00+00:00",
        portfolio=portfolio,
    )
    record = open_summary["records"][0]
    assert record["execution"]["status"] == "evidence_present"
    assert record["execution"]["evidence"][0]["source"] == "portfolio.trades"
    # Evidence is not compliance: the breach stays open until the detector clears.
    assert record["status"] == "open"

    _reconcile(
        tmp_path, {"breaches": [], "hard_stop_watch": [], "breach_count": 0},
        "2026-07-04T00:00:00+00:00", portfolio,
    )
    saved = discipline.load_ledger(tmp_path / "risk.json")["records"][0]
    assert saved["resolution"]["reason"] == "state_compliant_after_execution"


def _decision(ticker, action, shares, strategy="risk_rebalance"):
    row = decision_v2.legacy_action_to_decision({
        "ticker": ticker,
        "strategy_id": strategy,
        "action": action,
        "condition": {"type": "open"},
        "size": {"shares": shares},
        "confidence": 0.8,
        "driven_by": "risk_rule",
    }, "2026-07-01")
    row["episode_id"] = f"ep-{ticker}-{action}"
    return row


def test_open_hard_breach_freezes_same_risk_add_but_not_exits(tmp_path):
    summary = _reconcile(tmp_path)
    add = _decision("PLTU", "add_only_on_trigger", 1)
    unpaired_underlying = _decision("PLTR", "add_only_on_trigger", 1)
    cut = _decision("PLTU", "cut", 1)

    issues = discipline.validate_exposure_increases(
        [add, unpaired_underlying, cut], summary, _portfolio())
    assert len(issues) == 2
    assert "PLTU add_only_on_trigger frozen" in issues[0]
    assert "PLTR add_only_on_trigger frozen" in issues[1]
    assert discipline.validate_exposure_increases(
        [cut], summary, _portfolio()) == []


def test_book_cluster_freezes_only_its_measured_members(tmp_path):
    guardrail = _guardrail("factor_concentration", None, "BOOK")
    guardrail["breaches"][0]["required_reduction"]["target_tickers"] = [
        "PLTU", "PLTR"
    ]
    summary = _reconcile(tmp_path, guardrail)
    in_cluster = _decision("PLTR", "add_only_on_trigger", 1)
    outside = _decision("MSFT", "add_only_on_trigger", 1)

    issues = discipline.validate_exposure_increases(
        [in_cluster, outside], summary, _portfolio()
    )

    assert len(issues) == 1
    assert "PLTR add_only_on_trigger frozen" in issues[0]


def test_proven_two_x_to_one_x_pair_is_allowed(tmp_path):
    summary = _reconcile(
        tmp_path, _guardrail("leveraged_exposure", None, "US"))
    cut = _decision("PLTU", "cut", 10)
    add = _decision("PLTR", "add_only_on_trigger", 2)

    assert discipline.validate_exposure_increases(
        [cut, add], summary, _portfolio()) == []


def test_unpriceable_swap_is_not_assumed_to_reduce_risk(tmp_path):
    summary = _reconcile(
        tmp_path, _guardrail("leveraged_exposure", None, "US"))
    cut = _decision("PLTU", "cut", 10)
    add = _decision("PLTR", "add_only_on_trigger", 200)
    portfolio = _portfolio()
    next(h for h in portfolio["portfolios"]["us_stocks"]["holdings"]
         if h["ticker"] == "PLTR").pop("current_price")

    issues = discipline.validate_exposure_increases(
        [cut, add], summary, portfolio)
    assert len(issues) == 1
    assert "PLTR add_only_on_trigger frozen" in issues[0]


def test_plan_local_override_cannot_bypass_durable_open_breach(tmp_path):
    summary = _reconcile(tmp_path)
    guardrail = discipline.attach_breach_ids(_guardrail())
    hold = _decision("PLTU", "hold_and_watch", 0)
    hold["override"] = {
        "status": "active", "reason": "typed into today's plan",
        "expires_on": "2099-01-01", "revisit_condition": "",
    }
    plan_path = tmp_path / "2026-07-01-plan.json"
    plan_path.write_text(json.dumps({
        "schema_version": 2,
        "date": "2026-07-01",
        "decisions": [hold],
    }))
    context = {
        "risk_guardrail": guardrail,
        "risk_discipline": summary,
        "portfolio": _portfolio(),
    }

    issues = brief_postflight.validate_plan_json(plan_path, context)
    assert any("杠杆硬止损未处理" in issue for issue in issues)

    record = summary["records"][0]
    record["status"] = "overridden"
    record["override"] = {
        "status": "active", "reason": "durable exception",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    issues = brief_postflight.validate_plan_json(plan_path, context)
    assert not any("杠杆硬止损未处理" in issue for issue in issues)

    record["override"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    issues = brief_postflight.validate_plan_json(plan_path, context)
    assert any("杠杆硬止损未处理" in issue for issue in issues)
