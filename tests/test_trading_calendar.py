"""Guards for the package-owned hand-maintained holiday tables.

The tables cannot be generated. US observance shifts move dates around the
weekend, and HK dates come from the gazetted general holidays plus the lunar
calendar — 2027 substitutes the *4th* day of Lunar New Year because the 2nd
falls on a Sunday, which no rule in this repo could have derived.

Past its horizon the module deliberately fails OPEN, so an unextended table does
not skip a real session; it turns every public holiday into a trading day
instead. These tests pin the dates that prove the 2027 extension is real, and
the direction of the failure if it ever lapses again.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from clawock.market_data import sessions as trading_calendar


def test_calendar_implementation_and_cli_ship_in_the_product():
    assert Path(trading_calendar.__file__).relative_to(ROOT).as_posix() == (
        "src/clawock/market_data/sessions.py"
    )
    assert not (ROOT / "scripts" / "data" / "trading_calendar.py").exists()
    result = subprocess.run(
        [sys.executable, "-m", "clawock", "calendar", "us", "--date", "2026-06-19"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 1
    assert result.stdout.strip() == "CLOSED (US 2026-06-19)"


# --------------------------------------------------------------------------
# 2027 — the year this suite was written to land
# --------------------------------------------------------------------------

CLOSED_2027 = [
    # (date, market, what it is)
    ("2027-01-01", "us", "New Year's Day"),
    ("2027-01-01", "hk", "New Year's Day"),
    ("2027-02-08", "hk", "3rd day of Lunar New Year"),
    ("2027-02-09", "hk", "4th day of LNY, substituted for the Sunday 2nd day"),
    ("2027-03-26", "us", "Good Friday"),
    ("2027-03-26", "hk", "Good Friday"),
    ("2027-06-18", "us", "Juneteenth observed — 19 Jun is a Saturday"),
    ("2027-07-01", "hk", "HKSAR Establishment Day"),
    ("2027-07-05", "us", "Independence Day observed — 4 Jul is a Sunday"),
    ("2027-09-16", "hk", "day following Mid-Autumn Festival"),
    ("2027-10-01", "hk", "National Day"),
    ("2027-12-24", "us", "Christmas observed — 25 Dec is a Saturday"),
    ("2027-12-27", "hk", "first weekday after Christmas"),
]


@pytest.mark.parametrize("iso,market,what", CLOSED_2027,
                         ids=[f"{m}-{d}" for d, m, _ in CLOSED_2027])
def test_known_2027_holiday_is_closed(iso, market, what):
    assert not trading_calendar.is_trading_day(market, date.fromisoformat(iso)), what


def test_the_two_markets_do_not_share_a_calendar():
    """A single merged table would close each market on the other's holidays."""
    # HK trades through US Independence Day and Thanksgiving.
    assert trading_calendar.is_trading_day("hk", date(2027, 7, 5))
    assert trading_calendar.is_trading_day("hk", date(2027, 11, 25))
    # The US trades through Ching Ming, Tuen Ng and National Day.
    assert trading_calendar.is_trading_day("us", date(2027, 4, 5))
    assert trading_calendar.is_trading_day("us", date(2027, 6, 9))
    assert trading_calendar.is_trading_day("us", date(2027, 10, 1))


def test_us_christmas_eve_is_shut_while_hk_trades_the_morning():
    """25 Dec 2027 is a Saturday: the US observes on Friday, HK does not."""
    eve = date(2027, 12, 24)
    assert not trading_calendar.is_trading_day("us", eve)
    assert trading_calendar.is_trading_day("hk", eve)
    assert not trading_calendar.is_trading_day("hk", eve, session="afternoon")


@pytest.mark.parametrize("iso,what", [
    ("2027-02-05", "Lunar New Year's Eve"),
    ("2027-12-24", "Christmas Eve"),
    ("2027-12-31", "New Year's Eve"),
])
def test_2027_hk_half_days_trade_the_morning_only(iso, what):
    d = date.fromisoformat(iso)
    assert trading_calendar.is_trading_day("hk", d), f"{what}: morning is open"
    assert not trading_calendar.is_trading_day("hk", d, session="afternoon"), what
    assert trading_calendar.closed_reason("hk", d, session="afternoon") == "半日市·午后休市"


@pytest.mark.parametrize("festival,holiday", [
    ("2026-09-25", "2026-09-26"),
    ("2027-09-15", "2027-09-16"),
])
def test_mid_autumn_trades_a_full_day_and_the_day_after_is_closed(festival, holiday):
    """HKEX Rule 501 does not make Mid-Autumn Festival day a half-day."""
    festival_day = date.fromisoformat(festival)
    assert trading_calendar.is_trading_day("hk", festival_day)
    assert trading_calendar.is_trading_day("hk", festival_day, session="afternoon")
    assert trading_calendar.closed_reason(
        "hk", festival_day, session="afternoon"
    ) is None
    # 2026's gazetted holiday falls on Saturday, so behavior alone would only
    # prove the weekend branch. Pin both concrete holiday-table entries too.
    assert holiday in trading_calendar.HK_HOLIDAYS
    assert not trading_calendar.is_trading_day("hk", date.fromisoformat(holiday))


@pytest.mark.parametrize("iso", ["2026-09-25", "2027-09-15"])
@pytest.mark.parametrize("phase", ["pm", "close"])
def test_mid_autumn_keeps_hk_pm_and_close_report_gates_open(iso, phase):
    d = date.fromisoformat(iso)
    session = trading_calendar.phase_session("hk", phase)
    assert session == "afternoon"
    assert trading_calendar.closed_reason("hk", d, session=session) is None


def test_an_ordinary_2027_weekday_still_trades():
    """A table that closed too much would be caught by nothing else here."""
    for market in ("hk", "us"):
        assert trading_calendar.is_trading_day(market, date(2027, 3, 3))


def test_previous_us_session_skips_weekend_and_exchange_holiday():
    assert trading_calendar.previous_trading_day(
        "us", date(2026, 7, 27)
    ) == date(2026, 7, 24)
    assert trading_calendar.previous_trading_day(
        "us", date(2026, 9, 8)
    ) == date(2026, 9, 4)


# --------------------------------------------------------------------------
# coverage + the deliberate fail-open past the horizon
# --------------------------------------------------------------------------


def test_coverage_reports_both_markets_through_2027():
    coverage = trading_calendar.coverage(today=date(2026, 12, 1))
    for market in ("hk", "us"):
        assert 2027 in coverage[market]["years"]
        assert coverage[market]["covers_next_year"], market


def test_latest_year_matches_the_tables():
    """LATEST_YEAR is what the guards read; tables and horizon must agree.

    A table extended without bumping the constant is invisible — `closed_reason`
    returns None for any date past LATEST_YEAR before it ever looks at the set.
    """
    for market in ("hk", "us"):
        assert max(trading_calendar.covered_years(market)) == trading_calendar.LATEST_YEAR


def test_past_the_horizon_the_calendar_fails_open():
    """The point of the deadline: never skip a real session over a stale table."""
    beyond = date(trading_calendar.LATEST_YEAR + 1, 1, 1)
    assert trading_calendar.closed_reason("hk", beyond) is None
    assert trading_calendar.closed_reason("us", beyond) is None


def test_weekend_entries_are_harmless_but_kept():
    """Gazetted holidays that land on a weekend stay in the table as a record;
    they must not be mistaken for the reason the market is shut."""
    saturday = date(2027, 2, 6)  # Lunar New Year's Day
    assert saturday.weekday() == 5
    assert trading_calendar.closed_reason("hk", saturday) == "周末休市"
