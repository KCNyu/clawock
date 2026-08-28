"""A degraded quote must publish as degraded (#1116).

The failure mode this file pins is not "the fetch failed" — that path is loud
and already handled. It is the fetch that *succeeds on a worse source* and then
becomes indistinguishable from a healthy one:

* stooq carries OHLC only, so ``_fetch_stooq`` fills ``pc`` with the session
  OPEN. Written through, that stamps an open as a prior close, dates it to the
  previous HK session, and prints an intraday move as the daily change. Every
  existing gate agrees with it: TODAY_LEG reconciles (it checks arithmetic, not
  provenance) and STALE_PRICE stays quiet (an open rarely equals the close).
* Which provider actually priced the book lived in `data_source` and in one
  cron's stdout, and nothing read either. "We got a price" and "the primary
  source is alive" were the same sentence.
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

pytest.importorskip("requests")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clawock.market_data import hk_analysis as hk  # noqa: E402
from clawock.portfolio import integrity  # noqa: E402


def _sessions():
    now_hkt = datetime.now(timezone(timedelta(hours=8)))
    prior = hk.trading_calendar.previous_trading_day(
        "hk", now_hkt.date()).isoformat()
    return now_hkt.date().isoformat(), prior


def _book(tmp_path, monkeypatch, holding):
    port = {"portfolios": {"hk_stocks": {"holdings": [holding]}}}
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(port))
    monkeypatch.setattr(hk, "PORTFOLIO_PATH", str(path))
    monkeypatch.setattr(hk, "fetch_indices", lambda: {})
    return path


# stooq's shape: a real price, and a `pc` that is really the open.
STOOQ_QUOTE = {
    "name": "00100", "c": 299.6, "pc": 312.0, "o": 312.0,
    "dp": -3.97, "_pc_quality": "open-as-pc", "_src": "stooq",
}


def test_stooq_open_is_never_published_as_a_prior_close(tmp_path, monkeypatch):
    """The stored prior close wins over the approximation, and its date is kept.

    Keeping the stored close (rather than blanking the fields) is what leaves
    the published book arithmetically consistent: today_change still equals
    shares x (current - prev_close), so TODAY_LEG does not start firing about a
    problem it cannot see.
    """
    _, prior = _sessions()
    _book(tmp_path, monkeypatch, {
        "ticker": "00100", "shares": 100.0, "cost_basis": 300.0,
        "current_price": 312.0, "prev_close": 312.2, "prev_close_date": prior,
    })
    monkeypatch.setattr(hk, "fetch_hk_quotes", lambda codes: {"00100": STOOQ_QUOTE})

    h = hk.update_hk_portfolio(dry_run=True)["portfolios"]["hk_stocks"]["holdings"][0]

    assert h["prev_close"] == 312.2, "the open must not overwrite a real prior close"
    assert h["prev_close_date"] == prior
    # -4.04% against the real close, not -3.97% against the open.
    assert h["today_change_pct"] == pytest.approx(-4.04, abs=0.01)
    assert h["today_change"] == pytest.approx(100 * (299.6 - 312.2), abs=0.01)
    assert not h.get("quote_incomplete"), (
        "a verified prior close for the right session is not a degraded quote")


def test_no_verified_prior_close_flags_the_holding_instead_of_inventing_one(
        tmp_path, monkeypatch):
    """Nothing on file to fall back to → the day change is unknown, and says so.

    `quote_incomplete` is the flag the US path already sets and that integrity
    and intraday_preflight already read — a new flag would be a fourth word for
    the same thing.
    """
    today, prior = _sessions()
    _book(tmp_path, monkeypatch, {
        "ticker": "00100", "shares": 100.0, "cost_basis": 300.0,
        "current_price": 312.0,
    })
    monkeypatch.setattr(hk, "fetch_hk_quotes", lambda codes: {"00100": STOOQ_QUOTE})

    h = hk.update_hk_portfolio(dry_run=True)["portfolios"]["hk_stocks"]["holdings"][0]

    assert h["quote_incomplete"] is True
    assert "prev_close" not in h, "an open is not a prior close"
    assert "today_change_pct" not in h
    # The price itself is fine — the fallback did supply that.
    assert h["current_price"] == 299.6
    assert h["current_value"] == pytest.approx(29960.0)


def test_a_healthy_fetch_retires_the_flag(tmp_path, monkeypatch):
    """A degradation flag nobody clears is its own defect."""
    _, prior = _sessions()
    _book(tmp_path, monkeypatch, {
        "ticker": "00100", "shares": 100.0, "cost_basis": 300.0,
        "current_price": 312.0, "prev_close": 312.2, "prev_close_date": prior,
        "quote_incomplete": True,
    })
    healthy = {"name": "00100", "c": 299.6, "pc": 312.2, "o": 312.0,
               "dp": -4.04, "_src": "Tencent"}
    monkeypatch.setattr(hk, "fetch_hk_quotes", lambda codes: {"00100": healthy})

    h = hk.update_hk_portfolio(dry_run=True)["portfolios"]["hk_stocks"]["holdings"][0]

    assert "quote_incomplete" not in h


def test_a_stale_prior_close_is_degraded_even_though_it_is_real(
        tmp_path, monkeypatch):
    """The stored close belongs to an older session, so the change is not today's."""
    _book(tmp_path, monkeypatch, {
        "ticker": "00100", "shares": 100.0, "cost_basis": 300.0,
        "current_price": 312.0, "prev_close": 305.0,
        "prev_close_date": "2026-01-02",
    })
    monkeypatch.setattr(hk, "fetch_hk_quotes", lambda codes: {"00100": STOOQ_QUOTE})

    h = hk.update_hk_portfolio(dry_run=True)["portfolios"]["hk_stocks"]["holdings"][0]

    assert h["quote_incomplete"] is True
    assert h["prev_close_date"] == "2026-01-02", (
        "the date is what makes the staleness legible; restamping it hides it")


