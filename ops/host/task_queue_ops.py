#!/usr/bin/env python3
"""task_queue_ops — the one versioned entry point for reading and steering the agent-dispatch queue.

Installed at /root/tools/agent-dispatch/task_queue_ops.py (ops/host/install_task_queue_ops.sh).
Two consumers, one rule each place:

  * run-agent.sh asks `head <agent>` before it takes an agent lock, so the order a task
    waits in is decided here and nowhere else;
  * the dsh task chip (clawock-dsh host half) reads `list --json` and runs the write actions.
    The plugin never runs systemctl, flock or edits a task directory itself.

    task_queue_ops.py [--json] [--source ui|cli] <action> ...
      version                       ops_version (hash of this file) and api level
      list                          per-agent lock holder, queue order, quota hint
      head <agent>                  the task id that takes <agent>'s lock next ('' when none)
      cancel <id>                   stop a task (idempotent for one already cancelled)
      priority <id> <n|top|up|down|reset>
                                    reorder a waiting task within its agent's queue
      model <id> <model|keep|default> [<effort|keep|default>]
                                    the model/effort the task's NEXT attempt uses
      choices <id>                  what `model` accepts for this task, from the agent's own sources
      retry <id>                    continue an ended task's session as a new task
      append <id> [--queue]         add instructions (stdin) to a task, same session
      log <id> [--lines N]          the end of the task's run.log, redacted
      result <id>                   the latest final report (read-result.py)
      usage <id>                    tokens the task used and their API-price estimate (KEY=VALUE for the runner)
      brief <id>                    the task's brief (prompt.md) and its appends, capped (read-only); a cut says so
      deadline <id> <+Nh|+Nm|YYYY-MM-DD HH:MM|reset>
                                    move the whole task's deadline (runner api 3)
      attempts <id> <n|reset>       the retry budget MAX_ATTEMPTS (runner api 3)
      resumes <id> <n|reset>        the quota-resume budget QUOTA_RESUMES (runner api 3)
      reap [--dry-run]              mark tasks whose runner unit is gone (dispatch.sh doctor);
                                    never deletes, releases or retries

Exit codes: 0 ok · 2 usage · 3 refused (task ended, not allowed) · 4 unknown task ·
5 host failure (systemctl, a write) · 6 busy (another write on the same task is in flight).
With --json every action prints one JSON object, errors included ({"ok": false, "code": …}).

Queue order (per agent: every agent has its own lock, so orders never mix across agents):
  1. patrol-* rounds always go last, whatever their priority file says;
  2. a manual task that has waited QUEUE_FAIR_WAIT_SEC (limits.env, default 4h) is protected:
     it goes before every unprotected task and nothing can be placed ahead of it any more,
     so a task can only be overtaken during its first hours (no starvation);
  3. protected tasks in QUEUED_AT order; the rest by PRIORITY (higher first), then QUEUED_AT.
QUEUED_AT is when the runner first started waiting for the lock (epoch seconds); a task that
wakes from a quota wait re-queues with its original QUEUED_AT.

The runner registers a waiting task as <lock-dir>/.queue/<agent>/<id> (PID=, QUEUED_AT=) and
removes the file when it gets the lock or ends; an entry whose PID is gone is ignored.

A live task without RUNNER_API>=2 in its result.env (a runner from before 2026-09-26, or one
started by hand) takes no part in this order. It is never silently dropped (kcn 2026-09-26):
`list` names it under its agent's `unqueued`, `head --json` says so in its note, and a lock held
without a live holder file is reported as held by an unnamed task, never as free. The run.log
parsing that used to place such tasks was removed on 2026-09-27, once none was left.
"""
from __future__ import annotations

import argparse
import fcntl
import functools
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

for _candidate in (Path(__file__).resolve().parent,
                   Path(__file__).resolve().parent / "agent-dispatch"):
    if (_candidate / "dispatch_json.py").is_file():
        sys.path.insert(0, str(_candidate))
        break
from dispatch_json import read_json_object  # noqa: E402

API = 3
MIN_RUNNER_API = 2  # the runner that reads override.env and takes the lock in queue order
BUDGET_RUNNER_API = 3  # the runner that rereads DEADLINE_EPOCH/MAX_ATTEMPTS/QUOTA_RESUMES from override.env
MIN_RUN_SEC, KILL_MARGIN = 600, 70  # run-agent.sh: no attempt starts with less than MIN_RUN_SEC + KILL_MARGIN left
DEADLINE_CAP_SEC = 72 * 3600  # dispatch.sh: a deadline is at most 72h after dispatch; extending keeps that ceiling
MAX_ATTEMPTS_CAP, QUOTA_RESUMES_CAP = 10, 6
BRIEF_MAX_BYTES, APPENDS_MAX_BYTES = 48 * 1024, 16 * 1024  # `brief` answers at most 64 KB of text
PRIORITY_RANGE = (-99, 99)
VALUE_RE = re.compile(r"^[A-Za-z0-9._/:@-]{1,120}$")
REDACT = [(re.compile(r"(token|api[_-]?key|secret|password)=[^\s&\"]+", re.I), r"\1=<redacted>"),
          (re.compile(r"(?<![A-Za-z0-9])(sk|ghp|gho|github_pat|xox[bp])[-_][A-Za-z0-9_-]{12,}"), "<redacted>")]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
AGENTS = ("claude", "codex", "opencode", "dsh")
# dsh headless takes reasoningEffort from the patch overlay the runner writes per attempt. The two
# routes are what DeepSeek's API serves (GET /models, 2026-10-17); other dsh routes this host has
# dispatched join them through models_seen.
DSH_EFFORTS = ["off", "low", "high", "max"]
DSH_ROUTES = ("deepseek-official/deepseek-flash", "deepseek-official/deepseek-v4-pro")
TERMINAL = {"ok", "partial", "unverified", "failed", "blocked", "timeout", "quota", "cancelled"}
DEFAULT_FAIR_WAIT_SEC = 4 * 3600
CANCEL_SETTLE_SEC = 4.0
# Dead-runner reap (dispatch.sh doctor / task_queue_ops.py reap): the three conditions are
# unit not active, run.log quiet, result.env UPDATED old. Both ages are test seams.
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


REAP_LOG_QUIET_SEC = _env_int("AGENT_DISPATCH_REAP_LOG_QUIET_SEC", 120)
REAP_UPDATED_AGE_SEC = _env_int("AGENT_DISPATCH_REAP_UPDATED_AGE_SEC", 600)
REAP_CLEAR = ("WAITING", "WAKE_AT", "SLOT")

TOOLS_DIR = Path(os.environ.get("AGENT_DISPATCH_DIR", "/root/tools/agent-dispatch"))
TASKS_DIR = Path(os.environ.get("AGENT_DISPATCH_TASKS_DIR", "/root/logs/agent-dispatch"))
LOCK_DIR = Path(os.environ.get("AGENT_DISPATCH_LOCKDIR", "/root/logs/agent-dispatch"))
SYSTEMCTL = os.environ.get("AGENT_DISPATCH_SYSTEMCTL", "systemctl")
NOTIFY_CONF = Path(os.environ.get("AGENT_DISPATCH_NOTIFY_CONF", str(TOOLS_DIR / "notify.env")))
CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", "/root/.claude"))
OPENCODE_DB = Path(os.environ.get("AGENT_DISPATCH_OPENCODE_DB", "/root/.local/share/opencode/opencode.db"))
PRICES = Path(os.environ.get("AGENT_DISPATCH_PRICES", str(Path(__file__).resolve().with_name("model_prices.json"))))


class OpsError(Exception):
    def __init__(self, code: int, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def ops_version() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def file_sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return None


def unquote(raw: str) -> str:
    """One bash `printf %q` value: '' / $'…' / backslash escapes."""
    if raw == "''":
        return ""
    if raw.startswith("$'") and raw.endswith("'"):
        return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m[1], m[1]), raw[2:-1])
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    return re.sub(r"\\(.)", r"\1", raw)


