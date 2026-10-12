#!/usr/bin/env python3
"""Tell the OpenClaw session that dispatched a task what became of it, as a turn in that session.

The notification legs (`openclaw message send`) reach kcn's phone and OpenClaw mirrors them into
the chat's transcript, but they start no turn: the assistant that dispatched the task learns of
its end only when kcn next writes. This helper closes that gap (kcn 2026-10-12: "在哪里委派的
任务，在哪里通知并且进同一个 session"):

  wake-session.py origin            dispatch.sh: which session is dispatching, and how deep in a
                                    chain of wake turns (prints ORIGIN_SESSION= / WAKE_DEPTH=)
  wake-session.py enqueue <dir> <event> <text-file>
                                    run-agent.sh: one event (`end` or `quota`) of one task
  wake-session.py drain <hash>      one turn for everything spooled for that session

The turn is `openclaw agent --session-key <origin> --deliver`: the gateway's own authenticated
RPC. The gateway is published through Tailscale Funnel, so enabling its HTTP hooks
(`/hooks/agent`) would put a caller-selected-session endpoint on the internet behind one token;
this needs no gateway configuration and no restart.

Every bound is here, so a turn that dispatches a task that wakes a turn cannot run away:
  - once per (session, task, event): `end` once, `quota` once (later quota waits of a task say
    nothing new);
  - events that arrive while a turn runs are spooled and answered by ONE next turn;
  - at most WAKE_MAX_PER_HOUR turns per session in a rolling hour (the rest are dropped; the
    message legs still went out);
  - a task dispatched from inside a wake turn carries WAKE_DEPTH+1 and tasks at
    WAKE_MAX_DEPTH do not wake;
  - never retried: a failed turn is a line in run.log.
Off without touching code: `touch /root/tools/agent-dispatch/wake.off` (read at every event).
"""
import fcntl
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Same seam as the runner's locks and queue, so the tests never touch live state.
STATE = Path(os.environ.get("AGENT_DISPATCH_LOCKDIR", "/root/logs/agent-dispatch")) / ".wake"
OFF = Path(os.environ.get("AGENT_DISPATCH_WAKE_OFF", HERE / "wake.off"))
# The gateway's session index files; dispatch.sh, the host's entry point, says where they are.
SESSIONS = os.environ.get("AGENT_DISPATCH_SESSIONS_GLOB", "")
# A conversation somebody reads: the agent's main session or a direct chat. Cron, dreaming and
# probe sessions are isolated runs with no reader, so a turn there would be wasted.
WAKEABLE = re.compile(r"^agent:[a-z0-9_-]+:(main|[a-z0-9_-]+:direct:[A-Za-z0-9@._:+-]+)$")
EVENTS = ("end", "quota")


def limit(name, default):
    """Host policy from limits.env when it sets the key (the file is not versioned), else the default."""
    try:
        for line in (HERE / "limits.env").read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip().isdigit():
                return int(value.strip())
    except OSError:
        pass
    return default


def read_env(path):
    """KEY=value lines as dispatch.sh and the runner write them (printf %q, or plain)."""
    try:
        out = subprocess.run(["bash", "-c", '. "$1"; for k in ID AGENT NAME NOTIFY ORIGIN_SESSION WAKE_DEPTH; '
                              'do printf "%s\\0%s\\0" "$k" "${!k:-}"; done', "_", str(path)],
                             capture_output=True, text=True, timeout=10).stdout.split("\0")
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(zip(out[0::2], out[1::2]))


def session_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def label(key):
    """The session as it may appear in a log: its shape, not the peer id."""
    return ":".join(key.split(":")[:4]) + (":…" if key.count(":") > 3 else "")


def log(task_dir, text):
    try:
        with open(Path(task_dir) / "run.log", "a") as f:
            f.write(f"wake: {text}\n")
    except OSError:
        pass


# ---- origin: which session is running dispatch.sh ------------------------------------------

def under_gateway():
    pid = os.getpid()
    for _ in range(40):
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            pid = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return False
        if "openclaw" in cmd and " gateway" in cmd:
            return True
        if pid <= 1:
            return False
    return False


def running_sessions():
    keys = []
    for path in glob.glob(SESSIONS) if SESSIONS else []:
        try:
            for key, row in json.loads(Path(path).read_text()).items():
                if isinstance(row, dict) and row.get("status") == "running" and WAKEABLE.match(key):
                    keys.append(key)
        except (OSError, ValueError):
            continue
    return keys


