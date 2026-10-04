"""The dashboard says which session a block's numbers belong to (#2524).

Two blocks used to leave that to the reader's calendar. The sector scan is made
before the open, so its percentages are the previous close, yet it carried only
the scan day; the index strip carried no session at all, so the page counted
calendar days from the browser's clock and painted Friday's close as stale
through every weekend.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from clawock.publish import dashboard


def _scan(tmp_path, monkeypatch, block):
    folder = tmp_path / "memory" / ".tmp"
    folder.mkdir(parents=True)
    (folder / "sector-scan-2026-10-02.json").write_text(json.dumps(block))
    monkeypatch.setattr(dashboard, "WS_ROOT", tmp_path)
    return dashboard.load_sector_scan()


def test_a_pre_open_scan_is_stamped_with_the_closes_it_could_see(tmp_path, monkeypatch):
    # 08:32 HKT on Friday 2 October: Hong Kong was shut on the 1st, so its newest
    # close is 30 September; New York's is 1 October.
    scan = _scan(tmp_path, monkeypatch, {
        "date": "2026-10-02", "generated_at": "2026-10-02T08:32:00+08:00", "sectors": []})
    assert scan["date"] == "2026-10-02"
    assert scan["_sessions"] == {"hk": "2026-09-30", "us": "2026-10-01"}


def test_a_scan_without_its_own_timestamp_is_read_at_the_files_mtime(tmp_path, monkeypatch):
    scan = _scan(tmp_path, monkeypatch, {"date": "2026-10-02", "sectors": []})
    at = datetime.fromtimestamp(
        (tmp_path / "memory/.tmp/sector-scan-2026-10-02.json").stat().st_mtime, timezone.utc)
    assert scan["_sessions"] == {
        m: dashboard.trading_calendar.latest_completed_session(m, at).isoformat()
        for m in ("hk", "us")}


def _legs(us_source, hk_source):
    return ({"indices_snapshot": {"SPX": {"price": 1, "source": us_source}}},
            {"indices_snapshot": {"HSI": {"price": 1, "source": hk_source}}})


def test_fridays_close_is_not_stale_on_sunday_or_monday_morning():
    legs = _legs("Tencent usINX index @ 2026-10-02 16:03 ET",
                 "Tencent qt.gtimg.cn 2026/10/02 16:10 HKT")
    for at in (datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc),
               datetime(2026, 10, 5, 0, 30, tzinfo=timezone.utc)):
        rows = dashboard._aggregate_indices(*legs, at=at)
        assert {k: (r["session"], r["stale"]) for k, r in rows.items()} == {
            "SPX": ("2026-10-02", False), "HSI": ("2026-10-02", False)}


def test_a_quote_behind_the_markets_newest_close_is_stale():
    rows = dashboard._aggregate_indices(
        *_legs("Tencent usINX index @ 2026-09-30 16:03 ET", "no date here"),
        at=datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc))
    assert (rows["SPX"]["session"], rows["SPX"]["stale"]) == ("2026-09-30", True)
    assert (rows["HSI"]["session"], rows["HSI"]["stale"]) == (None, None)


def test_a_fetch_on_a_closed_day_belongs_to_the_last_session_that_traded():
    rows = dashboard._aggregate_indices(
        *_legs("x @ 2026-10-03 09:00 ET", "x 2026/10/01 16:10 HKT"),
        at=datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc))
    assert rows["SPX"]["session"] == "2026-10-02"
    assert rows["HSI"]["session"] == "2026-09-30"
