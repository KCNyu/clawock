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
           "size": {"shares": 10}, "confidence": 0.6,
           "invalidation_price": 9, "hypothesis": "growth"}
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


def test_missing_terminal_marks_do_not_report_an_earlier_value_as_trial_payoff(tmp_path, monkeypatch):
    from clawock.decision import ledger

    snapshot = spec()
    snapshot["end_date"] = "2026-07-06"
    snapshot["portfolio"]["portfolios"]["us_stocks"]["holdings"] = [
        {"ticker": "AAA", "shares": 10}]
    bars = {"2026-07-02": {"open": 10, "high": 10, "low": 10, "close": 10}}
    monkeypatch.setattr(ledger, "bar", lambda ticker, day: bars.get(day))
    monkeypatch.setattr(ledger, "load_ticker_bars", lambda ticker: bars)
    tid = mt.register(tmp_path, snapshot, now=NOW)["trial_id"]
    mt.submit(tmp_path, tid, "old_policy", {"status": "ok", "raw_response": "hold",
              "plan": {"date": snapshot["start_date"], "decisions": []}}, now=NOW)
    result = mt.replay(tmp_path, tid, now=LATER)
    metrics = result["arms"]["old_policy"]["metrics"]["USD"]
    assert metrics["status"] == "missing_marks"
    assert metrics["missing_marks"]
    assert "net_benefit" not in metrics


@pytest.mark.parametrize("shares", [True, 3.5, float("inf")])
def test_invalid_swap_size_is_rejected_before_freezing(tmp_path, shares):
    tid = mt.register(tmp_path, spec(), now=NOW)["trial_id"]
    buy = {"ticker": "AAA", "action": "add_only_on_trigger",
           "strategy_id": "risk_rebalance", "driven_by": "risk_rule",
           "decision_group_id": "swap", "condition": {"type": "open"},
           "size": {"shares": shares}, "confidence": 0.6}
    with pytest.raises(ValueError, match="positive integer size.shares"):
        mt.submit(tmp_path, tid, "old_policy", {"status": "ok", "raw_response": "buy",
                  "plan": {"date": "2026-07-02", "decisions": [buy]}}, now=NOW)
    assert not (mt._directory(tmp_path, tid) / "old_policy.json").exists()


@pytest.mark.parametrize('action', ['add_only_on_trigger', 'cut', 'buy'])
@pytest.mark.parametrize('shares', [True, False, 3.5, 3.999999, float('inf'), '3.5'])
@pytest.mark.parametrize('size_field', ['size', 'size_shares'])
def test_authored_order_size_is_checked_before_normalization(tmp_path, action, shares, size_field):
    tid = mt.register(tmp_path, spec(), now=NOW)['trial_id']
    row = {'ticker': 'AAA', 'action': action, 'strategy_id': 'tactical_entry',
           'confidence': 0.6, 'condition': {'type': 'open'},
           'invalidation_price': 9, 'hypothesis': 'growth'}
    row[size_field] = {'shares': shares} if size_field == 'size' else shares
    with pytest.raises(ValueError, match=r'decision\[0\] requires positive integer size.shares'):
        mt.submit(tmp_path, tid, 'old_policy', {'status': 'ok', 'raw_response': 'proposal',
                  'plan': {'date': '2026-07-02', 'decisions': [row]}}, now=NOW)
    assert not (mt._directory(tmp_path, tid) / 'old_policy.json').exists()


def test_zero_share_watch_remains_non_executable(tmp_path):
    tid = mt.register(tmp_path, spec(), now=NOW)['trial_id']
    row = {'ticker': 'AAA', 'action': 'watch', 'strategy_id': 'core_position',
           'confidence': 0.6, 'condition': {'type': 'open'}, 'size': {'shares': 0}}
    frozen = mt.submit(tmp_path, tid, 'old_policy', {'status': 'ok', 'raw_response': 'watch',
                       'plan': {'date': '2026-07-02', 'decisions': [row]}}, now=NOW)
    assert frozen['plan']['decisions'][0]['size']['shares'] == 0