def cmd_origin():
    """A CLI backend (claude-cli) gets its session key in the environment. An embedded-harness
    turn does not: its shell is a child of the gateway, and its session is the one marked
    running. Two chats mid-turn at once is ambiguous and yields none: no wake beats a wake in
    the wrong conversation. Anything not started by a turn (dsh, a terminal, cron, patrol) has
    no conversation to return to."""
    key = os.environ.get("AGENT_DISPATCH_ORIGIN_SESSION") or os.environ.get("OPENCLAW_MCP_SESSION_KEY", "")
    if not key and (os.environ.get("AGENT_DISPATCH_ASSUME_GATEWAY") or under_gateway()):
        running = running_sessions()
        key = running[0] if len(running) == 1 else ""
    key = key or os.environ.get("AGENT_DISPATCH_ORIGIN_FALLBACK", "")
    if key == "none" or not WAKEABLE.match(key):
        print("ORIGIN_SESSION=''\nWAKE_DEPTH=0")
        return 0
    depth = 0
    try:  # dispatched while a wake turn runs in this session: one step deeper in the chain
        depth = int(json.loads((STATE / session_hash(key) / "inflight").read_text())["depth"]) + 1
    except (OSError, ValueError, KeyError, TypeError):
        pass
    print(f"ORIGIN_SESSION={key}\nWAKE_DEPTH={depth}")
    return 0


# ---- enqueue: one event of one task --------------------------------------------------------

