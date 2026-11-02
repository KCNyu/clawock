"""The one place that knows where the OpenClaw binary lives, how to call it, and
where it keeps its cron state.

Everything OpenClaw-specific belongs here so the rest of the tree can be counted
as runtime-agnostic — see `tests/test_runtime_coupling_ratchet.py`, which exempts
`clawock/providers/` precisely because that is what an adapter is for.

Moved out of the former `scripts/harness/_watchdog_common.py`, which held the
binary path, cron CLI call and run-history fallback chain and was therefore the
largest single consumer that knew which runtime it was on. That source alias was
never in the wheel, so anything left behind it was unreachable from an install;
the alias has now been retired.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

# Keep this compatibility name for callers that need an argv default, but make
# its value belong to the current environment rather than to one operator's
# pnpm installation. Cron services that deliberately run with a restricted PATH
# should set CLAWOCK_OPENCLAW_BIN to an absolute path.
OPENCLAW_BIN = shutil.which("openclaw") or "openclaw"
DEFAULT_OPENCLAW_HOME = Path.home() / ".openclaw"
# (C-F8/#917) The old module-level compatibility aliases (OPENCLAW_HOME,
# CRON_RUNS_DIR, CRON_JOBS_JSON, STATE_DB and the :673 workspace trio) are
# gone: every consumer resolves through runtime_paths()/OpenClawPaths so
# overrides apply at use, not at import.


@dataclass(frozen=True)
class OpenClawPaths:
    """One OpenClaw installation, without assuming this host's layout."""

    binary: str
    home: Path
    install_dir: Path | None

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
    def weixin_accounts_dir(self) -> Path:
        return self.home / "openclaw-weixin" / "accounts"

    @property
    def workspace_memory_tmp(self) -> Path:
        return self.workspace / "memory" / ".tmp"


def _discover_install_dir(binary: str, *, search_path: str | None = None) -> Path | None:
    """Best-effort npm/pnpm package root discovery from a selected CLI.

    The package root is only needed by optional operator checks. Runtime calls
    need the binary and state home, so an unfamiliar installation layout must
    not make the provider unusable.
    """
    located = (binary if Path(binary).is_absolute()
               else shutil.which(binary, path=search_path))
    if not located:
        return None
    binary_path = Path(located)
    try:
        resolved = binary_path.resolve()
    except OSError:
        resolved = binary_path

    # npm commonly symlinks the executable into a package's bin script.
    for parent in (resolved.parent, *resolved.parents):
        if parent.name == "openclaw" and parent.parent.name == "node_modules":
            return parent

    # pnpm's global launcher is a shell wrapper next to global/<n>/node_modules.
    candidates = sorted(
        binary_path.parent.glob("global/*/node_modules/openclaw"), reverse=True)
    return candidates[0] if candidates else None


# Where a per-user launcher lives when it is not on the caller's PATH. A job
# started from the user crontab runs with PATH=/usr/bin:/bin, and none of these
# are on it — so `shutil.which` answering None does not mean "not installed", it
# means "not on this PATH". Getting that wrong killed the delivery backstop:
# 2026-08-10 10:40 and 11:40, two intraday slots failed, the watchdog detected
# both correctly, and the deterministic fallback reported `openclaw is not
# installed` instead of sending. Same shape as #438 (the money checker) and #444
# (the gold refresh); this one was the safety net.
_LAUNCHER_DIRS = (
    "~/.local/share/pnpm",      # pnpm global launcher
    "~/.local/bin",             # the clawock launcher's own directory
    "/usr/local/bin",
)


def _search_dirs(env: Mapping[str, str]) -> list[Path]:
    home = env.get("HOME")
    dirs = []
    for directory in _LAUNCHER_DIRS:
        if directory.startswith("~"):
            if not home:
                continue
            dirs.append(Path(home) / directory[2:])
        else:
            dirs.append(Path(directory))
    # nvm keeps node under a per-version directory and puts it on PATH through
    # a shell profile, which a cron job never sources. Newest version first.
    if home:
        dirs.extend(sorted((Path(home) / ".nvm" / "versions" / "node").glob("*/bin"),
                           reverse=True))
    return dirs


def _resolve_binary(env: Mapping[str, str], name: str = "openclaw") -> str:
    """The runtime launcher, found without depending on the caller's PATH."""
    found = shutil.which(name, path=env.get("PATH"))
    if found:
        return found
    for base in _search_dirs(env):
        candidate = base / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    # Unchanged last resort: the bare name, so a genuinely absent runtime still
    # reports "not installed" rather than a path that was never there.
    return name


