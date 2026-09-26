"""The versioned queue entry (ops/host/task_queue_ops.py), exercised on fixture task directories.

The runner asks it who takes an agent lock next, and the dsh task chip runs every write through
it, so its order rule and its write contract (ids, idempotency, audit, exit codes) are pinned here.
No systemd: a fake systemctl reports unit states from a file and records what it was asked.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops/host/task_queue_ops.py"
INSTALL = ROOT / "ops/host/install_task_queue_ops.sh"


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


@pytest.fixture
def q(tmp_path):
    tasks, locks, tools = tmp_path / "tasks", tmp_path / "locks", tmp_path / "tools"
    for d in (tasks, locks, tools):
        d.mkdir()
    (tools / "limits.env").write_text("MAX_RUNNING_CLAUDE=1\nQUEUE_FAIR_WAIT_SEC=14400\n")
    (tools / "run-agent.sh").write_text("#!/bin/bash\nRUNNER_API=2\n")
    units = tmp_path / "units"
    units.write_text("")
    calls = tmp_path / "systemctl.calls"
    systemctl = tmp_path / "systemctl"
    # is-active <unit>: 'active' when listed in units. stop: record, and act like the runner's
    # on_signal (STATE=cancelled) unless STOP_FAILS is set.
    systemctl.write_text(f"""#!/bin/bash
