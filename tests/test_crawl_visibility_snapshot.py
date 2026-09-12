"""The Search Console history has to be comparable, and that is a property of
its windows rather than of its formatting.

GitHub keeps workflow logs for 90 days, so until `--snapshot` existed the only
record of what the site's visibility was last month was the last time somebody
read the log. A history that double-counts its own cadence, or that records a
week which GSC had not finished filling in, is worse than no history: it looks
like a trend and it is an artifact.

The invariants here are the ones a reader cannot check by looking at the panel —
consecutive windows must not overlap, a re-run of the same week must replace its
entry rather than append a duplicate, and an unmeasured week must read as absent
rather than as zero.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "growth" / "crawl_visibility.py"

spec = importlib.util.spec_from_file_location("crawl_visibility", SCRIPT)
crawl_visibility = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(crawl_visibility)


def _daily(end: str, days: int, impressions: int = 1, clicks: int = 0,
           position: float = 5.0) -> list[dict]:
    """A dense run of days ending at `end`, ascending."""
    last = dt.date.fromisoformat(end)
    return [
        {"date": str(last - dt.timedelta(days=offset)),
         "impressions": impressions, "clicks": clicks, "position": position}
        for offset in range(days - 1, -1, -1)
    ]


def _report(daily: list[dict], **overrides) -> dict:
    report = {
        "site": "https://example.test/",
        "window": {"start": "2026-06-01", "end": "2026-09-01", "days": 90},
        "through": dt.date.fromisoformat(daily[-1]["date"]) if daily else dt.date(2026, 9, 1),
        "daily": daily,
        "queries": {"reported": 0, "top": []},
        "impressions": 0,
        "clicks": 0,
        "pages_with_impressions": 1,
        "sitemaps": [{"path": "sitemap.xml", "lastSubmitted": "2026-08-16T00:00:00Z",
                      "lastDownloaded": None, "isPending": True, "errors": 0}],
        "coverage": {"/": {"verdict": "PASS", "coverageState": "Submitted and indexed",
                           "lastCrawlTime": "2026-08-26T04:17:40Z"}},
    }
    report.update(overrides)
    return report


def test_complete_through_floors_to_the_last_day_gsc_can_have_finished():
    """A window ending on a day GSC is still filling in reads differently every
    time it is asked, which is how one week becomes two numbers."""
    daily = _daily("2026-09-12", 10)
    assert crawl_visibility._complete_through(daily) == dt.date(2026, 9, 11)
    # The lag has to be large enough to be safe, not large enough to be useless.
    assert crawl_visibility._complete_through(daily, lag_days=1) == dt.date(2026, 9, 12)


def test_an_empty_series_reports_no_measurable_day_rather_than_today():
    assert crawl_visibility._complete_through([]) is None


def test_window_stats_weigh_position_by_impressions():
    """A mean over days would let a single-impression day move a 7-day average as
    much as a twenty-impression one — a page can look like it improved its
    position while it was simply shown less."""
    daily = [
        {"date": "2026-09-01", "impressions": 100, "clicks": 1, "position": 10.0},
        {"date": "2026-09-02", "impressions": 1, "clicks": 0, "position": 1.0},
    ]
    stats = crawl_visibility._window_stats(daily, dt.date(2026, 9, 2), 7)
    assert stats["impressions"] == 101
    assert stats["clicks"] == 1
    # (10*100 + 1*1) / 101, not (10 + 1) / 2
    assert stats["position"] == 9.91
    assert stats["days"] == 7
    assert stats["days_with_data"] == 2
    assert stats["complete"] is False, (
        "a window GSC had not filled in must say so — it is the difference "
        "between a quiet week and an unmeasured one")


def test_window_with_no_rows_is_zeroed_not_missing():
    stats = crawl_visibility._window_stats([], dt.date(2026, 9, 2), 7)
    assert stats["impressions"] == 0
    assert stats["position"] is None, "no impressions means no position to report"


def test_a_snapshot_carries_both_fixed_windows():
    payload, stats = crawl_visibility.snapshot(_report(_daily("2026-09-08", 30)))
    entry = payload["snapshots"][-1]
    assert set(entry["windows"]) == {"7", "28"}
    assert entry["windows"]["7"]["days"] == 7
    assert entry["windows"]["28"]["days"] == 28
    assert entry["as_of"] == "2026-09-08"
    assert stats["added"] == 1


def test_consecutive_weeks_do_not_share_a_day():
    """The whole reason the windows are fixed-length. If they overlapped, the
    series would rise every week by construction and the panel would report the
    cadence as growth."""
    first, _ = crawl_visibility.snapshot(_report(_daily("2026-09-08", 60)))
    second, _ = crawl_visibility.snapshot(_report(_daily("2026-09-15", 60)), first)

    a = second["snapshots"][-2]["windows"]["7"]
    b = second["snapshots"][-1]["windows"]["7"]
    assert a["end"] == "2026-09-08" and b["start"] == "2026-09-09", (
        f"windows touch or overlap: {a} then {b}")
    assert len(second["snapshots"]) == 2


def test_remeasuring_the_same_week_replaces_its_entry():
    """The Actions schedule drifts by hours, so two runs land on one day. Keyed
    on the window rather than on the clock, they are the same measurement."""
    once, _ = crawl_visibility.snapshot(_report(_daily("2026-09-08", 30)))
    twice, stats = crawl_visibility.snapshot(
        _report(_daily("2026-09-08", 30), pages_with_impressions=3), once)

    assert len(twice["snapshots"]) == 1, "the same week was recorded twice"
    assert twice["snapshots"][-1]["pages_with_impressions"] == 3
    assert stats["added"] == 0


def test_history_is_capped_and_keeps_the_newest():
    payload = {"snapshots": []}
    start = dt.date(2024, 1, 2)
    for week in range(crawl_visibility.SNAPSHOT_CAP + 3):
        end = str(start + dt.timedelta(weeks=week))
        payload, _ = crawl_visibility.snapshot(_report(_daily(end, 30)), payload)
    assert len(payload["snapshots"]) == crawl_visibility.SNAPSHOT_CAP
    as_of = [entry["as_of"] for entry in payload["snapshots"]]
    assert as_of == sorted(as_of), "the cap must drop the oldest, not the newest"
    assert as_of[-1] == str(start + dt.timedelta(weeks=crawl_visibility.SNAPSHOT_CAP + 2))


def test_snapshot_records_the_query_dimension_with_its_own_count():
    """"No query rows" has two causes that read identically in a report. The
    count is what separates them, so it has to survive into the history."""
    payload, _ = crawl_visibility.snapshot(_report(
        _daily("2026-09-08", 30),
        queries={"reported": 5, "top": [{"query": "tencent29209", "impressions": 30,
                                         "clicks": 0, "position": 8.5}]}))
    entry = payload["snapshots"][-1]
    assert entry["queries"]["reported"] == 5
    assert entry["queries"]["top"][0]["query"] == "tencent29209"


def test_snapshot_keeps_only_the_recent_daily_tail():
    """Fourteen days, not the query window: the file is committed weekly forever."""
    payload, _ = crawl_visibility.snapshot(_report(_daily("2026-09-08", 90)))
    assert len(payload["snapshots"][-1]["daily"]) == 14


def test_history_lines_render_the_last_readings_side_by_side():
    payload = {"snapshots": []}
    for end in ("2026-09-01", "2026-09-08"):
        payload, _ = crawl_visibility.snapshot(_report(_daily(end, 30)), payload)
    text = "\n".join(crawl_visibility.history_lines(payload))
    assert "2026-09-01" in text and "2026-09-08" in text
    assert "7d imp" in text


def test_the_workflow_commits_what_the_script_writes():
    """The script and the workflow are one mechanism split across two files, and
    only one half is importable. A `--snapshot` path the commit step does not
    stage is a week of visibility that survives only in a 90-day log."""
    workflow = (ROOT / ".github" / "workflows" / "seo-visibility.yml").read_text()
    assert "--snapshot assets/data/crawl_visibility.json" in workflow
    assert "paths: assets/data/crawl_visibility.json" in workflow
    assert "contents: write" in workflow, (
        "a committing workflow without write permission fails on its first run")
    assert "group: data-write" in workflow, (
        "every data producer shares one writer lane; this one commits to master")