#: The runtime CLI's own floor for a gateway call: `resolveGatewayCallTimeout`
#: takes a configured handshake timeout only when it is ABOVE this, so asking
#: for less is inert.
GATEWAY_CALL_FLOOR_MS = 10_000
#: Room left inside a subprocess budget for node to start and stop. The CLI must
#: give up before we kill it, or a reportable error becomes an opaque one.
SPAWN_OVERHEAD_MS = 15_000


def rpc_ceiling_ms(timeout_s: float) -> int:
    """How long the CLI may wait for its gateway, given our budget for it, in ms.

    The CLI defaults to 10s, and 10s is below this gateway's real tail latency:
    on 2026-09-08 two sends were abandoned at 10 000 ms while the gateway went
    on to hand Telegram messageId 1318 (16 499 ms) and 1319 (25 708 ms) — see
    #1405. Every subprocess we spawn already carries a budget, so derive the
    ceiling from that one number instead of adding a knob that can drift away
    from it.
    """
    return max(GATEWAY_CALL_FLOOR_MS, int(timeout_s * 1000) - SPAWN_OVERHEAD_MS)


def runtime_env(env: Mapping[str, str] | None = None, *,
                call_timeout: float | None = None) -> dict:
    """Environment for spawning the runtime, with a PATH it can actually run on.

    `call_timeout` is the subprocess budget the caller is about to grant, in
    seconds. Passing it makes the CLI wait that long for its gateway instead of
    its own 10s — the difference between a slow gateway and a missing one.

    Resolving the launcher is not enough: the pnpm launcher is a shell script
    whose last line is `exec node …`, so a bare cron PATH turns
    `openclaw is not installed` into `exec: node: not found` — a different
    message for the same undelivered report. Only missing directories that hold
    a real executable are appended, and the caller's own PATH keeps priority so
    an operator's choice still wins.
    """
    env = os.environ if env is None else env
    resolved = dict(env)
    existing = [p for p in (env.get("PATH") or "").split(os.pathsep) if p]
    for base in _search_dirs(env):
        entry = str(base)
        if entry in existing or not base.is_dir():
            continue
        if any(item.is_file() and os.access(item, os.X_OK)
               for item in base.iterdir()):
            existing.append(entry)
    resolved["PATH"] = os.pathsep.join(existing)
    if call_timeout is not None:
        # An operator who set this deliberately keeps it; nothing here is a
        # better guess than a person who typed a number.
        resolved.setdefault("OPENCLAW_HANDSHAKE_TIMEOUT_MS",
                            str(rpc_ceiling_ms(call_timeout)))
    return resolved


def runtime_paths(environ: Mapping[str, str] | None = None) -> OpenClawPaths:
    """Resolve the selected external OpenClaw runtime.

    `CLAWOCK_OPENCLAW_*` is the package-facing namespace. `OPENCLAW_HOME` stays
    as a compatibility fallback for existing operator scripts.
    """
    env = os.environ if environ is None else environ
    binary = env.get("CLAWOCK_OPENCLAW_BIN") or _resolve_binary(env)
    home_override = env.get("CLAWOCK_OPENCLAW_HOME") or env.get("OPENCLAW_HOME")
    default_home = (Path(env["HOME"]) / ".openclaw"
                    if env.get("HOME") else DEFAULT_OPENCLAW_HOME)
    home = Path(home_override).expanduser() if home_override else default_home
    install_override = env.get("CLAWOCK_OPENCLAW_INSTALL_DIR")
    install_dir = (Path(install_override).expanduser() if install_override
                   else _discover_install_dir(binary, search_path=env.get("PATH")))
    return OpenClawPaths(binary=binary, home=home, install_dir=install_dir)

# `cron list --json` round-trips through the gateway and has been observed at
# ~42s on a loaded host. A tight timeout trips TimeoutExpired, which callers
# read as "no data" and quietly fall back to a stale source.
#
# That budget only ever belonged to the subprocess. The CLI inside it was still
# abandoning the gateway at its own 10s (measured idle on 2026-09-08: three
# `cron list --json` at 7.6s, 3.3s, 3.0s — the first already two thirds of the
# way to the ceiling), so the 42s read this number was chosen for could not
# have completed and the fallback it was chosen to prevent happened anyway.
# `runtime_env(call_timeout=…)` is what makes the CLI serve the same budget.
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
        cmd, capture_output=True, text=True, timeout=timeout,
        env=runtime_env(call_timeout=timeout)))
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


