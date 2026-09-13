"""Desk-date and market-timezone single-source contracts."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from clawock import sessions


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "clawock"


def test_hkt_today_uses_the_hong_kong_date_at_a_utc_boundary():
    instant = datetime(2026, 1, 1, 16, 30, tzinfo=timezone.utc)

    assert sessions.hkt_today(instant) == date(2026, 1, 2)


def test_clock_helpers_fail_closed_on_ambiguous_or_unknown_inputs():
    with pytest.raises(ValueError, match="timezone-aware"):
        sessions.hkt_today(datetime(2026, 1, 1, 16, 30))
    with pytest.raises(ValueError, match="unknown market"):
        sessions.market_tz("jp")


def test_market_timezone_objects_are_derived_from_market_tz():
    assert str(sessions.HKT) == sessions.MARKET_TZ["hk"]
    assert str(sessions.ET) == sessions.MARKET_TZ["us"]


def test_market_timezone_literals_are_not_redeclared_by_callers():
    forbidden = re.compile(
        r"ZoneInfo\(\s*['\"](?:Asia/Hong_Kong|America/New_York)['\"]\s*\)"
        r"|timezone\(\s*timedelta\(\s*hours\s*=\s*(?:8|-4)\s*\)\s*\)"
    )
    offenders = []
    for path in SOURCE_ROOT.rglob("*.py"):
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if forbidden.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{line_number}")

    assert offenders == [], "market timezone literal bypasses sessions.MARKET_TZ: " + ", ".join(offenders)


def test_today_assignments_use_the_hkt_helper():
    direct_today = re.compile(r"\btoday\s*=\s*(?:date\.today|datetime\.now)\s*\(")
    offenders = []
    for path in SOURCE_ROOT.rglob("*.py"):
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if direct_today.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{line_number}")

    assert offenders == [], "direct today assignment bypasses sessions.hkt_today: " + ", ".join(offenders)