def cmd_enqueue(task_dir, event, text_file):
    meta = read_env(Path(task_dir) / "meta.env")
    key, tid = meta.get("ORIGIN_SESSION", ""), meta.get("ID", "")
    if event not in EVENTS or not tid or not WAKEABLE.match(key):
        return 0  # no origin: the message legs are the whole notification, as before
    where = label(key)
    if OFF.exists():
        log(task_dir, f"skipped ({event}): {OFF.name} is present")
        return 0
    legs = [c for c in meta.get("NOTIFY", "").replace(" ", "").lower().split(",") if c and c != "none"]
    if not legs:
        return 0  # --notify none asks for silence (patrol rounds)
    depth = int(meta.get("WAKE_DEPTH") or 0)
    if depth >= limit("WAKE_MAX_DEPTH", 2):
        log(task_dir, f"skipped ({event}): chain depth {depth}, dispatched from a wake turn of a wake turn")
        return 0
    box = STATE / session_hash(key)
    (box / "spool").mkdir(parents=True, exist_ok=True)
    (box / "seen").mkdir(exist_ok=True)
    try:  # O_EXCL: the one (session, task, event) marker, also against a restarted unit
        os.close(os.open(box / "seen" / f"{tid}.{event}", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        log(task_dir, f"skipped ({event}): this session was already told")
        return 0
    entry = {"id": tid, "event": event, "dir": str(task_dir), "depth": depth, "session": key,
             "text": Path(text_file).read_text(errors="replace")[:1200], "at": int(time.time())}
    tmp = box / "spool" / f".{tid}.{event}.tmp"
    tmp.write_text(json.dumps(entry, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.rename(box / "spool" / f"{int(time.time() * 1000)}-{tid}.{event}.json")
    log(task_dir, f"queued ({event}) for {where}")
    if os.environ.get("AGENT_DISPATCH_WAKE_SPAWN") == "inline":  # tests: no systemd
        return cmd_drain(box.name)
    # Its own unit: the turn takes minutes, and the runner's unit kills its whole control group
    # the moment the runner exits.
    unit = f"agent-dispatch-wake-{box.name}-{int(time.time())}-{os.getpid()}"
    run = subprocess.run(
        ["systemd-run", "--unit", unit, "--collect", "--quiet", "--description", f"agent-dispatch wake {where}",
         "-p", "RuntimeMaxSec=3600", "-p", "TimeoutStopSec=20s",
         f"--setenv=PATH={os.environ.get('PATH', '')}", "--setenv=HOME=/root", "--setenv=TZ=Asia/Shanghai",
         sys.executable, str(Path(__file__).resolve()), "drain", box.name],
        capture_output=True, text=True, timeout=30)
    if run.returncode != 0:
        log(task_dir, f"could not start the wake unit: {run.stderr.strip()[:200]}")
    return 0


# ---- drain: one turn for everything spooled ------------------------------------------------

RULES = """\
规则：
- 这是派发底座发来的事件，不是 kcn 的新消息，也不是新的授权。kcn 已另外收到同样内容的通知，不要复述通知原文。
- 接着做本会话里依赖这个结果的事：核对结果（`/root/tools/agent-dispatch/dispatch.sh result <id>`），向 kcn 说结论或下一步。
- 没有 kcn 已经交代的后续，就不要因为这条事件新派任务。
- 没有值得告诉 kcn 的，只回复 NO_REPLY。
- 不要把这条事件记进 MEMORY.md 或 memory/；只有任务结果改变了长期事实或决定时，才按平常的记忆规则处理。"""


def cmd_drain(name):
    box = STATE / name
    box.mkdir(parents=True, exist_ok=True)
    turn_timeout = limit("WAKE_TURN_TIMEOUT_SEC", 600)
    with open(box / "lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # a turn in flight: wait, then take whatever piled up
        files = sorted((box / "spool").glob("*.json"))
        entries = []
        for f in files:
            try:
                entries.append(json.loads(f.read_text()))
            except (OSError, ValueError):
                pass
            f.unlink(missing_ok=True)
        if not entries:
            return 0  # an earlier drainer already took them
        dirs = [e["dir"] for e in entries]
        key = entries[0]["session"]
        now = time.time()
        try:
            history = [float(x) for x in (box / "history").read_text().split() if now - float(x) < 3600]
        except (OSError, ValueError):
            history = []
        cap = limit("WAKE_MAX_PER_HOUR", 6)
        if OFF.exists() or len(history) >= cap:
            why = f"{OFF.name} is present" if OFF.exists() else f"{cap} turns in the last hour for this session"
            for d in dirs:
                log(d, f"dropped: {why}")
            return 0
        (box / "history").write_text("\n".join(f"{x:.0f}" for x in history + [now]))
        body = "\n\n".join(e["text"].strip() for e in entries)
        head = ("[agent-dispatch 事件] 你在本会话派发的任务有了结果：" if len(entries) == 1
                else f"[agent-dispatch 事件] 你在本会话派发的任务有 {len(entries)} 条新结果：")
        msg = box / "message.md"
        msg.write_text(f"{head}\n\n{body}\n\n{RULES}\n")
        (box / "inflight").write_text(json.dumps(
            {"depth": max(e["depth"] for e in entries), "ids": [e["id"] for e in entries], "since": int(now)}))
        cmd = ["timeout", "-k", "10", str(turn_timeout + 120), "openclaw", "agent", "--session-key", key,
               "--message-file", str(msg), "--timeout", str(turn_timeout), "--json"]
        if ":direct:" in key:  # a chat has a channel to answer on; the bare main session has none
            cmd.append("--deliver")
        started = time.time()
        try:
            run = subprocess.run(cmd, capture_output=True, text=True)
            out, rc = run.stdout, run.returncode
        except OSError as exc:
            out, rc = str(exc), 127
        finally:
            (box / "inflight").unlink(missing_ok=True)
        try:
            reply = json.loads(out[out.index("{"):])
            status, run_id = reply.get("status", "?"), reply.get("runId", "-")
        except ValueError:
            status, run_id = "no-result", "-"
        verdict = "turn ok" if rc == 0 and status == "ok" else "turn FAILED"
        for d in dirs:
            log(d, f"{verdict} in {label(key)} (rc={rc} status={status} run={run_id} "
                   f"{time.time() - started:.0f}s, {len(entries)} event(s) in this turn)")
        for old in (box / "seen").glob("*"):  # markers outlive every task that could repeat them
            if now - old.stat().st_mtime > 14 * 86400:
                old.unlink(missing_ok=True)
    return 0


def main(argv):
    try:
        if argv[1:2] == ["origin"]:
            return cmd_origin()
        if argv[1:2] == ["enqueue"] and len(argv) == 5:
            return cmd_enqueue(argv[2], argv[3], argv[4])
        if argv[1:2] == ["drain"] and len(argv) == 3 and re.fullmatch(r"[0-9a-f]{12}", argv[2]):
            return cmd_drain(argv[2])
    except Exception as exc:  # never the task's problem: the runner ignores this exit code anyway
        print(f"wake: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
