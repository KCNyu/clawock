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
    crawl_visibility.py --snapshot PATH      # also merge this run into a history

`--snapshot` is the difference between a reading and a record. Without it every
number here lives in one run log, and GitHub keeps those 90 days: three months
later the same question is a fresh pull with nothing to compare it against, and
"曝光有没有动" gets answered from memory instead of from a series.

What a snapshot stores is fixed-window by construction, and that is a
correctness rule rather than a layout choice. The `--days` argument above is a
*reading* window; a history built from it would double-count every week it
overlapped the previous one and report a rise that is an artifact of the
cadence. So the snapshot records a 7-day and a 28-day window ending on the last
*complete* day, plus the per-day series those windows were summed from. The day
boundary is why they are reproducible: GSC keeps filling in the tail, so a
window that ends "today" returns a different number every time it is read.
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

# Fixed history windows, in days. See the module docstring: these are not
# preferences, they are what makes two snapshots comparable.
SNAPSHOT_WINDOWS = (7, 28)
# Two years of weekly snapshots. The cap exists because the file is committed on
# every run forever; it is not a claim that a longer series is uninteresting.
SNAPSHOT_CAP = 104
TOP_QUERIES = 15


def _daily_rows(token: str, start: datetime.date, end: datetime.date) -> list[dict]:
    """The per-day series, ascending. The windows below are summed from this."""
    quoted = urllib.parse.quote(SITE, safe="")
    response = _call(f"{API}/webmasters/v3/sites/{quoted}/searchAnalytics/query",
                     token, {"startDate": str(start), "endDate": str(end),
                             "dimensions": ["date"], "rowLimit": 500})
    rows = []
    for row in response.get("rows") or []:
        day = (row.get("keys") or [None])[0]
        if not day:
            continue
        rows.append({"date": str(day),
                     "impressions": row.get("impressions", 0),
                     "clicks": row.get("clicks", 0),
                     "position": row.get("position")})
    return sorted(rows, key=lambda row: row["date"])


#: GSC completes a day's data a day or two behind the wall clock. A window that
#: ends on the last complete day rather than on `today` is what makes the same
#: week read the same number on Monday and on Thursday — and, because the
#: boundary is a fixed offset, neither run needs to know when the other ran.
def _complete_through(daily: list[dict], lag_days: int = 2) -> datetime.date | None:
    """The last day covered by a complete `lag_days`-old window, or None.

    None is the honest answer for an empty series: a history entry claiming a
    7-day window it could not fill would be read later as a week of zero
    visibility, which is the one reading this file exists to distinguish from
    "not measured".
    """
    if not daily:
        return None
    return datetime.date.fromisoformat(daily[-1]["date"]) - datetime.timedelta(days=lag_days - 1)


def _window_stats(daily: list[dict], through: datetime.date, days: int) -> dict:
    end = through
    start = through - datetime.timedelta(days=days - 1)
    rows = [row for row in daily
            if start <= datetime.date.fromisoformat(row["date"]) <= end]
    if not rows:
        return {"start": str(start), "end": str(end), "days": days, "complete": True,
                "days_with_data": 0, "impressions": 0, "clicks": 0, "position": None}
    impressions = sum(row["impressions"] for row in rows)
    # Impression-weighted, the same basis the API reports for a whole window.
    # An unweighted mean over days would let a 1-impression day move the average
    # as much as a 20-impression one, which is how a position "improves" while
    # the page gets less visible.
    weighted = sum((row["position"] or 0) * row["impressions"] for row in rows)
    return {
        "start": str(start),
        "end": str(end),
        "days": days,
        # False when GSC had not filled in the tail yet. A reading, not a fail —
        # but a caller comparing windows must be able to see it.
        "complete": len(rows) == days,
        "days_with_data": len(rows),
        "impressions": impressions,
        "clicks": sum(row["clicks"] for row in rows),
        "position": round(weighted / impressions, 2) if impressions else None,
    }


