"""A prose rewrite is not a change in the trading decision."""
from clawock.decision.ledger import decision_delta


def test_decision_delta_ignores_description_but_counts_structural_changes():
    old = {"plan_date": "2026-09-24", "ticker": "CRCL",
           "strategy_id": "core_position", "action": "hold_and_watch",
           "condition": {"type": "price_above", "price": 92,
                         "valid_for_sessions": 1, "description": "old rationale"}}
    rewritten = {**old, "plan_date": "2026-09-25",
                 "condition": {**old["condition"], "description": "new rationale"}}
    assert decision_delta([old, rewritten])["changed"] == []
    repriced = {**rewritten, "condition": {**rewritten["condition"], "price": 93}}
    assert len(decision_delta([old, repriced])["changed"]) == 1
