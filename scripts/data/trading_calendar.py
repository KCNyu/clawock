#!/usr/bin/env python3
"""Trading-calendar guard for HK (HKEX) and US (NYSE/Nasdaq) markets.

Why this exists: every market cron is scheduled `* * 1-5`, which only skips
weekends. On public holidays the LLM crons still fire (burning tokens + sending
empty WeChat banners) and the fetchers still write the prior session's stale
close into *today's* snapshot — exactly the kind of cross-day / stale-price data
corruption catalogued in memory. This module is the single source of truth both
layers consult.

Holiday tables are static and hand-maintained (the local IP blocks most data
sources, and exchange calendars are published a year ahead). Update them each
December for the next year. Sources:
  HKEX: https://www.calendarlabs.com/hkex-market-holidays-2026/
  US (NYSE/Nasdaq): https://www.aarp.org/money/personal-finance/stock-market-holidays/

CLI:
  python3 trading_calendar.py hk            -> prints OPEN/CLOSED, exit 0/1
  python3 trading_calendar.py us            -> prints OPEN/CLOSED, exit 0/1
  python3 trading_calendar.py hk --session afternoon
                                            -> CLOSED on HK half-days too
  python3 trading_calendar.py us --date 2026-06-19
                                            -> check a specific date

Exit code: 0 = market open (trading day), 1 = closed. So bash guards read as:
  python3 trading_calendar.py us || exit 0   # bail on closed
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

# --- Full-day market closures (weekday ones are what matter; weekend-falling
#     entries are harmless, they're filtered as weekends anyway). ---

US_HOLIDAYS = {
    # 2026 NYSE/Nasdaq
    "2026-01-01",  # New Year's Day (Thu)
    "2026-01-19",  # Martin Luther King Jr. Day (Mon)
    "2026-02-16",  # Washington's Birthday (Mon)
    "2026-04-03",  # Good Friday (Fri)
    "2026-05-25",  # Memorial Day (Mon)
    "2026-06-19",  # Juneteenth (Fri)
    "2026-07-03",  # Independence Day observed (Fri)
    "2026-09-07",  # Labor Day (Mon)
    "2026-11-26",  # Thanksgiving (Thu)
    "2026-12-25",  # Christmas (Fri)
}

HK_HOLIDAYS = {
    # 2026 HKEX full-day closures
    "2026-01-01",  # New Year's Day (Thu)
    "2026-02-17",  # Lunar New Year (Tue)
    "2026-02-18",  # LNY 2nd day (Wed)
    "2026-02-19",  # LNY 3rd day (Thu)
    "2026-04-03",  # Good Friday (Fri)
    "2026-04-04",  # Day following Good Friday (Sat - weekend)
    "2026-04-06",  # Ching Ming / Easter Monday (Mon)
    "2026-04-07",  # Day following Easter Monday (Tue)
    "2026-05-01",  # Labour Day (Fri)
    "2026-05-25",  # Buddha's Birthday (Mon)
    "2026-06-19",  # Tuen Ng / Dragon Boat (Fri)
    "2026-07-01",  # HKSAR Establishment Day (Wed)
    "2026-09-26",  # Mid-Autumn Festival (Sat - weekend)
    "2026-10-01",  # National Day (Thu)
    "2026-10-19",  # Chung Yeung Festival (Mon)
    "2026-12-25",  # Christmas Day (Fri)
    "2026-12-26",  # Christmas observed (Sat - weekend)
}

# HK half-days: morning session only (afternoon closed). Open for the morning,
# so a trading day, but afternoon-session crons should treat them as closed.
HK_HALF_DAYS = {
    "2026-02-16",  # Lunar New Year's Eve (Mon)
    "2026-09-25",  # Day before Mid-Autumn (Fri)
    "2026-12-24",  # Christmas Eve (Thu)
    "2026-12-31",  # New Year's Eve (Thu)
}

MARKET_TZ = {"hk": "Asia/Hong_Kong", "us": "America/New_York"}
HOLIDAYS = {"hk": HK_HOLIDAYS, "us": US_HOLIDAYS}
LATEST_YEAR = 2026  # bump when tables are extended; guards warn past this


def _today_in_market(market: str) -> date:
    return datetime.now(ZoneInfo(MARKET_TZ[market])).date()


def is_trading_day(market: str, d: date | None = None, session: str = "full") -> bool:
    """True if `market` trades on date `d` (defaults to today in market TZ).

    session='afternoon' additionally returns False on HK half-days (morning-only).
    """
    market = market.lower()
    if market not in HOLIDAYS:
        raise ValueError(f"unknown market {market!r} (use 'hk' or 'us')")
    if d is None:
        d = _today_in_market(market)
    if d.weekday() >= 5:  # Sat/Sun
        return False
    iso = d.isoformat()
    if iso in HOLIDAYS[market]:
        return False
    if market == "hk" and session == "afternoon" and iso in HK_HALF_DAYS:
        return False
    return True


def closed_reason(market: str, d: date | None = None,
                  session: str = "full") -> str | None:
    """None if `market` trades; else a short Chinese reason for harness banners.

    Past the holiday-table horizon we fail OPEN (return None) — never silently
    skip a real trading day just because the table wasn't extended.
    """
    market = market.lower()
    if d is None:
        d = _today_in_market(market)
    if d.year > LATEST_YEAR:
        return None
    if d.weekday() >= 5:
        return "周末休市"
    if d.isoformat() in HOLIDAYS[market]:
        return "节假日休市"
    if market == "hk" and session == "afternoon" and d.isoformat() in HK_HALF_DAYS:
        return "半日市·午后休市"
    return None


def phase_session(market: str, phase: str | None) -> str:
    """Map a harness phase to a calendar session (HK afternoon = pm/close)."""
    if market == "hk" and phase in ("pm", "close"):
        return "afternoon"
    return "full"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="HK/US trading-calendar guard")
    p.add_argument("market", choices=["hk", "us"])
    p.add_argument("--date", help="YYYY-MM-DD (default: today in market TZ)")
    p.add_argument("--session", choices=["full", "morning", "afternoon"],
                   default="full")
    p.add_argument("--quiet", action="store_true", help="suppress OPEN/CLOSED print")
    a = p.parse_args(argv)

    d = date.fromisoformat(a.date) if a.date else _today_in_market(a.market)
    if d.year > LATEST_YEAR:
        # Fail open: don't silently skip a real trading day past the table.
        if not a.quiet:
            print(f"OPEN (warning: {a.market} holiday table only covers "
                  f"through {LATEST_YEAR}; extend trading_calendar.py)")
        return 0

    open_ = is_trading_day(a.market, d, a.session)
    if not a.quiet:
        label = "OPEN" if open_ else "CLOSED"
        sess = "" if a.session == "full" else f" {a.session}"
        print(f"{label} ({a.market.upper()}{sess} {d.isoformat()})")
    return 0 if open_ else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