def _top_queries(token: str, start: datetime.date, end: datetime.date) -> dict:
    """The query dimension, which stayed empty for three months.

    Recorded with its own count because "no row" has two causes that read the
    same in a report: nothing was searched, or everything fell under GSC's
    anonymisation threshold. The count separates them.
    """
    quoted = urllib.parse.quote(SITE, safe="")
    response = _call(f"{API}/webmasters/v3/sites/{quoted}/searchAnalytics/query",
                     token, {"startDate": str(start), "endDate": str(end),
                             "dimensions": ["query"], "rowLimit": 100})
    rows = response.get("rows") or []
    ranked = sorted(rows, key=lambda row: row.get("impressions", 0), reverse=True)
    return {
        "reported": len(rows),
        "top": [{"query": (row.get("keys") or [""])[0],
                 "impressions": row.get("impressions", 0),
                 "clicks": row.get("clicks", 0),
                 "position": round(row["position"], 2) if row.get("position") else None}
                for row in ranked[:TOP_QUERIES]],
    }


def snapshot(report: dict, previous: dict | None = None,
             now: datetime.datetime | None = None) -> tuple[dict, dict]:
    """Merge this reading into the committed history. Returns (payload, stats).

    Keyed on the window's end date rather than on the run's timestamp: two runs
    that measure the same week are the same measurement, and the Actions
    schedule drifts by hours (measured 10-160 minutes in this repository), so a
    key built from when the run happened would store the same week twice and
    show a flat line as change.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    windows = {str(days): _window_stats(report["daily"], report["through"], days)
               for days in SNAPSHOT_WINDOWS}
    entry = {
        "as_of": str(report["through"]),
        "captured_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "windows": windows,
        "queries": report.get("queries") or {"reported": 0, "top": []},
        # How many pages Google has ever shown anyone. One since June; the
        # number this whole panel is ultimately about.
        "pages_with_impressions": report["pages_with_impressions"],
        "sitemap": (report["sitemaps"] or [{}])[0],
        "coverage": report["coverage"],
        # Fourteen days, not the query window: enough to see the shape of a
        # spike's rise and fall between two weekly readings.
        "daily": report["daily"][-14:],
    }
    history = list((previous or {}).get("snapshots") or [])
    history = [item for item in history if item.get("as_of") != entry["as_of"]]
    history.append(entry)
    history = sorted(history, key=lambda item: item["as_of"])[-SNAPSHOT_CAP:]
    payload = {
        "generated_at": entry["captured_at"],
        "site": report["site"],
        "note": (
            "windows are fixed-length and end on the last complete day, so "
            "consecutive snapshots do not overlap and may be compared directly. "
            "`days_with_data` below `days` means GSC had not filled the tail."
        ),
        "snapshots": history,
    }
    added = 1 if len(history) != len((previous or {}).get("snapshots") or []) else 0
    return payload, {"days": len(history), "added": added,
                     "as_of": entry["as_of"], "replaced": 0 if added else len(history) > 0}



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

    # Fetched wide enough to fill the widest history window no matter where the
    # server's clock sits inside the UTC day, then bounded below by the lag that
    # makes the last complete day knowable.
    span = max(SNAPSHOT_WINDOWS)
    probe = _daily_rows(token, end - datetime.timedelta(days=span + 4), end)
    through = _complete_through(probe)
    day_start = (through - datetime.timedelta(days=span - 1)) if through else end
    daily = _daily_rows(token, day_start, through or end)

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
    for probe_url in PROBES:
        url = SITE + probe_url
        try:
            result = _call(f"{API}/v1/urlInspection/index:inspect", token,
                           {"inspectionUrl": url, "siteUrl": SITE})
            status = (result.get("inspectionResult") or {}).get(
                "indexStatusResult") or {}
            coverage[probe_url or "/"] = {
                "verdict": status.get("verdict"),
                "coverageState": status.get("coverageState"),
                "lastCrawlTime": status.get("lastCrawlTime"),
            }
        except urllib.error.HTTPError as error:
            coverage[probe_url or "/"] = {"error": f"{error.code}"}

    return {
        "site": SITE,
        "window": {"start": str(start), "end": str(end), "days": days},
        "through": through or end,
        "daily": daily,
        "queries": _top_queries(token, day_start, through or end),
        "impressions": rows[0].get("impressions", 0),
        "clicks": rows[0].get("clicks", 0),
        "position": rows[0].get("position"),
        "pages_with_impressions": len(pages.get("rows") or []),
        "sitemaps": sitemaps,
        "coverage": coverage,
    }


def _window_line(label: str, stats: dict) -> str:
    flag = "" if stats.get("complete") else f"  ⚠ {stats['days_with_data']}/{stats['days']} days"
    position = stats.get("position")
    return (f"  {label:5}  impressions {stats['impressions']:.0f} · "
            f"clicks {stats['clicks']:.0f} · "
            f"position {position if position is not None else '—'}"
            f"  ({stats['start']} → {stats['end']}){flag}")


def history_lines(payload: dict, limit: int = 5) -> list[str]:
    """The last few readings side by side — the thing a run log cannot give."""
    snapshots = (payload or {}).get("snapshots") or []
    if not snapshots:
        return []
    lines = ["", f"History — {len(snapshots)} weekly snapshot(s) on file"]
    lines.append(f"  {'as of':12} {'7d imp':>7} {'7d clk':>7} {'28d imp':>8} "
                 f"{'pages':>6}  queries")
    for entry in snapshots[-limit:]:
        week = (entry.get("windows") or {}).get(str(SNAPSHOT_WINDOWS[0])) or {}
        month = (entry.get("windows") or {}).get(str(SNAPSHOT_WINDOWS[-1])) or {}
        queries = (entry.get("queries") or {}).get("reported", 0)
        lines.append(f"  {entry.get('as_of','?'):12} {week.get('impressions',0):>7.0f} "
                     f"{week.get('clicks',0):>7.0f} {month.get('impressions',0):>8.0f} "
                     f"{entry.get('pages_with_impressions',0):>6}  {queries}")
    return lines


def render(report: dict, payload: dict | None = None) -> str:
    window = report["window"]
    lines = [f"Search Console — {report['site']}  ({window['start']} → {window['end']})",
             f"  impressions {report['impressions']:.0f} · clicks {report['clicks']:.0f}"
             f" · pages with any impression {report['pages_with_impressions']}"]
    for days in SNAPSHOT_WINDOWS:
        if report.get("daily"):
            lines.append(_window_line(f"{days}d", _window_stats(
                report["daily"], report["through"], days)))
    queries = report.get("queries") or {}
    lines.append(f"  queries reported {queries.get('reported', 0)}"
                 f" (top: {', '.join(repr(q['query']) for q in queries.get('top', [])[:3]) or '—'})")
    for sitemap in report["sitemaps"]:
        fetched = sitemap["lastDownloaded"] or "NEVER DOWNLOADED"
        lines.append(f"  sitemap submitted {sitemap['lastSubmitted']} · fetched {fetched}")
    for page, status in report["coverage"].items():
        lines.append(f"  {page:16} {status.get('coverageState') or status.get('error')}"
                     f"  last crawl {status.get('lastCrawlTime') or '—'}")
    lines.extend(history_lines(payload or {}))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="crawl_visibility")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--credentials", default=os.environ.get(
        "CLAWOCK_GSC_CREDENTIALS") or _default_credentials())
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=None, metavar="PATH",
                        help="merge this run into a committed history at PATH")
    parser.add_argument("--print", dest="dry_run", action="store_true",
                        help="report what --snapshot would write, write nothing")
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

    payload = None
    if args.snapshot is not None and not args.dry_run:
        previous = {}
        if args.snapshot.exists():
            try:
                previous = json.loads(args.snapshot.read_text(encoding="utf-8"))
            except ValueError as error:
                # Not fatal: a corrupt history must not cost the reading we just
                # took, and the reading is the part that cannot be re-fetched.
                print(f"WARN: unreadable {args.snapshot} ({error}) — starting over",
                      file=sys.stderr)
        payload, stats = snapshot(report, previous)
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8")
        print(f"snapshot: {stats['days']} week(s) on file · as_of {stats['as_of']}"
              f" · wrote {args.snapshot}", file=sys.stderr)
    elif args.snapshot is not None:
        payload, stats = snapshot(report, {})
        print(f"::notice::--print: would write as_of {stats['as_of']}", file=sys.stderr)

    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report, payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
