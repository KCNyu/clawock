#!/usr/bin/env python3
"""Weekly Search Console pull — turn "are we getting indexed yet" into a number.

Before this existed the honest answer to that question was "we should wait for
data", which is not an answer: the data was already there, behind a service
account sitting on this box. One 30-second query replaced a standing guess with

    62 impressions / 1 click in 90 days, 1 of 82 pages ever shown,
    homepage last crawled 50 days ago, sitemap submitted 7 weeks ago and
    never once downloaded.

That distinguishes the two explanations that otherwise look identical from the
outside: on-page quality (Lighthouse 100/100/100, valid sitemap, robots open)
versus crawl budget. Only the second is the constraint here, and only measuring
says which.

Credentials: a Search Console service account with read access to the property.
`--credentials` or `CLAWOCK_GSC_CREDENTIALS`; nothing is read from the repo.
Runs read-only — this cannot change anything on the property.

Usage:
    crawl_visibility.py                      # 90-day summary + coverage probes
    crawl_visibility.py --days 28
    crawl_visibility.py --json               # machine-readable, for a gate later
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Bootstrap before importing the package, the way every other ops entry point
# does. Without it the import resolves only when the caller happens to supply
# PYTHONPATH — which is exactly how the first cron line for this script failed
# with ModuleNotFoundError under a bare `python3`.
_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))

SITE = os.environ.get("CLAWOCK_SITE_URL", "https://kcnyu.github.io/clawock/")
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
API = "https://searchconsole.googleapis.com"

# Probed individually because the API exposes no whole-site coverage report.
# One page per discovery path: the entry point, a page reachable only through
# an internal link, and one reachable only through the sitemap.
PROBES = ("", "briefs.html", "evidence.html")


def _default_credentials() -> str:
    """Where this host keeps the Search Console key, without naming a runtime.

    Spelled through the adapter rather than as a literal `/root/.openclaw/...`:
    that literal is exactly what `test_runtime_coupling_ratchet` counts, and it
    caught this file on its first run. The credential lives beside the runtime
    state because that is where the operator put it, not because the package may
    assume so — `CLAWOCK_GSC_CREDENTIALS` overrides, and a foreign host that has
    neither gets the loud error below.
    """
    from clawock.providers.openclaw import runtime_paths

    return str(runtime_paths().home / "credentials" / "gsc-sa.json")


def _token(credentials_path: str) -> str:
    from google.oauth2 import service_account
    import google.auth.transport.requests as gtr

    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES)
    creds.refresh(gtr.Request())
    return creds.token


def _call(url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def collect(token: str, days: int) -> dict:
    quoted = urllib.parse.quote(SITE, safe="")
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)

    totals = _call(f"{API}/webmasters/v3/sites/{quoted}/searchAnalytics/query",
                   token, {"startDate": str(start), "endDate": str(end)})
    rows = totals.get("rows") or [{}]
    pages = _call(f"{API}/webmasters/v3/sites/{quoted}/searchAnalytics/query",
                  token, {"startDate": str(start), "endDate": str(end),
                          "dimensions": ["page"], "rowLimit": 100})

    sitemaps = []
    for entry in _call(f"{API}/webmasters/v3/sites/{quoted}/sitemaps",
                       token).get("sitemap", []):
        sitemaps.append({
            "path": entry.get("path"),
            "lastSubmitted": entry.get("lastSubmitted"),
            # Absent means Google has never fetched it. That absence is the
            # single most informative field this script reports.
            "lastDownloaded": entry.get("lastDownloaded"),
            "isPending": entry.get("isPending"),
            "errors": entry.get("errors"),
        })

    coverage = {}
    for probe in PROBES:
        url = SITE + probe
        try:
            result = _call(f"{API}/v1/urlInspection/index:inspect", token,
                           {"inspectionUrl": url, "siteUrl": SITE})
            status = (result.get("inspectionResult") or {}).get(
                "indexStatusResult") or {}
            coverage[probe or "/"] = {
                "verdict": status.get("verdict"),
                "coverageState": status.get("coverageState"),
                "lastCrawlTime": status.get("lastCrawlTime"),
            }
        except urllib.error.HTTPError as error:
            coverage[probe or "/"] = {"error": f"{error.code}"}

    return {
        "site": SITE,
        "window": {"start": str(start), "end": str(end), "days": days},
        "impressions": rows[0].get("impressions", 0),
        "clicks": rows[0].get("clicks", 0),
        "position": rows[0].get("position"),
        "pages_with_impressions": len(pages.get("rows") or []),
        "sitemaps": sitemaps,
        "coverage": coverage,
    }


def render(report: dict) -> str:
    window = report["window"]
    lines = [f"Search Console — {report['site']}  ({window['start']} → {window['end']})",
             f"  impressions {report['impressions']:.0f} · clicks {report['clicks']:.0f}"
             f" · pages with any impression {report['pages_with_impressions']}"]
    for sitemap in report["sitemaps"]:
        fetched = sitemap["lastDownloaded"] or "NEVER DOWNLOADED"
        lines.append(f"  sitemap submitted {sitemap['lastSubmitted']} · fetched {fetched}")
    for page, status in report["coverage"].items():
        lines.append(f"  {page:16} {status.get('coverageState') or status.get('error')}"
                     f"  last crawl {status.get('lastCrawlTime') or '—'}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="crawl_visibility")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--credentials", default=os.environ.get(
        "CLAWOCK_GSC_CREDENTIALS") or _default_credentials())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.exists(args.credentials):
        # Loud rather than silent: a visibility check that cannot see is not a
        # clean bill of health, and this runs unattended from cron.
        print(f"ERROR: no Search Console credentials at {args.credentials}",
              file=sys.stderr)
        return 2
    try:
        report = collect(_token(args.credentials), args.days)
    except Exception as error:  # network, auth, quota
        print(f"ERROR: Search Console query failed: {error}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
