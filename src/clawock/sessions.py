"""Trading-calendar guard for HK (HKEX) and US (NYSE/Nasdaq) markets.

Why this exists: every market cron is scheduled `* * 1-5`, which only skips
weekends. On public holidays the LLM crons still fire (burning tokens + sending
empty WeChat banners) and the fetchers still write the prior session's stale
close into *today's* snapshot — exactly the kind of cross-day / stale-price data
corruption catalogued in memory. This module is the single source of truth both
layers consult.

Holiday tables are static and hand-maintained (the local IP blocks most data
sources, and exchange calendars are published a year ahead). Extend them before
the covered year runs out; `system_check` warns from October and goes critical
once the current year is uncovered.

US dates are rule-based but must still be read off the exchange calendar: the
Saturday/Sunday observance shifts are what move them (2027 has two — Juneteenth
back to Fri 18 Jun, Christmas back to Fri 24 Dec — and one forward, Independence
Day to Mon 5 Jul). HK dates depend on the gazetted general holidays and the
lunar calendar and cannot be computed at all: 2027 substitutes the 4th day of
Lunar New Year because the 2nd falls on a Sunday.

Sources (authoritative, re-checked 2026-07-27):
  US (NYSE/Nasdaq) 2025-2027 holiday and early-closings calendar:
    https://ir.theice.com/press/news-details/2024/NYSE-Group-Announces-2025-2026-and-2027-Holiday-and-Early-Closings-Calendar/default.aspx
  HK general holidays, gazetted:
    https://www.gov.hk/en/about/abouthk/holiday/2027.htm
  HKEX Rule 501 half-day sessions (eves of LNY/Christmas/New Year only):
    https://www.hkex.com.hk/-/media/hkex-market/services/trading-hours-and-severe-weather-arrangements/severe-weather-arrangements/trading/chap-5_eng
  HKEX 2027 holiday/half-day circular (pins the three concrete half-days):
    https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2026/MO_DT_133_26_e1.pdf

CLI:
  clawock calendar hk                       -> prints OPEN/CLOSED, exit 0/1
  clawock calendar us                       -> prints OPEN/CLOSED, exit 0/1
  clawock calendar hk --session afternoon
                                            -> CLOSED on HK half-days too
  clawock calendar us --date 2026-06-19
                                            -> check a specific date

Exit code: 0 = market open (trading day), 1 = closed. So bash guards read as:
  clawock calendar us || exit 0              # bail on closed
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta
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

    # 2027 NYSE/Nasdaq — NYSE Group calendar (see module docstring).
    "2027-01-01",  # New Year's Day (Fri)
    "2027-01-18",  # Martin Luther King Jr. Day (Mon)
    "2027-02-15",  # Washington's Birthday (Mon)
    "2027-03-26",  # Good Friday (Fri)
    "2027-05-31",  # Memorial Day (Mon)
    "2027-06-18",  # Juneteenth observed (Fri; 19 Jun is a Sat)
    "2027-07-05",  # Independence Day observed (Mon; 4 Jul is a Sun)
    "2027-09-06",  # Labor Day (Mon)
    "2027-11-25",  # Thanksgiving (Thu)
    "2027-12-24",  # Christmas observed (Fri; 25 Dec is a Sat)
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
    "2026-09-26",  # Day following Mid-Autumn Festival (Sat - weekend)
    "2026-10-01",  # National Day (Thu)
    "2026-10-19",  # Chung Yeung Festival (Mon)
    "2026-12-25",  # Christmas Day (Fri)
    "2026-12-26",  # Christmas observed (Sat - weekend)

    # 2027 HKEX full-day closures — gazetted general holidays (see docstring).
    "2027-01-01",  # New Year's Day (Fri)
    "2027-02-06",  # Lunar New Year's Day (Sat - weekend)
    "2027-02-08",  # LNY 3rd day (Mon)
    "2027-02-09",  # LNY 4th day (Tue) — substitutes the 2nd day, which is a Sun
    "2027-03-26",  # Good Friday (Fri)
    "2027-03-27",  # Day following Good Friday (Sat - weekend)
    "2027-03-29",  # Easter Monday (Mon)
    "2027-04-05",  # Ching Ming Festival (Mon)
    "2027-05-01",  # Labour Day (Sat - weekend)
    "2027-05-13",  # Buddha's Birthday (Thu)
    "2027-06-09",  # Tuen Ng / Dragon Boat (Wed)
    "2027-07-01",  # HKSAR Establishment Day (Thu)
    "2027-09-16",  # Day following Mid-Autumn Festival (Thu)
    "2027-10-01",  # National Day (Fri)
    "2027-10-08",  # Chung Yeung Festival (Fri)
    "2027-12-25",  # Christmas Day (Sat - weekend)
    "2027-12-27",  # First weekday after Christmas (Mon)
}

# HK half-days: morning session only (afternoon closed). Open for the morning,
# so a trading day, but afternoon-session crons should treat them as closed.
HK_HALF_DAYS = {
    "2026-02-16",  # Lunar New Year's Eve (Mon)
    "2026-12-24",  # Christmas Eve (Thu)
    "2026-12-31",  # New Year's Eve (Thu)

    # 2027
    "2027-02-05",  # Lunar New Year's Eve (Fri)
    "2027-12-24",  # Christmas Eve (Fri) — US is shut, HK trades the morning
    "2027-12-31",  # New Year's Eve (Fri)
}

MARKET_TZ = {"hk": "Asia/Hong_Kong", "us": "America/New_York"}
HOLIDAYS = {"hk": HK_HOLIDAYS, "us": US_HOLIDAYS}
LATEST_YEAR = 2027  # bump when tables are extended; guards warn past this


def _today_in_market(market: str) -> date:
    return datetime.now(ZoneInfo(MARKET_TZ[market])).date()


def covered_years(market: str) -> set[int]:
    """Years the hand-maintained holiday table actually has data for."""
    market = market.lower()
    if market not in HOLIDAYS:
        raise ValueError(f"unknown market {market!r} (use 'hk' or 'us')")
    return {int(day[:4]) for day in HOLIDAYS[market]}


def coverage(today: date | None = None) -> dict:
    """Calendar coverage per market, for the pre-push and CI gates."""
    today = today or date.today()
    out = {}
    for market in HOLIDAYS:
        years = covered_years(market)
        out[market] = {
            "years": sorted(years),
            "covers_current_year": today.year in years,
            "covers_next_year": (today.year + 1) in years,
        }
    return out


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


#: How long after midnight, in market-local time, a session is treated as
#: finished. Both exchanges close at 16:00 local; the extra hour is for the
#: settling quotes to arrive, so that "the session ended" never gets read as
#: "today's prices are in the book" while they are still landing.
SESSION_SETTLED_HOUR = 17


def latest_completed_session(market: str, at: datetime | None = None) -> date | None:
    """Newest trading session that has conservatively finished in market time.

    The one place this is decided. It used to be decided in three, and the odd
    one out was load-bearing: `portfolio.integrity` asked `date.today()` — the
    *host's* date, and counting today as complete — so from midnight until the
    market actually produced a quote, every holding still carrying the newest
    real close was flagged stale. For the US leg, whose quotes only arrive
    around 21:30 Hong Kong time, that was most of every trading day. A staleness
    warning that fires while nothing is wrong is not a conservative gate; it is
    the reason a real one goes unread.

    Returns None only if no trading day is found within a fortnight, which means
    the holiday table is broken rather than that the market is quiet.
    """
    market = market.lower()
    if market not in MARKET_TZ:
        raise ValueError(f"unknown market {market!r} (use 'hk' or 'us')")
    tz = ZoneInfo(MARKET_TZ[market])
    now = at.astimezone(tz) if at else datetime.now(tz)
    probe = now.date() if now.hour >= SESSION_SETTLED_HOUR else now.date() - timedelta(days=1)
    for _ in range(14):
        if is_trading_day(market, probe):
            return probe
        probe -= timedelta(days=1)
    return None


def previous_trading_day(market: str, d: date) -> date:
    """Most recent trading day strictly before ``d``."""
    probe = d - timedelta(days=1)
    for _ in range(14):
        if is_trading_day(market, probe):
            return probe
        probe -= timedelta(days=1)
    raise ValueError(f"no {market} trading day found before {d}")


#: Regular-hours trading windows in market-local time. HK breaks for lunch; a
#: half day is the morning window alone (`HK_HALF_DAYS`). Pre/post-market is
#: deliberately NOT a session: every consumer of this predicate is asking "is
#: today's bar still being written", and an extended-hours print does not move
#: the day range these gates are built on.
SESSION_WINDOWS = {
    "hk": ((time(9, 30), time(12, 0)), (time(13, 0), time(16, 0))),
    "us": ((time(9, 30), time(16, 0)),),
}


def in_session(market: str, at: datetime | None = None) -> bool:
    """Is `market` trading RIGHT NOW — calendar day AND clock.

    `closed_reason` answers a different question: whether the market trades on
    a given DATE. Reading it as "is it open" is how `compute_t0_setups` came to
    enrich US holdings from Hong Kong's afternoon: on any weekday
    `closed_reason("us")` is None, so at 15:33 HKT — six hours before the US
    open — the US rows were built from the previous session's close and filed
    with today's `as_of`, graded "现价在当日区间 84% 高位" off a bar that had
    closed the day before.

    Past the holiday table's horizon `closed_reason` fails OPEN, and so does
    this: an unextended table must never make a real trading day look shut.
    """
    market = market.lower()
    if market not in SESSION_WINDOWS:
        raise ValueError(f"unknown market {market!r} (use 'hk' or 'us')")
    tz = ZoneInfo(MARKET_TZ[market])
    now = at.astimezone(tz) if at else datetime.now(tz)
    session = "afternoon" if market == "hk" else "full"
    if closed_reason(market, now.date(), session=session) is not None:
        # A HK half day is shut in the afternoon but open in the morning, so a
        # blanket False here would call 11:00 on a half day closed.
        if not (market == "hk" and now.date().isoformat() in HK_HALF_DAYS):
            return False
    windows = SESSION_WINDOWS[market]
    if market == "hk" and now.date().isoformat() in HK_HALF_DAYS:
        windows = windows[:1]
    clock = now.time()
    return any(start <= clock < end for start, end in windows)


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
                  f"through {LATEST_YEAR}; extend clawock.sessions)")
        return 0

    open_ = is_trading_day(a.market, d, a.session)
    if not a.quiet:
        label = "OPEN" if open_ else "CLOSED"
        sess = "" if a.session == "full" else f" {a.session}"
        print(f"{label} ({a.market.upper()}{sess} {d.isoformat()})")
    return 0 if open_ else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
