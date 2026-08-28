#!/usr/bin/env python3
"""Capture GitHub repository traffic before the 14-day window drops it.

GitHub's Traffic API is the only first-party measurement of who reaches this
project and from where, and it keeps **14 days**. Nothing captured it until
#789, so every week that passed erased a week of the only distribution data
that exists.

The snapshot that motivated this, taken 2026-08-22, already had three things in
it that cannot be answered without history:

    views   514 / 110 unique          clones 14,867 / 1,147 unique
    referrers: github.com 253 · Google 4 · chatgpt.com 2 · zhihu.com 1
    paths:  / 165/41u · /pulls 38/4u · /issues 27/6u · README.zh.md 13/8u

  - clone uniques are 10x view uniques, and this repository's own CI accounts
    for maybe 200 of the ~1,060 daily clones. Nobody knows what the rest is.
  - Google sent 4 unique visitors in 14 days, which is the crawl-budget
    constraint finally expressed as a number rather than an inference.
  - README.zh.md outdraws every English entry point.

Precision boundary, and it is not cosmetic: `views` and `clones` come back as
**per-day series**, so they can be merged into a real timeline. `referrers` and
`popular/paths` come back only as a **single aggregate over the trailing 14
days** — there is no per-day breakdown to recover. Those are stored as dated
snapshots and must never be summed or differenced as if they were daily.

Package downloads ride along because they are the same kind of perishable
rolling window, and because the package pages turn out to be the highest-traffic
surface this project has (#790).

Stars, forks and watchers ride along for the opposite reason (#1120): they are
running totals that never age out, so no capture can lose them — but nothing was
writing them down either, and "indexed but with no standing" is the real
distribution gap, not crawl budget. Stored as dated snapshots so the KPI is a
curve rather than whatever the number happened to be the day someone looked.

Usage:
    repo_traffic.py                      # merge into assets/data/repo-traffic.json
    repo_traffic.py --print              # show what would be written, write nothing
    repo_traffic.py --out other.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = os.environ.get("CLAWOCK_TRAFFIC_REPO", "KCNyu/clawock")
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "assets" / "data" / "repo-traffic.json"

PYPI_PACKAGE = "clawock"
NPM_PACKAGE = "clawock-dsh"


class TrafficError(RuntimeError):
    """A source could not be read. Never silently becomes an empty reading."""


def _get_json(url: str, token: str | None = None, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        # GitHub rejects requests without one, and a mailbox that cannot receive
        # mail is what got the SEC leg 403'd for three days.
        "User-Agent": "clawock-repo-traffic (+https://github.com/KCNyu/clawock)",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise TrafficError(f"{url} -> HTTP {exc.code} {exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001 - the caller decides what a failure means
        raise TrafficError(f"{url} -> {exc}") from exc


def fetch_github(token: str) -> dict[str, Any]:
    base = f"https://api.github.com/repos/{REPO}/traffic"
    views = _get_json(f"{base}/views?per=day", token)
    clones = _get_json(f"{base}/clones?per=day", token)
    referrers = _get_json(f"{base}/popular/referrers", token)
    paths = _get_json(f"{base}/popular/paths", token)
    # Authority, alongside reach (#1120). The distribution problem was framed
    # for a long time as crawl budget; it is not — the site is indexed, the
    # package is on PyPI, a search returns all three surfaces. What is missing
    # is standing: stars, forks, people watching. Those are the numbers a
    # reader of this repository actually weighs it by, and until now the only
    # place they existed was whatever `gh repo view` printed the day someone
    # ran it.
    repo = _get_json(f"https://api.github.com/repos/{REPO}", token)
    return {"views": views, "clones": clones, "referrers": referrers,
            "paths": paths, "repo": repo}


def fetch_packages() -> dict[str, Any]:
    """Downloads are advisory: a registry being down must not lose a traffic run.

    The GitHub half is the part that cannot be re-fetched later. PyPI and npm
    both expose longer history through their own APIs, so a miss here is
    recoverable and should not fail the job.
    """
    out: dict[str, Any] = {}
    try:
        out["pypi"] = _get_json(f"https://pypistats.org/api/packages/{PYPI_PACKAGE}/recent")["data"]
    except (TrafficError, KeyError, TypeError) as exc:
        out["pypi_error"] = str(exc)
    try:
        npm = _get_json(f"https://api.npmjs.org/downloads/point/last-month/{NPM_PACKAGE}")
        out["npm"] = {"downloads": npm["downloads"], "start": npm["start"], "end": npm["end"]}
    except (TrafficError, KeyError, TypeError) as exc:
        out["npm_error"] = str(exc)
    return out


def _merge_series(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int, int]:
    """Upsert a per-day series keyed on timestamp.

    The 14-day window and a weekly cadence overlap by 7 days on purpose: the
    overlap is a free consistency check. A day whose numbers changed is reported
    rather than silently overwritten — GitHub does revise a day while it is
    still in progress, but a revision to a settled day means the merge key or
    the source is wrong.
    """
    by_day = {row["timestamp"]: row for row in existing}
    added = revised = 0
    for row in incoming:
        key = row["timestamp"]
        prior = by_day.get(key)
        if prior is None:
            added += 1
        elif prior != row:
            revised += 1
        by_day[key] = row
    return [by_day[k] for k in sorted(by_day)], added, revised


def find_gap(existing: list[dict], incoming: list[dict]) -> tuple[str, str] | None:
    """Days that fell between the stored history and the incoming window.

    This is the failure mode that cannot be repaired: if the newest stored day
    is older than the oldest day the API is still willing to return, the days
    in between aged out of the 14-day window while nobody was capturing, and no
    retry brings them back. It has to be said out loud at the moment it is
    detectable, because a month later the series just looks shorter.
    """
    if not existing or not incoming:
        return None
    newest_stored = max(row["timestamp"] for row in existing)
    oldest_incoming = min(row["timestamp"] for row in incoming)
    stored_day = dt.date.fromisoformat(newest_stored[:10])
    incoming_day = dt.date.fromisoformat(oldest_incoming[:10])
    if (incoming_day - stored_day).days > 1:
        return newest_stored[:10], oldest_incoming[:10]
    return None


def merge(previous: dict[str, Any], github: dict[str, Any], packages: dict[str, Any],
          now: dt.datetime) -> tuple[dict[str, Any], dict[str, int]]:
    stamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    merged: dict[str, Any] = {
        "generated_at": stamp,
        "repo": REPO,
        "note": (
            "views/clones are per-day series merged across runs. referrers/paths "
            "are 14-day aggregates captured as dated snapshots and must not be "
            "summed or differenced as daily values."
        ),
    }
    views, v_add, v_rev = _merge_series(previous.get("views", []), github["views"]["views"])
    clones, c_add, c_rev = _merge_series(previous.get("clones", []), github["clones"]["clones"])
    merged["views"] = views
    merged["clones"] = clones

    for name, payload in (("referrers", github["referrers"]), ("paths", github["paths"])):
        history = list(previous.get(f"{name}_snapshots", []))
        history = [s for s in history if s.get("captured_at") != stamp]
        history.append({"captured_at": stamp, "window_days": 14, "rows": payload})
        merged[f"{name}_snapshots"] = sorted(history, key=lambda s: s["captured_at"])

    # Authority is a running total, not a window: unlike views and clones it
    # cannot age out, so this is a dated snapshot series rather than a merge.
    # It is also the one section that survives a missing input — an older
    # capture file, or a caller that did not ask for the repo block, keeps its
    # traffic half rather than failing over a secondary metric.
    repo_meta = github.get("repo")
    if isinstance(repo_meta, dict):
        authority = [s for s in previous.get("authority_snapshots", [])
                     if s.get("captured_at") != stamp]
        authority.append({
            "captured_at": stamp,
            "stargazers": repo_meta.get("stargazers_count"),
            "forks": repo_meta.get("forks_count"),
            "watchers": repo_meta.get("subscribers_count"),
            "open_issues": repo_meta.get("open_issues_count"),
        })
        merged["authority_snapshots"] = sorted(authority,
                                               key=lambda s: s["captured_at"])
    elif previous.get("authority_snapshots"):
        merged["authority_snapshots"] = previous["authority_snapshots"]

    pkg_history = [s for s in previous.get("package_downloads", [])
                   if s.get("captured_at") != stamp]
    pkg_history.append({"captured_at": stamp, **packages})
    merged["package_downloads"] = sorted(pkg_history, key=lambda s: s["captured_at"])

    return merged, {
        "views_added": v_add, "views_revised": v_rev,
        "clones_added": c_add, "clones_revised": c_rev,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--print", dest="dry_run", action="store_true",
                    help="report what would be written and exit without writing")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        # Loud, not empty. A traffic capture that cannot see is not a capture of
        # zero traffic, and the data it missed cannot be fetched again later.
        print("::error::GITHUB_TOKEN/GH_TOKEN is unset — traffic cannot be read, "
              "and this window is unrecoverable once it ages out", file=sys.stderr)
        return 2

    try:
        github = fetch_github(token)
    except TrafficError as exc:
        print(f"::error::GitHub traffic read failed: {exc}", file=sys.stderr)
        return 2

    packages = fetch_packages()

    previous: dict[str, Any] = {}
    if args.out.exists():
        previous = json.loads(args.out.read_text(encoding="utf-8"))

    gap = find_gap(previous.get("views", []), github["views"]["views"])
    merged, stats = merge(previous, github, packages, dt.datetime.now(dt.timezone.utc))

    if gap:
        # A warning, not an error: the run still has to store the window it can
        # still see. Failing here would turn one lost gap into two.
        print(f"::warning::traffic history has an unrecoverable gap between {gap[0]} "
              f"and {gap[1]} — those days aged out of the 14-day window uncaptured")

    v14 = github["views"]
    c14 = github["clones"]
    print(f"views  14d: {v14['count']} / {v14['uniques']} unique")
    print(f"clones 14d: {c14['count']} / {c14['uniques']} unique")
    print("referrers: " + ", ".join(
        f"{r['referrer']} {r['count']}/{r['uniques']}u" for r in github["referrers"][:6]) or "(none)")
    if merged.get("authority_snapshots"):
        latest = merged["authority_snapshots"][-1]
        print(f"authority: {latest['stargazers']}★ · {latest['forks']} forks · "
              f"{latest['watchers']} watching")
    print(f"series: +{stats['views_added']} view days, +{stats['clones_added']} clone days, "
          f"{stats['views_revised'] + stats['clones_revised']} revised")
    print(f"history now spans {len(merged['views'])} view days / {len(merged['clones'])} clone days")
    for key in ("pypi", "npm"):
        if key in packages:
            print(f"{key}: {packages[key]}")
        elif f"{key}_error" in packages:
            print(f"{key}: unavailable ({packages[f'{key}_error']})")

    if args.dry_run:
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
