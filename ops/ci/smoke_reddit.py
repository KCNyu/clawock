#!/usr/bin/env python3
"""Can a GitHub runner reach Reddit's search feed at all?

This probe exists because of a specific unknown left by #1237. Reddit's
unauthenticated JSON API returns `403 Blocked` everywhere, and the replacement
(`search.rss`) was verified from the project's own VPS — 200, 25 entries — but
the producer runs on a GitHub Actions runner, and datacenter ranges are exactly
what a source like this blocks first. Three months of published zeros came from
nobody ever asking that question, so it gets asked on every code PR instead of
being assumed either way.

The probe is advisory, and "advisory" has to survive the checks UI: the job
carries `continue-on-error`, but GitHub still paints the commit with a red X for
a failed check, and a check that goes red every time Reddit blocks a datacenter
range trains people to ignore red. So an outcome that only says "this runner
cannot reach Reddit" — 403, 429, a timeout, a connection failure — is printed
as a visible warning and exits 0. What still fails is an answer that contradicts
the probe's contract: an unexpected HTTP status, or a 200 whose body cannot be
parsed or names no entries. A blocked source is a fact about the runner; the
last three are facts about the probe.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

import requests

FEED = "https://www.reddit.com/search.rss?q=MSFT&sort=new&limit=25"
UA = "clawock-sentiment-scan/1.0 (github.com/KCNyu/clawock)"
ATOM = {"a": "http://www.w3.org/2005/Atom"}


class Unreachable(Exception):
    """This runner got no usable answer: blocked, throttled, timed out, offline."""

    def __init__(self, verdict: str):
        super().__init__(verdict)
        self.verdict = verdict


def check(get=None) -> tuple[str, int]:
    """(verdict, entry count), or raise `Unreachable` when the runner cannot reach it.

    A 200 that cannot be read — malformed XML, or an empty feed for a mega-cap
    ticker — still raises: that is the probe failing, not the network.
    """
    try:
        response = (get or requests.get)(FEED, headers={"User-Agent": UA}, timeout=15)
    except (requests.RequestException, TimeoutError) as exc:
        raise Unreachable(f"unreachable ({type(exc).__name__})") from exc
    if response.status_code == 403:
        raise Unreachable("blocked (HTTP 403)")
    if response.status_code == 429:
        raise Unreachable("throttled (HTTP 429)")
    if response.status_code != 200:
        raise RuntimeError(f"unexpected HTTP {response.status_code} from Reddit")
    entries = ET.fromstring(response.text).findall("a:entry", ATOM)
    assert entries, "Reddit answered 200 with an empty feed for a mega-cap ticker"
    return "reachable", len(entries)


def main() -> int:
    try:
        verdict, count = check()
    except Unreachable as exc:
        print(f"reddit search feed from this runner: {exc} (0 entries)")
        print(f"::warning::Reddit is not reachable from this runner ({exc}); this is "
              "a source-side block/throttle or a network outcome, not a code failure. "
              "The sentiment producer publishes null from such a host.")
        return 0
    except Exception as exc:  # noqa: BLE001 - probe, report anything
        print(f"::error::reddit search feed probe failed: {type(exc).__name__}: {exc}")
        return 1
    print(f"reddit search feed from this runner: {verdict} ({count} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
