"""The dead-runner reap: three conditions, mark once, notify once, never retry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops/host/task_queue_ops.py"


def stamp(age: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - age))


@pytest.fixture
def q(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    units = tmp_path / "units"
    units.write_text("")
    messages = tmp_path / "messages"
    calls = tmp_path / "systemctl.calls"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(f"""#!/bin/sh
echo "$*" >>"{calls}"
case "$1" in
  is-active) grep -qx "$2" "{units}" && echo active || echo inactive ;;
  is-enabled) exit 0 ;;
  *) exit 0 ;;
esac
""")
    systemctl.chmod(0o755)
    openclaw = tmp_path / "openclaw"
    openclaw.write_text(f"""#!/bin/sh
printf '%s\\n' "$*" >>"{messages}"
exit 0
""")
    openclaw.chmod(0o755)
    conf = tmp_path / "notify.env"
    conf.write_text("NOTIFY_CHANNEL=test\nNOTIFY_TARGET=target\n")
    env = {**os.environ, "AGENT_DISPATCH_TASKS_DIR": str(tasks),
           "AGENT_DISPATCH_SYSTEMCTL": str(systemctl),
           "AGENT_DISPATCH_NOTIFY_CONF": str(conf),
           "AGENT_DISPATCH_REAP_LOG_QUIET_SEC": "60",
           "AGENT_DISPATCH_REAP_UPDATED_AGE_SEC": "300",
           "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    return {"tasks": tasks, "units": units, "messages": messages, "env": env, "root": tmp_path}


def task(q, tid, state="running", notify="weixin", unit=False, log_age=600, updated_age=900,
         result=True, created_age=3600):
    d = q["tasks"] / tid
    d.mkdir()
    (d / "meta.env").write_text(
        f"ID={tid}\nAGENT=claude\nNAME={tid}\nNOTIFY={notify}\n"
        f"CREATED={stamp(created_age)}\n")
    (d / "prompt.md").write_text("fixture\n")
    (d / "run.log").write_text("last line\n")
    os.utime(d / "run.log", (time.time() - log_age, time.time() - log_age))
    if result:
        (d / "result.env").write_text(f"STATE={state}\nUPDATED='{stamp(updated_age)}'\nATTEMPTS=1\n")
    if unit:
        with open(q["units"], "a") as f:
            f.write(f"agent-dispatch-{tid}.service\n")
    return d


def fields(d: Path) -> dict:
    out = {}
    for line in (d / "result.env").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key] = value.strip("'")
    return out


def sends(q) -> int:
    try:
        return sum(1 for line in q["messages"].read_text().splitlines() if line.startswith("message send"))
    except OSError:
        return 0


def reap(q, *args):
    r = subprocess.run([sys.executable, str(OPS), "--json", "reap", *args], env=q["env"],
                       capture_output=True, text=True, timeout=60)
    return r, json.loads(r.stdout)


def test_a_gone_runner_is_marked_once_notified_once(q):
    d = task(q, "gone-20260101-000000")
    (d / "later.json").write_text('{"state": "waiting"}')
    (d / "later-prompt.txt").write_text("stale")
    r, out = reap(q)
    assert r.returncode == 0, r.stderr
    assert [row["id"] for row in out["reaped"]] == ["gone-20260101-000000"]
    state = fields(d)
    assert state["STATE"] == "failed"
    assert state["FAILURE_REASON"] == state["STOP_REASON"] == "runner_gone"
    assert state["ATTENTION"] == "person" and state["STAGE"] == "ended"
    assert state["WAITING"] == state["WAKE_AT"] == state["SLOT"] == ""
    assert "runner_gone: unit inactive" in (d / "audit.log").read_text()
    assert (d / ".reaped").is_file()
    assert not (d / "later.json").exists() and not (d / "later-prompt.txt").exists()
    assert sends(q) == 1
    assert "retry" in q["messages"].read_text()
    # The second run sees the marker: no second notice, no second audit line.
    audit_before = (d / "audit.log").read_text()
    r, out = reap(q)
    assert r.returncode == 0
    assert out["reaped"] == [] and out["skipped"].get("already_reaped") == 1
    assert sends(q) == 1
    assert (d / "audit.log").read_text() == audit_before


def test_only_all_three_conditions_mark_a_task(q):
    active = task(q, "active-20260101-000000", unit=True)
    fresh = task(q, "fresh-20260101-000000", log_age=5)
    young = task(q, "young-20260101-000000", updated_age=10)
    terminal = task(q, "done-20260101-000000", state="ok")
    r, out = reap(q)
    assert r.returncode == 0
    assert out["reaped"] == []
    for d in (active, fresh, young, terminal):
        assert "FAILURE_REASON" not in (d / "result.env").read_text()
        assert not (d / ".reaped").exists()
    assert not q["messages"].exists() or q["messages"].read_text() == ""
    assert out["skipped"] == {"unit_active": 1, "log_recent": 1, "updated_recent": 1}


def test_dry_run_writes_nothing_and_notifies_nothing(q):
    d = task(q, "dry-20260101-000000")
    before = (d / "result.env").read_text()
    r, out = reap(q, "--dry-run")
    assert r.returncode == 0
    assert out["dry_run"] is True and len(out["reaped"]) == 1
    assert (d / "result.env").read_text() == before
    assert not (d / ".reaped").exists()
    assert not (d / "audit.log").exists()
    assert not q["messages"].exists()


def test_notify_none_still_marks_but_sends_nothing(q):
    d = task(q, "quiet-20260101-000000", notify="none")
    r, out = reap(q)
    assert r.returncode == 0 and len(out["reaped"]) == 1
    state = fields(d)
    assert state["STATE"] == "failed" and state["NOTICE"] == "none"
    assert not q["messages"].exists()


def test_a_pending_task_without_result_env_uses_created_and_dir_age(q):
    d = task(q, "pending-20260101-000000", result=False, created_age=3600, log_age=600)
    r, out = reap(q)
    assert r.returncode == 0 and [row["id"] for row in out["reaped"]] == ["pending-20260101-000000"]
    assert fields(d)["STATE"] == "failed"
    assert fields(d)["FAILURE_REASON"] == "runner_gone"


def test_a_busy_task_is_skipped_not_marked(q):
    d = task(q, "busy-20260101-000000")
    # Another writer holds the task's ops lock; the reaper must not write over it.
    holder = subprocess.Popen([sys.executable, "-c", (
        "import fcntl, sys, time; "
        f"f=open({str(d / '.ops.lock')!r}, 'a'); fcntl.flock(f, fcntl.LOCK_EX); "
        "print('locked', flush=True); time.sleep(30)")], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        r, out = reap(q)
        assert r.returncode == 0
        assert out["reaped"] == [] and out["skipped"].get("busy") == 1
        assert "FAILURE_REASON" not in (d / "result.env").read_text()
    finally:
        holder.kill()
        holder.wait()


@pytest.mark.parametrize("reply,code", [("", 1), ("", 3), ("inactive", 1), ("unexpected", 0)])
def test_systemctl_error_is_unknown_and_never_marks_a_task(q, reply, code):
    d = task(q, "query-error-20260101-000000")
    before = (d / "result.env").read_bytes()
    (q["root"] / "systemctl").write_text(
        f"#!/bin/sh\nprintf '%s\\n' '{reply}'\necho 'Failed to connect to bus' >&2\nexit {code}\n")
    r, out = reap(q)
    assert r.returncode == 0
    assert out["reaped"] == []
    assert (d / "result.env").read_bytes() == before
    assert not (d / ".reaped").exists()
    assert sends(q) == 0


@pytest.mark.parametrize("reply,code", [("inactive", 3), ("failed", 3), ("unknown", 4)])
def test_explicit_systemctl_dead_states_are_reaped(q, reply, code):
    task(q, "dead-state-20260101-000000", notify="none")
    (q["root"] / "systemctl").write_text(f"#!/bin/sh\necho {reply}\nexit {code}\n")
    r, out = reap(q)
    assert r.returncode == 0
    assert len(out["reaped"]) == 1


def test_notification_failure_without_stderr_does_not_abort_the_reap(q):
    first = task(q, "first-dead-20260101-000000")
    second = task(q, "second-dead-20260101-000000")
    (q["root"] / "openclaw").write_text("#!/bin/sh\nexit 1\n")
    r, out = reap(q)
    assert r.returncode == 0
    assert len(out["reaped"]) == 2
    for d in (first, second):
        assert fields(d)["STATE"] == "failed"
        assert fields(d)["NOTIFY_FAILED"] == "weixin"
        assert fields(d)["NOTICE"] == "attempted"
