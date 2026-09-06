#!/usr/bin/env python3
"""Assemble the Jekyll source tree from owned repository directories.

Static website source lives in ``site/``. Runtime-generated public data stays
in the KCNyu workspace at its producer-owned paths until the data-plane
contract is migrated. This staging step joins those inputs without making the
repository root double as the website source directory.
"""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

WEEK_FILE_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")
BRIEF_FILE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-pre-open\.md$")

# The review workflow fires `cron: '0 14 * * 0'` — Sunday 14:00 UTC, the last
# day of the ISO week it writes. GitHub's scheduled runs drift: the 2026-08-30
# run started at 17:51 UTC, 3.8 hours late. A week only counts as due once that
# drift has had time to play out, or the page would announce a missing review
# every Sunday evening.
_REVIEW_FIRE_WEEKDAY = 6  # Sunday
_REVIEW_FIRE_HOUR = 14
_REVIEW_GRACE_HOURS = 8


# The daily brief fires `3 8 * * 1-5` in Asia/Shanghai — a host cron, not a
# GitHub schedule, so it does not drift by hours the way the weekly review does.
# The grace is still generous: a brief that has not landed by the afternoon is
# the case this index exists to show, and the 09:05 miss-detector watchdog owns
# the minutes. Asia/Shanghai has no DST, so a fixed +08:00 is exact.
_BRIEF_TZ = timezone(timedelta(hours=8))
_BRIEF_FIRE_HOUR = 8
_BRIEF_FIRE_MINUTE = 3
_BRIEF_GRACE_HOURS = 8


def _last_due_brief_day(now: datetime) -> date:
    """The most recent weekday whose 08:03 fire is past its grace."""
    cutoff = now.astimezone(_BRIEF_TZ) - timedelta(hours=_BRIEF_GRACE_HOURS)
    candidate = cutoff.replace(hour=_BRIEF_FIRE_HOUR, minute=_BRIEF_FIRE_MINUTE,
                               second=0, microsecond=0)
    if candidate > cutoff:
        candidate -= timedelta(days=1)
    while candidate.weekday() > 4:  # Sat/Sun carry no fire at all
        candidate -= timedelta(days=1)
    return candidate.date()


def daily_index(source_root: Path = ROOT, *, now: datetime = None) -> list[dict]:
    """Every weekday the brief series should contain, newest first.

    Same defect the weekly index was carrying, on the same page, one section
    higher: the list was `site.pages` — the files that exist — so a weekday the
    brief never landed on simply is not there. `memory/` has no brief for
    2026-06-04, 2026-06-12, 2026-08-11 or 2026-08-12, and on all four days the
    host was up and committing intraday refreshes; the reader's only clue was
    that a date is absent from a list of dates, and for the newest day there is
    no clue at all.

    Weekdays, because that is what `3 8 * * 1-5` fires on — market holidays
    included, which is why 2026-07-01 (HK closed) has a brief. Days outside that
    rule are listed when a file exists for them (the hand-run weekend briefs of
    2026-05), never demanded when one does not.
    """
    now = now or datetime.now(timezone.utc)
    directory = source_root / "memory"
    present = {}
    for path in sorted(directory.glob("*-pre-open.md")) if directory.is_dir() else []:
        match = BRIEF_FILE_RE.match(path.name)
        if match:
            present[date(*(int(part) for part in match.groups()))] = path.name
    if not present:
        return []

    days = set(present)
    cursor, end = min(present), max(max(present), _last_due_brief_day(now))
    while cursor <= end:
        if cursor.weekday() <= 4:
            days.add(cursor)
        cursor += timedelta(days=1)
    return [
        {
            "date": day.isoformat(),
            "present": day in present,
            "path": f"memory/{day.isoformat()}-pre-open.md",
        }
        for day in sorted(days, reverse=True)
    ]


def _iso_weeks(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    """Every ISO (year, week) from `first` through `last`, inclusive.

    Walked by date rather than by arithmetic on the week number, because a year
    has 52 or 53 ISO weeks depending on where its days fall and the difference
    is exactly the one a hand-rolled `range` gets wrong.
    """
    cursor = date.fromisocalendar(first[0], first[1], 1)
    end = date.fromisocalendar(last[0], last[1], 1)
    out = []
    while cursor <= end:
        year, week, _ = cursor.isocalendar()
        out.append((year, week))
        cursor += timedelta(days=7)
    return out


def _last_due_week(now: datetime) -> tuple[int, int]:
    """The ISO week of the most recent review fire whose grace has elapsed."""
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=_REVIEW_GRACE_HOURS)
    candidate = cutoff.replace(
        hour=_REVIEW_FIRE_HOUR, minute=0, second=0, microsecond=0
    )
    if candidate > cutoff:
        candidate -= timedelta(days=1)
    while candidate.weekday() != _REVIEW_FIRE_WEEKDAY:
        candidate -= timedelta(days=1)
    year, week, _ = candidate.isocalendar()
    return year, week


