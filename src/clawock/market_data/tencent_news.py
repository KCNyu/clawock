"""Tencent's per-symbol news and announcement search — one adapter for every reader.

`appstock/news/info/search` answers both feeds the harness reads per issuer:
type 0 is exchange/regulator announcements (`primary_disclosures`, grade
`primary`), type 1 is broker and media news (`mover_evidence`, grade
`supporting`). Both readers used to build the request, parse the publisher's
HKT timestamp and apply the caller's window themselves. That shared part lives
here now. Each reader keeps its own item shape and grade.

One request through the caller's `http` seam; no cache, no retry — those
belong to the caller (`evidence.live_sources.Limits`, the mover probe budget).
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime

from clawock.sessions import HKT

URL = "https://web.ifzq.gtimg.cn/appstock/news/info/search"
FILINGS = 0   # exchange / regulator announcements
NEWS = 1      # broker and media news
PAGE_SIZE = 8


def parse_time(value):
    """The feed's `YYYY-MM-DD HH:MM:SS`, which is Hong Kong time; None if absent or malformed."""
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=HKT)
    except (TypeError, ValueError):
        return None


def age_minutes(when: datetime, now: datetime) -> int:
    return int((now - when).total_seconds() // 60)


def url(symbol: str, feed_type: int) -> str:
    query = urllib.parse.urlencode(
        {'symbol': symbol, 'n': PAGE_SIZE, 'page': 1, 'type': feed_type})
    return f"{URL}?{query}"


def recent_rows(symbol, feed_type, *, now, window_minutes, http):
    """`(published_at, age_minutes, row)` for each row inside the window, in feed order.

    A row without a readable time is dropped (its age cannot be known), as is
    one dated after `now` or older than `window_minutes`. `http(url)` returns
    the decoded JSON payload and raises on a non-answer.
    """
    payload = http(url(symbol, feed_type))
    rows = ((payload or {}).get("data") or {}).get("data") or []
    out = []
    for row in rows:
        when = parse_time(row.get("time"))
        if when is None:
            continue
        age = age_minutes(when, now)
        if age < 0 or age > window_minutes:
            continue
        out.append((when, age, row))
    return out
