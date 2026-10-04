#!/usr/bin/env python3
"""Measure how late GitHub actually delivers this repository's scheduled runs.

Every scheduled workflow here is late, systematically, and until #781 nobody
kept a number. Measured 2026-08-21 over the last 5-8 runs of each workflow:

    45 21 / 40 21   +10..15 min      30 21   +14..23 min
    0 22 / 0 23     +13..71 min      17 9    +30..63 min
    0 13 / 50 12    +31..74 min      25 0    +89..159 min

Two things follow, and both were being got wrong:

  - What drives the delay is the **UTC hour**, not whether the minute is round.
    `cron-health.yml` carried a comment saying the opposite ("避开整点" avoids
    delay) while sitting at `17 9` and drifting 30-63 minutes. A workflow whose
    value depends on arriving before a deadline cannot be scheduled by picking
    a nice-looking minute.
  - The delay is large enough to invalidate a design. brief-fallback's own
    lateness gate turns it off at 10:00 HKT, and GitHub was delivering it at
    11:00-12:30 HKT (#780).

`drift = run.created_at - the cron instant it was scheduled for`. GitHub does
not report the scheduled instant, so it is reconstructed: the most recent cron
occurrence at or before `created_at`, searched back over a bounded window. A run
delayed past its own next occurrence would be attributed to that later one, so
the reported drift is a **lower bound** — which is the right direction to be
wrong in for a number used to argue that things are late.

Two refinements keep that reconstruction honest (#2517, #2526):

  - **Which crons.** A run is matched against the cron lines the workflow file
    carried when the run was created, read from the file's commit history — not
    against today's file. Otherwise moving a cron re-attributes every earlier
    run to an instant that did not exist yet.
  - **Which occurrence.** Runs that arrive with no cron instant between them
    are one delivery wave: a workflow with two crons ten minutes apart, both
    delivered three hours late, produced two runs minutes apart. Those are
    matched in order to the latest occurrences before the wave, one each,
    instead of all to the last one — which left the earlier cron unmeasured.

Usage:
    schedule_drift.py                 # merge into assets/data/schedule-drift.json
    schedule_drift.py --print         # table only, write nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

REPO = os.environ.get("CLAWOCK_TRAFFIC_REPO", "KCNyu/clawock")
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "assets" / "data" / "schedule-drift.json"
WORKFLOW_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
RUNS_PER_WORKFLOW = 20
# How far back to search for the cron occurrence a run belongs to. Beyond this a
# run is left unattributed rather than matched to a guess.
LOOKBACK_MINUTES = 24 * 60


class DriftError(RuntimeError):
    pass


def _api(path: str, token: str, raw: bool = False) -> Any:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        headers={
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "clawock-schedule-drift (+https://github.com/KCNyu/clawock)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return body if raw else json.loads(body)
    except urllib.error.HTTPError as exc:
        raise DriftError(f"{path} -> HTTP {exc.code} {exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001
        raise DriftError(f"{path} -> {exc}") from exc


def _cron_fields(expr: str) -> tuple[set[int], set[int], set[int]]:
    """Parse the minute, hour and day-of-week fields of a 5-field cron.

    Only the forms this repository actually uses: `*`, a number, a `a-b` range,
    and comma lists of those. Anything else raises rather than silently matching
    everything, because a cron nobody can parse must not be reported as
    perfectly on time.
    """
    parts = expr.split()
    if len(parts) != 5:
        raise DriftError(f"not a 5-field cron: {expr!r}")

    def field(raw: str, low: int, high: int) -> set[int]:
        if raw == "*":
            return set(range(low, high + 1))
        out: set[int] = set()
        try:
            for chunk in raw.split(","):
                if "-" in chunk:
                    a, b = chunk.split("-", 1)
                    out |= set(range(int(a), int(b) + 1))
                else:
                    out.add(int(chunk))
        except ValueError as exc:
            # Steps (`*/5`) and names (`MON`) are valid cron this parser does
            # not implement. Raising is the point: treating an unread field as
            # `*` would report a late workflow as perfectly punctual.
            raise DriftError(f"unsupported cron field {raw!r} in {expr!r}") from exc
        if not out or min(out) < low or max(out) > high:
            raise DriftError(f"cron field {raw!r} out of range in {expr!r}")
        return out

    minutes = field(parts[0], 0, 59)
    hours = field(parts[1], 0, 23)
    dow = {d % 7 for d in field(parts[4], 0, 7)}  # cron allows both 0 and 7 for Sunday
    if parts[2] != "*" or parts[3] != "*":
        raise DriftError(f"day-of-month/month fields are not supported: {expr!r}")
    return minutes, hours, dow


def previous_occurrence(expr: str, when: dt.datetime) -> dt.datetime | None:
    """The latest cron instant at or before `when`, within the lookback window."""
    minutes, hours, dow = _cron_fields(expr)
    cursor = when.replace(second=0, microsecond=0)
    for _ in range(LOOKBACK_MINUTES + 1):
        # cron's day-of-week is Sunday=0; Python's weekday() is Monday=0.
        if (cursor.minute in minutes and cursor.hour in hours
                and ((cursor.weekday() + 1) % 7) in dow):
            return cursor
        cursor -= dt.timedelta(minutes=1)
    return None


def scheduled_crons(path: Path) -> list[str]:
    """Cron expressions of a workflow, read as text.

    Deliberately not a YAML parse: `on:` is the YAML 1.1 boolean and the schedule
    block is unambiguous as text, so this stays dependency-free and cannot be
    thrown off by the rest of the file.
    """
    return _crons_in(path.read_text(encoding="utf-8"))


def _crons_in(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- cron:"):
            out.append(stripped.split(":", 1)[1].strip().strip("'\""))
    return out


def _instant(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(
        dt.timezone.utc).replace(tzinfo=None)


def cron_history(name: str, since: dt.datetime, token: str) -> list[tuple[dt.datetime, list[str]]]:
    """(effective from, crons) for each version of a workflow file that was live
    at or after `since`, oldest first.

    Read from the file's commits: the one in effect at `since` and every later
    one. The checkout this runs in is shallow, so the history comes from the API.
    """
    commits = _api(f"commits?path=.github/workflows/{name}&per_page=30", token)
    versions = []
    for commit in commits:                      # newest first
        when = _instant(commit["commit"]["committer"]["date"])
        text = _api(f"contents/.github/workflows/{name}?ref={commit['sha']}", token, raw=True)
        versions.append((when, _crons_in(text)))
        if when <= since:
            break
    return sorted(versions, key=lambda v: v[0])


def crons_at(history: list[tuple[dt.datetime, list[str]]], when: dt.datetime,
             current: list[str]) -> list[str]:
    """The crons a run created at `when` could have been scheduled by."""
    live = [crons for since, crons in history if since <= when]
    if live:
        return live[-1]
    return history[0][1] if history else current


def _latest_occurrences(crons: list[str], when: dt.datetime, count: int,
                        claimed: set[dt.datetime]) -> list[tuple[dt.datetime, str]]:
    """Up to `count` unclaimed cron instants at or before `when`, oldest first."""
    found: list[tuple[dt.datetime, str]] = []
    cursor = when
    while len(found) < count:
        best: tuple[dt.datetime, str] | None = None
        for expr in crons:
            occurrence = previous_occurrence(expr, cursor)
            if occurrence is not None and (best is None or occurrence > best[0]):
                best = (occurrence, expr)
        if best is None or (when - best[0]).total_seconds() > LOOKBACK_MINUTES * 60:
            break
        if best[0] not in claimed:
            found.append(best)
        cursor = best[0] - dt.timedelta(minutes=1)
    return found[::-1]


def attribute(runs: list[tuple[Any, dt.datetime, list[str]]]) -> list[dict[str, Any]]:
    """Match each run — (id, created, crons live at that time) — to a cron instant.

    Runs are taken oldest first and grouped into delivery waves: a run joins the
    previous one's wave when no cron instant falls between them. A wave of k
    runs takes the k latest instants before it, in order, so two crons that are
    closer together than GitHub's delay each keep their own run. An instant is
    never given to two runs. A run with no instant inside the lookback window is
    left out rather than matched to a guess.
    """
    ordered = sorted(runs, key=lambda r: r[1])
    waves: list[list[tuple[Any, dt.datetime, list[str]]]] = []
    for run in ordered:
        newest = _latest_occurrences(run[2], run[1], 1, set())
        if not newest:
            continue
        if waves and newest[0][0] <= waves[-1][-1][1]:
            waves[-1].append(run)
        else:
            waves.append([run])
    samples: list[dict[str, Any]] = []
    claimed: set[dt.datetime] = set()
    for wave in waves:
        slots = _latest_occurrences(wave[0][2], wave[0][1], len(wave), claimed)
        # Fewer instants than runs: the newest runs keep the newest instants.
        for (run_id, created, _), (occurrence, expr) in zip(wave[len(wave) - len(slots):], slots):
            claimed.add(occurrence)
            samples.append({
                "run_id": run_id,
                "cron": expr,
                "scheduled_at": occurrence.isoformat() + "Z",
                "started_at": created.isoformat() + "Z",
                "drift_minutes": round((created - occurrence).total_seconds() / 60, 1),
            })
    return samples[::-1]


def measure(token: str, workflows: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(workflows):
        crons = scheduled_crons(path)
        if not crons:
            continue
        try:
            runs = _api(f"actions/workflows/{path.name}/runs"
                        f"?event=schedule&per_page={RUNS_PER_WORKFLOW}", token)
        except DriftError as exc:
            # A newly added workflow has no run history yet, and GitHub answers
            # 404 rather than an empty list. That is not a measurement failure.
            if "404" in str(exc):
                rows.append({"workflow": path.name, "crons": crons,
                             "samples": 0, "note": "no scheduled runs yet"})
                continue
            raise
        listed = [(run["id"], _instant(run["created_at"]))
                  for run in runs.get("workflow_runs", [])]
        history: list[tuple[dt.datetime, list[str]]] = []
        history_error = None
        if listed:
            try:
                history = cron_history(path.name, min(c for _, c in listed), token)
            except (DriftError, KeyError, TypeError) as exc:
                # Without the history every run is matched against today's
                # crons. Say so in the row instead of passing it off as measured.
                history_error = str(exc)
        samples = attribute([(run_id, created, crons_at(history, created, crons))
                             for run_id, created in listed])
        if not samples:
            continue
        drifts = [s["drift_minutes"] for s in samples]
        rows.append({
            "workflow": path.name,
            "crons": crons,
            "samples": len(samples),
            "drift_min": min(drifts),
            "drift_median": round(statistics.median(drifts), 1),
            "drift_max": max(drifts),
            # A cron in today's file that no sampled run was scheduled by: new,
            # or not delivered. Its punctuality is unknown, not fine.
            "unmeasured_crons": [c for c in crons if c not in {s["cron"] for s in samples}],
            **({"cron_history": f"unavailable ({history_error}); matched against today's crons"}
               if history_error else {}),
            "runs": samples,
        })
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    lines = [f"{'workflow':<28} {'cron(s)':<26} {'n':>3} {'min':>7} {'med':>7} {'max':>7}"]
    for row in sorted(rows, key=lambda r: -r.get("drift_median", -1)):
        if not row["samples"]:
            lines.append(f"{row['workflow']:<28} {','.join(row['crons'])[:26]:<26} "
                         f"{0:>3} {'—':>7} {'—':>7} {'—':>7}")
            continue
        lines.append(
            f"{row['workflow']:<28} {','.join(row['crons'])[:26]:<26} "
            f"{row['samples']:>3} {row['drift_min']:>7.1f} "
            f"{row['drift_median']:>7.1f} {row['drift_max']:>7.1f}"
        )
    lines.append("")
    lines.append("drift in minutes; a lower bound (a run delayed past its own next "
                 "occurrence is attributed to that later one)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--print", dest="dry_run", action="store_true")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("::error::GITHUB_TOKEN/GH_TOKEN is unset — drift cannot be measured, "
              "and a missing measurement is not a measurement of zero", file=sys.stderr)
        return 2

    try:
        rows = measure(token, WORKFLOW_DIR.glob("*.yml"))
    except DriftError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    print(render(rows))
    if args.dry_run:
        return 0

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repo": REPO,
        "note": ("drift_minutes = run.created_at - the reconstructed cron instant. "
                 "GitHub does not report the scheduled instant, so a run delayed "
                 "past its own next occurrence is attributed to that later one: "
                 "every figure here is a lower bound. A run is matched against the "
                 "crons its workflow file carried when the run was created, and runs "
                 "delivered in one wave take one occurrence each, in order."),
        "workflows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
