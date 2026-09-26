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
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

API = 1
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
AGENTS = ("claude", "codex", "opencode")
TERMINAL = {"ok", "partial", "unverified", "failed", "blocked", "timeout", "quota", "cancelled"}
DEFAULT_FAIR_WAIT_SEC = 4 * 3600
CANCEL_SETTLE_SEC = 4.0

TOOLS_DIR = Path(os.environ.get("AGENT_DISPATCH_DIR", "/root/tools/agent-dispatch"))
TASKS_DIR = Path(os.environ.get("AGENT_DISPATCH_TASKS_DIR", "/root/logs/agent-dispatch"))
LOCK_DIR = Path(os.environ.get("AGENT_DISPATCH_LOCKDIR", "/root/logs/agent-dispatch"))
SYSTEMCTL = os.environ.get("AGENT_DISPATCH_SYSTEMCTL", "systemctl")


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

def queue_entries(agent: str) -> list[dict]:
    """Live waiters for <agent>'s lock, in queue order (see the module docstring)."""
    qdir = LOCK_DIR / ".queue" / agent
    now = int(time.time())
    fair = fair_wait_sec()
    rows = []
    try:
        names = sorted(os.listdir(qdir))
    except OSError:
        return []
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
    """Who holds <agent>'s lock: the runner's holder file when its PID lives, else a probe."""
    h = read_env(LOCK_DIR / ".queue" / f"{agent}.holder")
    if h.get("ID") and pid_alive(to_int(h.get("PID"))):
        return {"held": True, "id": h["ID"], "since": to_int(h.get("SINCE"), 0) or None}
    lock = LOCK_DIR / f"{agent}.lock"
    if not lock.exists():
        return {"held": False, "id": None, "since": None}
    fd = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return {"held": False, "id": None, "since": None}
    except BlockingIOError:
        # Held by a runner from before the holder file (or one that just took it).
        return {"held": True, "id": None, "since": None}
    finally:
        os.close(fd)


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
    return {"ok": True, "agent": args.agent, "head": rows[0]["id"] if rows else ""}


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
        agents[agent] = {"holder": lock_holder(agent), "queue": rows, "quota": quota_hint(agent)}
        for r in rows:
            tasks[r["id"]] = r
    return {
        "ok": True,
        "ops_version": ops_version(),
        "api": API,
        "fair_wait_sec": fair_wait_sec(),
        "runner": {"api": api, "sha": file_sha(runner)},
        "host_files": {name: file_sha(TOOLS_DIR / name) for name in ("run-agent.sh", "dispatch.sh", "limits.env")},
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
            return {"ok": True, "id": args.id, "state": state, "pending": True, "was": was, "session": session,
                    "resume": resume_hint(meta, session), "message": "cancel already requested"}
        marker.write_text(time.strftime("%Y-%m-%d %H:%M:%S") + f" {args.source}\n")
        try:
            r = subprocess.run([SYSTEMCTL, "stop", "--no-block", f"agent-dispatch-{args.id}.service"],
                               capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            marker.unlink(missing_ok=True)
            audit(d, args.source, "cancel", f"failed: {e}")
            raise OpsError(5, f"systemctl stop failed: {e}")
        if r.returncode != 0:
            marker.unlink(missing_ok=True)
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
    return p


def human(action: str, out: dict) -> str:
    if action == "head":
        return out["head"]
    if action == "version":
        return f"{out['ops_version']} (api {out['api']})"
    if action == "list":
        lines = [f"ops {out['ops_version']} · runner api {out['runner']['api']} · fair wait {out['fair_wait_sec']}s"]
        for agent, g in out["agents"].items():
            holder = g["holder"]
            who = holder["id"] or ("held (older runner)" if holder["held"] else "free")
            lines.append(f"{agent}: lock {who}" + (f" · quota until {time.strftime('%m-%d %H:%M', time.localtime(g['quota']['until']))} ({g['quota']['by']})" if g["quota"] else ""))
            for r in g["queue"]:
                tag = "patrol" if r["patrol"] else ("protected" if r["protected"] else f"p{r['priority']}")
                lines.append(f"  {r['position']}. {r['id']}  {tag}  waited {r['waited_sec'] // 60}m")
        return "\n".join(lines)
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