echo "$*" >>"{calls}"
case "$1" in
  is-active) grep -qx "$2" "{units}" && echo active || echo inactive ;;
  stop)
    [ -n "${{STOP_FAILS:-}}" ] && {{ echo "Failed to stop: access denied" >&2; exit 1; }}
    id=${{3#agent-dispatch-}}; id=${{id%.service}}
    sed -i 's/^STATE=.*/STATE=cancelled/' "{tasks}/$id/result.env"
    grep -vx "$3" "{units}" >"{units}.new"; mv "{units}.new" "{units}" ;;
esac
""")
    systemctl.chmod(0o755)
    env = dict(os.environ, AGENT_DISPATCH_TASKS_DIR=str(tasks), AGENT_DISPATCH_LOCKDIR=str(locks),
               AGENT_DISPATCH_DIR=str(tools), AGENT_DISPATCH_SYSTEMCTL=str(systemctl))
    env.pop("AGENT_DISPATCH_FAIR_WAIT_SEC", None)

    class Q:
        def __init__(self):
            self.tasks, self.locks, self.tools, self.env = tasks, locks, tools, env
            self.calls = calls

        def task(self, tid, agent="claude", result="STATE=running\n", active=True, session=""):
            d = tasks / tid
            d.mkdir()
            (d / "meta.env").write_text(f"ID={tid}\nAGENT={agent}\nCWD=/root\nMODEL=m\nEFFORT=high\n")
            (d / "result.env").write_text(result + (f"SESSION={session}\n" if session else ""))
            if active:
                with units.open("a") as f:
                    f.write(f"agent-dispatch-{tid}.service\n")
            return d

        def queue(self, tid, agent="claude", queued_at=None, pid=None, priority=None):
            qd = locks / ".queue" / agent
            qd.mkdir(parents=True, exist_ok=True)
            (qd / tid).write_text(f"PID={pid or os.getpid()}\nQUEUED_AT={queued_at or int(time.time())}\n")
            if priority is not None:
                (tasks / tid).mkdir(exist_ok=True)
                (tasks / tid / "override.env").write_text(f"PRIORITY={priority}\n")

        def run(self, *args, extra_env=None):
            r = subprocess.run([sys.executable, str(OPS), "--json", *args], env=dict(env, **(extra_env or {})),
                               capture_output=True, text=True, timeout=30)
            return r.returncode, json.loads(r.stdout)

        def order(self, agent="claude"):
            code, out = self.run("list")
            assert code == 0
            return [r["id"] for r in out["agents"][agent]["queue"]]

    return Q()


def test_version_is_the_hash_of_the_installed_file(q):
    code, out = q.run("version")
    assert code == 0 and out["api"] >= 1
    import hashlib
    assert out["ops_version"] == hashlib.sha256(OPS.read_bytes()).hexdigest()[:12]


def test_waiters_go_in_queued_at_order_and_a_dead_runner_is_not_a_waiter(q):
    now = int(time.time())
    q.queue("b-task", queued_at=now - 100)
    q.queue("a-task", queued_at=now - 50)
    q.queue("gone-task", queued_at=now - 999, pid=dead_pid())
    assert q.order() == ["b-task", "a-task"]
    assert q.run("head", "claude")[1]["head"] == "b-task"


def test_orders_never_mix_across_agents(q):
    now = int(time.time())
    q.queue("claude-late", agent="claude", queued_at=now - 10)
    q.queue("codex-early", agent="codex", queued_at=now - 500)
    assert q.run("head", "claude")[1]["head"] == "claude-late"
    assert q.run("head", "codex")[1]["head"] == "codex-early"
    assert q.run("head", "opencode")[1]["head"] == ""


def test_higher_priority_goes_first_among_manual_tasks(q):
    now = int(time.time())
    q.queue("first-in", queued_at=now - 300)
    q.queue("bumped", queued_at=now - 10, priority=1)
    assert q.order() == ["bumped", "first-in"]


def test_patrol_goes_last_whatever_its_priority_file_says(q):
    now = int(time.time())
    q.queue("patrol-docs-20260926-000000", agent="opencode", queued_at=now - 9000, priority=99)
    q.queue("manual-late", agent="opencode", queued_at=now - 5, priority=-5)
    assert q.order("opencode") == ["manual-late", "patrol-docs-20260926-000000"]
    assert q.run("head", "opencode")[1]["head"] == "manual-late"


def test_a_task_waiting_past_the_fair_wait_can_no_longer_be_overtaken(q):
    now = int(time.time())
    q.queue("starving", queued_at=now - 5 * 3600, priority=-3)
    q.queue("bumped", queued_at=now - 60, priority=9)
    code, out = q.run("list")
    rows = out["agents"]["claude"]["queue"]
    assert [r["id"] for r in rows] == ["starving", "bumped"]
    assert rows[0]["protected"] is True and rows[1]["protected"] is False
    # The window comes from limits.env: with a longer one the bump wins again.
    (q.tools / "limits.env").write_text("QUEUE_FAIR_WAIT_SEC=86400\n")
    assert q.order() == ["bumped", "starving"]


def test_list_reports_the_holder_the_quota_hint_and_host_file_hashes(q):
    now = int(time.time())
    (q.locks / ".queue").mkdir(parents=True)
    (q.locks / ".queue" / "claude.holder").write_text(f"ID=holder-task\nPID={os.getpid()}\nSINCE={now}\n")
    (q.locks / ".queue" / "claude.quota").write_text(f"UNTIL={now + 3600}\nBY=holder-task\n")
    (q.locks / ".queue" / "codex.holder").write_text(f"ID=gone\nPID={dead_pid()}\n")
    code, out = q.run("list")
    assert out["agents"]["claude"]["holder"] == {"held": True, "id": "holder-task", "since": now}
    assert out["agents"]["claude"]["quota"] == {"until": now + 3600, "by": "holder-task"}
    assert out["agents"]["codex"]["holder"]["held"] is False
    assert out["runner"]["api"] == 2 and out["host_files"]["run-agent.sh"]
    assert out["host_files"]["dispatch.sh"] is None


@pytest.mark.parametrize("tid, code", [("../etc", 2), ("Bad_ID", 2), ("no-such-task", 4)])
def test_cancel_rejects_what_is_not_a_known_task(q, tid, code):
    got, out = q.run("cancel", tid)
    assert got == code and out["ok"] is False and out["code"] == code
    assert not q.calls.exists()


def test_cancel_of_an_ended_task_is_an_explicit_error(q):
    q.task("done-task", result="STATE=ok\n", active=False)
    code, out = q.run("cancel", "done-task")
    assert code == 3 and "already ended (state=ok)" in out["error"]


def test_cancel_of_a_queued_task_is_cheap_audited_and_idempotent(q):
    d = q.task("queued-task", result="STATE=queued\nWAITING=lock\nATTEMPTS=0\n")
    code, out = q.run("--source", "ui", "cancel", "queued-task")
    assert code == 0 and out["state"] == "cancelled" and out["was"] == "queued"
    assert out["progress_lost"] is False and out["pending"] is False
    assert "stop --no-block agent-dispatch-queued-task.service" in q.calls.read_text()
    line = (d / "audit.log").read_text()
    assert "source=ui\taction=cancel\twas=queued state=cancelled" in line
    # Again: the unit is gone and the task says cancelled, so this is a no-op, not an error.
    code, out = q.run("cancel", "queued-task")
    assert code == 0 and out["already"] is True
    assert q.calls.read_text().count("stop ") == 1


def test_cancel_of_a_running_task_reports_the_session_to_resume(q):
    q.task("busy-task", result="STATE=running\nATTEMPTS=1\nSLOT=claude-1\n", session="abc-123")
    code, out = q.run("cancel", "busy-task")
    assert code == 0 and out["was"] == "running" and out["progress_lost"] is True
    assert out["session"] == "abc-123" and out["resume"] == "cd /root && claude --resume abc-123"


def test_a_second_cancel_while_the_first_is_settling_does_not_stop_twice(q):
    d = q.task("slow-task", result="STATE=running\nATTEMPTS=1\n")
    (d / "cancel-requested").write_text("earlier\n")
    code, out = q.run("cancel", "slow-task")
    assert code == 0 and out["pending"] is True
    assert not q.calls.exists() or "stop" not in q.calls.read_text()


def test_systemctl_refusal_is_a_visible_failure(q):
    d = q.task("stuck-task", result="STATE=running\nATTEMPTS=1\n")
    code, out = q.run("cancel", "stuck-task", extra_env={"STOP_FAILS": "1"})
    assert code == 5 and "access denied" in out["error"]
    assert not (d / "cancel-requested").exists()
    assert "action=cancel\tfailed: rc=1" in (d / "audit.log").read_text()


def test_a_write_already_in_flight_on_the_same_task_answers_busy(q):
    import fcntl
    d = q.task("locked-task", result="STATE=running\nATTEMPTS=1\n")
    fd = os.open(d / ".ops.lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        code, out = q.run("cancel", "locked-task")
    finally:
        os.close(fd)
    assert code == 6 and out["ok"] is False


def test_installer_saves_installs_checks_and_rolls_back(tmp_path):
    dest = tmp_path / "agent-dispatch"
    dest.mkdir()
    (dest / "task_queue_ops.py").write_text("print('old')\n")
    env = dict(os.environ, AGENT_DISPATCH_DIR=str(dest))
    run = lambda *a: subprocess.run(["bash", str(INSTALL), *a], env=env, capture_output=True, text=True, timeout=60)
    assert run("--check").returncode == 1
    r = run()
    assert r.returncode == 0, r.stderr
    assert (dest / "task_queue_ops.py").read_bytes() == OPS.read_bytes()
    assert (dest / "task_queue_ops.py.before-update").read_text() == "print('old')\n"
    assert os.access(dest / "task_queue_ops.py", os.X_OK)
    assert run("--check").returncode == 0
    assert "already installed" in run().stdout
    assert run("--rollback").returncode == 0
    assert (dest / "task_queue_ops.py").read_text() == "print('old')\n"
