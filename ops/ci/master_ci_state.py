#!/usr/bin/env python3
"""Is master itself red right now — and for how long?

Nothing measured this until 2026-09-10, and it had already cost two incidents.
`validate` went red on 09-09 at 19:20Z and stayed red through **five consecutive
master pushes over eighteen hours**, every one of them a pure data commit with
no code changed. The cause was a test naming today's holdings (#1425). The
reason nobody saw it is that master's CI conclusion had no reader at all:

  * `ops/system_check.py` says so in its own docstring — it "only knows the
    local workspace";
  * `ops/ci/workflow_health.py` filters to `event == "schedule"`, so `ci.yml`'s
    master pushes are outside it by construction;
  * `cron-health.yml` reads the day's git artefacts and heartbeats;
  * a pull request *does* go red — and its author reads it as their own diff.
    Not hypothetical: PR #1418 opened red on 09-09 and it took a `git bisect`
    to prove the break came from a data commit.

**A red master is a state, not an event.** The push that broke it is one line in
one log nobody opens; "the last finished run on master failed" is still true on
the next run, which is what makes it reportable at all.

One module, two readers, so the two cannot drift into disagreeing about the same
fact: `system_check` calls `read_state()` from the live checkout every time
anything runs it, and `cron-health.yml` calls this file's CLI once a day so the
day cannot pass without somebody having asked.

`unknown` is not `red`. An unreachable `gh`, a rate limit, an unfinished newest
run — none of those are evidence about master, and a check that reddened on them
would train its reader to skip the line that matters. Same rule, and the same
reason, as `backstop_rehearsal.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: How many master runs to walk back looking for one that finished. The newest
#: is often still in progress, and master's CI is path-filtered, so a data-only
#: commit starts no run at all — ten is several days of code pushes on a quiet
#: week and still one `gh` call.
SCAN_LIMIT = 10
#: Seconds before the lookup gives up. It also runs inside `pre-push`; a hung
#: network must cost the push a moment, not the push.
TIMEOUT = 8
WORKFLOW = "ci.yml"
BRANCH = "master"

#: `system_check` runs inside `.githooks/pre-push`, once per push ATTEMPT, and
#: `safe_push.sh` attempts up to three times — so an unconditional `gh` call
#: (1.4s measured) is paid three times against a 9.3s budget that
#: `test_system_check_reads_without_spawning` exists to defend. The run list is
#: cached on disk for this long instead. Only the LIST is cached: the age and
#: the stack on top are recomputed from local git every read, so a cache hit
#: still reports the red getting older.
CACHE_TTL = 300
_CACHE = Path(tempfile.gettempdir()) / "clawock_master_ci_runs.json"


@dataclass(frozen=True)
class State:
    """What the last *finished* run on master concluded, and what it cost."""

    state: str  # 'green' | 'red' | 'unknown'
    conclusion: str | None = None
    sha: str | None = None
    run_id: int | None = None
    hours: float | None = None
    stacked: int | None = None  # commits pushed on top of that sha since
    reason: str | None = None  # only set when state == 'unknown'

    @property
    def short_sha(self) -> str:
        return (self.sha or "")[:8]

    def summary(self) -> str:
        if self.state == "unknown":
            return f"master CI state unknown: {self.reason or 'no reason given'}"
        if self.state == "green":
            return f"last finished run on master passed ({self.short_sha})"
        parts = [f"{self.conclusion or 'unknown'} on {self.short_sha}"]
        if self.hours is not None:
            parts.append(f"{self.hours:.1f}h ago")
        if self.stacked:
            parts.append(f"{self.stacked} commit(s) pushed on top since")
        return (", ".join(parts) + " — master is red and every PR opened "
                f"against it inherits the red; run {self.run_id}")


def _sh(argv, timeout=TIMEOUT):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _cached_runs(now: float) -> list[dict] | None:
    try:
        blob = json.loads(_CACHE.read_text(encoding="utf-8"))
        if now - float(blob["at"]) > CACHE_TTL:
            return None
        runs = blob["runs"]
    except Exception:
        return None
    return runs if isinstance(runs, list) else None


def _store_runs(runs: list[dict], now: float) -> None:
    # Atomic, because three push attempts can be in flight at once and a
    # half-written cache reads as `unknown` — which would be reported as
    # silence, the one outcome this whole module exists to avoid.
    try:
        tmp = _CACHE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"at": now, "runs": runs}), encoding="utf-8")
        tmp.replace(_CACHE)
    except OSError:
        pass


def fetch_runs(runner=_sh, use_cache=True) -> list[dict] | None:
    """Master's recent `ci.yml` runs, newest first. `None` means "could not ask"."""
    now = time.time()
    if use_cache:
        cached = _cached_runs(now)
        if cached is not None:
            return cached
    if not shutil.which("gh"):
        return None
    try:
        proc = runner([
            "gh", "run", "list", "--workflow", WORKFLOW, "--branch", BRANCH,
            "--limit", str(SCAN_LIMIT), "--json",
            "conclusion,status,databaseId,headSha,createdAt",
        ])
    except Exception:
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    try:
        runs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(runs, list):
        return None
    if use_cache:
        _store_runs(runs, now)
    return runs


def _stacked_since(sha: str, runner=_sh) -> int | None:
    """Commits pushed on top of `sha` since. The number that turns a stale red
    into "and we kept building on it"."""
    try:
        proc = runner(["git", "rev-list", "--count", f"{sha}..origin/{BRANCH}"])
        if proc.returncode != 0:
            # A CI checkout has no `origin/master` ref for a master build; the
            # local branch is the same tip there.
            proc = runner(["git", "rev-list", "--count", f"{sha}..HEAD"])
        if proc.returncode != 0:
            return None
        return int((proc.stdout or "0").strip() or 0)
    except Exception:
        return None


def read_state(runs=None, runner=_sh, now=None, use_cache=True) -> State:
    if runs is None:
        runs = fetch_runs(runner=runner, use_cache=use_cache)
    if runs is None:
        return State("unknown", reason="gh could not be asked")
    # Newest first. An unfinished run is not a verdict — walk to the first one
    # that reached a conclusion.
    finished = [r for r in runs if (r or {}).get("status") == "completed"]
    if not finished:
        return State("unknown", reason="no finished run on master in the last "
                                       f"{SCAN_LIMIT}")
    latest = finished[0]
    sha = str(latest.get("headSha") or "")
    conclusion = latest.get("conclusion")
    run_id = latest.get("databaseId")
    if conclusion == "success":
        return State("green", conclusion=conclusion, sha=sha, run_id=run_id)
    hours = None
    try:
        started = datetime.fromisoformat(
            str(latest["createdAt"]).replace("Z", "+00:00"))
        moment = now or datetime.now(timezone.utc)
        hours = (moment - started).total_seconds() / 3600
    except Exception:
        pass
    return State("red", conclusion=conclusion, sha=sha, run_id=run_id,
                 hours=hours, stacked=_stacked_since(sha, runner=runner) if sha
                 else None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true",
        help="exit non-zero when master is DETERMINED red; `unknown` still "
             "exits 0, because a gh hiccup is not evidence about master")
    args = parser.parse_args(argv)

    # The daily gate asks for itself. A cache is a pre-push economy, and this
    # step runs once a day on a fresh runner where there is nothing to save.
    state = read_state(use_cache=False)
    line = state.summary()
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        icon = {"green": "✅", "red": "🔴", "unknown": "➖"}[state.state]
        try:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(f"\n### master CI\n\n{icon} {line}\n")
        except OSError:
            pass
    return 1 if (args.strict and state.state == "red") else 0


if __name__ == "__main__":
    sys.exit(main())
