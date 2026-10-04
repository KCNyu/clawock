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
import subprocess
import sys
import time
from pathlib import Path

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
          (re.compile(r"(sk|ghp|gho|github_pat|xox[bp])[-_][A-Za-z0-9_-]{12,}"), "<redacted>")]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
AGENTS = ("claude", "codex", "opencode")
TERMINAL = {"ok", "partial", "unverified", "failed", "blocked", "timeout", "quota", "cancelled"}
DEFAULT_FAIR_WAIT_SEC = 4 * 3600
CANCEL_SETTLE_SEC = 4.0

TOOLS_DIR = Path(os.environ.get("AGENT_DISPATCH_DIR", "/root/tools/agent-dispatch"))
TASKS_DIR = Path(os.environ.get("AGENT_DISPATCH_TASKS_DIR", "/root/logs/agent-dispatch"))
LOCK_DIR = Path(os.environ.get("AGENT_DISPATCH_LOCKDIR", "/root/logs/agent-dispatch"))
SYSTEMCTL = os.environ.get("AGENT_DISPATCH_SYSTEMCTL", "systemctl")
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
        if waiting in ("quota", "retry"):
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
    else:
        models = list(dict.fromkeys([*own, *pool_models()]))
        efforts = {m: [] for m in models if m}   # the free pool has no variants; --variant stays unset
        flag = "--variant"
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
            raise OpsError(5, (r.stderr or r.stdout).strip()[-400:] or f"dispatch.sh append exited {r.returncode}")
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
        r = dispatch(["append", args.id, *(["--queue"] if args.queue else [])], text)
        audit(d, args.source, "append", f"mode={'queue' if args.queue else 'now'} chars={len(text)} rc={r.returncode}")
        if r.returncode != 0:
            raise OpsError(5, (r.stderr or r.stdout).strip()[-400:] or f"dispatch.sh append exited {r.returncode}")
        return {"ok": True, "id": args.id, "mode": "queue" if args.queue else "now", "message": r.stdout.strip()}


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
            if re.fullmatch(r"inbox: \d+ appended message\(s\) not delivered", line):
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


def claude_usage(session: str, since: float) -> dict[str, dict[str, int]] | None:
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
                if at is not None and at < since:
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
    return out


def codex_usage(session: str, since: float, model: str) -> dict[str, dict[str, int]] | None:
    home = Path(os.environ.get("CODEX_HOME", "/root/.codex"))
    files = sorted(home.glob(f"sessions/**/rollout-*-{session}.jsonl"))
    if not files:
        return None
    b = _bucket()
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
                if at is not None and at < since:
                    continue
                b["cache_r"] += delta["cached_input_tokens"]
                b["cache_w5m"] += delta["cache_write_input_tokens"]
                b["in"] += max(0, delta["input_tokens"] - delta["cached_input_tokens"] - delta["cache_write_input_tokens"])
                b["out"] += delta["output_tokens"]
    return {model: b}


def opencode_usage(session: str, since: float) -> tuple[dict[str, dict[str, int]], float] | None:
    import sqlite3
    if not OPENCODE_DB.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{OPENCODE_DB}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT data FROM message WHERE session_id = ? AND time_created >= ?",
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
        if m.get("role") != "assistant" or not isinstance(m.get("tokens"), dict):
            continue
        t = m["tokens"]
        model = (m.get("providerID") + "/" if m.get("providerID") else "") + (m.get("modelID") or "")
        b = out.setdefault(model, _bucket())
        cache = t.get("cache") or {}
        b["in"] += int(t.get("input") or 0)
        b["out"] += int(t.get("output") or 0) + int(t.get("reasoning") or 0)
        b["cache_r"] += int(cache.get("read") or 0)
        b["cache_w5m"] += int(cache.get("write") or 0)
        cost += float(m.get("cost") or 0)
    return out, cost


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
    base = {"agent": agent, "session": session, "tokens": None, "cost_usd": "", "cost_kind": "unknown",
            "models": [], "prices_as_of": prices().get("as_of", ""), "reason": ""}
    if not session:
        return {**base, "reason": "no session recorded yet"}
    per_model, cost_kind, cost = None, "unknown", ""
    if agent == "claude":
        per_model = claude_usage(session, since)
    elif agent == "codex":
        per_model = codex_usage(session, since, result.get("MODEL_USED") or meta.get("MODEL", ""))
    elif agent == "opencode":
        found = opencode_usage(session, since)
        if found is not None:
            per_model, reported = found
            pool = set(pool_models())
            if reported > 0:
                cost, cost_kind = f"{reported:.2f}", "reported"
            elif per_model and all(m in pool or m.endswith("-free") for m in per_model):
                cost, cost_kind = "free", "free"
    if per_model is None:
        return {**base, "reason": f"no {agent} session record found for {session}"}
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


