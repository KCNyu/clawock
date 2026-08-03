"""The one place that knows where the OpenClaw binary lives, how to call it, and
where it keeps its cron state.

Everything OpenClaw-specific belongs here so the rest of the tree can be counted
as runtime-agnostic — see `tests/test_runtime_coupling_ratchet.py`, which exempts
`clawock/providers/` precisely because that is what an adapter is for.

Moved out of `scripts/harness/_watchdog_common.py`, which held the binary path,
the cron CLI call and the run-history fallback chain, and was therefore the
largest single consumer that knew which runtime it was on. `_watchdog_common`
lives in `scripts/harness/`, which is deliberately not in the wheel, so anything
left there was unreachable from an installation — `OpenClawRuns.list_runs()`
imported it at call time and raised `ModuleNotFoundError` outside the checkout.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# pnpm's global bin. Kept as one constant rather than resolved through PATH: the
# cron environment is not a login shell, and PATH resolution has bitten this
# before.
OPENCLAW_BIN = "/root/.local/share/pnpm/openclaw"

# Where the runtime keeps its own state. 6.1 migrated cron out of the JSONL
# files into SQLite; both are still read, newest first, because the fossil is
# the only thing left when the gateway and the DB are both unreadable.
OPENCLAW_HOME = Path("/root/.openclaw")
CRON_RUNS_DIR = OPENCLAW_HOME / "cron" / "runs"
CRON_JOBS_JSON = OPENCLAW_HOME / "cron" / "jobs.json"
STATE_DB = OPENCLAW_HOME / "state" / "openclaw.sqlite"

# `cron list --json` round-trips through the gateway and has been observed at
# ~42s on a loaded host. A tight timeout trips TimeoutExpired, which callers
# read as "no data" and quietly fall back to a stale source.
CRON_TIMEOUT_SECONDS = 120


def cron_cli_json(cli_args, *, binary: str = OPENCLAW_BIN,
                  timeout: int = CRON_TIMEOUT_SECONDS, runner=None):
    """Run `openclaw cron <args> --json` and parse the object it prints.

    Returns the dict, or None on any failure — the caller decides what an
    unavailable runtime means, because for a watchdog it is not the same as an
    empty result.

    Leading `Config warnings:` noise is skipped: the CLI prints it before the
    JSON body and it is not an error.
    """
    run = runner or (lambda cmd: subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout))
    try:
        done = run([binary, "cron", *cli_args])
        # Deliberately NOT gated on returncode: the original helper parsed
        # stdout regardless, and a command that exits non-zero while still
        # printing a valid object was treated as data. Preserving that keeps
        # this a move rather than a behaviour change.
        text = done.stdout
        start = text.find("{")
        if start < 0:
            return None
        return json.loads(text[start:])
    except Exception:
        return None


# ── Cron state ───────────────────────────────────────────────────────────────
# Moved verbatim from `_watchdog_common`, with one shape change: which source
# answered is returned instead of being left in a module global. A watchdog that
# reports a failure off the pre-6.1 fossil is reporting on stale payloads, so
# that fact is part of the answer, not a side channel the caller has to
# remember to consult.

SOURCES = ("auto", "cli", "sqlite", "fossil")


@dataclass(frozen=True)
class CronRead:
    """What the runtime's cron storage returned, and which layer answered.

    `source` is one of:
      'cli'    — live gateway (authoritative for payload/model/delivery)
      'sqlite' — live read-only state DB (authoritative, gateway-independent)
      'fossil' — pre-6.1 jobs.json[.migrated] (STALE for payload — schedule only)
      'empty'  — nothing readable
    """

    entries: list
    source: str


def _open_state_db():
    """Open the OpenClaw state DB read-only, including its live WAL."""
    return sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=5)


def _sqlite_store_key(conn):
    row = conn.execute(
        "SELECT store_key FROM cron_jobs "
        "GROUP BY store_key ORDER BY MAX(updated_at) DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _sqlite_jobs():
    """Return live cron jobs from SQLite, or None when the DB/schema is unreadable."""
    try:
        with _open_state_db() as conn:
            conn.execute("PRAGMA query_only = ON")
            store_key = _sqlite_store_key(conn)
            if store_key is None:
                return []
            rows = conn.execute(
                "SELECT job_json, state_json FROM cron_jobs "
                "WHERE store_key = ? ORDER BY sort_order, job_id",
                (store_key,),
            ).fetchall()
        jobs = []
        for raw_job, raw_state in rows:
            job = json.loads(raw_job)
            state = json.loads(raw_state or "{}")
            if not isinstance(job, dict) or not isinstance(state, dict):
                raise ValueError("cron SQLite row is not a JSON object")
            # Runtime state is maintained separately from the declarative job
            # JSON. Merge it so callers see the same current view as the CLI.
            job["state"] = {**(job.get("state") or {}), **state}
            jobs.append(job)
        return jobs
    except Exception:
        return None


def _fossil_jobs():
    for path in (CRON_JOBS_JSON, CRON_JOBS_JSON.with_suffix(".json.migrated")):
        try:
            data = json.loads(path.read_text())
            jobs = data if isinstance(data, list) else data.get("jobs", data.get("items", []))
            if not isinstance(jobs, list):
                continue
            print(f"warn: live cron state unreadable; falling back to STALE {path.name} "
                  "(pre-6.1 fossil — do not trust model/delivery/message)", file=sys.stderr)
            return jobs
        except Exception:
            continue
    return None


def _sqlite_runs(job_id):
    """Return one job's finished runs oldest→newest, or None if SQLite is unreadable."""
    try:
        with _open_state_db() as conn:
            conn.execute("PRAGMA query_only = ON")
            store_key = _sqlite_store_key(conn)
            if store_key is None:
                return []
            rows = conn.execute(
                "SELECT entry_json FROM cron_run_logs "
                "WHERE store_key = ? AND job_id = ? ORDER BY ts, seq",
                (store_key, job_id),
            ).fetchall()
        entries = [json.loads(row[0]) for row in rows]
        if not all(isinstance(entry, dict) for entry in entries):
            raise ValueError("cron run SQLite row is not a JSON object")
        return [entry for entry in entries if entry.get("action") in (None, "finished")]
    except Exception:
        return None


