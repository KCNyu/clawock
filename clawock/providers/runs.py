"""Run history, normalised across the two implementations we already had.

`_watchdog_common.read_runs` reads OpenClaw's cron records (with its own
cli → sqlite → fossil fallback chain) and `workflow_health.fetch_runs` reads
GitHub Actions via `gh run list --json`. Both answer "did the scheduled thing
run, and how did it end" — in different shapes, so nothing could consume them
interchangeably.

Normalising is what makes GitHub and OpenClaw peers rather than one being the
substrate. It is also why `Run.status` is a small closed set: a caller deciding
whether to fire a fallback must not have to know which scheduler answered.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Protocol

from . import openclaw

# Deliberately small and closed. `unknown` is a real answer — a run that is
# recorded but whose outcome the source cannot state must not be silently
# rounded to success.
STATUSES = ("ok", "error", "running", "cancelled", "skipped", "unknown")

_GITHUB_CONCLUSIONS = {
    "success": "ok",
    "failure": "error",
    # Cancellation and skipping are scheduler outcomes, not failed work. The
    # GitHub rollup has always ignored them when counting a failure streak; the
    # provider used to collapse cancelled into error before it had a production
    # caller, which would have reversed that policy the moment it was wired in
    # (#362).
    "cancelled": "cancelled",
    "skipped": "skipped",
    "timed_out": "error",
    "startup_failure": "error",
    None: "running",
    "": "running",
}


@dataclass(frozen=True)
class Run:
    job: str
    started_at: str | None       # ISO 8601
    status: str                  # one of STATUSES
    duration_ms: int | None = None
    source: str = ""             # which provider answered
    reference: str | None = None  # session id / run id, for tracing back
    trigger: str | None = None    # schedule / workflow_dispatch / push / ...

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown run status {self.status!r}")


class RunHistoryProvider(Protocol):
    name: str

    def history(self, job: str, limit: int = 20) -> list[Run]:
        ...


class OpenClawRuns:
    """Wraps the adapter's cron-state chain: CLI → read-only SQLite → fossil."""

    name = "openclaw"

    def __init__(self, reader=None) -> None:
        self._reader = reader

    def _read(self, job: str):
        if self._reader is not None:
            return self._reader(job)
        # Previously `import _watchdog_common`, which lives in scripts/harness
        # and is not in the wheel: this class was importable but not callable
        # from an installation, so "interchangeable providers" held only where
        # the checkout happened to be on sys.path.
        return openclaw.read_runs(job).entries

    def history(self, job: str, limit: int = 20) -> list[Run]:
        entries = list(self._read(job))[-limit:]
        out = []
        for entry in entries:
            # `action` distinguishes a finished record from a lifecycle event;
            # `status` carries the outcome when the record has one.
            raw = (entry.get("status") or "").lower()
            if entry.get("action") not in (None, "finished"):
                status = "running"
            elif raw in ("ok", "success", "succeeded"):
                status = "ok"
            elif raw in ("error", "failed", "failure"):
                status = "error"
            else:
                status = "unknown"
            out.append(Run(
                job=entry.get("jobName") or job,
                started_at=entry.get("runAtIso"),
                status=status,
                duration_ms=entry.get("durationMs"),
                source=self.name,
                reference=entry.get("sessionId"),
                trigger=entry.get("trigger"),
            ))
        return out


class GitHubRuns:
    """GitHub Actions history, normalised for scheduler-agnostic consumers."""

    name = "github"

    def __init__(self, runner=None, timeout: int = 60) -> None:
        self.timeout = timeout
        self._runner = runner or self._run

    def _run(self, cmd):
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=self.timeout).stdout

    def history(self, job: str, limit: int = 20) -> list[Run]:
        raw = self._runner([
            "gh", "run", "list", "--workflow", job, "--limit", str(limit),
            "--json", "conclusion,createdAt,event,databaseId",
        ])
        try:
            entries = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []
        return [
            Run(job=job,
                started_at=entry.get("createdAt"),
                status=_GITHUB_CONCLUSIONS.get(entry.get("conclusion"), "unknown"),
                source=self.name,
                reference=str(entry["databaseId"]) if entry.get("databaseId") else None,
                trigger=entry.get("event"))
            for entry in entries
        ]
