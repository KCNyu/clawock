"""One answer to "which session has finished", and it must not name today early.

Three modules used to decide this independently. Two agreed — market timezone,
17:00 local before today counts — and the third, `portfolio.integrity`, asked
`date.today()` on the *host* and counted today as already complete. So from
midnight until the market actually produced a quote, every holding still
carrying the newest real close was reported stale. The US leg's quotes arrive
around 21:30 Hong Kong time, which made that most of every trading day.

The existing integrity suite could not catch it: its fixture monkeypatches
`_last_session`, so the one thing that was wrong was stubbed out in every case.
These tests exercise the real calendar.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from clawock import sessions
from clawock.portfolio import integrity
from clawock.publish import dashboard
from clawock.decision import signals


# (market, local wall clock, what has actually finished at that moment).
# 2026-08-10 is a Monday; both markets last traded Friday the 7th.
NOT_YET_COMPLETE = [
    ("us", datetime(2026, 8, 10, 2, 0), "2026-08-07"),
    ("us", datetime(2026, 8, 10, 9, 35), "2026-08-07"),
    ("us", datetime(2026, 8, 10, 16, 30), "2026-08-07"),
    ("hk", datetime(2026, 8, 10, 2, 0), "2026-08-07"),
    ("hk", datetime(2026, 8, 10, 11, 0), "2026-08-07"),
    ("hk", datetime(2026, 8, 10, 16, 30), "2026-08-07"),
    # Only once the settling window has passed does today count.
    ("us", datetime(2026, 8, 10, 17, 0), "2026-08-10"),
    ("hk", datetime(2026, 8, 10, 17, 0), "2026-08-10"),
]


@pytest.mark.parametrize("market, wall_clock, expected", NOT_YET_COMPLETE)
def test_a_session_is_not_complete_until_its_own_market_has_settled(
        market, wall_clock, expected):
    at = wall_clock.replace(tzinfo=ZoneInfo(sessions.MARKET_TZ[market]))

    resolved = sessions.latest_completed_session(market, at)

    assert resolved.isoformat() == expected, (
        f"at {wall_clock:%H:%M} {market.upper()} local, the newest finished "
        f"session is {expected}, not {resolved}")


def test_the_three_call_sites_ask_the_same_calendar():
    """The drift guard.

    Two of these agreed by being copies of each other, which is exactly how the
    third was able to be wrong for as long as it was: nothing compared them.
    Asserted at a real instant so the check keeps meaning something as the
    calendar moves.
    """
    now = datetime.now(timezone.utc)

    from_integrity = integrity._last_session("us")
    from_dashboard = dashboard._latest_completed_session("us", sessions, now)
    from_signals = signals._latest_completed_session("us", now)

    assert from_integrity == from_dashboard.isoformat() == from_signals.isoformat(), (
        f"integrity={from_integrity} dashboard={from_dashboard} "
        f"signals={from_signals}")


def test_integrity_does_not_call_the_newest_available_close_stale(monkeypatch):
    """The false positive itself, end to end through the real gate.

    A book holding a quote dated the newest *finished* session is as fresh as it
    is possible to be. Before the fix this was reported stale for most of the
    day, and a warning that fires while nothing is wrong is the reason the real
    one goes unread.
    """
    newest = sessions.latest_completed_session("us")
    portfolio = {
        "portfolios": {
            "us_stocks": {
                "currency": "USD",
                "holdings": [{
                    "ticker": "EXMPL",
                    "shares": 10,
                    "current_price": 100.0,
                    "data_source": f"provider {newest.isoformat()}",
                }],
            }
        }
    }
    monkeypatch.setattr(
        integrity, "Path",
        lambda _unused: type("P", (), {"read_text": staticmethod(
            lambda: __import__("json").dumps(portfolio))})())

    report = integrity.check("ignored")
    staleness = [f for f in report["findings"] if f["code"] == "STALENESS"]

    assert not staleness, (
        f"a holding quoted at the newest finished session ({newest}) was "
        f"reported stale: {staleness}")


def test_integrity_still_catches_a_genuinely_old_quote(monkeypatch):
    """The other half — the gate must still bite when the quote really is old."""
    newest = sessions.latest_completed_session("us")
    stale_day = sessions.previous_trading_day("us", newest)
    portfolio = {
        "portfolios": {
            "us_stocks": {
                "currency": "USD",
                "holdings": [{
                    "ticker": "EXMPL",
                    "shares": 10,
                    "current_price": 100.0,
                    "data_source": f"provider {stale_day.isoformat()}",
                }],
            }
        }
    }
    monkeypatch.setattr(
        integrity, "Path",
        lambda _unused: type("P", (), {"read_text": staticmethod(
            lambda: __import__("json").dumps(portfolio))})())

    report = integrity.check("ignored")

    assert any(f["code"] == "STALENESS" for f in report["findings"]), (
        f"a quote from {stale_day}, one session behind {newest}, was accepted")
