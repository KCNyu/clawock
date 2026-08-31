#!/usr/bin/env python3
"""Can a GitHub runner reach Reddit's search feed at all?

This probe exists because of a specific unknown left by #1237. Reddit's
unauthenticated JSON API returns `403 Blocked` everywhere, and the replacement
(`search.rss`) was verified from the project's own VPS — 200, 25 entries — but
the producer runs on a GitHub Actions runner, and datacenter ranges are exactly
what a source like this blocks first. Three months of published zeros came from
nobody ever asking that question, so it gets asked on every code PR instead of
being assumed either way.

Advisory by construction: the job carries `continue-on-error`, so a red here
annotates rather than blocks. What it must never do is pass quietly on an
answer that is not an answer — `429` and `403` are distinct outcomes and both
are printed, because "throttled" is a source that works and "blocked" is not.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

import requests

FEED = "https://www.reddit.com/search.rss?q=MSFT&sort=new&limit=25"
UA = "clawock-sentiment-scan/1.0 (github.com/KCNyu/clawock)"
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def check(get=None) -> tuple[str, int]:
    """(verdict, entry count). Raises only on an unreadable 200."""
    response = (get or requests.get)(FEED, headers={"User-Agent": UA}, timeout=15)
    if response.status_code == 429:
        return "throttled", 0
    if response.status_code != 200:
        return f"blocked (HTTP {response.status_code})", 0
    entries = ET.fromstring(response.text).findall("a:entry", ATOM)
    assert entries, "Reddit answered 200 with an empty feed for a mega-cap ticker"
    return "reachable", len(entries)


def main() -> int:
    try:
        verdict, count = check()
    except Exception as exc:  # noqa: BLE001 - advisory probe, report anything
        print(f"::warning::reddit search feed probe failed: {type(exc).__name__}: {exc}")
        return 1
    print(f"reddit search feed from this runner: {verdict} ({count} entries)")
    if verdict == "reachable":
        return 0
    # Not a crash and not a pass. The sentiment producer already publishes
    # `null` rather than `0` for a name it could not reach, so this outcome
    # costs honesty nothing — it decides where the scan should run.
    print("::warning::sentiment's Reddit leg cannot run from GitHub Actions; "
          "counts will publish as null until the scan moves to a host that can "
          "reach it")
    return 1


if __name__ == "__main__":
    sys.exit(main())
