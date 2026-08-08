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
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

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
# The npm/pnpm install is a different root from the state home.
INSTALL_DIR = Path("/root/.local/share/pnpm/global/5/node_modules/openclaw")


@dataclass(frozen=True)
class OpenClawPaths:
    """One OpenClaw installation, without assuming this host's layout."""

    binary: str
    home: Path
    install_dir: Path

    @property
    def cron_runs_dir(self) -> Path:
        return self.home / "cron" / "runs"

    @property
    def cron_jobs_json(self) -> Path:
        return self.home / "cron" / "jobs.json"

    @property
    def state_db(self) -> Path:
        return self.home / "state" / "openclaw.sqlite"

    @property
    def workspace(self) -> Path:
        return self.home / "workspace"

    @property
    def config_file(self) -> Path:
        return self.home / "openclaw.json"

    @property
    def memory_index_db(self) -> Path:
        return self.home / "agents" / "main" / "agent" / "openclaw-agent.sqlite"

    @property
    def sessions_dir(self) -> Path:
        return self.home / "agents" / "main" / "sessions"

    @property
    def supervisor_handoff(self) -> Path:
        return self.home / "gateway-supervisor-restart-handoff.json"

    @property
    def workspace_memory_tmp(self) -> Path:
        return self.workspace / "memory" / ".tmp"


def runtime_paths(environ: Mapping[str, str] | None = None) -> OpenClawPaths:
    """Resolve the selected external OpenClaw runtime.

    `CLAWOCK_OPENCLAW_*` is the package-facing namespace. `OPENCLAW_HOME` stays
    as a compatibility fallback for existing operator scripts.
    """
    env = os.environ if environ is None else environ
    binary = env.get("CLAWOCK_OPENCLAW_BIN") or OPENCLAW_BIN
    home_override = env.get("CLAWOCK_OPENCLAW_HOME") or env.get("OPENCLAW_HOME")
    home = Path(home_override).expanduser() if home_override else OPENCLAW_HOME
    install_override = env.get("CLAWOCK_OPENCLAW_INSTALL_DIR")
    install_dir = Path(install_override).expanduser() if install_override else INSTALL_DIR
    return OpenClawPaths(binary=binary, home=home, install_dir=install_dir)

# `cron list --json` round-trips through the gateway and has been observed at
# ~42s on a loaded host. A tight timeout trips TimeoutExpired, which callers
# read as "no data" and quietly fall back to a stale source.
CRON_TIMEOUT_SECONDS = 120


def cron_cli_json(cli_args, *, binary: str | None = None,
                  timeout: int = CRON_TIMEOUT_SECONDS, runner=None):
    """Run `openclaw cron <args> --json` and parse the object it prints.

    Returns the dict, or None on any failure — the caller decides what an
    unavailable runtime means, because for a watchdog it is not the same as an
    empty result.

    Leading `Config warnings:` noise is skipped: the CLI prints it before the
    JSON body and it is not an error.
    """
    selected_binary = binary or runtime_paths().binary
    run = runner or (lambda cmd: subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout))
    try:
        done = run([selected_binary, "cron", *cli_args])
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


def _open_state_db(paths: OpenClawPaths | None = None):
    """Open the OpenClaw state DB read-only, including its live WAL."""
    state_db = (paths or runtime_paths()).state_db
    return sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=5)


