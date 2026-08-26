"""A breach nobody decided about must not read as a breach nobody saw (#1075).

`memory/risk_breaches.json` on 2026-08-26: three hard stops open 42 days, all
`unacknowledged` / `override: none` / `execution: pending`. The ledger's own
vocabulary said "nobody has looked at this". What had actually happened is that
somebody looked every day and chose not to act — a decision the schema has a
field for (`override`) that had never once been used.
"""
from __future__ import annotations

import pytest

risk = pytest.importorskip("clawock.decision.risk")


def _record(age, *, ack="unacknowledged", override="none", execution="pending"):
    return {
        "age_days": age,
        "acknowledgement": {"status": ack},
        "override": {"status": override},
        "execution": {"status": execution},
    }


def test_a_breach_standing_past_the_threshold_is_overdue():
    standing = risk._standing(_record(42))
    assert standing["decision_overdue"] is True
    assert standing["undecided"] is True
    assert standing["days_open"] == 42
    assert standing["closes_with"] == ["execute", "acknowledge", "override"]


def test_a_fresh_breach_is_not_overdue():
    """An ordinary execution delay — a weekend, a level not yet reached."""
    assert risk._standing(_record(3))["decision_overdue"] is False


@pytest.mark.parametrize("field, value", [
    ("ack", "acknowledged"),
    ("override", "active"),
    ("execution", "confirmed"),
])
def test_any_of_the_three_exits_closes_it(field, value):
    """All three are real decisions; the ledger must accept any of them.

    An override in particular: declining on purpose, with a reason, is what was
    actually happening for six weeks and the ledger had no way to say it.
    """
    standing = risk._standing(_record(90, **{field: value}))
    assert standing["undecided"] is False
    assert standing["decision_overdue"] is False


def test_the_threshold_is_long_enough_not_to_fire_on_normal_delay():
    assert risk.STANDING_DECISION_DAYS >= 5, (
        "a gate that fires over a long weekend is a gate nobody reads")
    assert risk._standing(_record(risk.STANDING_DECISION_DAYS - 1))[
        "decision_overdue"] is False
    assert risk._standing(_record(risk.STANDING_DECISION_DAYS))[
        "decision_overdue"] is True


def test_the_plan_writer_sees_it(monkeypatch):
    """The flag is useless in a file nobody reads at plan time."""
    packet = pytest.importorskip("clawock.decision.packet")
    guardrail = {"hard_stop_watch": [{
        "ticker": "07226", "breach_id": "risk-1", "severity": "critical",
        "detail": "浮亏 -26%", "action": "换仓 03033",
        "standing": {"decision_overdue": True, "days_open": 42},
        "required_reduction": {"swap_to": "03033", "minimum_value": 1.0,
                               "currency": "HKD"},
    }]}
    rows = packet._risk_map({"risk_guardrail": guardrail}, {"07226"})
    assert rows["07226"][0]["standing"]["decision_overdue"] is True
