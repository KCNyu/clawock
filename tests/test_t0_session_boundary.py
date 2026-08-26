"""A T+0 card grades a session, and a session is not a calendar day (#1077).

Measured on 2026-08-26 at 15:33 HKT — six hours before the US open —
`assets/data/t0_setups.json` carried:

    "CRCL": {"current": 92.02, "today_change_pct": 4.902, "range_pos": 84.5,
             "grade_label": "追高低质",
             "grade_reason": "现价在当日区间 84% 高位、今日振幅已达典型日的 1.6×"}

92.02 was CRCL's **2026-08-25** close (`prev_close_date` in portfolio.json says
so) and 4.902% was 08-25's move. The card was filed with `as_of: 2026-08-26`.

Cause: `closed_reason()` answers "does this market trade on this DATE", which is
None on any weekday, so `market_closed["us"]` read False all through Hong Kong's
session. Two consequences, both asserted here: the card is built from a stale
bar, and the history line lands under an HKT date that folds two different US
sessions into one settlement observation.
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

HKT = ZoneInfo("Asia/Hong_Kong")


@pytest.fixture(scope="module")
def sessions():
    return pytest.importorskip("clawock.sessions")


@pytest.fixture(scope="module")
def review():
    return pytest.importorskip("clawock.decision.setup_review")


# ── the clock half ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("when, market, expected", [
    # The measured case: Hong Kong's afternoon, the US has not opened.
    (datetime(2026, 8, 26, 15, 33, tzinfo=HKT), "us", False),
    (datetime(2026, 8, 26, 15, 33, tzinfo=HKT), "hk", True),
    # US regular hours (21:30 HKT = 09:30 ET).
    (datetime(2026, 8, 26, 22, 0, tzinfo=HKT), "us", True),
    (datetime(2026, 8, 26, 22, 0, tzinfo=HKT), "hk", False),
    # HK lunch break is not a session.
    (datetime(2026, 8, 26, 12, 30, tzinfo=HKT), "hk", False),
    # Before the HK open, on a trading day: the calendar says open, the clock does not.
    (datetime(2026, 8, 26, 9, 0, tzinfo=HKT), "hk", False),
    # Weekend.
    (datetime(2026, 8, 29, 11, 0, tzinfo=HKT), "hk", False),
])
def test_in_session_reads_the_clock_not_only_the_calendar(
        sessions, when, market, expected):
    assert sessions.in_session(market, when) is expected


def test_the_calendar_gate_alone_would_have_said_open(sessions):
    """The exact confusion that shipped: same instant, two different answers."""
    when = datetime(2026, 8, 26, 15, 33, tzinfo=HKT)
    assert sessions.closed_reason("us", when.date()) is None, (
        "the calendar says the US trades on 2026-08-26 — it just is not 09:30 ET yet")
    assert sessions.in_session("us", when) is False


def test_an_unknown_session_does_not_grant_intraday_enrichment(monkeypatch):
    """`not None` is True, so a crashed probe used to read as 'open'."""
    t0 = pytest.importorskip("clawock.decision.setups")

    def explode(market):
        raise RuntimeError("holiday table unreadable")

    monkeypatch.setattr(t0.tc, "in_session", explode)
    fetched = []
    monkeypatch.setattr(t0, "fetch_vwap_orb", lambda code: fetched.append(code))
    t0.compute(intraday=True)
    assert fetched == [], (
        "an unknown session must not be read as permission to enrich")


# ── the settlement half ──────────────────────────────────────────────────────

def _line(as_of, ticker, market, label, close, session_date=None):
    row = {"grade_label": label, "range_pos": 50.0, "close": close, "market": market}
    if session_date is not None:
        row["session_date"] = session_date
    return json.dumps({"as_of": as_of, "ts": f"{as_of}T00:00:00+08:00",
                       "rows": {ticker: row}}, ensure_ascii=False)


def test_two_us_sessions_under_one_hkt_date_stay_two_observations(review, tmp_path,
                                                                  monkeypatch):
    """The shipped shape: an HKT day holds the tail of one session and the head
    of the next, so folding on `as_of` loses one of them entirely."""
    hist = tmp_path / "t0_setups_history.jsonl"
    hist.write_text("\n".join([
        # written 15:33 HKT on 08-26 — this is 08-25's closing bar
        _line("2026-08-26", "CRCL", "us", "追高低质", 92.02, session_date="2026-08-25"),
        # written 22:03 HKT on 08-26 — now it really is 08-26's bar
        _line("2026-08-26", "CRCL", "us", "中性", 91.99, session_date="2026-08-26"),
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(review, "HIST", hist)

    days = review._load_days()
    assert [d["as_of"] for d in days] == ["2026-08-25", "2026-08-26"], (
        "settling on the host's HKT date folds two US sessions into one row")
    assert days[0]["rows"]["CRCL"]["close"] == 92.02
    assert days[1]["rows"]["CRCL"]["close"] == 91.99


def test_rows_without_a_session_date_still_settle_on_as_of(review, tmp_path,
                                                           monkeypatch):
    """Read-side defence, data untouched — the frozen-price gate's pattern.

    Every line written before #1077 lacks the field; rejecting them would throw
    away the whole existing sample to fix its tail.
    """
    hist = tmp_path / "t0_setups_history.jsonl"
    hist.write_text("\n".join([
        _line("2026-08-20", "CRCL", "us", "追高低质", 84.49),
        _line("2026-08-21", "CRCL", "us", "中性", 85.16),
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(review, "HIST", hist)

    days = review._load_days()
    assert [d["as_of"] for d in days] == ["2026-08-20", "2026-08-21"]


def test_the_producer_records_which_session_each_row_belongs_to():
    """`persist_history` must carry the field the reader now settles on."""
    import inspect
    t0 = pytest.importorskip("clawock.decision.setups")
    source = inspect.getsource(t0.persist_history)
    assert "session_date" in source