def run_cron_job(job_id, *, binary: str | None = None,
                 timeout: int = CRON_TIMEOUT_SECONDS, runner=None):
    """Ask the runtime to run a cron job now. Returns (ok, output tail).

    The runtime queues the run and returns; it is not waited on, because the
    callers are watchdogs that must not hold a crontab slot for the length of an
    agent turn.

    This exists because the runtime's own transient retry is budgeted by
    `consecutiveErrors`, which only resets on success and is not per slot: a job
    that gets one attempt a day loses its retry after `cron.retry.maxAttempts`
    bad days (5 on the live host, 3 by runtime default) and keeps it lost
    (#493). Recovery for such a job has to be driven from outside the
    scheduler's own accounting.
    """
    selected_binary = binary or runtime_paths().binary
    run = runner or (lambda cmd: subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        env=runtime_env(call_timeout=timeout)))
    try:
        done = run([selected_binary, "cron", "run", str(job_id)])
        tail = ((done.stdout or "") + (done.stderr or ""))[-400:]
        return done.returncode == 0, tail
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:300]


# The runtime's own default when `cron.retry.maxAttempts` is unset
# (DEFAULT_MAX_TRANSIENT_RETRIES in the scheduler bundle).
RUNTIME_DEFAULT_MAX_TRANSIENT_RETRIES = 3
# The runtime's config schema rejects a larger value, so a job already past this
# many consecutive failures cannot be rescued by raising the cap at all.
RUNTIME_MAX_ALLOWED_ATTEMPTS = 10


@dataclass(frozen=True)
class CronRetryBudget:
    """Whether the runtime will still retry a job after a transient error.

    The scheduler's rule is `consecutiveErrors > cron.retry.maxAttempts ⇒ no
    retry`, and `consecutiveErrors` counts *runs*, not attempts within a run: it
    only resets on a success. For a once-a-day job that makes the budget a
    countdown of bad days, and once it runs out the job is in a ring — it needs
    a retry to succeed, and a success to get its retry back. Nothing in the
    runtime reports that state, which is why 2026-08-13's brief died looking
    exactly like a provider timeout (#506).

    `exhausted` is None whenever either side of the comparison is unreadable —
    the counter or the cap. Absence of evidence is not evidence of a healthy
    budget, and it is not evidence of an exhausted one either: a caller that
    fills in a plausible cap can accuse a job whose real cap is higher.
    """

    consecutive_errors: int | None
    max_attempts: int | None
    exhausted: bool | None

    @property
    def cap_needed(self) -> int | None:
        """The smallest `maxAttempts` that would let the *next* failure retry.

        The scheduler increments `consecutiveErrors` on a failed run and only
        then compares it, so the stored counter is what the failure that just
        happened was judged against — and the next one will be judged at
        counter + 1. A cap merely equal to the stored counter therefore buys
        nothing: the next failure steps past it in the same instant.
        """
        if self.consecutive_errors is None:
            return None
        return self.consecutive_errors + 1

    @property
    def raisable(self) -> bool:
        """Can raising the configured cap alone restore this job's retries?

        Only while the cap it would take is one the runtime's schema will
        actually store — at a stored counter of 10 the needed cap is 11, which
        is rejected, so the counter itself has to be reset.
        """
        return (self.cap_needed is not None
                and self.cap_needed <= RUNTIME_MAX_ALLOWED_ATTEMPTS)

    def describe(self) -> str:
        if self.exhausted is None:
            return "retry budget unknown (counter or cap unreadable)"
        return (f"consecutiveErrors={self.consecutive_errors} "
                f"{'>' if self.exhausted else '<='} maxAttempts={self.max_attempts}")