def test_the_whole_chain_falling_back_to_stooq_still_marks_the_quality(monkeypatch):
    """Both live sources out (the #1116 outage), stooq answers — and says how."""
    class _Dead:
        def get(self, *a, **k):
            raise OSError("503 Service Unavailable")

    monkeypatch.setattr(hk, "SESSION", _Dead())
    monkeypatch.setattr(hk, "_fetch_eastmoney_hk", lambda codes: {})
    monkeypatch.setattr(hk, "_fetch_stooq", lambda code: dict(STOOQ_QUOTE))

    quotes = hk.fetch_hk_quotes(["00100"])

    assert quotes["00100"]["_src"] == "stooq"
    assert quotes["00100"]["_pc_quality"] == "open-as-pc", (
        "the fetcher must hand the caller the quality, not just the number")


def _ledger(tmp_path, holdings):
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps({"portfolios": {"us_stocks": {
        "currency": "USD", "holdings": holdings}}}))
    return path


def test_the_report_names_who_priced_the_book(tmp_path):
    """Provider coverage is a ledger line, not an alarm.

    Measured 2026-08-19..28: the whole US book is priced by Finnhub nearly every
    day, because Nasdaq's /info endpoint carries no prior close and
    `_quote_is_complete` rejects it. The chain is working. A daily WARN about
    it would be the fourth yellow light nobody reads, so this is reported as a
    count instead — but it is reported, which is the change.
    """
    path = _ledger(tmp_path, [
        {"ticker": "AAA", "shares": 10, "cost_basis": 1.0, "current_price": 2.0,
         "data_source": "Nasdaq API (stocks) Aug 28 21:45 HKT"},
        {"ticker": "BBB", "shares": 10, "cost_basis": 1.0, "current_price": 2.0,
         "data_source": "Finnhub Aug 28 21:45 HKT"},
    ])

    ledger = integrity.check(path)["quote_sources"]["us_stocks"]

    assert ledger["primary"] == "Nasdaq API"
    assert ledger["primary_priced"] == 1 and ledger["active"] == 2
    assert ledger["by_source"] == {
        "Nasdaq API (stocks)": ["AAA"], "Finnhub": ["BBB"]}


def test_provider_parsing_survives_every_stamp_format_in_use():
    for stamp, want in (
        ("Tencent+Eastmoney Aug 28 16:10 HKT", "Tencent+Eastmoney"),
        ("Nasdaq API (etf) Aug 28 21:45 HKT", "Nasdaq API (etf)"),
        ("stooq 2026/08/28 15:32", "stooq"),
        ("Polygon (prev close) Aug 28 05:00 HKT", "Polygon (prev close)"),
        ("", None),
        (None, None),
    ):
        assert integrity._quote_provider(stamp) == want