def _fossil_runs(job_id):
    out = []
    for cand in (CRON_RUNS_DIR / f"{job_id}.jsonl", CRON_RUNS_DIR / f"{job_id}.jsonl.migrated"):
        if not cand.exists():
            continue
        for line in cand.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    return None


def read_jobs(source: str = "auto") -> CronRead:
    """Cron jobs from auto|cli|sqlite|fossil.

    Auto prefers the public CLI, then the same live SQLite state read-only. The
    pre-6.1 JSON is retained only for watchdog compatibility and is explicitly
    marked stale; contract/operator tools must reject it.
    """
    if source not in SOURCES:
        raise ValueError(f"unsupported cron source: {source}")
    if source in {"auto", "cli"}:
        data = cron_cli_json(["list", "--json"])
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return CronRead(data["jobs"], "cli")
        if source == "cli":
            return CronRead([], "empty")
    if source in {"auto", "sqlite"}:
        jobs = _sqlite_jobs()
        if jobs is not None:
            return CronRead(jobs, "sqlite")
        if source == "sqlite":
            return CronRead([], "empty")
    if source in {"auto", "fossil"}:
        jobs = _fossil_jobs()
        if jobs is not None:
            return CronRead(jobs, "fossil")
    return CronRead([], "empty")


def read_runs(job_id: str, source: str = "auto") -> CronRead:
    """Finished-run records for a job, OLDEST→NEWEST (so callers' [-1] = newest).
    Auto uses CLI → read-only SQLite → migrated JSONL fossil."""
    if source not in SOURCES:
        raise ValueError(f"unsupported cron source: {source}")
    if source in {"auto", "cli"}:
        data = cron_cli_json(["runs", "--id", job_id])
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            finished = [e for e in data["entries"] if e.get("action") in (None, "finished")]
            # CLI returns newest-first; reverse to match the old append-order contract.
            return CronRead(list(reversed(finished)), "cli")
        if source == "cli":
            return CronRead([], "empty")
    if source in {"auto", "sqlite"}:
        entries = _sqlite_runs(job_id)
        if entries is not None:
            return CronRead(entries, "sqlite")
        if source == "sqlite":
            return CronRead([], "empty")
    if source in {"auto", "fossil"}:
        entries = _fossil_runs(job_id)
        if entries is not None:
            print(f"warn: live cron runs unreadable; using STALE migrated JSONL "
                  f"for {job_id}", file=sys.stderr)
            return CronRead(entries, "fossil")
    return CronRead([], "empty")