def _valid_attempts(value) -> int | None:
    """A usable `maxAttempts`, or None when the runtime could not be running it."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > RUNTIME_MAX_ALLOWED_ATTEMPTS:
        # The runtime's config schema rejects these outright, so a file holding
        # one is not the configuration the live scheduler loaded.
        return None
    return value


def cron_max_attempts(*, paths: OpenClawPaths | None = None) -> int | None:
    """`cron.retry.maxAttempts` from the live runtime config.

    None means the config could not be read — a missing file, a permission
    error, corrupt JSON, or a value the runtime would have refused to start on.
    That is not the same as a config that parses and simply omits the field,
    which is the documented case for the runtime's own default: a caller that
    treats the two alike will compare a real counter against an invented cap.
    """
    config_file = (paths or runtime_paths()).config_file
    try:
        config = json.loads(config_file.read_text())
    except Exception:
        return None
    # `cron: null` and `retry: []` are not "the field is absent" — they are
    # shapes the runtime's schema rejects, so they say nothing about the cap the
    # live scheduler is running. Only a well-formed section may fall back.
    for key in ("cron", "retry"):
        if not isinstance(config, dict):
            return None
        config = config.get(key, {})
    if not isinstance(config, dict):
        return None
    if "maxAttempts" not in config:
        return RUNTIME_DEFAULT_MAX_TRANSIENT_RETRIES
    return _valid_attempts(config["maxAttempts"])


def cron_retry_budget(job, *, paths: OpenClawPaths | None = None,
                      max_attempts: int | None = None) -> CronRetryBudget:
    """Read one job's remaining transient-retry budget from its live state."""
    cap = (cron_max_attempts(paths=paths) if max_attempts is None
           else _valid_attempts(max_attempts))
    state = job.get("state") if isinstance(job, dict) else None
    errors = state.get("consecutiveErrors") if isinstance(state, dict) else None
    if isinstance(errors, bool) or not isinstance(errors, int) or errors < 0:
        errors = None
    if errors is None or cap is None:
        return CronRetryBudget(errors, cap, None)
    return CronRetryBudget(errors, cap, errors > cap)


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


def _sqlite_runs(job_id, paths: OpenClawPaths | None = None, *, since_ms=None):
    """Return one job's finished runs oldest→newest, or None if SQLite is unreadable.

    `since_ms` bounds the read to runs that finished at or after it; the usage
    footer asks for one calendar day, not the job's whole history.
    """
    try:
        with _open_state_db(paths) as conn:
            conn.execute("PRAGMA query_only = ON")
            store_key = _sqlite_store_key(conn)
            if store_key is None:
                return []
            query = ("SELECT entry_json FROM cron_run_logs "
                     "WHERE store_key = ? AND job_id = ?")
            args = [store_key, job_id]
            if since_ms is not None:
                query += " AND ts >= ?"
                args.append(int(since_ms))
            rows = conn.execute(query + " ORDER BY ts, seq", args).fetchall()
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


#: Disabled jobs included — see `read_jobs`.
LIST_ALL_JOBS = ["list", "--all", "--json"]


def read_jobs(source: str = "auto", *, paths: OpenClawPaths | None = None) -> CronRead:
    """Cron jobs from auto|cli|sqlite|fossil.

    Auto prefers the public CLI, then the same live SQLite state read-only. The
    pre-6.1 JSON is retained only for watchdog compatibility and is explicitly
    marked stale; contract/operator tools must reject it.
    """
    if source not in SOURCES:
        raise ValueError(f"unsupported cron source: {source}")
    if source in {"auto", "cli"}:
        # `--all`: without it the CLI omits disabled jobs, and a host-triggered job
        # is disabled in OpenClaw on purpose (clawock.automation.cron_trigger). On
        # 2026-09-12 that made the contract check report it as a missing live job
        # (CRITICAL, which blocks every live push) the moment it was disabled.
        data = (cron_cli_json(LIST_ALL_JOBS, binary=paths.binary)
                if paths else cron_cli_json(LIST_ALL_JOBS))
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
        LIST_ALL_JOBS, binary=paths.binary if paths else None, runner=runner)
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
def is_installed(paths: OpenClawPaths | None = None) -> bool:
    """Whether this runtime is present on this host.

    Callers ask the capability question — "is there a runtime here?" — rather
    than testing a binary path themselves. A CI runner and a dev clone both
    answer False, which is what lets an operator check skip cleanly instead of
    reporting a fault that only means "not this machine".
    """
    binary = (paths or runtime_paths()).binary
    return (Path(binary).exists() if Path(binary).is_absolute()
            else shutil.which(binary) is not None)


# ── The run a delivered card came from ───────────────────────────────────────
#: A cron row still marked `running` longer than this is a crash leftover, not
#: the turn that is asking for its footer. The longest configured turn is 1740s;
#: this leaves room for a slow postflight without adopting yesterday's row.
RUNNING_TASK_MAX_AGE_MS = 60 * 60 * 1000
#: A live cron turn appends to its transcript throughout; a file written within
#: this window belongs to the turn asking for its footer, not an older run.
LIVE_TRANSCRIPT_MAX_AGE_MS = 10 * 60 * 1000


