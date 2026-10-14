"""Every reader values a row before its first quote by the one rule (#2967).

`safe_io.carried_value` is the book's rule: a row's `current_value`, or its
cost until a first quote prices it. The leg totals and `TCV_SUM` already used
it. The row's own public value, the concentration card and the sector and
leverage panels read the bare leaf with `or 0`, and so did the look-through
exposure, the decision packet's invested totals, the risk book and the
guardrail's correlation clusters. A freshly bought row then counted at cost in
its leg and at 0 everywhere else.
"""
from __future__ import annotations

import pytest

from clawock import instruments
from clawock.decision import packet
from clawock.portfolio import risk
from clawock.publish import dashboard
from clawock.safe_io import carried_value

UNQUOTED = {'ticker': 'CRCL', 'shares': 4, 'cost_basis': 25.0}
QUOTED = {'ticker': 'RKLB', 'shares': 2, 'cost_basis': 10.0, 'current_price': 30.0,
          'current_value': 60.0}


def _book():
    return {'portfolios': {
        'us_stocks': {'holdings': [dict(UNQUOTED), dict(QUOTED)]},
        'hk_stocks': {'holdings': []},
    }}


@pytest.mark.parametrize('row,value', [
    (UNQUOTED, 100.0),
    (QUOTED, 60.0),
    # A row whose quote dropped keeps the value it carries.
    ({'ticker': 'X', 'shares': 2, 'cost_basis': 50.0, 'current_value': 90.0}, 90.0),
    ({'ticker': 'X', 'shares': 2}, 0),
])
def test_the_rule(row, value):
    assert carried_value(row) == value


def test_the_public_row_carries_what_its_leg_counts():
    assert dashboard.trim_holding(dict(UNQUOTED), 'USD')['current_value'] == 100.0


def test_look_through_exposure_counts_the_row():
    assert instruments.compute_lookthrough_exposure(_book())['us']['capital_value'] == 160.0


def test_the_decision_packets_invested_total_counts_the_row():
    invested, _ = packet._book_totals(_book()['portfolios'])
    assert invested['US'] == 160.0


def test_the_risk_book_keeps_the_row(monkeypatch):
    monkeypatch.setattr(risk, 'require_instrument',
                        lambda ticker: {'leverage_multiple': 1.0, 'region': 'US'})
    rows = {row['ticker']: row for row in risk.active_holdings(_book(), 'us_stocks')}
    assert rows['CRCL']['current_value'] == 100.0