def weekly_index(source_root: Path = ROOT, *, now: datetime = None) -> list[dict]:
    """Every ISO week the review series should contain, newest first.

    The site used to list the files that exist, so a week the workflow failed to
    produce left no trace at all: `memory/weekly/` is missing 2026-W33 and
    2026-W35 (runs 31952091127 and 33326401496, both three `timeout after 180s`
    lines against a dead fallback), and the reader's only clue was that the week
    numbers skip. A trailing gap had no clue whatsoever — nothing follows the
    last file to look wrong next to.

    So the span is computed rather than read: from the first review present
    through the last fire that is actually due, with every week in between
    named whether or not it was written.
    """
    now = now or datetime.now(timezone.utc)
    directory = source_root / "memory" / "weekly"
    present = {}
    for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
        match = WEEK_FILE_RE.match(path.name)
        if match:
            present[(int(match.group(1)), int(match.group(2)))] = path.name
    if not present:
        return []

    span = _iso_weeks(min(present), max(max(present), _last_due_week(now)))
    return [
        {
            "week": f"{year}-W{week:02d}",
            "present": (year, week) in present,
            "path": f"memory/weekly/{year}-W{week:02d}.md",
        }
        for year, week in reversed(span)
    ]


def _write_weekly_index(output_dir: Path, source_root: Path) -> None:
    """Hand the index to Jekyll as data, not as rendered markup.

    Liquid can compare two week numbers, but it cannot answer "is this week due
    yet" without ISO-week arithmetic over the build clock, and a trailing gap is
    exactly the case that needs it.
    """
    rows = weekly_index(source_root)
    if not rows:
        return
    lines = []
    for row in rows:
        lines.append(f"- week: \"{row['week']}\"")
        lines.append(f"  present: {'true' if row['present'] else 'false'}")
        lines.append(f"  path: \"{row['path']}\"")
    data_dir = output_dir / "_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "weekly_reviews.yml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _write_daily_index(output_dir: Path, source_root: Path) -> None:
    """Same reason as the weekly index: "is this day due yet" is clock
    arithmetic, and Liquid gets the newest row — the one with nothing after it —
    wrong precisely because there is nothing after it to compare against."""
    rows = daily_index(source_root)
    if not rows:
        return
    lines = []
    for row in rows:
        lines.append(f"- date: \"{row['date']}\"")
        lines.append(f"  present: {'true' if row['present'] else 'false'}")
        lines.append(f"  path: \"{row['path']}\"")
    data_dir = output_dir / "_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "daily_briefs.yml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _copy(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def stage(output_dir: Path, *, source_root: Path = ROOT) -> Path:
    output_dir = output_dir.resolve()
    source_root = source_root.resolve()
    site_source = source_root / "site"
    if not (site_source / "index.html").is_file():
        raise ValueError(f"site source has no index.html: {site_source}")
    if output_dir.exists():
        raise ValueError(f"site staging output already exists: {output_dir}")

    shutil.copytree(site_source, output_dir)

    # Product/legal documentation is repository-owned but publicly rendered.
    for relative in ("docs", "THIRD_PARTY_LICENSES", "LICENSE", "NOTICE"):
        _copy(source_root / relative, output_dir / relative)

    # These files are live-instance outputs. Copying is intentionally one-way:
    # Jekyll must never write back into the portfolio workspace.
    _copy(source_root / "site" / "evidence.md", output_dir / "evidence.md")
    _copy(source_root / "assets" / "data", output_dir / "assets" / "data")
    for report in sorted((source_root / "memory").glob("*-pre-open.md")):
        _copy(report, output_dir / "memory" / report.name)
    _copy(source_root / "memory" / "weekly", output_dir / "memory" / "weekly")
    _write_weekly_index(output_dir, source_root)
    _write_daily_index(output_dir, source_root)

    print(f"staged Jekyll source: {site_source} + public runtime inputs -> {output_dir}")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "_site-source")
    args = parser.parse_args()
    stage(args.output_dir)


if __name__ == "__main__":
    main()