@dataclass(frozen=True)
class RunUsage:
    """What one live cron turn used, read from the runtime's own records.

    Every field is evidence, never a guess: `turn_usd` is the sum of the
    per-call `usage.cost.total` values the runtime wrote into the session
    transcript, and `day_usd` adds the same number for this job's earlier runs
    today. None means the source could not answer — the card then omits that
    piece instead of printing a zero.
    """

    model: str | None
    provider: str | None
    turn_usd: float | None
    day_usd: float | None
    cache_hit_pct: int | None
    context_pct: int | None


@dataclass(frozen=True)
class _TranscriptUsage:
    model: str | None
    provider: str | None
    turn_usd: float | None
    cache_hit_pct: int | None
    prompt_tokens: int | None


def _finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _token_count(value) -> int:
    return int(value) if _finite_number(value) and value > 0 else 0


def _scan_transcript(path: Path) -> _TranscriptUsage | None:
    """Sum one session transcript's assistant-message cost and token buckets."""
    model = provider = None
    spent = 0.0
    priced = False
    unpriced = False
    input_tokens = cache_read = cache_write = 0
    prompt_tokens = None
    try:
        with path.open(encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get('type') != 'message':
                    continue
                message = event.get('message')
                if not isinstance(message, dict) or message.get('role') != 'assistant':
                    continue
                if isinstance(message.get('model'), str) and message['model'].strip():
                    model = message['model'].strip()
                if isinstance(message.get('provider'), str) and message['provider'].strip():
                    provider = message['provider'].strip()
                usage = message.get('usage')
                if not isinstance(usage, dict):
                    continue
                call_input = _token_count(usage.get('input'))
                call_read = _token_count(usage.get('cacheRead'))
                call_write = _token_count(usage.get('cacheWrite'))
                input_tokens += call_input
                cache_read += call_read
                cache_write += call_write
                call_total = (call_input + _token_count(usage.get('output'))
                              + call_read + call_write)
                declared_total = _token_count(usage.get('totalTokens'))
                call_prompt = call_input + call_read + call_write
                if call_prompt or declared_total:
                    # The last call's prompt is the context the turn left behind;
                    # an empty call after a failed hop must not erase it. Prefer
                    # the split buckets: totalTokens also contains the output.
                    prompt_tokens = call_prompt or declared_total
                cost = usage.get('cost')
                amount = cost.get('total') if isinstance(cost, dict) else None
                if _finite_number(amount) and amount >= 0:
                    spent += float(amount)
                    priced = True
                elif call_total:
                    # Tokens ran, but the runtime wrote no price for them. A sum
                    # over only the priced calls would understate the bill.
                    unpriced = True
    except OSError:
        return None
    prompt_total = input_tokens + cache_read + cache_write
    return _TranscriptUsage(
        model=model,
        provider=provider,
        turn_usd=round(spent, 10) if priced and not unpriced else None,
        cache_hit_pct=(round(cache_read / prompt_total * 100)
                       if prompt_total > 0 else None),
        prompt_tokens=prompt_tokens,
    )


def _model_context_window(config_file: Path, provider, model) -> int | None:
    """The model's advertised window, from the runtime's own model table."""
    if not model:
        return None
    try:
        config = json.loads(config_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    providers = ((config.get('models') or {}).get('providers') or {})
    if not isinstance(providers, dict):
        return None
    ordered = ([providers[provider]] if provider in providers else [])
    ordered += [row for name, row in providers.items() if name != provider]
    for entry in ordered:
        if not isinstance(entry, dict):
            continue
        for row in entry.get('models') or []:
            if not isinstance(row, dict) or row.get('id') != model:
                continue
            window = row.get('contextWindow')
            if _finite_number(window) and window > 0:
                return int(window)
    return None


def _local_midnight_ms(now_ms: int) -> int:
    start = datetime.fromtimestamp(now_ms / 1000).astimezone()
    return int(start.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)


def _running_cron_tasks(paths: OpenClawPaths, now_ms: int) -> list[dict] | None:
    """Live `task_runs` rows for cron turns that are still in flight."""
    try:
        with _open_state_db(paths) as conn:
            conn.execute("PRAGMA query_only = ON")
            rows = conn.execute(
                "SELECT child_session_key, source_id, started_at, last_event_at "
                "FROM task_runs WHERE runtime = 'cron' AND status = 'running' "
                "ORDER BY created_at DESC"
            ).fetchall()
    except Exception:
        return None
    out = []
    for session_key, job_id, started_at, last_event_at in rows:
        anchor = started_at if _finite_number(started_at) else last_event_at
        if not _finite_number(anchor) or anchor < now_ms - RUNNING_TASK_MAX_AGE_MS:
            continue
        if not isinstance(session_key, str) or not session_key:
            continue
        out.append({'session_key': session_key, 'job_id': job_id,
                    'started_at': int(started_at) if _finite_number(started_at) else None})
    # The scheduler runs one agent turn at a time (maxConcurrent), so a second
    # in-window row is a crash leftover. Newest is the turn reading this.
    out.sort(key=lambda task: task['started_at'] or 0, reverse=True)
    return out


def _job_prior_day_cost(paths: OpenClawPaths, job_id, *, day_start_ms: int,
                        current_started_ms: int | None,
                        current_session_id: str | None) -> float | None:
    """This job's already-finished runs today, in the same costing unit."""
    runs = _sqlite_runs(job_id, paths, since_ms=day_start_ms)
    if runs is None:
        return None
    total = 0.0
    seen = set()
    for entry in runs:
        run_at = entry.get('runAtMs', entry.get('ts'))
        if not _finite_number(run_at) or run_at < day_start_ms:
            continue
        if current_started_ms is not None and run_at >= current_started_ms:
            continue
        session_id = entry.get('sessionId')
        if not isinstance(session_id, str) or not session_id:
            return None
        if session_id == current_session_id or session_id in seen:
            continue
        seen.add(session_id)
        scan = _scan_transcript(paths.sessions_dir / f'{session_id}.jsonl')
        if scan is None or scan.turn_usd is None:
            return None
        total += scan.turn_usd
    return total


def _read_session_store(paths: OpenClawPaths) -> dict | None:
    """The runtime's session store, or None when it cannot answer."""
    try:
        store = json.loads((paths.sessions_dir / 'sessions.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return store if isinstance(store, dict) else None


def _cron_turn_header(path: Path) -> tuple[str, str] | None:
    """`(job id, job name)` from a transcript's own `[cron:…]` first message."""
    try:
        with path.open(encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                message = event.get('message') if isinstance(event, dict) else None
                if not isinstance(message, dict) or message.get('role') != 'user':
                    continue
                content = message.get('content')
                if isinstance(content, list):
                    content = '\n'.join(
                        block.get('text', '') for block in content
                        if isinstance(block, dict) and isinstance(block.get('text'), str))
                if not isinstance(content, str):
                    continue
                text = content.lstrip()
                if not text.startswith('[cron:'):
                    continue
                close = text.find(']')
                if close < 0:
                    continue
                parts = text[len('[cron:'):close].split(None, 1)
                if len(parts) != 2 or not parts[1].strip():
                    continue
                return parts[0], parts[1].strip()
    except OSError:
        return None
    return None


def _live_cron_transcript(paths: OpenClawPaths, job: str, now_ms: int):
    """`(mtime, path, job id)` for the transcript `job` is writing, or None."""
    try:
        candidates = [path for path in paths.sessions_dir.glob('*.jsonl')
                      if not path.name.endswith('.trajectory.jsonl')]
    except OSError:
        return None
    best = None
    for path in candidates:
        try:
            modified = path.stat().st_mtime * 1000
        except OSError:
            continue
        if modified < now_ms - LIVE_TRANSCRIPT_MAX_AGE_MS:
            continue
        header = _cron_turn_header(path)
        if header is None or header[1] != job:
            continue
        if best is None or modified > best[0]:
            best = (modified, path, header[0])
    return best


def _live_cron_task(paths: OpenClawPaths, job: str, now_ms: int) -> dict | None:
    """The identity of the named cron job's in-flight turn, or None.

    While a turn runs, the job's session-store entry is recent but carries no
    `sessionId`: the runtime clears it at start and records the new session only
    when the turn ends. A running `task_runs` row therefore names a session the
    store cannot resolve yet. The transcript the job is writing is the identity
    in that window — its own `[cron:<job id> <name>]` header plus a write inside
    the live window — and `task_runs` stays the fallback for a saved session.
    """
    store = _read_session_store(paths)
    if store is None:
        return None
    key = entry = None
    for candidate_key, candidate in store.items():
        if isinstance(candidate, dict) and candidate.get('label') == f'Cron: {job}':
            key, entry = candidate_key, candidate
            break
    if not isinstance(entry, dict):
        return None
    started = entry.get('updatedAt')
    if not (_finite_number(started) and started >= now_ms - RUNNING_TASK_MAX_AGE_MS):
        return None
    saved = entry.get('sessionId')
    if isinstance(saved, str) and saved:
        # The turn already saved its session. Only a live `task_runs` row may
        # still claim it, so a manual postflight does not reuse it.
        return None
    live = _live_cron_transcript(paths, job, now_ms)
    if live is None:
        return None
    _, path, job_id = live
    return {'session_key': key, 'job_id': job_id,
            'session_id': path.stem, 'started_at': int(started)}


def _usage_for_session(paths: OpenClawPaths, *, session_id, job_id, started_at,
                       now_ms: int, entry=None) -> RunUsage | None:
    """One session transcript's usage, with the store as metadata fallback."""
    if not isinstance(session_id, str) or not session_id:
        return None
    scan = _scan_transcript(paths.sessions_dir / f'{session_id}.jsonl')
    if scan is None:
        return None
    entry = entry if isinstance(entry, dict) else {}
    model = scan.model or (entry.get('model') if isinstance(entry.get('model'), str) else None)
    provider = scan.provider or (
        entry.get('modelProvider') if isinstance(entry.get('modelProvider'), str) else None)
    if not model:
        return None
    budget = entry.get('contextTokens')
    if not (_finite_number(budget) and budget > 0):
        budget = _model_context_window(paths.config_file, provider, model)
    context_pct = (round(scan.prompt_tokens / budget * 100)
                   if scan.prompt_tokens and _finite_number(budget) and budget > 0 else None)
    prior = None
    if isinstance(job_id, str) and job_id:
        prior = _job_prior_day_cost(
            paths, job_id, day_start_ms=_local_midnight_ms(now_ms),
            current_started_ms=started_at if _finite_number(started_at) else None,
            current_session_id=session_id)
    day_usd = (round(prior + scan.turn_usd, 10)
               if prior is not None and scan.turn_usd is not None else None)
    return RunUsage(
        model=model,
        provider=provider,
        turn_usd=scan.turn_usd,
        day_usd=day_usd,
        cache_hit_pct=scan.cache_hit_pct,
        context_pct=context_pct,
    )


def _usage_for_task(paths: OpenClawPaths, task: dict, now_ms: int) -> RunUsage | None:
    store = _read_session_store(paths)
    entry = store.get(task.get('session_key')) if store is not None else None
    session_id = task.get('session_id')
    if not isinstance(session_id, str) or not session_id:
        session_id = entry.get('sessionId') if isinstance(entry, dict) else None
    return _usage_for_session(
        paths, session_id=session_id, job_id=task.get('job_id'),
        started_at=task.get('started_at'), now_ms=now_ms, entry=entry)


def current_cron_run_usage(*, paths: OpenClawPaths | None = None,
                           now_ms: int | None = None,
                           job: str | None = None) -> RunUsage | None:
    """The live cron turn's model, cost and token shape, or None.

    A postflight names the job it serves. While that turn runs, the session
    store holds the job's entry without a `sessionId` (the runtime fills it in
    when the turn ends), so the live transcript is found from the job's own
    `[cron:<job id> <name>]` header and a write inside the turn window. The
    runtime's `task_runs` row is the fallback identity, and the only one for a
    caller that names no job.

    The transcript carries the per-call usage the runtime already priced, so
    nothing here estimates a token or invents a price. None is deliberate for a
    dry run, a manual postflight, or an unreadable state DB — the card then has
    no footer at all. If a stale `running` row is newer than the live one, the
    youngest candidate that resolves wins; the scheduler runs one turn at a
    time, so only one of them can be this process.
    """
    selected = paths or runtime_paths()
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    tasks = []
    if isinstance(job, str) and job.strip():
        live = _live_cron_task(selected, job.strip(), now)
        if live is not None:
            tasks.append(live)
    tasks.extend(_running_cron_tasks(selected, now) or [])
    for task in tasks:
        usage = _usage_for_task(selected, task, now)
        if usage is not None:
            return usage
    return None
