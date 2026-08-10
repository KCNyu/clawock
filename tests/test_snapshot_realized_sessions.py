"""A fill belongs to the session it traded in, not to the date it was typed.

`realized_as_of` decides which sells a dated snapshot reflects, and
`clawock.publish.dashboard.load_snapshots` **overrides** each snapshot's stored
realized with its answer — so this function, which had no test at all, writes the
published equity curve.

The defect (#454): a US session runs 21:30–04:00 in Hong Kong time, so a fill
reported at 01:08 HKT on a Saturday belongs to Friday's session while the ledger
stamps it with Saturday's date. Comparing that raw date against a snapshot named
for the session dropped the fill from the very session containing it, and the
published curve carried two artificial steps because of it:

    2026-06-12  us_realized 1372.88  (snapshot: 1567.23)  understated 194.35
    2026-08-07  us_realized 2180.35  (snapshot: 2220.56)  understated  40.21

Against the live book, the repair tool went from "would change 2/64 snapshots"
to 0/64 — the snapshots were right the whole time.
"""
import pytest

from clawock.portfolio.snapshots import (
    realized_as_of,
    session_date,
    snapshot_shares,
)


FRIDAY = "2026-06-12"      # a US session
SATURDAY = "2026-06-13"    # not a session in any market


def _holding(ticker, trades):
    return {"ticker": ticker, "trades": trades}


def _closed_position(ticker, sell_date, realized):
    return _holding(ticker, [
        {"date": "2026-05-01", "action": "buy", "shares": 5, "price": 80.0},
        {"date": sell_date, "action": "sell", "shares": 5, "price": 100.0,
         "realized_pnl": realized},
    ])


def test_a_weekend_stamped_us_fill_belongs_to_the_session_before_it():
    ledger = [_closed_position("RKLB", SATURDAY, 145.85)]
    snapshot = {"holdings": [{"ticker": "RKLB", "shares": 0}]}

    total, note = realized_as_of(
        ledger, FRIDAY, snapshot_shares(snapshot), market="us")

    assert total == 145.85, note

    # Without the calendar the same fill reads as belonging to a later day,
    # which is what put two artificial steps in the published equity curve.
    blind, _ = realized_as_of(ledger, FRIDAY, snapshot_shares(snapshot))
    assert blind == 0


def test_a_fill_on_a_real_session_is_not_moved():
    """Only impossible dates shift. A Thursday fill stays on Thursday, so a
    snapshot taken before that session still excludes it."""
    thursday = "2026-06-11"
    ledger = [_closed_position("RKLB", thursday, 100.0)]

    assert session_date("us", thursday) == thursday
    held_before, _ = realized_as_of(
        ledger, "2026-06-10", {"RKLB": 5}, market="us")
    assert held_before == 0


@pytest.mark.parametrize("market, day, expected", [
    ("us", SATURDAY, FRIDAY),
    ("us", "2026-08-08", "2026-08-07"),          # the PLTU fill in #454
    ("hk", SATURDAY, "2026-06-12"),
    ("us", FRIDAY, FRIDAY),                       # a session date is untouched
    (None, SATURDAY, SATURDAY),                   # no market claimed, no guess
    ("jp", SATURDAY, SATURDAY),                   # no calendar for this market
    ("us", "2021-06-12", "2021-06-12"),           # outside the holiday tables
    ("us", "not-a-date", "not-a-date"),
])
def test_session_date_only_moves_what_it_can_justify(market, day, expected):
    assert session_date(market, day) == expected


def test_an_incomplete_trade_list_still_credits_a_closed_sell():
    """RKLB records a 5-share sell with no buy beside it, so the running balance
    goes to -5. The same-day tie-break asks whether the snapshot has been drawn
    down to the post-sell level; against an impossible balance it can never be,
    and a real fully-closed sell was dropped. Shares cannot be negative, so the
    test is read at zero."""
    ledger = [_holding("RKLB", [
        {"date": SATURDAY, "action": "sell", "shares": 5, "price": 100.17,
         "realized_pnl": 145.85},
    ])]

    total, _ = realized_as_of(ledger, FRIDAY, {"RKLB": 0}, market="us")
    assert total == 145.85

    # The tie-break still means something: a snapshot that still holds the
    # position has not been drawn down, so the sell is not yet reflected.
    still_held, _ = realized_as_of(ledger, FRIDAY, {"RKLB": 5}, market="us")
    assert still_held == 0


def test_the_dashboard_asks_with_a_market():
    """The curve is only correct if the caller passes one; a build that forgets
    reverts to the defect without any test here failing."""
    import inspect

    from clawock.publish import dashboard

    source = inspect.getsource(dashboard.load_snapshots)
    assert "market=leg.key" in source, (
        "load_snapshots must resolve fill dates against the leg's calendar, or "
        "the published equity curve silently returns to raw ledger dates")
