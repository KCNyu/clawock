"""Shared due-week inventory for the public index and operational health."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re

WEEK_FILE_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")

# The review workflow fires `cron: '0 14 * * 0'` — Sunday 14:00 UTC, the last
# day of the ISO week it writes. GitHub's scheduled runs drift: the 2026-08-30
# run started at 17:51 UTC, 3.8 hours late. A week only counts as due once that
# drift has had time to play out, or the page would announce a missing review
# every Sunday evening.
_REVIEW_FIRE_WEEKDAY = 6  # Sunday
_REVIEW_FIRE_HOUR = 14
_REVIEW_GRACE_HOURS = 8


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


def weekly_index(source_root: Path, *, now: datetime = None) -> list[dict]:
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


def missing_weeks(source_root: Path, *, now: datetime = None) -> list[str]:
    return [row['week'] for row in weekly_index(source_root, now=now) if not row['present']]