def cmd_brief(args) -> dict:
    d = task_dir(args.id)
    meta = read_env(d / "meta.env")
    text, size, cut = capped(d / "prompt.md", BRIEF_MAX_BYTES)
    ended = read_env(d / "result.env").get("STATE") in TERMINAL
    appends, budget = [], APPENDS_MAX_BYTES
    entries = [(f, False) for f in (d / "inbox").glob("*.md")] + [(f, True) for f in (d / "inbox" / "delivered").glob("*.md")]
    for f, delivered in sorted(entries, key=lambda e: e[0].name):
        m = re.match(r"^(\d{8})-(\d{6})", f.name)
        stamp = f"{m[1][:4]}-{m[1][4:6]}-{m[1][6:]} {m[2][:2]}:{m[2][2:4]}:{m[2][4:]}" if m else ""
        body, n, over = capped(f, max(0, budget))
        budget -= len(body.encode())
        appends.append({"file": f.name, "path": str(f), "stamp": stamp, "delivered": delivered, "dropped": ended and not delivered, "bytes": n,
                        "text": body, "truncated": over})
    # `truncated` stays prompt.md's own flag (the chip labels it with brief_bytes); the appends say
    # so each, and together in appends_truncated / dropped_bytes (#1988: the text answer used to
    # drop them without a word).
    dropped = size - len(text.encode()) + sum(a["bytes"] - len(a["text"].encode()) for a in appends)
    return {"ok": True, "id": args.id, "name": meta.get("NAME", args.id), "agent": meta.get("AGENT", ""),
            "model": meta.get("MODEL", ""), "path": str(d / "prompt.md"), "brief": text, "brief_bytes": size,
            "truncated": cut, "appends_truncated": any(a["truncated"] for a in appends),
            "dropped_bytes": dropped, "limit_bytes": BRIEF_MAX_BYTES + APPENDS_MAX_BYTES, "appends": appends}


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
    if result.get("WAITING") in ("quota", "retry"):
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
    h = sub.add_parser("head")
    h.add_argument("agent")
    h.set_defaults(fn=cmd_head)
    c = sub.add_parser("cancel")
    c.add_argument("id")
    c.set_defaults(fn=cmd_cancel)
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
    if action == "log":
        return "\n".join(out["lines"])
    if action == "result":
        return out["report"]
    if action == "usage":
        return usage_env(out)
    if action == "brief":
        def cut(item_bytes: int, shown: str, path: str) -> str:
            return f" [truncated: {item_bytes} -> {len(shown.encode())} bytes; full text: {path}]"
        parts = [out["brief"]]
        if out["truncated"]:
            parts.append("\n---" + cut(out["brief_bytes"], out["brief"], out["path"]))
        for a in out["appends"]:
            status = "delivered" if a["delivered"] else "not delivered (task ended)" if a["dropped"] else "pending"
            head = f"\n\n--- append {a['stamp']} ({status})"
            parts.append(head + (cut(a["bytes"], a["text"], a["path"]) if a["truncated"] else "") + "\n" + a["text"])
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