def _sqlite_store_key(conn):
    row = conn.execute(
        "SELECT store_key FROM cron_jobs "
        "GROUP BY store_key ORDER BY MAX(updated_at) DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _sqlite_jobs(paths: OpenClawPaths | None = None):
    """Return live cron jobs from SQLite, or None when the DB/schema is unreadable."""
    try:
        with _open_state_db(paths) as conn:
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


def _fossil_jobs(paths: OpenClawPaths | None = None):
    jobs_json = (paths or runtime_paths()).cron_jobs_json
    for path in (jobs_json, jobs_json.with_suffix(".json.migrated")):
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


def _sqlite_runs(job_id, paths: OpenClawPaths | None = None):
    """Return one job's finished runs oldest→newest, or None if SQLite is unreadable."""
    try:
        with _open_state_db(paths) as conn:
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


def _fossil_runs(job_id, paths: OpenClawPaths | None = None):
    out = []
    runs_dir = (paths or runtime_paths()).cron_runs_dir
    for cand in (runs_dir / f"{job_id}.jsonl", runs_dir / f"{job_id}.jsonl.migrated"):
        try:
            if not cand.exists():
                continue
            text = cand.read_text()
        except OSError:
            # Unreadable is not the same as absent, and neither is a crash.
            # `Path.exists()` swallows ENOENT but re-raises EACCES, so this
            # blew up for any process that is not the user owning the runtime's
            # home — which is every process outside the live host, i.e. exactly
            # the installed-elsewhere case this provider is supposed to serve.
            # None means "this layer cannot answer"; the chain ends at empty.
            return None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    return None


def read_jobs(source: str = "auto", *, paths: OpenClawPaths | None = None) -> CronRead:
    """Cron jobs from auto|cli|sqlite|fossil.

    Auto prefers the public CLI, then the same live SQLite state read-only. The
    pre-6.1 JSON is retained only for watchdog compatibility and is explicitly
    marked stale; contract/operator tools must reject it.
    """
    if source not in SOURCES:
        raise ValueError(f"unsupported cron source: {source}")
    if source in {"auto", "cli"}:
        data = (cron_cli_json(["list", "--json"], binary=paths.binary)
                if paths else cron_cli_json(["list", "--json"]))
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return CronRead(data["jobs"], "cli")
        if source == "cli":
            return CronRead([], "empty")
    if source in {"auto", "sqlite"}:
        jobs = _sqlite_jobs(paths)
        if jobs is not None:
            return CronRead(jobs, "sqlite")
        if source == "sqlite":
            return CronRead([], "empty")
    if source in {"auto", "fossil"}:
        jobs = _fossil_jobs(paths)
        if jobs is not None:
            return CronRead(jobs, "fossil")
    return CronRead([], "empty")


def read_runs(job_id: str, source: str = "auto", *,
              paths: OpenClawPaths | None = None) -> CronRead:
    """Finished-run records for a job, OLDEST→NEWEST (so callers' [-1] = newest).
    Auto uses CLI → read-only SQLite → migrated JSONL fossil."""
    if source not in SOURCES:
        raise ValueError(f"unsupported cron source: {source}")
    if source in {"auto", "cli"}:
        data = (cron_cli_json(["runs", "--id", job_id], binary=paths.binary)
                if paths else cron_cli_json(["runs", "--id", job_id]))
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            finished = [e for e in data["entries"] if e.get("action") in (None, "finished")]
            # CLI returns newest-first; reverse to match the old append-order contract.
            return CronRead(list(reversed(finished)), "cli")
        if source == "cli":
            return CronRead([], "empty")
    if source in {"auto", "sqlite"}:
        entries = _sqlite_runs(job_id, paths)
        if entries is not None:
            return CronRead(entries, "sqlite")
        if source == "sqlite":
            return CronRead([], "empty")
    if source in {"auto", "fossil"}:
        entries = _fossil_runs(job_id, paths)
        if entries is not None:
            print(f"warn: live cron runs unreadable; using STALE migrated JSONL "
                  f"for {job_id}", file=sys.stderr)
            return CronRead(entries, "fossil")
    return CronRead([], "empty")


# ── Scheduling ───────────────────────────────────────────────────────────────
# The capability the two schedule WRITERS need (#330 step 2). Reading is already
# above; writing was the only part of the cron interface still spelled out as an
# argv literal inside `scripts/`, which made those two files the only places that
# had to know this runtime's command line in order to do their job.
#
# The split: the patch vocabulary below is ours — what a scheduler is asked to
# change — and mapping it onto a command line is this adapter's business. A
# second runtime reimplements the mapping, not the callers.


def read_jobs_strict(*, paths: OpenClawPaths | None = None, runner=None) -> list[dict]:
    """Jobs from the CLI, raising if the runtime cannot be read.

    `read_jobs` is fail-soft on purpose: for a watchdog, an unreachable runtime
    is not the same as an empty schedule. For the paths that WRITE the schedule
    the opposite is true — an empty read means "every job differs from the
    contract", which would rewrite the whole table off a failed command. So the
    writer path gets its own read, and the difference is stated rather than left
    to whoever calls which.
    """
    data = cron_cli_json(
        ["list", "--json"], binary=paths.binary if paths else None, runner=runner)
    if not isinstance(data, dict):
        raise RuntimeError("openclaw cron list failed: no JSON object returned")
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError("openclaw cron list failed: response has no job list")
    return jobs


def build_cron_edit_argv(job_id: str, patch: dict, *,
                         binary: str | None = None,
                         run_timeout_ms: int | None = None) -> list[str]:
    """One job patch as this runtime's `cron edit` command line.

    Only declared fields are emitted, so an edit never carries a value the caller
    did not ask to change — that is what keeps a payload sync from clobbering
    delivery settings it has no opinion about.

    `binary` defaults to the absolute path rather than relying on PATH: the DST
    sync runs from crontab, where a bare name resolves only because the entry
    happens to use a login shell.
    """
    command = [binary or runtime_paths().binary, "cron", "edit", job_id]
    if "schedule" in patch:
        schedule = patch["schedule"]
        if not schedule.get("tz"):
            # A cron row with no timezone silently follows the host's, which for
            # a market schedule is the difference between an open and a close.
            raise ValueError("clearing a cron timezone is not supported safely")
        command.extend(["--cron", schedule["expr"], "--tz", schedule["tz"], "--exact"])
    if "enabled" in patch:
        command.append("--enable" if patch["enabled"] else "--disable")
    if "model" in patch:
        command.extend(["--model", patch["model"]])
    if "fallbacks" in patch:
        if patch["fallbacks"]:
            command.extend(["--fallbacks", ",".join(patch["fallbacks"])])
        else:
            command.append("--clear-fallbacks")
    if "thinking" in patch:
        command.extend(["--thinking", patch["thinking"]])
    if "toolsAllow" in patch:
        tools = patch["toolsAllow"]
        if tools:
            command.extend(["--tools", ",".join(tools)])
        else:
            command.append("--clear-tools")
    if "timeoutSeconds" in patch:
        command.extend(["--timeout-seconds", str(patch["timeoutSeconds"])])
    if "message" in patch:
        command.extend(["--message", patch["message"]])
    if "deliveryMode" in patch:
        mode = patch["deliveryMode"]
        if mode == "none":
            command.append("--no-deliver")
        elif mode == "announce":
            command.append("--announce")
        else:
            raise ValueError(f"unsupported delivery mode {mode!r}")
    if patch.get("clearTrigger"):
        command.append("--clear-trigger")
    if "trigger" in patch:
        trigger = patch["trigger"]
        command.extend(["--trigger-script", trigger["scriptPath"]])
        if trigger["once"]:
            command.append("--trigger-once")
    if run_timeout_ms is not None:
        command.extend(["--timeout", str(run_timeout_ms)])
    return command


# ── Runtime layout and availability ──────────────────────────────────────────
# Where this runtime keeps the things an operator check needs to look at, and
# whether it is installed at all (#330 step 3). These were literals in
# `system_check.py`, which is the last consumer to migrate — deliberately, since
# it is what proves the earlier steps did not break anything.

# The runtime's own workspace. Not derived from a caller's workspace_root: the
# semantic index only ever covers the live runtime checkout, so an interactive
# worktree must judge that one rather than its own copy.
LIVE_WORKSPACE = OPENCLAW_HOME / "workspace"
CONFIG_FILE = OPENCLAW_HOME / "openclaw.json"
MEMORY_INDEX_DB = OPENCLAW_HOME / "agents" / "main" / "agent" / "openclaw-agent.sqlite"


def is_installed(paths: OpenClawPaths | None = None) -> bool:
    """Whether this runtime is present on this host.

    Callers ask the capability question — "is there a runtime here?" — rather
    than testing a binary path themselves. A CI runner and a dev clone both
    answer False, which is what lets an operator check skip cleanly instead of
    reporting a fault that only means "not this machine".
    """
    return Path((paths or runtime_paths()).binary).exists()
