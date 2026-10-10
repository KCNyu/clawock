"""Prospective windows, fixed inputs, no rewrites and separate simulation books."""
from datetime import datetime, timezone

import pytest

from clawock.decision import method_trials as mt

NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)
LATER = datetime(2026, 7, 10, tzinfo=timezone.utc)


def spec():
    return {"start_date": "2026-07-02", "end_date": "2026-07-08",
            "portfolio": {"portfolios": {"us_stocks": {"cash_usd": 1000, "holdings": []}}},
            "leg_config": {"US": {"portfolio_key": "us_stocks", "currency": "USD",
                                   "cash_key": "cash_usd", "market": "us"}},
            "observations": {"AAA": {"close": 10}}, "policy_reference": {"stance": "hold"},
            "arms": {arm: {"method": arm, "model": "test", "prompt": "frozen " + arm}
                     for arm in mt.ARMS}}


def test_register_before_start_and_freeze_every_arm(tmp_path):
    trial = mt.register(tmp_path, spec(), now=NOW)
    tid = trial["trial_id"]
    assert mt.register(tmp_path, spec(), now=NOW) == trial
    assert "policy_reference" not in mt.inputs(tmp_path, tid, "observations_only")
    assert "policy_reference" in mt.inputs(tmp_path, tid, "policy_reference")
    with pytest.raises(ValueError, match="after today's"):
        mt.register(tmp_path, spec(), now=LATER)
    response = {"status": "ok", "raw_response": "hold", "plan": {
        "date": "2026-07-02", "decisions": []}}
    first = mt.submit(tmp_path, tid, "old_policy", response, now=NOW)
    assert mt.submit(tmp_path, tid, "old_policy", response, now=NOW) == first
    with pytest.raises(ValueError, match="already exists"):
        mt.submit(tmp_path, tid, "old_policy", {**response, "raw_response": "changed"}, now=NOW)
    with pytest.raises(ValueError, match="window closed"):
        mt.submit(tmp_path, tid, "policy_reference", response, now=LATER)


def test_missing_failed_and_idle_arms_remain_in_report(tmp_path):
    tid = mt.register(tmp_path, spec(), now=NOW)["trial_id"]
    mt.submit(tmp_path, tid, "old_policy", {"status": "ok", "raw_response": "no actions",
              "plan": {"date": "2026-07-02", "decisions": []}}, now=NOW)
    mt.submit(tmp_path, tid, "observations_only", {"status": "failed",
              "raw_response": "provider unavailable"}, now=NOW)
    result = mt.replay(tmp_path, tid, now=LATER)
    assert result["arms"]["policy_reference"]["status"] == "missing"
    assert result["arms"]["observations_only"]["status"] == "failed"
    idle = result["arms"]["old_policy"]
    assert idle["simulation"]["curves"]["USD"]["net"]["followed_sim"] == 1000
    assert idle["metrics"]["USD"]["net_benefit"] == 0
    assert set(idle["metrics"]["USD"]["idle_cash"]) == {1000}
    assert result["realized_returns"] is None and result["automatic_selection"] is False
    assert result["registered_trials"] == 1
    assert not (tmp_path / "memory" / "decisions.jsonl").exists()


def test_tampered_frozen_response_is_rejected(tmp_path):
    tid = mt.register(tmp_path, spec(), now=NOW)["trial_id"]
    mt.submit(tmp_path, tid, "old_policy", {"status": "failed", "raw_response": "failed"}, now=NOW)
    path = mt._directory(tmp_path, tid) / "old_policy.json"
    path.write_text(path.read_text().replace('"failed"', '"refused"'))
    with pytest.raises(ValueError, match="response digest"):
        mt.replay(tmp_path, tid, now=LATER)


def test_three_arms_use_the_same_capital_and_completed_terminal_session(tmp_path, monkeypatch):
    from clawock.decision import ledger

    snapshot = spec()
    snapshot["end_date"] = snapshot["start_date"]
    bars = {"AAA": {"2026-07-02": {"open": 10, "high": 12, "low": 10, "close": 12}}}
    monkeypatch.setattr(ledger, "bar", lambda ticker, day: bars.get(ticker, {}).get(day))
    monkeypatch.setattr(ledger, "load_ticker_bars", lambda ticker: bars.get(ticker, {}))
    tid = mt.register(tmp_path, snapshot, now=NOW)["trial_id"]
    buy = {"ticker": "AAA", "leg": "US", "action": "add_only_on_trigger",
           "strategy_id": "tactical_entry", "condition": {"type": "open"},
           "size": {"shares": 10}}
    for arm, rows in zip(mt.ARMS, ([], [buy], [buy])):
        mt.submit(tmp_path, tid, arm, {"status": "ok", "raw_response": "frozen",
                  "plan": {"date": "2026-07-02", "decisions": rows}}, now=NOW)
    report = mt.replay(tmp_path, tid, now=LATER)
    curves = {arm: value["simulation"]["curves"]["USD"] for arm, value in report["arms"].items()}
    assert {curve["initial"]["cash"] for curve in curves.values()} == {1000}
    assert curves["old_policy"]["net"]["followed_sim"] == 1000
    assert curves["observations_only"]["net"]["followed_sim"] > 1000
    assert curves["observations_only"]["net"] == curves["policy_reference"]["net"]
    assert report["settlement_bars"] == bars