def read_env(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if m:
            out[m[1]] = unquote(m[2])
    return out


def to_int(raw: str | None, default: int = 0) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def fair_wait_sec() -> int:
    env = os.environ.get("AGENT_DISPATCH_FAIR_WAIT_SEC")
    if env is not None:
        return to_int(env, DEFAULT_FAIR_WAIT_SEC)
    return to_int(read_env(TOOLS_DIR / "limits.env").get("QUEUE_FAIR_WAIT_SEC"), DEFAULT_FAIR_WAIT_SEC)


def task_dir(task_id: str) -> Path:
    if not ID_RE.match(task_id or ""):
        raise OpsError(2, f"not a task id: {task_id!r}")
    d = TASKS_DIR / task_id
    if not (d / "meta.env").is_file():
        raise OpsError(4, f"no task {task_id} (unknown, or already pruned)")
    return d


def unit_active(task_id: str) -> bool:
    try:
        r = subprocess.run([SYSTEMCTL, "is-active", f"agent-dispatch-{task_id}.service"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.stdout.strip() in ("active", "activating", "deactivating")


def audit(d: Path, source: str, action: str, detail: str) -> None:
    """One line per write in the task's own directory: who, when, what."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}\tsource={source}\taction={action}\t{detail}\tops={ops_version()}\n"
    with open(d / "audit.log", "a", encoding="utf-8") as f:
        f.write(line)


class TaskLock:
    """Serialises writes to one task (a double click must not become two cancels)."""

    def __init__(self, d: Path):
        self.path = d / ".ops.lock"
        self.fd = None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            raise OpsError(6, "another write to this task is still in progress; try again in a moment")
        return self

    def __exit__(self, *exc):
        os.close(self.fd)


# ---- queue --------------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def active_ids() -> frozenset[str]:
    """Ids of the active agent-dispatch-<id>.service units (empty when systemctl cannot say)."""
    try:
        out = subprocess.run([SYSTEMCTL, "list-units", "agent-dispatch-*", "--state=active", "--no-legend", "--plain"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    units = (line.split()[0] for line in out.splitlines() if line.strip())
    return frozenset(u[len("agent-dispatch-"):-len(".service")] for u in units
                     if u.startswith("agent-dispatch-") and u.endswith(".service"))


def unqueued_tasks(agent: str) -> list[dict]:
    """Live tasks of <agent> this entry cannot order: no RUNNER_API>=2 in result.env, so no
    registration, QUEUED_AT or override.env is honoured. Named, never dropped."""
    rows = []
    for tid in sorted(active_ids()):
        d = TASKS_DIR / tid
        if not ID_RE.match(tid) or read_env(d / "meta.env").get("AGENT") != agent:
            continue
        api = read_env(d / "result.env").get("RUNNER_API", "")
        if to_int(api, 0) < MIN_RUNNER_API:
            rows.append({"id": tid, "reason": f"RUNNER_API={api or 'missing'}: not started by the current runner, "
                                               "so it takes no part in this queue's order"})
    return rows


def queue_entries(agent: str) -> list[dict]:
    """Live waiters for <agent>'s lock, in queue order (see the module docstring)."""
    qdir = LOCK_DIR / ".queue" / agent
    now = int(time.time())
    fair = fair_wait_sec()
    rows = []
    try:
        names = sorted(os.listdir(qdir))
    except OSError:
        names = []
    for name in names:
        if name.startswith(".") or not ID_RE.match(name):
            continue
        entry = read_env(qdir / name)
        if not pid_alive(to_int(entry.get("PID"))):
            continue
        queued_at = to_int(entry.get("QUEUED_AT"), now)
        patrol = name.startswith("patrol-")
        priority = 0 if patrol else to_int(read_env(TASKS_DIR / name / "override.env").get("PRIORITY"))
        waited = max(0, now - queued_at)
        protected = (not patrol) and fair > 0 and waited >= fair
        rows.append({"id": name, "queued_at": queued_at, "priority": priority, "patrol": patrol,
                     "protected": protected, "waited_sec": waited})
    rows.sort(key=lambda r: (r["patrol"], not r["protected"],
                             0 if r["protected"] else -r["priority"], r["queued_at"], r["id"]))
    for i, r in enumerate(rows):
        r["position"] = i + 1
    return rows


def lock_holder(agent: str) -> dict:
    """Who holds <agent>'s lock: the runner's holder file when its PID lives; else, when the lock
    is held anyway, an explicit unnamed holder (never reported as free)."""
    h = read_env(LOCK_DIR / ".queue" / f"{agent}.holder")
    if h.get("ID") and pid_alive(to_int(h.get("PID"))):
        return {"held": True, "id": h["ID"], "since": to_int(h.get("SINCE"), 0) or None, "note": ""}
    free = {"held": False, "id": None, "since": None, "note": ""}
    lock = LOCK_DIR / f"{agent}.lock"
    if not lock.exists():
        return free
    fd = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return free
    except BlockingIOError:
        pass
    finally:
        os.close(fd)
    return {"held": True, "id": None, "since": None,
            "note": "held, but no live holder file names the task (one taking it right now, or not started by the current runner)"}


def quota_hint(agent: str) -> dict | None:
    """A quota wait some task of <agent> is in: other tasks wait for it instead of spending an attempt."""
    q = read_env(LOCK_DIR / ".queue" / f"{agent}.quota")
    until = to_int(q.get("UNTIL"))
    if until <= int(time.time()):
        return None
    return {"until": until, "by": q.get("BY", "")}


def cmd_version(_args) -> dict:
    return {"ok": True, "ops_version": ops_version(), "api": API}


def cmd_head(args) -> dict:
    if args.agent not in AGENTS:
        raise OpsError(2, f"unknown agent {args.agent!r}")
    rows = queue_entries(args.agent)
    unqueued = [r["id"] for r in unqueued_tasks(args.agent)]
    skipped = f"; not ordered (no RUNNER_API 2): {', '.join(unqueued)}" if unqueued else ""
    if rows:
        return {"ok": True, "agent": args.agent, "head": rows[0]["id"], "unqueued": unqueued, "note": skipped.lstrip("; ")}
    holder = lock_holder(args.agent)
    note = ("nobody waits; the lock is " + (f"held by {holder['id']}" if holder["id"] else "held by an unnamed task")
            if holder["held"] else "nobody waits and the lock is free")
    return {"ok": True, "agent": args.agent, "head": "", "unqueued": unqueued, "note": note + skipped}


def cmd_list(_args) -> dict:
    runner = TOOLS_DIR / "run-agent.sh"
    api = None
    try:
        m = re.search(r"^RUNNER_API=(\d+)", runner.read_text(errors="replace"), re.M)
        api = int(m[1]) if m else 1
    except OSError:
        pass
    agents = {}
    tasks = {}
    for agent in AGENTS:
        rows = queue_entries(agent)
        agents[agent] = {"holder": lock_holder(agent), "queue": rows, "quota": quota_hint(agent),
                         "unqueued": unqueued_tasks(agent)}
        for r in rows:
            tasks[r["id"]] = r
    return {
        "ok": True,
        "ops_version": ops_version(),
        "api": API,
        "fair_wait_sec": fair_wait_sec(),
        "runner": {"api": api, "sha": file_sha(runner)},
        "host_files": {name: file_sha(TOOLS_DIR / name) for name in ("run-agent.sh", "dispatch.sh", "limits.env",
                                                                   "opencode-fallback-models")},
        "agents": agents,
    }


def cmd_history(args) -> dict:
    """Read a small metadata index, then let callers fetch brief/log/result by id."""
    if not 1 <= args.limit <= 50:
        raise OpsError(2, "--limit must be between 1 and 50")
    if args.since:
        from datetime import date
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
                raise ValueError
            date.fromisoformat(args.since)
        except ValueError:
            raise OpsError(2, "--since takes a valid YYYY-MM-DD") from None
    before = None
    if args.before:
        d = task_dir(args.before)
        before = (read_env(d / "meta.env").get("CREATED", ""), d.name)
    terms = args.query.casefold().split()
    rows = []
    for meta_file in TASKS_DIR.glob("*/meta.env"):
        d = meta_file.parent
        if not ID_RE.fullmatch(d.name) or (d.name.startswith("patrol-") and not args.all):
            continue
        meta, result = read_env(meta_file), read_env(d / "result.env")
        created = meta.get("CREATED", "")
        if before is not None and (created, d.name) >= before:
            continue
        if args.since and created[:10] < args.since:
            continue
        state = result.get("STATE") or "pending"
        if args.agent and meta.get("AGENT") != args.agent:
            continue
        if args.state and state != args.state:
            continue
        if args.attention and (result.get("ATTENTION") or "unknown") != args.attention:
            continue
        searchable = " ".join((d.name, meta.get("NAME", ""), state, result.get("OUTCOME", ""))).casefold()
        if not all(term in searchable for term in terms):
            continue
        # Only the index fields: never prompts, session ids, origins or raw logs.
        row = {"id": d.name, "created": created, "name": meta.get("NAME", ""),
               "agent": meta.get("AGENT", ""), "state": state,
               "outcome": result.get("OUTCOME", ""),
               "attention": result.get("ATTENTION") or "unknown"}
        rows.append(row)
    rows.sort(key=lambda r: (r["created"], r["id"]), reverse=True)
    page = rows[:args.limit]
    more = len(rows) > args.limit
    # Keep every displayed field bounded and on one line, including legacy metadata.
    shown = [{k: " ".join(redact(v).split())[:240] for k, v in r.items()} for r in page]
    return {"ok": True, "tasks": shown, "has_more": more,
            "next_before": page[-1]["id"] if more else None,
            "note": "Metadata only; read brief, log or result by id. Pages are not a frozen snapshot."}


# ---- cancel -------------------------------------------------------------------------------

def resume_hint(meta: dict, session: str) -> str:
    if not session:
        return ""
    agent, cwd = meta.get("AGENT", ""), meta.get("CWD", "/root")
    if agent == "claude":
        return f"cd {cwd} && claude --resume {session}"
    if agent == "opencode":
        return f"cd {cwd} && opencode -s {session}"
    return f"cd {cwd} && codex resume {session}"


def cmd_cancel(args) -> dict:
    d = task_dir(args.id)
    meta = read_env(d / "meta.env")
    with TaskLock(d):
        result = read_env(d / "result.env")
        state = result.get("STATE", "")
        session = result.get("SESSION", "")
        if not unit_active(args.id):
            if state == "cancelled":
                return {"ok": True, "id": args.id, "state": state, "already": True, "session": session,
                        "resume": resume_hint(meta, session), "message": "already cancelled"}
            raise OpsError(3, f"task {args.id} has already ended (state={state or 'unknown'})", state=state)
        # Queued = nothing of this task has run yet: cancelling costs nothing. Anything else
        # stops live work; the session (when there is one) can be continued with --resume.
        waiting = result.get("WAITING", "")
        started = to_int(result.get("ATTEMPTS")) > 0
        was = "queued" if not started and waiting in ("lock", "slot", "memory", "") and not result.get("SLOT") else "running"
        if waiting in ("quota", "retry", "later"):
            was = "sleeping"
        marker = d / "cancel-requested"
        if marker.exists() and time.time() - marker.stat().st_mtime < 30:
            # A repeat while the unit winds down: no second stop, and the answer says whether the
            # first one has already landed (the runner writes its terminal state before it exits).
            return {"ok": True, "id": args.id, "state": state, "pending": state not in TERMINAL, "was": was,
                    "session": session, "resume": resume_hint(meta, session),
                    "message": "already cancelled" if state in TERMINAL else "cancel already requested"}
        # Same lock as the runner's final launch decision: a committed cancel
        # prevents every later launch, including quota and retry continuations.
        with open(d / ".launch.lock", "a") as launch_lock:
            fcntl.flock(launch_lock, fcntl.LOCK_EX)
            marker.write_text(time.strftime("%Y-%m-%d %H:%M:%S") + f" {args.source}\n")
        try:
            r = subprocess.run([SYSTEMCTL, "stop", "--no-block", f"agent-dispatch-{args.id}.service"],
                               capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            audit(d, args.source, "cancel", f"failed: {e}")
            raise OpsError(5, f"systemctl stop failed: {e}")
        if r.returncode != 0:
            audit(d, args.source, "cancel", f"failed: rc={r.returncode} {r.stderr.strip()[:200]}")
            raise OpsError(5, f"systemctl refused to stop the task: {r.stderr.strip() or r.returncode}")
        deadline = time.time() + CANCEL_SETTLE_SEC
        while time.time() < deadline:
            state = read_env(d / "result.env").get("STATE", state)
            if state in TERMINAL:
                break
            time.sleep(0.25)
        session = read_env(d / "result.env").get("SESSION", session)
        audit(d, args.source, "cancel", f"was={was} state={state} session={session or '-'}")
        return {"ok": True, "id": args.id, "state": state, "pending": state not in TERMINAL, "was": was,
                "session": session, "resume": resume_hint(meta, session),
                "progress_lost": was != "queued",
                "message": ("cancelled before it started" if was == "queued"
                            else "stopped; the current step's unsaved progress is lost"
                            + (f"; continue with: {resume_hint(meta, session)}" if session else ""))}


# ---- dead runners: mark once, never retry ---------------------------------------------------
# A runner is a transient systemd unit. TERM runs its finish path, but SIGKILL/OOM/reboot leaves
# result.env at running/queued with the lock already released and no notice: the task looks alive
# forever. The reaper only records the fact (STATE=failed, FAILURE_REASON/STOP_REASON=runner_gone,
# ATTENTION=person, STAGE=ended) and notifies once; it never deletes the directory, releases a
# lock (a dead process already did) or retries. A person decides between `result` and `retry`.
#
# The three conditions keep a live runner safe: `systemctl is-active` excludes a starting or
# restarting unit, a run.log written within REAP_LOG_QUIET_SEC excludes an orphan child still
# writing, and result.env UPDATED older than REAP_UPDATED_AGE_SEC excludes a task that has just
# started. Before writing, UPDATED is re-read under the task lock (CAS), so a runner that wrote
# between the scan and the write wins. `.reaped` makes the notice once per task.

def _unit_gone(task_id: str) -> bool:
    """True only when systemctl answered that the unit is not active; an error is 'unknown'."""
    try:
        r = subprocess.run([SYSTEMCTL, "is-active", f"agent-dispatch-{task_id}.service"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode in (0, 3, 4) and r.stdout.strip() in ("inactive", "failed", "unknown")


def _stamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _update_result(d: Path, values: dict[str, str], clear: tuple[str, ...] = ()) -> None:
    """Replace/add KEY=value lines without executing the file (quoting is bash-safe)."""
    try:
        lines = (d / "result.env").read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    seen = set()
    out = []
    for line in lines:
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
        key = m[1] if m else ""
        if key in values:
            out.append(f"{key}={shlex.quote(str(values[key]))}")
            seen.add(key)
        elif key in clear:
            out.append(f"{key}=''")
            seen.add(key)
        else:
            out.append(line)
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={shlex.quote(str(value))}")
    for key in clear:
        if key not in seen:
            out.append(f"{key}=''")
    tmp = d / ".reap-result.tmp"
    tmp.write_text("\n".join(out) + "\n")
    os.replace(tmp, d / "result.env")


def _notify_legs(meta: dict, text: str) -> tuple[str, str, str]:
    """Send one message on each configured leg, in parallel. Never raises."""
    raw = (meta.get("NOTIFY") or "").split(",")
    legs = []
    for leg in raw:
        leg = leg.strip().lower()
        if leg and leg != "none" and leg not in legs:
            legs.append(leg)
    if not legs:
        return "", "", ""
    conf = read_env(NOTIFY_CONF)
    binary = os.environ.get("AGENT_DISPATCH_OPENCLAW_BIN") or shutil.which("openclaw") or "openclaw"
    targets = {"weixin": (conf.get("NOTIFY_CHANNEL", ""), conf.get("NOTIFY_TARGET", "")),
               "telegram": (conf.get("TELEGRAM_CHANNEL", "telegram"), conf.get("TELEGRAM_TARGET", ""))}

    def send(leg: str) -> tuple[str, bool, str]:
        channel, target = targets.get(leg, ("", ""))
        if not channel or not target:
            return leg, False, "target not configured"
        try:
            r = subprocess.run([binary, "message", "send", "--channel", channel, "--target", target, "-m", text],
                               capture_output=True, text=True, timeout=60)
            return leg, r.returncode == 0, (r.stderr or "").strip()[-200:] if r.returncode else ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            return leg, False, str(exc)[:200]

    with ThreadPoolExecutor(max_workers=len(legs)) as pool:
        results = list(pool.map(send, legs))
    ok = [leg for leg, good, _ in results if good]
    bad = [leg for leg, good, _ in results if not good]
    return ",".join(ok), ",".join(bad), time.strftime("%Y-%m-%d %H:%M:%S")


def reap_notice(meta: dict, task_id: str, log_quiet: int, age: int) -> str:
    name = meta.get("NAME") or task_id
    agent = meta.get("AGENT") or "?"
    return (f"⚠️ 委派任务 {name}（{agent}）的 runner 不在了：unit 不是 active，run.log 已静默 "
            f"{log_quiet // 60} 分钟，结果已 {age // 60} 分钟没更新。\n"
            f"已标 failed/runner_gone，不会自动重试，也没有删任务目录。\n"
            f"查看：/root/tools/agent-dispatch/dispatch.sh result {task_id}\n"
            f"重试：python3 /root/tools/agent-dispatch/task_queue_ops.py retry {task_id}")[:900]


def cmd_reap(args) -> dict:
    now = time.time()
    reaped, skipped = [], {}

    def skip(reason: str, d: Path) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1
        if args.dry_run:
            print(f"would skip {d.name}: {reason}", file=sys.stderr)

    for meta_file in sorted(TASKS_DIR.glob("*/meta.env")):
        d = meta_file.parent
        if not ID_RE.fullmatch(d.name):
            continue
        if (d / ".reaped").exists():
            skip("already_reaped", d)
            continue
        meta, result = read_env(meta_file), read_env(d / "result.env")
        state = result.get("STATE") or "pending"
        if state in TERMINAL:
            continue
        if state not in ("running", "queued", "pending"):
            skip(f"state_{state}", d)
            continue
        if not _unit_gone(d.name):
            skip("unit_active", d)
            continue
        log_quiet = int(now - (_stamp(d / "run.log") if (d / "run.log").exists() else _stamp(d)))
        if log_quiet < REAP_LOG_QUIET_SEC:
            skip("log_recent", d)
            continue
        updated = stamp_epoch(result.get("UPDATED", "")) or stamp_epoch(meta.get("CREATED", "")) or int(_stamp(d))
        age = int(now - updated)
        if age < REAP_UPDATED_AGE_SEC:
            skip("updated_recent", d)
            continue
        row = {"id": d.name, "name": meta.get("NAME", ""), "agent": meta.get("AGENT", ""),
               "state": state, "log_quiet_sec": log_quiet, "updated_age_sec": age}
        if args.dry_run:
            reaped.append(row | {"dry_run": True})
            continue
        try:
            with TaskLock(d):
                if (d / ".reaped").exists():
                    skip("already_reaped", d)
                    continue
                current = read_env(d / "result.env")
                if current.get("STATE") in TERMINAL:
                    skip("state_changed", d)
                    continue
                if current.get("UPDATED", "") != result.get("UPDATED", ""):
                    skip("updated_changed", d)
                    continue
                if not _unit_gone(d.name):
                    skip("unit_active", d)
                    continue
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                _update_result(d, {"STATE": "failed", "FAILURE_REASON": "runner_gone",
                                   "STOP_REASON": "runner_gone", "ATTENTION": "person",
                                   "STAGE": "ended", "UPDATED": stamp, "REAPED_AT": stamp},
                               REAP_CLEAR)
                audit(d, args.source, "reap", f"runner_gone: unit inactive, log quiet {log_quiet}s, "
                                              f"UPDATED {age}s old")
                # A runner killed during a later wait leaves a wait file that can never fire.
                for name in ("later.json", "later-prompt.txt"):
                    try:
                        (d / name).unlink()
                    except OSError:
                        pass
                (d / ".reaped").write_text(f"{stamp} source={args.source}\n")
                ok, bad, at = _notify_legs(meta, reap_notice(meta, d.name, log_quiet, age))
                _update_result(d, {"NOTIFIED": ok, "NOTIFY_FAILED": bad, "NOTIFY_AT": at,
                                   "NOTICE": "none" if not ok and not bad else "attempted"})
                row |= {"notified": ok, "notify_failed": bad, "reaped_at": stamp}
                reaped.append(row)
        except OpsError as exc:
            if exc.code == 6:
                skip("busy", d)
                continue
            raise
    return {"ok": True, "dry_run": bool(args.dry_run), "thresholds": {
                "log_quiet_sec": REAP_LOG_QUIET_SEC, "updated_age_sec": REAP_UPDATED_AGE_SEC},
            "reaped": reaped, "skipped": skipped}


# ---- override.env: priority, model, effort ------------------------------------------------
# Plain KEY=VALUE lines, values restricted to VALUE_RE (the runner re-checks them), written
# atomically. meta.env stays the record of what was dispatched; this file is what changed since.

OVERRIDE_KEYS = ("PRIORITY", "MODEL", "EFFORT", "DEADLINE_EPOCH", "MAX_ATTEMPTS", "QUOTA_RESUMES")


def read_override(d: Path) -> dict[str, str]:
    return {k: v for k, v in read_env(d / "override.env").items() if k in OVERRIDE_KEYS}


def write_override(d: Path, values: dict[str, str]) -> None:
    body = "".join(f"{k}={v}\n" for k, v in values.items() if v != "")
    tmp = d / ".override.env.tmp"
    tmp.write_text(body)
    os.replace(tmp, d / "override.env")


def live_task(d: Path, task_id: str, action: str) -> tuple[dict, dict]:
    """meta and result of a task a steering action may touch; refuses ended tasks and tasks without
    RUNNER_API 2 (their runner would ignore override.env and the queue order)."""
    meta, result = read_env(d / "meta.env"), read_env(d / "result.env")
    if not unit_active(task_id):
        raise OpsError(3, f"task {task_id} has already ended (state={result.get('STATE') or 'unknown'}); {action} no longer applies",
                       state=result.get("STATE", ""))
    if to_int(result.get("RUNNER_API"), 1) < MIN_RUNNER_API:
        raise OpsError(3, f"task {task_id} has no RUNNER_API 2 in its result.env: its runner ignores {action}; "
                          "it keeps its current order and model until it ends")
    return meta, result


def cmd_ack(args) -> dict:
    """Dismiss a finished task's NEEDS. Writes only needs-ack.json (time, operator,
    source); never result.env, the state or the task service. Idempotent."""
    d = task_dir(args.id)
    result = read_env(d / "result.env")
    if result.get("STATE") not in TERMINAL:
        raise OpsError(3, f"task {args.id} has not ended (state={result.get('STATE') or 'unknown'})")
    if not (result.get("NEEDS") or "").strip():
        raise OpsError(3, f"task {args.id} has no NEEDS to dismiss")
    with TaskLock(d):
        path = d / "needs-ack.json"
        if path.exists():
            return {"ok": True, "id": args.id, "already": True, "message": "already dismissed"}
        payload = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "by": args.by or os.environ.get("USER", "") or "unknown",
                   "source": args.source}
        tmp = d / f".needs-ack.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        audit(d, args.source, "ack", "dismissed NEEDS")
        return {"ok": True, "id": args.id, "already": False, "ack": payload, "message": "NEEDS dismissed"}


def cmd_priority(args) -> dict:
    d = task_dir(args.id)
    with TaskLock(d):
        meta, result = live_task(d, args.id, "priority")
        agent = meta.get("AGENT", "")
        if args.id.startswith("patrol-"):
            raise OpsError(3, "patrol rounds always go last; their priority cannot be changed")
        if result.get("SLOT") or (to_int(result.get("ATTEMPTS")) > 0 and result.get("WAITING") in ("", "slot")):
            raise OpsError(3, f"task {args.id} is already running; priority only orders tasks waiting for the {agent} lock")
        rows = queue_entries(agent)
        me = next((r for r in rows if r["id"] == args.id), None)
        if me is None:
            # Asleep on quota/retry: not in the queue now; the value applies when it re-queues.
            me = {"id": args.id, "priority": to_int(read_override(d).get("PRIORITY")), "patrol": False,
                  "protected": False, "queued_at": to_int(result.get("QUEUED_AT"), int(time.time()))}
            rows = rows + [me]
        if me["protected"] and args.value != "reset":
            return {"ok": True, "id": args.id, "changed": False, "queue": [r["id"] for r in queue_entries(agent)],
                    "message": f"{args.id} has waited past the fair wait: it already goes before every unprotected task, in arrival order"}
        movable = [r for r in rows if not r["patrol"] and not r["protected"]]
        movable.sort(key=lambda r: (-r["priority"], r["queued_at"], r["id"]))
        new: dict[str, int] = {}
        value = args.value
        if value == "top":
            others = [r["priority"] for r in movable if r["id"] != args.id]
            new[args.id] = max([0, *others]) + 1 if others else max(me["priority"], 0)
        elif value in ("up", "down"):
            ids = [r["id"] for r in movable]
            i = ids.index(args.id)
            j = i - 1 if value == "up" else i + 1
            if j < 0 or j >= len(ids):
                return {"ok": True, "id": args.id, "changed": False, "queue": [r["id"] for r in queue_entries(agent)],
                        "message": f"{args.id} is already {'first' if value == 'up' else 'last'} among the tasks that can be reordered"}
            ids[i], ids[j] = ids[j], ids[i]
            # Renumber the reorderable waiters so exactly this swap happens (a new arrival, priority 0,
            # still lands behind all of them).
            for k, tid in enumerate(ids):
                new[tid] = len(ids) - 1 - k
        elif value == "reset":
            new[args.id] = 0
        else:
            if not re.fullmatch(r"-?\d{1,2}", value):
                raise OpsError(2, f"priority takes an integer {PRIORITY_RANGE[0]}..{PRIORITY_RANGE[1]}, top, up, down or reset (got {value!r})")
            new[args.id] = int(value)
        changed = []
        for tid, prio in new.items():
            td = TASKS_DIR / tid
            ov = read_override(td)
            old = to_int(ov.get("PRIORITY"))
            if old == prio and (prio != 0 or "PRIORITY" not in ov):
                continue
            ov["PRIORITY"] = "" if prio == 0 else str(prio)
            write_override(td, ov)
            detail = f"priority {old}->{prio}" + ("" if tid == args.id else f" (reorder: {args.id} {value})")
            audit(td, args.source, "priority", detail)
            changed.append({"id": tid, "from": old, "to": prio})
        order = [r["id"] for r in queue_entries(agent)]
        return {"ok": True, "id": args.id, "changed": bool(changed), "changes": changed, "queue": order,
                "position": order.index(args.id) + 1 if args.id in order else None,
                "message": f"{agent} queue: " + " > ".join(order) if order else "saved; applies when the task queues again"}


@functools.lru_cache(maxsize=1)
def claude_help() -> str:
    try:
        return subprocess.run(["claude", "--help"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def claude_efforts() -> list[str]:
    text = claude_help()
    m = re.search(r"--effort <level>[^(]*\(([a-z, ]+)\)", text)
    return [e.strip() for e in m[1].split(",")] if m else []


def claude_aliases() -> list[str]:
    text = claude_help()
    m = re.search(r"--model <model>(.*?)\n\s+-", text, re.S)
    return re.findall(r"'([a-z0-9.-]+)'", m[1]) if m else []


def dispatch_default(agent: str) -> str:
    try:
        text = (TOOLS_DIR / "dispatch.sh").read_text()
    except OSError:
        return ""
    m = re.search(rf"^\s*{agent}\) MODEL=\$\{{MODEL:-([^}}]+)\}}", text, re.M)
    return m[1] if m else ""


def models_seen(agent: str, limit: int = 400) -> list[str]:
    """Models this host's tasks of <agent> were dispatched with or ran on (newest dirs first)."""
    seen: list[str] = []
    try:
        dirs = sorted((p for p in TASKS_DIR.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    except OSError:
        return seen
    for p in dirs:
        meta = read_env(p / "meta.env")
        if meta.get("AGENT") != agent:
            continue
        for m in (meta.get("MODEL", ""), read_env(p / "result.env").get("MODEL_USED", "")):
            if m and VALUE_RE.match(m) and m not in seen:
                seen.append(m)
    return seen


def codex_models() -> dict[str, list[str]]:
    home = Path(os.environ.get("CODEX_HOME", "/root/.codex"))
    try:
        data = json.loads((home / "models_cache.json").read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for m in data.get("models", []) if isinstance(data, dict) else []:
        if m.get("slug") and m.get("visibility", "list") == "list":
            out[m["slug"]] = [e.get("effort") for e in m.get("supported_reasoning_levels", []) if e.get("effort")]
    return out


def pool_models() -> list[str]:
    try:
        lines = (TOOLS_DIR / "opencode-fallback-models").read_text().splitlines()
    except OSError:
        return []
    return [w for line in lines for w in line.split("#", 1)[0].split()]


def task_choices(meta: dict, result: dict) -> dict:
    """What `model` accepts for this task. Every list comes from the agent's own source of truth:
    claude --help (efforts, aliases), codex's models_cache.json (models and their efforts), the
    opencode pool file; plus the task's own models and those this host has dispatched before."""
    agent = meta.get("AGENT", "")
    own = [m for m in (meta.get("MODEL", ""), *meta.get("FALLBACK_MODELS", "").split(",")) if m]
    if agent == "claude":
        models = list(dict.fromkeys([*own, dispatch_default("claude"), *models_seen("claude"), *claude_aliases()]))
        efforts = {m: claude_efforts() for m in models if m}
        flag = "--effort"
    elif agent == "codex":
        cache = codex_models()
        models = list(dict.fromkeys([*own, dispatch_default("codex"), *cache]))
        efforts = {m: cache.get(m, []) for m in models if m}
        flag = "model_reasoning_effort"
    elif agent == "dsh":
        # <provider>/<model> routes of dsh's headless profile; the runner's overlay applies a change
        # to the next attempt, a resumed session included (checked 2026-10-17 on dsh 0.2.1-rc.2).
        models = list(dict.fromkeys([*own, dispatch_default("dsh"), *models_seen("dsh"), *DSH_ROUTES]))
        efforts = {m: DSH_EFFORTS for m in models if m}
        flag = "reasoningEffort"
    else:
        models = list(dict.fromkeys([*own, *pool_models()]))
        # v2 carries a variant inside the model reference (`provider/model#variant`); the pool
        # checks do not select one, so no effort is offered unless a model is changed explicitly.
        efforts = {m: [] for m in models if m}
        flag = "#variant"
    return {"agent": agent, "models": [m for m in models if m], "efforts": efforts, "effort_flag": flag}


def cmd_choices(args) -> dict:
    d = task_dir(args.id)
    meta, result = read_env(d / "meta.env"), read_env(d / "result.env")
    ov = read_override(d)
    out = {"ok": True, "id": args.id, **task_choices(meta, result),
           "requested": {"model": ov.get("MODEL") or meta.get("MODEL", ""), "effort": ov.get("EFFORT") or meta.get("EFFORT", "")},
           "used": {"model": result.get("MODEL_USED", ""), "effort": result.get("EFFORT_USED", "")},
           "override": ov}
    try:
        live_task(d, args.id, "a model change")
        refusal = model_refusal(meta, result)
    except OpsError as e:
        refusal = e.message
    out["allowed"] = refusal is None
    out["reason"] = refusal or ""
    return out


def model_refusal(meta: dict, result: dict) -> str | None:
    if meta.get("ID", "").startswith("patrol-"):
        return "patrol rounds pick their models from the pool file"
    if meta.get("AGENT") == "codex" and result.get("SESSION"):
        # Not verified: codex's weekly quota was out when this was built (2026-09-26). claude
        # (`--resume` with another --model, checked) and opencode (-s on the next pool model, the
        # fallback path of every patrol round) are.
        return "switching a codex session's model on resume is unverified; only a codex task that has not started can change it"
    return None


def cmd_model(args) -> dict:
    d = task_dir(args.id)
    with TaskLock(d):
        meta, result = live_task(d, args.id, "a model change")
        refusal = model_refusal(meta, result)
        if refusal:
            raise OpsError(3, refusal)
        choices = task_choices(meta, result)
        ov = read_override(d)
        before = dict(ov)
        if args.model == "default":
            ov["MODEL"] = ""
        elif args.model != "keep":
            if args.model not in choices["models"]:
                raise OpsError(2, f"{args.model!r} is not a {choices['agent']} model this host knows: {', '.join(choices['models'])}")
            ov["MODEL"] = "" if args.model == meta.get("MODEL") else args.model
        model_next = ov.get("MODEL") or meta.get("MODEL", "")
        if args.effort == "default":
            ov["EFFORT"] = ""
        elif args.effort not in ("keep", None):
            allowed = choices["efforts"].get(model_next, [])
            if args.effort not in allowed:
                raise OpsError(2, f"{args.effort!r} is not an effort {model_next} accepts ({choices['effort_flag']}: "
                                  f"{', '.join(allowed) or 'none — this model takes no effort setting'})")
            ov["EFFORT"] = "" if args.effort == meta.get("EFFORT") else args.effort
        effort_next = ov.get("EFFORT") or meta.get("EFFORT", "")
        if ov == before:
            return {"ok": True, "id": args.id, "changed": False, "model_next": model_next, "effort_next": effort_next,
                    "message": "nothing to change"}
        write_override(d, ov)
        audit(d, args.source, "model", f"model {before.get('MODEL') or '-'}->{ov.get('MODEL') or '-'} "
                                         f"effort {before.get('EFFORT') or '-'}->{ov.get('EFFORT') or '-'}")
        running = bool(result.get("SLOT"))
        return {"ok": True, "id": args.id, "changed": True, "applies": "next_attempt", "running": running,
                "model_next": model_next, "effort_next": effort_next,
                "message": (f"next attempt: {model_next}{'/' + effort_next if effort_next else ''}"
                            + ("; the attempt running now keeps its model" if running else ""))}


# ---- session actions (through dispatch.sh, which owns them) ----------------------------------

def dispatch(argv: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([str(TOOLS_DIR / "dispatch.sh"), *argv], input=stdin, capture_output=True,
                              text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OpsError(5, f"dispatch.sh failed: {e}")


CONTINUE_TEXT = ("重试：上一轮没有做完（失败、超时或被取消）。先检查当前真实状态（git/PR/CI/文件），复用已有产物，"
                 "不要重复已完成的步骤，继续完成原任务。结束时按原要求输出 STATUS 行。")


def cmd_retry(args) -> dict:
    d = task_dir(args.id)
    with TaskLock(d):
        result = read_env(d / "result.env")
        if unit_active(args.id):
            raise OpsError(3, f"task {args.id} is still running; append to it instead of retrying")
        state = result.get("STATE", "")
        if state == "ok" and result.get("OUTCOME") in ("DONE", ""):
            raise OpsError(3, f"task {args.id} finished (state=ok); append a new instruction instead of retrying")
        if not result.get("SESSION"):
            raise OpsError(3, f"task {args.id} ended without a session to continue; dispatch it again")
        r = dispatch(["append", args.id], CONTINUE_TEXT)
        m = re.search(r"^dispatched (\S+)", r.stdout, re.M)
        audit(d, args.source, "retry", f"rc={r.returncode} new={m[1] if m else '-'}")
        if r.returncode != 0:
            raise OpsError(3 if r.returncode == 3 else 5, (r.stderr or r.stdout).strip()[-400:] or f"dispatch.sh append exited {r.returncode}")
        return {"ok": True, "id": args.id, "new_id": m[1] if m else "", "session": result.get("SESSION", ""),
                "message": f"continuing session {result.get('SESSION')} as {m[1] if m else 'a new task'}"}


def cmd_append(args) -> dict:
    d = task_dir(args.id)
    text = sys.stdin.read() if args.text is None else args.text
    if not text.strip():
        raise OpsError(2, "empty instruction")
    if len(text) > 20000:
        raise OpsError(2, "instruction longer than 20000 characters")
    with TaskLock(d):
        live = unit_active(args.id)
        if not live:
            raise OpsError(3, f"task {args.id} has already ended; use retry (or dispatch.sh append) to continue its session")
        r = dispatch(["append", args.id, "--require-active", *(["--queue"] if args.queue else [])], text)
        audit(d, args.source, "append", f"mode={'queue' if args.queue else 'now'} chars={len(text)} rc={r.returncode}")
        if r.returncode != 0:
            raise OpsError(3 if r.returncode == 3 else 5, (r.stderr or r.stdout).strip()[-400:] or f"dispatch.sh append exited {r.returncode}")
        receipt = next((json.loads(line[9:]) for line in r.stdout.splitlines() if line.startswith("receipt: ")), {})
        return {"ok": True, "id": args.id, "mode": "queue" if args.queue else "now", "message": r.stdout.strip(),
                **receipt}


def redact(text: str) -> str:
    for pattern, repl in REDACT:
        text = pattern.sub(repl, text)
    return text


def task_timeline(d: Path) -> dict:
    """Read supervisor events on demand, never model/tool prose or an invented state history.

    Head + tail are bounded for a large log. Missing intervals and missing logs are explicit;
    result.UPDATED is a write stamp, not an end event (notification writes change it too).
    """
    events = []

    def add(stamp: str, kind: str, text: str) -> None:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", stamp):
            events.append({"stamp": stamp, "kind": kind, "text": redact(text)[:600]})

    meta = read_env(d / "meta.env")
    add(meta.get("CREATED", ""), "created", "")
    # 2 MiB head + 2 MiB tail; small files are read only once. Split boundary fragments
    # are discarded so a model output fragment cannot become a supervisor event.
    limit, omitted, missing = 2 * 1024 * 1024, 0, False
    try:
        with (d / "run.log").open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size <= limit * 2:
                chunks = [f.read(limit * 2).decode("utf-8", "replace")]
            else:
                head = f.read(limit).decode("utf-8", "replace").rsplit("\n", 1)[0]
                f.seek(size - limit)
                tail = f.read(limit).decode("utf-8", "replace").split("\n", 1)[-1]
                chunks = [head, tail]
                omitted = size - len(head.encode()) - len(tail.encode())
    except OSError:
        chunks, missing = [], True
    patterns = (
        (r"waiting for .+ lock \(", "lock_wait"),
        (r"lock held$", "lock_acquired"),
        (r"waiting for a .+ run slot", "slot_wait"),
        (r"waiting: ", "memory_wait"),
        (r"got run slot ", "slot_acquired"),
        (r"queue: ", "queue"),
        (r"attempt \d+/\d+ ", "attempt"),
        (r"attempt \d+ \(.+\) rc=", "attempt_end"),
        (r"(?:quota: .*sleeping until|quota; sleeping until|released .* quota wait)", "quota"),
        (r"\w+; sleeping until", "retry_wait"),
        (r"no progress for ", "stall"),
        (r"delivering appended instruction\(s\):$", "append_delivered"),
        (r"(?:appended instruction:|finished with appended instruction)", "append_resume"),
        (r"(?:override:|budget:|switching to model )", "change"),
    )
    for chunk in chunks:
        pending_drops = []
        for line in chunk.splitlines():
            boundary = re.fullmatch(r"=+ (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \S+ (start|end state=.+) =+", line)
            if boundary:
                if boundary[2].startswith("end state="):
                    for drop in pending_drops:
                        add(boundary[1], "append_dropped", drop + " (recorded at task end)")
                pending_drops = []
                add(boundary[1], "started" if boundary[2] == "start" else "ended", "" if boundary[2] == "start" else boundary[2])
                continue
            if re.fullmatch(r"inbox: \d+ appended message\(s\) (?:taken by a run that never started; )?not delivered", line):
                pending_drops.append(line)
                continue
            m = re.match(r"^(?:---- )?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.+)$", line)
            if m:
                for pattern, kind in patterns:
                    if re.match(pattern, m[2]):
                        add(m[1], kind, m[2])
                        break
    # Submission time comes from the immutable append filename, not its mtime. Delivered
    # is today's file location; its actual delivery event above has the supervisor timestamp.
    entries = list((d / "inbox").glob("*.md")) + list((d / "inbox" / "delivered").glob("*.md"))
    for f in sorted(entries, key=lambda f: f.name):
        m = re.match(r"^(\d{8})-(\d{6})", f.name)
        if m:
            stamp = f"{m[1][:4]}-{m[1][4:6]}-{m[1][6:]} {m[2][:2]}:{m[2][2:4]}:{m[2][4:]}"
            add(stamp, "append_submitted", f.name)
    audit, _, audit_cut = capped(d / "audit.log", 262144)
    for line in audit.splitlines():
        m = re.match(r"^(.*?)\tsource=(.*?)\taction=(.*?)\t(.*?)\tops=", line)
        if m and m[3] != "append":  # append submission is already represented by its file
            add(m[1], "change", f"{m[3]} ({m[2]}): {m[4]}")
    result = read_env(d / "result.env")
    receipts = result.get("NOTIFIED", "") or result.get("NOTIFY_FAILED", "")
    if receipts:
        add(result.get("NOTIFY_AT", ""), "notification", f"sent={result.get('NOTIFIED') or '-'} failed={result.get('NOTIFY_FAILED') or '-'}")
    events.sort(key=lambda e: e["stamp"])
    total = len(events)
    # Keep both ends and state the omitted event count; no hidden preselection by mtime.
    if total > 200:
        events = events[:100] + events[-100:]
    return {"events": events, "omitted_bytes": max(0, omitted), "omitted_events": max(0, total - 200),
            "audit_truncated": audit_cut, "log_missing": missing}


def _one_line(value, limit: int = 240) -> str:
    return " ".join(redact(str(value or "")).split())[:limit]


_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def _safe_text(value, limit: int = 300) -> str:
    """Redacted log text with session ids shortened (the full id stays in the session file)."""
    text = _UUID.sub(lambda m: m[0][:8] + "…", str(value or ""))
    text = re.sub(r"\bsession=([^\s]+)", lambda m: "session=" + m[1][:8] + ("…" if len(m[1]) > 8 else ""), text)
    return _one_line(text, limit)


def _session_hint(value: str) -> str:
    """A chat/session key without its peer id: the first four colon-separated parts."""
    parts = (value or "").split(":")
    if len(parts) > 4:
        return ":".join(parts[:4]) + ":…"
    return value or ""


def _epoch_text(raw: str) -> str:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def cmd_why(args) -> dict:
    """One page: who dispatched, what authorized it, every run/append/wait, and the result.

    Read-only and deliberately bounded: no prompt, log body, transcript or secret. Session
    keys keep a short prefix; the full report is still `result`.
    """
    d = task_dir(args.id)
    meta, result = read_env(d / "meta.env"), read_env(d / "result.env")
    mandate = read_json_object(d / "mandate.json")
    selection = read_json_object(d / "free-pool-selection.json")
    timeline = task_timeline(d)
    models = {}
    for event in timeline["events"]:
        if event.get("kind") != "attempt":
            continue
        m = re.search(r"attempt (\d+)/\d+ \(([^)]+)\).*?model=([^ ]+)", event.get("text", ""))
        if m:
            models.setdefault(int(m[1]), {"kind": m[2], "model": m[3], "stamp": event["stamp"]})

    runs = []
    attempt_files = []
    for path in d.glob("attempt*.env"):
        m = re.fullmatch(r"attempt(\d+)\.env", path.name)
        if m:
            attempt_files.append((int(m[1]), path))
    for run_no, path in sorted(attempt_files):
        rec = read_env(path)
        started = rec.get("STARTED_EPOCH", "")
        ended = rec.get("ENDED_EPOCH", "")
        try:
            duration = int(float(ended) - float(started)) if started and ended else None
        except ValueError:
            duration = None
        info = models.get(run_no, {})
        runs.append({"run_no": run_no, "kind": rec.get("KIND", ""), "started": bool(started),
                     "started_at": _epoch_text(started), "ended_at": _epoch_text(ended),
                     "rc": to_int(rec.get("RC"), None), "result": rec.get("AKIND", ""),
                     "model": info.get("model", ""), "duration_sec": duration})

    appends = []
    entries = [(f, False) for f in (d / "inbox").glob("*.md")] +               [(f, True) for f in (d / "inbox" / "delivered").glob("*.md")]
    for path, delivered in sorted(entries, key=lambda item: item[0].name):
        m = re.match(r"^(\d{8})-(\d{6})", path.name)
        stamp = f"{m[1][:4]}-{m[1][4:6]}-{m[1][6:]} {m[2][:2]}:{m[2][2:4]}:{m[2][4:]}" if m else ""
        run_no = None
        run_started = None
        if delivered:
            try:
                run_no = int(path.with_name(path.name + ".run").read_text().strip())
            except (OSError, ValueError):
                run_no = None
            if run_no is not None:
                rec = read_env(d / f"attempt{run_no}.env")
                run_started = bool(rec.get("STARTED_EPOCH"))
        if not delivered and result.get("STATE") in TERMINAL:
            disposition = "not_delivered"
        elif not delivered:
            disposition = "pending"
        elif run_no is None:
            disposition = "taken_legacy"
        elif run_started:
            disposition = "attached_to_run"
        else:
            disposition = "taken_not_started"
        appends.append({"stamp": stamp, "file": path.name, "run_no": run_no,
                        "disposition": disposition})

    wake = {}
    for event in ("quota", "end"):
        data = read_json_object(d / f"wake-{event}.json")
        if data:
            wake[event] = {"state": data.get("state", ""), "attempts": to_int(data.get("attempts")),
                           "last_error": _safe_text(data.get("last_error"), 160)}

    question = read_json_object(d / "question.json")
    answer = read_json_object(d / "answer.json")
    later = read_json_object(d / "later.json")
    later_history = [read_json_object(p) for p in sorted(d.glob("later-*.json"), reverse=True)[:3]]
    later_history = [item for item in later_history if item]

    try:
        audit_lines = (d / "audit.log").read_text(errors="replace").splitlines()[-20:]
    except OSError:
        audit_lines = []

    summary = ""
    try:
        summary = next((line for line in (d / "runner-summary.txt").read_text(errors="replace").splitlines()
                        if line.strip()), "")
    except OSError:
        pass

    return {
        "ok": True, "id": d.name,
        "task": {"id": d.name, "name": meta.get("NAME", ""), "agent": meta.get("AGENT", ""),
                 "created": meta.get("CREATED", ""), "started": result.get("STARTED", ""),
                 "finished_epoch": result.get("FINISHED_EPOCH", ""),
                 "state": result.get("STATE") or "pending", "outcome": result.get("OUTCOME", ""),
                 "stop_reason": result.get("STOP_REASON", ""), "failure_reason": result.get("FAILURE_REASON", "")},
        "dispatch": {"origin": _session_hint(meta.get("ORIGIN_SESSION", "")),
                     "parent": meta.get("PARENT_TASK_ID", ""), "answer_of": meta.get("ANSWER_OF", ""),
                     "wake_depth": to_int(meta.get("WAKE_DEPTH"))},
        "mandate": ({"actions": mandate.get("actions", {}), "source_kind": (mandate.get("source") or {}).get("kind", ""),
                     "source_id": _session_hint((mandate.get("source") or {}).get("id", "")),
                     "strength": mandate.get("strength", ""), "policy_version": mandate.get("policy_version", ""),
                     "scope": (mandate.get("scope") or {}).get("cwd", "")} if mandate else None),
        "models": {"dispatched": meta.get("MODEL", ""), "effort": meta.get("EFFORT", ""),
                   "used": result.get("MODEL_USED", ""), "effort_used": result.get("EFFORT_USED", ""),
                   "free_pool": ({"mode": selection.get("mode", ""),
                                  "models": list(selection.get("models") or [])[:5],
                                  "reasons": {k: _one_line(v, 200) for k, v in
                                              (selection.get("reasons") or {}).items()
                                              if k in (selection.get("models") or [])[:5]}}
                                 if selection else None)},
        "runs": runs, "appends": appends, "wake": wake,
        "notify": {"sent": result.get("NOTIFIED", ""), "failed": result.get("NOTIFY_FAILED", ""),
                   "at": result.get("NOTIFY_AT", ""), "notice": result.get("NOTICE", "")},
        "state": {"needs": result.get("NEEDS", ""), "need_summary": result.get("NEED_SUMMARY", ""),
                  "attention": result.get("ATTENTION") or "unknown", "stage": result.get("STAGE", ""),
                  "restart": result.get("RESTART", ""), "attempts": to_int(result.get("ATTEMPTS")),
                  "max_attempts": to_int(result.get("MAX_ATTEMPTS")),
                  "quota_resumes_used": to_int(result.get("QUOTA_RESUMES_USED")),
                  "later_used": to_int(result.get("LATER_USED"))},
        "report_first_line": _one_line(summary, 240),
        "question": ({"state": "answered" if answer.get("state") == "answered" else
                               "resolved" if answer.get("state") == "resolved" else "open",
                      "key": question.get("key", ""), "title": _one_line(question.get("title"), 160),
                      "options": [str(o)[:80] for o in (question.get("options") or [])],
                      "recommend": to_int(question.get("recommend"))} if question else None),
        "answer": ({"choice": answer.get("choice"), "text": _one_line(answer.get("choice_text") or answer.get("text"), 200),
                    "by": _session_hint(answer.get("answered_by", "")), "at": answer.get("answered_at", ""),
                    "resume_task_id": answer.get("resume_task_id", ""), "resolved": answer.get("state") == "resolved"}
                   if answer else None),
        "later": ({"state": later.get("state", ""), "at": later.get("at", ""), "key": later.get("key", ""),
                   "about": _one_line(later.get("about"), 200), "attempt": later.get("attempt")} if later else None),
        "later_history": [{"state": item.get("state", ""), "at": item.get("at", ""),
                           "key": item.get("key", ""), "attempt": item.get("attempt")}
                          for item in later_history],
        "timeline": [{**event, "text": _safe_text(event.get("text"), 300)} for event in timeline["events"][-40:]],
        "timeline_counts": {"events": len(timeline["events"]), "omitted_events": timeline["omitted_events"],
                            "log_missing": timeline["log_missing"]},
        "audit": [_safe_text(line, 300) for line in audit_lines],
    }


def _why_text(out: dict) -> str:
    t, disp, mand, models, state = out["task"], out["dispatch"], out["mandate"], out["models"], out["state"]
    lines = [f"task: {t['id']}  ({t['name'] or '-'})",
             f"agent: {t['agent'] or '-'}  state: {t['state']}/{t['outcome'] or '-'}"
             f"  attention: {state['attention']}  stage: {state['stage'] or '-'}",
             f"created: {t['created'] or '-'}  started: {t['started'] or '-'}  finished: {t['finished_epoch'] or '-'}"]
    if disp["origin"] or disp["parent"] or disp["answer_of"]:
        lines.append(f"dispatch: origin={disp['origin'] or '-'} parent={disp['parent'] or '-'} "
                     f"answer_of={disp['answer_of'] or '-'} wake_depth={disp['wake_depth']}")
    if mand:
        actions = " ".join(f"{k}={v}" for k, v in sorted(mand["actions"].items()))
        lines.append(f"mandate: {actions} source={mand['source_kind']}/{mand['strength']} "
                     f"policy={mand['policy_version'] or '-'} cwd={mand['scope'] or '-'}")
    else:
        lines.append("mandate: none (a task from before mandates)")
    model_line = f"model: dispatched={models['dispatched'] or '-'}/{models['effort'] or '-'}"
    model_line += f" used={models['used'] or '-'}/{models['effort_used'] or '-'}"
    lines.append(model_line)
    pool = models["free_pool"]
    if pool:
        lines.append(f"free pool: {pool['mode'] or '-'} selected={','.join(pool['models']) or '-'}")
        for name, reason in pool["reasons"].items():
            lines.append(f"  {name}: {reason}")
    lines.append(f"runs: {len(out['runs'])}")
    for run in out["runs"]:
        lines.append(f"  {run['run_no']}. kind={run['kind'] or '-'} model={run['model'] or '-'} "
                     f"started={run['started_at'] or '-'} ended={run['ended_at'] or '-'} "
                     f"rc={run['rc'] if run['rc'] is not None else '-'} result={run['result'] or '-'}"
                     + (f" duration={run['duration_sec']}s" if run["duration_sec"] is not None else ""))
    if out["appends"]:
        lines.append(f"appends: {len(out['appends'])}")
        for append in out["appends"]:
            run = f" run {append['run_no']}" if append["run_no"] is not None else ""
            lines.append(f"  {append['stamp'] or '?'} {append['file']} -> {append['disposition']}{run}")
    if out["wake"]:
        lines.append("wake: " + " ".join(f"{k}={v['state']}/{v['attempts']}" for k, v in sorted(out["wake"].items())))
    lines.append(f"notify: sent={out['notify']['sent'] or '-'} failed={out['notify']['failed'] or '-'} "
                 f"at={out['notify']['at'] or '-'} notice={out['notify']['notice'] or '-'}")
    lines.append(f"needs: {state['needs'] or 'unknown'}  restart: {state['restart'] or '-'}  "
                 f"attempts: {state['attempts']}/{state['max_attempts'] or '?'}  "
                 f"quota waits: {state['quota_resumes_used']}  later: {state['later_used']}")
    if out["report_first_line"]:
        lines.append(f"report: {out['report_first_line']}")
    if out["question"]:
        q = out["question"]
        lines.append(f"question: {q['state']} key={q['key']} title={q['title']}")
        lines.append("  " + "  ".join(f"{i}. {o}" for i, o in enumerate(q["options"], 1)))
    if out["answer"]:
        a = out["answer"]
        lines.append(f"answer: {'resolved' if a['resolved'] else a['text'] or '-'} by={a['by'] or '-'} "
                     f"at={a['at'] or '-'} resumed_as={a['resume_task_id'] or '-'}")
    if out["later"]:
        later = out["later"]
        lines.append(f"later: {later['state'] or '-'} at={later['at'] or '-'} key={later['key'] or '-'} "
                     f"about={later['about'] or '-'}")
    for item in out["later_history"]:
        lines.append(f"later history: {item['state'] or '-'} at={item['at'] or '-'} key={item['key'] or '-'}")
    if out["timeline"]:
        lines.append("timeline (last events):")
        for event in out["timeline"][-15:]:
            lines.append(f"  {event['stamp']} {event['kind']}: {event['text'] or ''}".rstrip())
    if out["audit"]:
        lines.append("audit:")
        lines += [f"  {line}" for line in out["audit"][-10:]]
    return "\n".join(lines)


def cmd_log(args) -> dict:
    d = task_dir(args.id)
    n = max(1, min(args.lines, 400))
    try:
        with open(d / "run.log", "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 262144))
            lines = f.read().decode("utf-8", "replace").splitlines()[-n:]
    except OSError:
        lines = []
    return {"ok": True, "id": args.id, "lines": [redact(line) for line in lines], "timeline": task_timeline(d)}


def cmd_result(args) -> dict:
    task_dir(args.id)
    try:
        r = subprocess.run([sys.executable, str(TOOLS_DIR / "read-result.py"), args.id], capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OpsError(5, f"read-result.py failed: {e}")
    if r.returncode != 0:
        raise OpsError(3, (r.stderr or r.stdout).strip() or "no final report yet")
    return {"ok": True, "id": args.id, "report": redact(r.stdout.strip())}



# ---- usage: tokens and an API-price estimate ------------------------------------------------
# Every figure comes from the agent's own session record; nothing is guessed. Messages are counted
# from the task's dispatch time (a retried task resumes an older session: its earlier turns belong
# to the earlier task). claude repeats one API message's usage on every content-block line, so
# lines are deduplicated by message id; codex writes a cumulative total per process.

def stamp_epoch(stamp: str) -> int | None:
    try:
        return int(time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S")))
    except (TypeError, ValueError):
        return None


def iso_epoch(stamp: str) -> float | None:
    try:
        from datetime import datetime
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def task_session(d: Path, result: dict) -> str:
    """result.env SESSION, else the newest attempt*.json session_id (tasks from before SESSION was kept)."""
    if result.get("SESSION"):
        return result["SESSION"]
    for f in sorted(d.glob("attempt*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            m = re.search(r'"session_id"\s*:\s*"([^"]+)"', f.read_text(errors="replace")[:4096])
        except OSError:
            continue
        if m:
            return m[1]
    return ""


def _bucket() -> dict[str, int]:
    return {"in": 0, "cache_w5m": 0, "cache_w1h": 0, "cache_r": 0, "out": 0}


def claude_usage(session: str, since: float, until: float | None = None) -> dict[str, dict[str, int]] | None:
    files = sorted(CLAUDE_HOME.glob(f"projects/*/{session}.jsonl"))
    if not files:
        return None
    last: dict[str, tuple[str, dict]] = {}
    for f in files:
        with open(f, errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line or '"assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                m = d.get("message") or {}
                if d.get("type") != "assistant" or not isinstance(m.get("usage"), dict):
                    continue
                at = iso_epoch(d.get("timestamp", ""))
                if at is None or at < since or (until is not None and at > until):
                    continue
                last[m.get("id") or f"{f}:{len(last)}"] = (m.get("model") or "", m["usage"])
    out: dict[str, dict[str, int]] = {}
    for model, u in last.values():
        b = out.setdefault(model, _bucket())
        split = u.get("cache_creation") or {}
        w1h = int(split.get("ephemeral_1h_input_tokens") or 0)
        b["in"] += int(u.get("input_tokens") or 0)
        b["cache_w1h"] += w1h
        b["cache_w5m"] += max(0, int(u.get("cache_creation_input_tokens") or 0) - w1h)
        b["cache_r"] += int(u.get("cache_read_input_tokens") or 0)
        b["out"] += int(u.get("output_tokens") or 0)
    return out or None


def codex_usage(session: str, since: float, model: str, until: float | None = None) -> dict[str, dict[str, int]] | None:
    home = Path(os.environ.get("CODEX_HOME", "/root/.codex"))
    files = sorted(home.glob(f"sessions/**/rollout-*-{session}.jsonl"))
    if not files:
        return None
    b = _bucket()
    observed = False
    keys = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")
    for f in files:
        prev = dict.fromkeys(keys, 0)
        with open(f, errors="replace") as fh:
            for line in fh:
                if '"token_count"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                total = (((d.get("payload") or {}).get("info") or {}).get("total_token_usage")) or None
                if not total:
                    continue
                cur = {k: int(total.get(k) or 0) for k in keys}
                # A new process (resume) restarts its cumulative total; a repeat of the same total adds nothing.
                delta = cur if cur["input_tokens"] < prev["input_tokens"] else {k: cur[k] - prev[k] for k in keys}
                prev = cur
                at = iso_epoch(d.get("timestamp", ""))
                if at is None or at < since or (until is not None and at > until):
                    continue
                observed = True
                b["cache_r"] += delta["cached_input_tokens"]
                b["cache_w5m"] += delta["cache_write_input_tokens"]
                b["in"] += max(0, delta["input_tokens"] - delta["cached_input_tokens"] - delta["cache_write_input_tokens"])
                b["out"] += delta["output_tokens"]
    return {model: b} if observed else None


def opencode_usage(session: str, since: float) -> tuple[dict[str, dict[str, int]], float] | None:
    """Assistant tokens/cost for one session, from whichever storage schema the DB has.

    v2 moved assistant messages to session_message(type='assistant') with a nested
    data.model={id,providerID} and data.tokens; v1 used message(data.role='assistant'). The live
    DB keeps both tables across the migration, so select by whether this session has v2 assistant
    rows, and fall back to the v1 table for sessions written before the upgrade.
    """
    import sqlite3
    if not OPENCODE_DB.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{OPENCODE_DB}?mode=ro", uri=True, timeout=5)
        try:
            tables = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            rows, v2 = [], False
            if "session_message" in tables:
                rows = con.execute(
                    "SELECT data FROM session_message WHERE session_id = ? AND type = 'assistant' "
                    "AND time_created >= ?", (session, int(since * 1000))).fetchall()
                v2 = bool(rows)
            if not rows and "message" in tables:
                rows = con.execute(
                    "SELECT data FROM message WHERE session_id = ? AND time_created >= ?",
                    (session, int(since * 1000))).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    out: dict[str, dict[str, int]] = {}
    cost = 0.0
    for (raw,) in rows:
        try:
            m = json.loads(raw)
        except ValueError:
            continue
        if v2:
            model_info = m.get("model") if isinstance(m.get("model"), dict) else {}
            provider, name = model_info.get("providerID") or "", model_info.get("id") or ""
        else:
            if m.get("role") != "assistant":
                continue
            provider, name = m.get("providerID") or "", m.get("modelID") or ""
        if not isinstance(m.get("tokens"), dict):
            continue
        t = m["tokens"]
        model = (provider + "/" if provider else "") + name
        b = out.setdefault(model, _bucket())
        cache = t.get("cache") or {}
        b["in"] += int(t.get("input") or 0)
        b["out"] += int(t.get("output") or 0) + int(t.get("reasoning") or 0)
        b["cache_r"] += int(cache.get("read") or 0)
        b["cache_w5m"] += int(cache.get("write") or 0)
        cost += float(m.get("cost") or 0)
    return out, cost


def dsh_usage(d: Path, fallback_model: str) -> dict[str, dict[str, int]] | None:
    """Tokens from this task's own attempt<N>.jsonl (dsh --json): each step_end event carries the
    step's usage (Anthropic semantics: inputTokens excludes cache reads). The files belong to this
    task alone, so a session another task continues is never counted here. The model of attempt N
    is the overlay the runner wrote for it (attempt<N>.yml)."""
    out: dict[str, dict[str, int]] = {}
    for f in sorted(d.glob("attempt*.jsonl"), key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", p.name)]):
        model = fallback_model
        try:
            overlay = f.with_suffix(".yml").read_text()
            provider = re.search(r'^\s*provider:\s*"?([^"\n]+)"?\s*$', overlay, re.M)
            name = re.search(r'^\s*model:\s*"?([^"\n]+)"?\s*$', overlay, re.M)
            if provider and name:
                model = f"{provider[1]}/{name[1]}"
        except OSError:
            pass
        try:
            lines = f.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"step_end"' not in line or '"usage"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict) or e.get("type") != "status" or e.get("phase") != "step_end" \
                    or not isinstance(e.get("usage"), dict):
                continue
            u = e["usage"]
            b = out.setdefault(model, _bucket())
            b["in"] += int(u.get("inputTokens") or 0)
            b["out"] += int(u.get("outputTokens") or 0)
            b["cache_r"] += int(u.get("cacheReadTokens") or 0)
            b["cache_w5m"] += int(u.get("cacheWriteTokens") or 0)
    return out or None


@functools.lru_cache(maxsize=1)
def prices() -> dict:
    try:
        return json.loads(PRICES.read_text())
    except (OSError, ValueError):
        return {}


def price_of(model: str) -> dict | None:
    table = prices().get("models") or {}
    bare = re.sub(r"\[.*\]$", "", model.rsplit("/", 1)[-1])
    return table.get(bare) or table.get(re.sub(r"-\d{8}$", "", bare))


def estimate_usd(per_model: dict[str, dict[str, int]]) -> str:
    """The API-price estimate, '' when any model that used tokens has no price row."""
    mult = prices().get("cache") or {}
    total = 0.0
    for model, b in per_model.items():
        if not any(b.values()):
            continue
        p = price_of(model)
        if p is None:
            return ""
        read = p.get("cache_read", p["in"] * mult.get("read", 0.1))
        total += (b["in"] * p["in"] + b["cache_w5m"] * p["in"] * mult.get("write_5m", 1.25)
                  + b["cache_w1h"] * p["in"] * mult.get("write_1h", 2.0) + b["cache_r"] * read + b["out"] * p["out"]) / 1e6
    return f"{total:.2f}"


def task_usage(d: Path) -> dict:
    meta, result = read_env(d / "meta.env"), read_env(d / "result.env")
    agent = meta.get("AGENT", "")
    session = task_session(d, result)
    since = stamp_epoch(meta.get("CREATED", "")) or 0
    if agent in ("claude", "codex"):
        since = float(result.get("USAGE_START_EPOCH") or 0) or since
    base = {"agent": agent, "session": session, "tokens": None, "cost_usd": "", "cost_kind": "unknown",
            "models": [], "prices_as_of": prices().get("as_of", ""), "reason": ""}
    if not session:
        return {**base, "reason": "no session recorded yet"}
    if agent in ("claude", "codex") and result.get("ATTEMPTS") == "0":
        return {**base, "reason": "no model run started; session usage is not attributable to this task"}
    until = None
    if agent in ("claude", "codex") and result.get("STATE") not in ("running", "queued", "waiting", None, ""):
        try:
            until = float(result["FINISHED_EPOCH"])
        except (KeyError, ValueError):
            # Legacy tasks have no reliable end boundary. Their frozen values are safer
            # than rereading a session which another task may have continued since.
            keys = {"in": "TOKENS_IN", "cache_w": "TOKENS_CACHE_W", "cache_r": "TOKENS_CACHE_R",
                    "out": "TOKENS_OUT", "total": "TOKENS_TOTAL"}
            if all(result.get(k, "").isdigit() for k in keys.values()):
                # The frozen totals carry no per-model split; the model is what the runner last used.
                model = result.get("MODEL_USED") or meta.get("MODEL", "")
                return {**base, "tokens": {k: int(result[v]) for k, v in keys.items()},
                        "cost_usd": result.get("COST_USD", ""),
                        "cost_kind": "estimate" if result.get("COST_USD") else "unpriced",
                        "models": [model] if model else [],
                        "reason": "legacy frozen usage; end boundary unknown; model from MODEL_USED"}
            return {**base, "reason": "terminal task has no reliable usage boundary or frozen usage"}
    base["usage_as_of"] = until
    per_model, cost_kind, cost = None, "unknown", ""
    if agent == "claude":
        per_model = claude_usage(session, since, until)
    elif agent == "codex":
        per_model = codex_usage(session, since, result.get("MODEL_USED") or meta.get("MODEL", ""), until)
    elif agent == "opencode":
        found = opencode_usage(session, since)
        if found is not None:
            per_model, reported = found
            pool = set(pool_models())
            if reported > 0:
                cost, cost_kind = f"{reported:.2f}", "reported"
            elif per_model and all(m in pool or m.endswith("-free") for m in per_model):
                cost, cost_kind = "free", "free"
    elif agent == "dsh":
        per_model = dsh_usage(d, result.get("MODEL_USED") or meta.get("MODEL", ""))
    if per_model is None:
        return {**base, "reason": f"no {agent} session record with attributable usage found for {session}"}
    b = _bucket()
    for v in per_model.values():
        for k in b:
            b[k] += v[k]
    if agent != "opencode":
        cost = estimate_usd(per_model)
        cost_kind = "estimate" if cost else "unpriced"
    tokens = {"in": b["in"], "cache_w": b["cache_w5m"] + b["cache_w1h"], "cache_r": b["cache_r"], "out": b["out"]}
    tokens["total"] = sum(tokens.values())
    return {**base, "tokens": tokens, "cost_usd": cost, "cost_kind": cost_kind, "models": sorted(per_model)}


def cmd_usage(args) -> dict:
    return {"ok": True, "id": args.id, **task_usage(task_dir(args.id))}


def usage_env(out: dict) -> str:
    """KEY=VALUE lines the runner copies into result.env; empty values when nothing was found."""
    t = out.get("tokens") or {}
    pairs = [("TOKENS_IN", t.get("in")), ("TOKENS_CACHE_W", t.get("cache_w")), ("TOKENS_CACHE_R", t.get("cache_r")),
             ("TOKENS_OUT", t.get("out")), ("TOKENS_TOTAL", t.get("total")), ("COST_USD", out.get("cost_usd"))]
    return "\n".join(f"{k}={'' if v is None else v}" for k, v in pairs)


# ---- summary: totals over the frozen results, read-only ------------------------------------

def cmd_summary(args) -> dict:
    """Per agent: tasks by runner STATE and model OUTCOME, and the token/cost numbers each task froze
    into result.env when it ended. A bounded --since window also gets per-day provider token buckets
    for the stats chart, from those same frozen numbers. Never rereads a session: a later task
    continuing the same session would be counted twice. COST_USD is an API list-price estimate, not
    subscription quota spent."""
    agents = [a for a in (args.agent or "").split(",") if a] or list(AGENTS)
    if any(a not in AGENTS for a in agents):
        raise OpsError(2, f"--agent takes {','.join(AGENTS)}")
    if args.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        raise OpsError(2, "--since takes YYYY-MM-DD")
    out = {a: {"tasks": 0, "states": {}, "outcomes": {}, "tokens_total": 0, "tokens_unknown": 0,
               "cost_usd_estimate": 0.0, "cost_unpriced": 0, "cost_free": 0, "live": 0,
               "needs_person": 0} for a in agents}
    # Per-day buckets for the stats chart, built in the same pass and from the same frozen
    # result.env numbers as the aggregates. Only a bounded --since window is bucketed; the
    # all-time summary leaves this empty instead of carrying years of days. A day with no task
    # is absent here and is filled as a real 0 by the reader, not treated as missing.
    daily = {} if args.since else None
    for meta_file in sorted(TASKS_DIR.glob("*/meta.env")):
        d = meta_file.parent
        if d.name.startswith("patrol-") and not args.all:
            continue
        meta, result = read_env(meta_file), read_env(d / "result.env")
        g = out.get(meta.get("AGENT", ""))
        if g is None or (args.since and meta.get("CREATED", "")[:10] < args.since):
            continue
        state = result.get("STATE") or "pending"
        g["tasks"] += 1
        g["states"][state] = g["states"].get(state, 0) + 1
        date = meta.get("CREATED", "")[:10]
        day = None
        if daily is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            day = daily.setdefault(date, {a: {"tasks": 0, "tokens": 0, "unknown": 0} for a in agents})[meta["AGENT"]]
            day["tasks"] += 1
        if state not in TERMINAL:
            g["live"] += 1   # its numbers are still moving: counted as a task, not in the totals
            continue
        outcome = result.get("OUTCOME") or "-"
        g["outcomes"][outcome] = g["outcomes"].get(outcome, 0) + 1
        # Runner api 5 publishes whether the agent said a person has to act. An older task has
        # no ATTENTION field: its blocked/failed/timeout/quota states are the same fact.
        attention = result.get("ATTENTION", "")
        if attention == "person" or (not attention and state in {"blocked", "failed", "timeout", "quota", "partial", "unverified"}):
            g["needs_person"] += 1
        total, cost = result.get("TOKENS_TOTAL", ""), result.get("COST_USD", "")
        if total.isdigit():
            g["tokens_total"] += int(total)
            if day is not None:
                day["tokens"] += int(total)
        else:
            g["tokens_unknown"] += 1   # empty is unknown, never 0
            if day is not None:
                day["unknown"] += 1
        if cost == "free":
            g["cost_free"] += 1
        else:
            try:
                g["cost_usd_estimate"] += float(cost)
            except ValueError:
                g["cost_unpriced"] += 1
    for g in out.values():
        g["cost_usd_estimate"] = round(g["cost_usd_estimate"], 2)
    return {"ok": True, "since": args.since or None, "patrol_included": bool(args.all), "agents": out,
            "daily": daily or {},
            "cost_kind": "estimate", "note": "tokens and COST_USD as frozen at each task's end; COST_USD "
            "is an API list-price estimate, not subscription quota; live tasks are not in the totals"}


# ---- brief: the task's instructions, read-only --------------------------------------------

def capped(path: Path, limit: int) -> tuple[str, int, bool]:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            raw = f.read(limit + 1)
    except OSError:
        return "", 0, False
    cut = len(raw) > limit
    return raw[:limit].decode("utf-8", "ignore"), size, cut


def run_outcome(d: Path, run_no: int) -> dict:
    """Whether run <run_no> launched its CLI and how it returned (rc, kind); None fields are unknown."""
    rec = read_env(d / f"attempt{run_no}.env")
    return {"started": bool(rec.get("STARTED_EPOCH")), "rc": to_int(rec.get("RC"), None), "kind": rec.get("AKIND") or None,
            "prompt_kind": rec.get("KIND") or None}


def cmd_brief(args) -> dict:
    d = task_dir(args.id)
    meta = read_env(d / "meta.env")
    context = []
    try:
        manifest = json.loads((d / "context" / "manifest.json").read_text())
        for item in (manifest.get("files") or [])[:5]:
            if not isinstance(item, dict):
                continue
            context.append({"name": str(item.get("name") or "")[:120],
                            "source": redact(str(item.get("source") or ""))[:240],
                            "bytes": to_int(item.get("bytes")),
                            "sha256": str(item.get("sha256") or "")[:64]})
    except (OSError, ValueError):
        pass
    text, size, cut = capped(d / "prompt.md", BRIEF_MAX_BYTES)
    result = read_env(d / "result.env")
    ended = result.get("STATE") in TERMINAL
    # Runner api 4 records each run's launch in attempt<N>.env; older runners leave it unknown.
    records_runs = to_int(result.get("RUNNER_API"), 1) >= 4
    appends, budget = [], APPENDS_MAX_BYTES
    entries = [(f, False) for f in (d / "inbox").glob("*.md")] + [(f, True) for f in (d / "inbox" / "delivered").glob("*.md")]
    for f, delivered in sorted(entries, key=lambda e: e[0].name):
        m = re.match(r"^(\d{8})-(\d{6})", f.name)
        stamp = f"{m[1][:4]}-{m[1][4:6]}-{m[1][6:]} {m[2][:2]}:{m[2][2:4]}:{m[2][4:]}" if m else ""
        body, n, over = capped(f, max(0, budget))
        budget -= len(body.encode())
        try:
            run_no = int(f.with_name(f.name + ".run").read_text()) if delivered else None
        except (OSError, ValueError):
            run_no = None
        disposition = ("attached_to_run" if run_no is not None else "taken_legacy") if delivered else (
            "not_delivered" if ended else "pending")
        run = run_outcome(d, run_no) if run_no is not None and records_runs else None
        if run is not None and not run["started"] and ended:
            # Moved out of the inbox, but its run was stopped before launching a CLI: not delivered.
            disposition, delivered = "taken_not_started", False
        appends.append({"run_no": run_no, "disposition": disposition, "run": run, "file": f.name, "path": str(f), "stamp": stamp,
                        "delivered": delivered, "dropped": ended and not delivered,
                        "bytes": n, "text": body, "truncated": over})
    # `truncated` stays prompt.md's own flag (the chip labels it with brief_bytes); the appends say
    # so each, and together in appends_truncated / dropped_bytes (#1988: the text answer used to
    # drop them without a word).
    dropped = size - len(text.encode()) + sum(a["bytes"] - len(a["text"].encode()) for a in appends)
    return {"ok": True, "id": args.id, "name": meta.get("NAME", args.id), "agent": meta.get("AGENT", ""),
            "model": meta.get("MODEL", ""), "path": str(d / "prompt.md"), "brief": text, "brief_bytes": size,
            "truncated": cut, "appends_truncated": any(a["truncated"] for a in appends),
            "dropped_bytes": dropped, "limit_bytes": BRIEF_MAX_BYTES + APPENDS_MAX_BYTES,
            "appends": appends, "context": context}


# ---- budgets: deadline, retries, quota resumes (runner api 3) --------------------------------
# Written to override.env like the model: the runner rereads DEADLINE_EPOCH, MAX_ATTEMPTS and
# QUOTA_RESUMES at every poll of its lock wait and before every attempt. meta.env (read once at
# start) stays the record of what was dispatched. A task whose runner predates api 3 read its
# deadline once and armed its outer timeout from it, so it is refused rather than half-applied.

def budget_view(meta: dict, result: dict, ov: dict) -> dict:
    """The value in force: a saved override (the runner takes it within one poll, or at its next attempt),
    else what the runner published in result.env, else the dispatch record."""
    def pick(key: str, default: int) -> int:
        return to_int(ov.get(key) or result.get(key) or meta.get(key), default)
    return {"deadline_epoch": pick("DEADLINE_EPOCH", 0), "max_attempts": pick("MAX_ATTEMPTS", 3),
            "quota_resumes": pick("QUOTA_RESUMES", 3), "attempts": to_int(result.get("ATTEMPTS")),
            "quota_resumes_used": to_int(result.get("QUOTA_RESUMES_USED")),
            "ceiling_epoch": (stamp_epoch(meta.get("CREATED", "")) or 0) + DEADLINE_CAP_SEC,
            "dispatched": {"deadline_epoch": to_int(meta.get("DEADLINE_EPOCH")), "max_attempts": to_int(meta.get("MAX_ATTEMPTS"), 3),
                           "quota_resumes": to_int(meta.get("QUOTA_RESUMES"), 3)}}


def budget_task(d: Path, task_id: str, action: str) -> tuple[dict, dict, dict]:
    meta, result = live_task(d, task_id, action)
    if to_int(result.get("RUNNER_API"), 1) < BUDGET_RUNNER_API:
        raise OpsError(3, f"task {task_id} runs on runner api {result.get('RUNNER_API') or 1}: it read its deadline and "
                          f"retry budgets once at start (and armed its outer timeout from the deadline), so {action} "
                          "would not apply; tasks started after runner api 3 was installed accept it")
    return meta, result, read_override(d)


def applies(result: dict) -> tuple[str, str]:
    if result.get("WAITING") in ("quota", "retry", "later"):
        return "on_wake", "the saved change is visible now; the runner applies it when it wakes for the next attempt"
    running = bool(result.get("SLOT")) or (to_int(result.get("ATTEMPTS")) > 0 and result.get("WAITING") in ("", "slot"))
    if running:
        return "next_attempt", "the attempt running now keeps its time cap; the change applies to the next attempt and every wait"
    return "now", "the runner rereads it within one queue poll (a few seconds)"


def save_budget(d: Path, args, ov: dict, key: str, value: str, dispatched: str, detail: str, result: dict) -> dict:
    before = ov.get(key, "")
    ov[key] = "" if value == dispatched else value
    if ov.get(key, "") == before:
        return {"ok": True, "id": args.id, "changed": False, "message": "nothing to change"}
    write_override(d, ov)
    audit(d, args.source, args.action, detail)
    when, why = applies(result)
    return {"ok": True, "id": args.id, "changed": True, "applies": when, "message": f"{detail}; {why}"}


def cmd_deadline(args) -> dict:
    d = task_dir(args.id)
    with TaskLock(d):
        meta, result, ov = budget_task(d, args.id, "a deadline change")
        view = budget_view(meta, result, ov)
        now, cur = int(time.time()), view["deadline_epoch"]
        when = args.when.strip()
        if when == "reset":
            new = view["dispatched"]["deadline_epoch"]
        elif (m := re.fullmatch(r"\+(\d{1,3})([hm])", when)):
            new = cur + int(m[1]) * (3600 if m[2] == "h" else 60)
        else:
            new = stamp_epoch(when if len(when) > 16 else when + ":00") or -1
            if new < 0:
                raise OpsError(2, f"deadline takes +Nh, +Nm, 'YYYY-MM-DD HH:MM[:SS]' or reset (got {when!r})")
        floor = now + MIN_RUN_SEC + KILL_MARGIN
        fmt = lambda e: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e))  # noqa: E731
        if cur <= now and new < cur:
            raise OpsError(3, f"the deadline {fmt(cur)} has already passed; it cannot be moved earlier")
        if new < floor:
            raise OpsError(2, f"{fmt(new)} is too soon: a deadline must leave at least {MIN_RUN_SEC + KILL_MARGIN}s "
                              f"(MIN_RUN_SEC + KILL_MARGIN), so no earlier than {fmt(floor)}")
        if new > view["ceiling_epoch"]:
            raise OpsError(2, f"{fmt(new)} is past this task's ceiling {fmt(view['ceiling_epoch'])} (dispatch + 72h)")
        return save_budget(d, args, ov, "DEADLINE_EPOCH", str(new), str(view["dispatched"]["deadline_epoch"]),
                           f"deadline {fmt(cur)}->{fmt(new)}", result) | {"deadline_epoch": new}


def cmd_count_budget(args) -> dict:
    key, cap, used_key, lo = (("MAX_ATTEMPTS", MAX_ATTEMPTS_CAP, "attempts", 1) if args.action == "attempts"
                              else ("QUOTA_RESUMES", QUOTA_RESUMES_CAP, "quota_resumes_used", 0))
    d = task_dir(args.id)
    with TaskLock(d):
        meta, result, ov = budget_task(d, args.id, f"a {args.action} change")
        view = budget_view(meta, result, ov)
        dispatched = view["dispatched"]["max_attempts" if args.action == "attempts" else "quota_resumes"]
        value = dispatched if args.value == "reset" else to_int(args.value, -1)
        if not re.fullmatch(r"\d{1,2}|reset", args.value) or not lo <= value <= cap:
            raise OpsError(2, f"{args.action} takes an integer {lo}..{cap} or reset (got {args.value!r})")
        if value < view[used_key]:
            raise OpsError(3, f"{view[used_key]} already used; {args.action} cannot go below that")
        cur = view["max_attempts" if args.action == "attempts" else "quota_resumes"]
        return save_budget(d, args, ov, key, str(value), str(dispatched), f"{args.action} {cur}->{value}", result) \
            | {key.lower(): value}

# ---- entry --------------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="task_queue_ops.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.add_argument("--source", default="cli", choices=("ui", "cli", "runner"), help="recorded in audit.log")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("version").set_defaults(fn=cmd_version)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    hist = sub.add_parser("history", help="search task metadata, newest created first")
    hist.add_argument("query", nargs="?", default="", help="words in id, name, state or outcome (AND)")
    hist.add_argument("--agent", choices=AGENTS)
    hist.add_argument("--state", help="exact runner STATE (ok, blocked, running, ...)")
    hist.add_argument("--attention", choices=("person", "none", "unknown"),
                      help="only tasks with this recorded ATTENTION")
    hist.add_argument("--since", help="created on or after YYYY-MM-DD (host time)")
    hist.add_argument("--before", help="exclusive task id cursor returned as next_before")
    hist.add_argument("--limit", type=int, default=10, help="page size, 1–50")
    hist.add_argument("--all", action="store_true", help="include patrol-* rounds")
    hist.set_defaults(fn=cmd_history)
    h = sub.add_parser("head")
    h.add_argument("agent")
    h.set_defaults(fn=cmd_head)
    c = sub.add_parser("cancel")
    c.add_argument("id")
    c.set_defaults(fn=cmd_cancel)
    ack = sub.add_parser("ack")
    ack.add_argument("id")
    ack.add_argument("--by", default="", help="operator recorded in needs-ack.json")
    ack.set_defaults(fn=cmd_ack)
    pr = sub.add_parser("priority")
    pr.add_argument("id")
    pr.add_argument("value")
    pr.set_defaults(fn=cmd_priority)
    m = sub.add_parser("model")
    m.add_argument("id")
    m.add_argument("model")
    m.add_argument("effort", nargs="?", default="keep")
    m.set_defaults(fn=cmd_model)
    for name, fn in (("choices", cmd_choices), ("retry", cmd_retry), ("result", cmd_result), ("usage", cmd_usage),
                     ("brief", cmd_brief)):
        a = sub.add_parser(name)
        a.add_argument("id")
        a.set_defaults(fn=fn)
    ap = sub.add_parser("append")
    ap.add_argument("id")
    ap.add_argument("--queue", action="store_true", help="deliver when the current attempt ends")
    ap.add_argument("--text", help="the instruction (default: stdin)")
    ap.set_defaults(fn=cmd_append)
    dl = sub.add_parser("deadline")
    dl.add_argument("id")
    dl.add_argument("when")
    dl.set_defaults(fn=cmd_deadline)
    for name in ("attempts", "resumes"):
        b = sub.add_parser(name)
        b.add_argument("id")
        b.add_argument("value")
        b.set_defaults(fn=cmd_count_budget)
    rp = sub.add_parser("reap", help="mark tasks whose runner unit is gone; never retry")
    rp.add_argument("--dry-run", action="store_true", help="report candidates, write and notify nothing")
    rp.set_defaults(fn=cmd_reap)
    wh = sub.add_parser("why", help="one page: who dispatched, runs, appends, waits, result")
    wh.add_argument("id")
    wh.set_defaults(fn=cmd_why)
    sm = sub.add_parser("summary", help="per-agent totals over frozen task results")
    sm.add_argument("--since", help="tasks created on or after YYYY-MM-DD")
    sm.add_argument("--agent", help="comma list of claude,codex,opencode (default: all)")
    sm.add_argument("--all", action="store_true", help="include patrol-* rounds")
    sm.set_defaults(fn=cmd_summary)
    lg = sub.add_parser("log")
    lg.add_argument("id")
    lg.add_argument("--lines", type=int, default=60)
    lg.set_defaults(fn=cmd_log)
    return p


def human(action: str, out: dict) -> str:
    if action == "head":
        # Bare id: run-agent.sh reads this line. The explanation is in --json (`note`).
        return out["head"]
    if action == "version":
        return f"{out['ops_version']} (api {out['api']})"
    if action == "list":
        lines = [f"ops {out['ops_version']} · runner api {out['runner']['api']} · fair wait {out['fair_wait_sec']}s"]
        for agent, g in out["agents"].items():
            holder = g["holder"]
            who = holder["id"] if holder["id"] else ("held by an unnamed task" if holder["held"] else "free")
            lines.append(f"{agent}: lock {who}" + (f" · quota until {time.strftime('%m-%d %H:%M', time.localtime(g['quota']['until']))} ({g['quota']['by']})" if g["quota"] else ""))
            for r in g["queue"]:
                tag = "patrol" if r["patrol"] else "protected" if r["protected"] else f"p{r['priority']}"
                lines.append(f"  {r['position']}. {r['id']}  {tag}  waited {r['waited_sec'] // 60}m")
            for r in g["unqueued"]:
                lines.append(f"  !  {r['id']}  not ordered: {r['reason']}")
        return "\n".join(lines)
    if action == "reap":
        lines = []
        for r in out["reaped"]:
            prefix = "would reap" if out["dry_run"] else "reaped"
            lines.append(f"{prefix} {r['id']}  {r['state']} -> failed/runner_gone  "
                         f"(log quiet {r['log_quiet_sec'] // 60}m, updated {r['updated_age_sec'] // 60}m ago)"
                         + ("" if out["dry_run"] else f"  notify sent={r.get('notified') or '-'} "
                            f"failed={r.get('notify_failed') or '-'}"))
        if not lines:
            lines = ["No dead runners."]
        if out["skipped"]:
            lines.append("skipped: " + " ".join(f"{k}={v}" for k, v in sorted(out["skipped"].items())))
        if out["dry_run"]:
            lines.append("dry run: nothing written, no notification sent")
        return "\n".join(lines)
    if action == "why":
        return _why_text(out)
    if action == "history":
        lines = [f"{r['created'] or '?'}  {r['id']}  {r['agent']}  {r['state']}/{r['outcome'] or '-'}  "
                 f"attention={r['attention']}  {r['name']}" for r in out["tasks"]]
        if not lines:
            lines = ["No matching tasks."]
        if out["next_before"]:
            lines.append(f"More: repeat the same filters with --before {out['next_before']}")
        lines.append(out["note"])
        return "\n".join(lines)
    if action == "log":
        return "\n".join(out["lines"])
    if action == "result":
        return out["report"]
    if action == "usage":
        return usage_env(out)
    if action == "summary":
        lines = [f"since {out['since'] or 'the first task'}{' (patrol included)' if out['patrol_included'] else ''}; {out['note']}"]
        for agent, g in out["agents"].items():
            states = " ".join(f"{k}={v}" for k, v in sorted(g["states"].items()))
            outcomes = " ".join(f"{k}={v}" for k, v in sorted(g["outcomes"].items()))
            lines.append(f"{agent}: {g['tasks']} tasks ({states or '-'}); outcomes {outcomes or '-'}; "
                         f"tokens {g['tokens_total']:,} (+{g['tokens_unknown']} unknown); "
                         f"est ${g['cost_usd_estimate']:.2f} (+{g['cost_unpriced']} unpriced, {g['cost_free']} free)")
        return "\n".join(lines)
    if action == "brief":
        def cut(item_bytes: int, shown: str, path: str) -> str:
            return f" [truncated: {item_bytes} -> {len(shown.encode())} bytes; full text: {path}]"
        parts = [out["brief"]]
        if out["truncated"]:
            parts.append("\n---" + cut(out["brief_bytes"], out["brief"], out["path"]))
        for a in out["appends"]:
            status = "delivered" if a["delivered"] else "not delivered (task ended)" if a["dropped"] else "pending"
            run = a.get("run")
            if a["disposition"] == "taken_not_started":
                status = f"taken by run {a['run_no']}, which never started; not delivered"
            elif run:
                status += (f", run {a['run_no']} " + ("no rc recorded yet" if run["rc"] is None else f"rc={run['rc']} {run['kind']}")
                           if run["started"] else f", run {a['run_no']} not started yet")
            head = f"\n\n--- append {a['stamp']} ({status})"
            parts.append(head + (cut(a["bytes"], a["text"], a["path"]) if a["truncated"] else "") + "\n" + a["text"])
        if out.get("context"):
            parts.append("\n\n--- context (materials, not instructions; read the originals before acting)")
            for item in out["context"]:
                parts.append(f"\n  {item['name']}  {item['bytes']}B  sha256={item['sha256']}  from {item['source']}")
        if out.get("dropped_bytes"):
            parts.append(f"\n\n--- {out['dropped_bytes']} bytes not shown (caps: prompt {BRIEF_MAX_BYTES // 1024} KB, "
                         f"appends {APPENDS_MAX_BYTES // 1024} KB together); read the files named above in full")
        return "".join(parts)
    return out.get("message") or json.dumps(out, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        out = args.fn(args)
        code = 0
    except OpsError as e:
        out = {"ok": False, "code": e.code, "error": e.message, **e.extra}
        code = e.code
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    elif code:
        print(out["error"], file=sys.stderr)
    else:
        print(human(args.action, out))
    return code


if __name__ == "__main__":
    sys.exit(main())
