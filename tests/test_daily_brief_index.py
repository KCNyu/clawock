"""The daily brief index lists weekdays, not files.

The same defect the weekly list was carrying, on the same page, one section
higher. `memory/` has no pre-open brief for 2026-06-04, 2026-06-12, 2026-08-11
or 2026-08-12; on all four days the host was up and committing intraday
refreshes, so nothing else looked wrong. The list rendered `site.pages` — the
files that exist — so a weekday the brief never landed on was simply not in it,
and for the newest day there is nothing after it to look wrong beside.

`stage_site.daily_index` computes the span the series should cover from the
cron that writes it (`3 8 * * 1-5`, Asia/Shanghai) and marks each day present or
not. This file pins the cases that make the computation worth having.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "pages"))

import stage_site  # noqa: E402

UTC = timezone.utc


def _tree(tmp_path, days):
    directory = tmp_path / "memory"
    directory.mkdir(parents=True, exist_ok=True)
    for day in days:
        (directory / f"{day}-pre-open.md").write_text(
            "---\nlayout: default\n---\n", encoding="utf-8")
    return tmp_path


def _days(rows):
    return [(row["date"], row["present"]) for row in rows]


def test_a_weekday_with_no_brief_is_named(tmp_path):
    # 2026-08-10 Mon .. 2026-08-13 Thu, with Tue and Wed missing — the real gap.
    root = _tree(tmp_path, ["2026-08-10", "2026-08-13"])
    rows = stage_site.daily_index(root, now=datetime(2026, 8, 14, 12, tzinfo=UTC))
    assert _days(rows) == [
        ("2026-08-14", False),
        ("2026-08-13", True),
        ("2026-08-12", False),
        ("2026-08-11", False),
        ("2026-08-10", True),
    ]


def test_a_trailing_gap_is_named_too(tmp_path):
    """The case the file listing cannot express at all."""
    root = _tree(tmp_path, ["2026-08-10"])
    rows = stage_site.daily_index(root, now=datetime(2026, 8, 12, 12, tzinfo=UTC))
    assert _days(rows) == [
        ("2026-08-12", False),
        ("2026-08-11", False),
        ("2026-08-10", True),
    ]


def test_today_is_not_called_missing_before_its_grace_has_passed(tmp_path):
    """08:03 Asia/Shanghai on 2026-08-11 is 00:03 UTC; at 02:00 UTC the brief is
    still landing. Calling it missing every morning is how a page like this
    stops being read."""
    root = _tree(tmp_path, ["2026-08-10"])
    rows = stage_site.daily_index(root, now=datetime(2026, 8, 11, 2, tzinfo=UTC))
    assert _days(rows) == [("2026-08-10", True)]


def test_the_weekend_is_never_demanded(tmp_path):
    """`3 8 * * 1-5` does not fire on Saturday or Sunday, so a Monday-morning
    index must end on Friday — not report two silent misses every weekend."""
    root = _tree(tmp_path, ["2026-09-04"])  # Friday
    rows = stage_site.daily_index(root, now=datetime(2026, 9, 6, 15, tzinfo=UTC))
    assert _days(rows) == [("2026-09-04", True)]


def test_a_brief_written_off_schedule_is_still_listed(tmp_path):
    """The hand-run weekend briefs of 2026-05 exist. A day outside the cron's
    rule is listed when a file is there, and never demanded when it is not."""
    root = _tree(tmp_path, ["2026-05-16", "2026-05-18"])  # Sat, Mon
    rows = stage_site.daily_index(root, now=datetime(2026, 5, 18, 12, tzinfo=UTC))
    assert _days(rows) == [("2026-05-18", True), ("2026-05-16", True)]


def test_staging_hands_the_index_to_jekyll(tmp_path):
    output = tmp_path / "site-source"
    subprocess.run(
        ["python3", str(ROOT / "ops/pages/stage_site.py"), "--output-dir", str(output)],
        cwd=ROOT,
        check=True,
    )
    rows = yaml.safe_load(
        (output / "_data" / "daily_briefs.yml").read_text(encoding="utf-8"))
    assert rows and isinstance(rows, list)
    for row in rows:
        assert set(row) == {"date", "present", "path"}, row
        assert isinstance(row["present"], bool), row
        assert isinstance(row["date"], str), (
            "an unquoted date becomes a datetime.date and the page prints "
            "something else than the file name")
    assert rows[0]["date"] > rows[-1]["date"], "newest first"


def test_the_page_reads_the_index_rather_than_the_file_listing():
    page = (ROOT / "site" / "briefs.md").read_text(encoding="utf-8")
    daily = page.split("## Daily Deep Brief")[1].split("## Weekly Reviews")[0]
    assert "site.data.daily_briefs" in daily, (
        "the daily list is back to rendering whatever files exist, which is "
        "the rendering that hid four missing weekday briefs")
