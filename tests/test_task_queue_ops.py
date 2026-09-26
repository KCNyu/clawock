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
  list-units) sed 's/$/ loaded active running agent-dispatch/' "{units}" ;;
  stop)
    [ -n "${{STOP_FAILS:-}}" ] && {{ echo "Failed to stop: access denied" >&2; exit 1; }}
    id=${{3#agent-dispatch-}}; id=${{id%.service}}
    sed -i 's/^STATE=.*/STATE=cancelled/' "{tasks}/$id/result.env"
    grep -vx "$3" "{units}" >"{units}.new"; mv "{units}.new" "{units}" ;;
esac
""")
    systemctl.chmod(0o755)
    # dispatch.sh owns append/continue; the fake records what it was asked and what it read.
    (tools / "dispatch.sh").write_text(f"""#!/bin/bash
printf '%s\\n' "$*" >>"{tmp_path}/dispatch.calls"; cat >>"{tmp_path}/dispatch.stdin"
[ -n "${{DISPATCH_FAILS:-}}" ] && {{ echo "refused: nope" >&2; exit 2; }}
[ "$1" = append ] && echo "task $2 has ended; continuing session as a new task" && echo "dispatched $2-retry-20260926-000000"
exit 0
""")
    (tools / "dispatch.sh").chmod(0o755)
    (tools / "opencode-fallback-models").write_text("# pool\nopencode/free-a\nopencode/free-b  # comment\n")
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-6-sol", "visibility": "list", "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}]},
        {"slug": "gpt-hidden", "visibility": "hide", "supported_reasoning_levels": [{"effort": "low"}]}]}))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text("""#!/bin/sh
cat <<'EOF'
  --effort <level>                      Effort level for the current session
                                        (low, medium, high, xhigh, max)
  --model <model>                       Model for the current session. Provide
                                        an alias for the latest model (e.g.
                                        'fable', 'opus', or 'sonnet') or a
                                        model's full name (e.g.
                                        'claude-fable-5').
  -n, --name <name>                     Set a display name
EOF
""")
    (bindir / "claude").chmod(0o755)
    env = dict(os.environ, AGENT_DISPATCH_TASKS_DIR=str(tasks), AGENT_DISPATCH_LOCKDIR=str(locks),
               AGENT_DISPATCH_DIR=str(tools), AGENT_DISPATCH_SYSTEMCTL=str(systemctl), CODEX_HOME=str(codex_home),
               PATH=f"{bindir}:{os.environ['PATH']}")
    env.pop("AGENT_DISPATCH_FAIR_WAIT_SEC", None)

    class Q:
        def __init__(self):
            self.tasks, self.locks, self.tools, self.env = tasks, locks, tools, env
            self.calls = calls
            self.root = tmp_path

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

        def waiter(self, tid, agent="claude", queued_at=None, priority=None, extra=""):
            """A live task of the current runner, registered as waiting for its agent lock."""
            self.task(tid, agent=agent, result=f"STATE=running\nWAITING=lock\nATTEMPTS=0\nRUNNER_API=2\n{extra}")
            self.queue(tid, agent=agent, queued_at=queued_at, priority=priority)
            return tasks / tid

        def run(self, *args, extra_env=None, stdin=None):
            r = subprocess.run([sys.executable, str(OPS), "--json", *args], env=dict(env, **(extra_env or {})),
                               capture_output=True, text=True, timeout=30, input=stdin)
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
    assert out["agents"]["claude"]["holder"] == {"held": True, "id": "holder-task", "since": now, "legacy": False, "note": ""}
    assert out["agents"]["claude"]["quota"] == {"until": now + 3600, "by": "holder-task"}
    assert out["agents"]["codex"]["holder"]["held"] is False
    assert out["runner"]["api"] == 2 and out["host_files"]["run-agent.sh"]
    assert set(out["host_files"]) == {"run-agent.sh", "dispatch.sh", "limits.env", "opencode-fallback-models"}
    assert all(out["host_files"].values())


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
    # The runner has written its terminal state but the unit is still winding down.
    (d / "result.env").write_text("STATE=cancelled\nATTEMPTS=1\n")
    code, out = q.run("cancel", "slow-task")
    assert code == 0 and out["pending"] is False and out["message"] == "already cancelled"


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


# ---- priority --------------------------------------------------------------------------------

def test_top_puts_a_task_first_and_records_who_did_it(q):
    now = int(time.time())
    for i, tid in enumerate(["a-task", "b-task", "c-task"]):
        q.waiter(tid, queued_at=now - 300 + i)
    code, out = q.run("--source", "ui", "priority", "c-task", "top")
    assert code == 0 and out["queue"] == ["c-task", "a-task", "b-task"] and out["position"] == 1
    assert (q.tasks / "c-task" / "override.env").read_text() == "PRIORITY=1\n"
    assert "source=ui\taction=priority\tpriority 0->1" in (q.tasks / "c-task" / "audit.log").read_text()
    assert q.run("head", "claude")[1]["head"] == "c-task"


def test_up_and_down_move_exactly_one_place(q):
    now = int(time.time())
    for i, tid in enumerate(["a-task", "b-task", "c-task"]):
        q.waiter(tid, queued_at=now - 300 + i)
    assert q.run("priority", "c-task", "up")[1]["queue"] == ["a-task", "c-task", "b-task"]
    assert q.run("priority", "a-task", "down")[1]["queue"] == ["c-task", "a-task", "b-task"]
    # A reordered neighbour gets its own audit line naming the move.
    assert "(reorder: a-task down)" in (q.tasks / "c-task" / "audit.log").read_text()
    # At the edge it is a no-op, not an error.
    code, out = q.run("priority", "c-task", "up")
    assert code == 0 and out["changed"] is False and "already first" in out["message"]


def test_reset_and_absolute_values(q):
    now = int(time.time())
    q.waiter("a-task", queued_at=now - 300)
    q.waiter("b-task", queued_at=now - 200)
    assert q.run("priority", "b-task", "5")[1]["queue"] == ["b-task", "a-task"]
    assert q.run("priority", "b-task", "reset")[1]["queue"] == ["a-task", "b-task"]
    assert not (q.tasks / "b-task" / "override.env").read_text().strip()
    code, out = q.run("priority", "b-task", "sideways")
    assert code == 2


def test_priority_refusals_are_explicit(q):
    now = int(time.time())
    q.task("ended-task", result="STATE=ok\nRUNNER_API=2\n", active=False)
    assert q.run("priority", "ended-task", "top")[0] == 3
    q.task("old-runner-task", result="STATE=running\nWAITING=lock\n")
    code, out = q.run("priority", "old-runner-task", "top")
    assert code == 3 and "older runner" in out["error"]
    q.waiter("patrol-docs-20260926-000000", agent="opencode", queued_at=now)
    code, out = q.run("priority", "patrol-docs-20260926-000000", "top")
    assert code == 3 and "patrol rounds always go last" in out["error"]
    q.task("running-task", result="STATE=running\nSLOT=claude-1\nATTEMPTS=1\nRUNNER_API=2\n")
    code, out = q.run("priority", "running-task", "top")
    assert code == 3 and "already running" in out["error"]


def test_a_protected_task_is_not_reordered(q):
    now = int(time.time())
    q.waiter("old-task", queued_at=now - 5 * 3600)
    q.waiter("new-task", queued_at=now - 10)
    code, out = q.run("priority", "new-task", "top")
    assert code == 0 and out["queue"] == ["old-task", "new-task"]
    code, out = q.run("priority", "old-task", "down")
    assert code == 0 and out["changed"] is False and "fair wait" in out["message"]


def test_priority_of_a_task_asleep_on_quota_is_kept_for_its_return(q):
    q.task("sleeping-task", result=f"STATE=running\nWAITING=quota\nATTEMPTS=1\nRUNNER_API=2\nQUEUED_AT={int(time.time()) - 60}\n")
    code, out = q.run("priority", "sleeping-task", "3")
    assert code == 0 and "PRIORITY=3" in (q.tasks / "sleeping-task" / "override.env").read_text()


# ---- model / effort ------------------------------------------------------------------------

def test_choices_come_from_each_agents_own_sources(q):
    q.task("c-task", result="STATE=running\nRUNNER_API=2\n")
    code, out = q.run("choices", "c-task")
    assert code == 0 and out["allowed"] is True and out["effort_flag"] == "--effort"
    assert {"m", "fable", "opus", "sonnet", "claude-fable-5"} <= set(out["models"])
    assert out["efforts"]["opus"] == ["low", "medium", "high", "xhigh", "max"]
    q.task("x-task", agent="codex", result="STATE=running\nRUNNER_API=2\n")
    out = q.run("choices", "x-task")[1]
    assert "gpt-6-sol" in out["models"] and "gpt-hidden" not in out["models"]
    assert out["efforts"]["gpt-6-sol"] == ["low", "medium"] and out["effort_flag"] == "model_reasoning_effort"
    q.task("o-task", agent="opencode", result="STATE=running\nRUNNER_API=2\n")
    out = q.run("choices", "o-task")[1]
    assert out["models"] == ["m", "opencode/free-a", "opencode/free-b"] and out["efforts"]["opencode/free-a"] == []


def test_model_change_is_validated_written_and_audited(q):
    d = q.task("c-task", result="STATE=running\nSLOT=claude-1\nRUNNER_API=2\n")
    code, out = q.run("--source", "ui", "model", "c-task", "sonnet", "max")
    assert code == 0 and out["applies"] == "next_attempt" and out["running"] is True
    assert out["model_next"] == "sonnet" and out["effort_next"] == "max"
    assert (d / "override.env").read_text() == "MODEL=sonnet\nEFFORT=max\n"
    assert "source=ui\taction=model\tmodel -->sonnet effort -->max" in (d / "audit.log").read_text()
    assert q.run("model", "c-task", "gpt-6-sol")[0] == 2
    assert q.run("model", "c-task", "keep", "ultra")[0] == 2
    code, out = q.run("model", "c-task", "default", "default")
    assert code == 0 and out["model_next"] == "m" and not (d / "override.env").read_text().strip()


def test_codex_model_changes_only_before_there_is_a_session(q):
    q.task("x-new", agent="codex", result="STATE=running\nWAITING=lock\nRUNNER_API=2\n")
    assert q.run("model", "x-new", "gpt-6-sol", "low")[0] == 0
    assert q.run("model", "x-new", "keep", "high")[0] == 2   # not an effort gpt-6-sol accepts
    q.task("x-resumed", agent="codex", result="STATE=running\nRUNNER_API=2\n", session="thread-1")
    code, out = q.run("model", "x-resumed", "gpt-6-sol")
    assert code == 3 and "unverified" in out["error"]
    assert q.run("choices", "x-resumed")[1]["allowed"] is False


def test_opencode_takes_pool_models_and_no_effort(q):
    q.task("o-task", agent="opencode", result="STATE=running\nRUNNER_API=2\n", session="ses_1")
    assert q.run("model", "o-task", "opencode/free-b")[0] == 0
    code, out = q.run("model", "o-task", "keep", "high")
    assert code == 2 and "takes no effort" in out["error"]


def test_model_change_refused_for_ended_or_old_runner_tasks(q):
    q.task("ended", result="STATE=failed\nRUNNER_API=2\n", active=False)
    assert q.run("model", "ended", "sonnet")[0] == 3
    q.task("old", result="STATE=running\n")
    assert q.run("model", "old", "sonnet")[0] == 3


# ---- retry / append / log ------------------------------------------------------------------

def test_retry_continues_an_ended_session_through_dispatch(q):
    d = q.task("failed-task", result="STATE=failed\n", active=False, session="s-1")
    code, out = q.run("--source", "ui", "retry", "failed-task")
    assert code == 0 and out["new_id"] == "failed-task-retry-20260926-000000"
    assert (q.root / "dispatch.calls").read_text() == "append failed-task\n"
    assert "重试" in (q.root / "dispatch.stdin").read_text()
    assert "action=retry\trc=0 new=failed-task-retry" in (d / "audit.log").read_text()


def test_retry_refusals(q):
    q.task("live", result="STATE=running\n", session="s")
    assert q.run("retry", "live")[0] == 3
    q.task("no-session", result="STATE=failed\n", active=False)
    assert q.run("retry", "no-session")[0] == 3
    q.task("done", result="STATE=ok\nOUTCOME=DONE\n", active=False, session="s")
    assert q.run("retry", "done")[0] == 3
    q.task("broken", result="STATE=failed\n", active=False, session="s")
    code, out = q.run("retry", "broken", extra_env={"DISPATCH_FAILS": "1"})
    assert code == 5 and "refused: nope" in out["error"]


def test_append_goes_to_a_live_task_only(q):
    q.task("live", result="STATE=running\n")
    code, out = q.run("append", "live", "--queue", stdin="体面收尾\n")
    assert code == 0 and out["mode"] == "queue"
    assert (q.root / "dispatch.calls").read_text() == "append live --queue\n"
    assert q.run("append", "live", stdin="  \n")[0] == 2
    q.task("gone", result="STATE=ok\n", active=False)
    assert q.run("append", "gone", stdin="more\n")[0] == 3


def test_log_tail_is_redacted(q):
    d = q.task("t", result="STATE=running\n")
    (d / "run.log").write_text("".join(f"line {i}\n" for i in range(100)) + "token=abc123secret ghp_aaaaaaaaaaaaaaaaaaaa\n")
    code, out = q.run("log", "t", "--lines", "3")
    assert out["lines"] == ["line 98", "line 99", "token=<redacted> <redacted>"]


# ---- legacy: tasks of a runner from before RUNNER_API 2 --------------------------------------

def legacy(q, tid, log, result="STATE=queued\nWAITING=lock\n", agent="claude"):
    d = q.task(tid, agent=agent, result=result)
    (d / "run.log").write_text(log)
    return d


def test_legacy_waiters_and_holder_are_listed_never_dropped(q):
    legacy(q, "old-holder", "==== start ====\n2026-09-26 15:06:36 waiting for claude lock (budget 85730s)\n"
           "2026-09-26 18:28:30 lock held\n", result="STATE=running\nSLOT=claude-1\nATTEMPTS=1\n")
    legacy(q, "old-waiter-b", "2026-09-26 15:16:56 waiting for claude lock (budget 1s)\n")
    legacy(q, "old-waiter-a", "2026-09-26 15:16:20 waiting for claude lock (budget 1s)\n")
    import fcntl
    lock = q.locks / "claude.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        code, out = q.run("list")
        head = q.run("head", "claude")[1]
    finally:
        os.close(fd)
    g = out["agents"]["claude"]
    assert g["holder"]["held"] is True and g["holder"]["id"] == "old-holder" and g["holder"]["legacy"] is True
    assert [(r["id"], r["legacy"]) for r in g["queue"]] == [("old-waiter-a", True), ("old-waiter-b", True)]
    assert g["queue"][0]["queued_at"] == int(time.mktime(time.strptime("2026-09-26 15:16:20", "%Y-%m-%d %H:%M:%S")))
    # head is never empty while an older-runner task queues, and says why it goes first.
    assert head["head"] == "old-waiter-a" and head["legacy"] is True and "older runner" in head["note"]


def test_an_unnamed_holder_is_said_so_not_shown_free(q):
    import fcntl
    fd = os.open(q.locks / "claude.lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        out = q.run("list")[1]["agents"]["claude"]["holder"]
        head = q.run("head", "claude")[1]
    finally:
        os.close(fd)
    assert out["held"] is True and out["id"] is None and "older runner" in out["note"]
    assert head["head"] == "" and "held by an unnamed older-runner task" in head["note"]
    assert "nobody waits and the lock is free" in q.run("head", "codex")[1]["note"]


def test_new_runner_tasks_queue_behind_legacy_ones_and_cannot_jump_them(q):
    now = int(time.time())
    legacy(q, "old-waiter", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 600)) + " waiting for claude lock (budget 1s)\n")
    q.waiter("new-a", queued_at=now - 100)
    q.waiter("new-b", queued_at=now - 50)
    assert q.order() == ["old-waiter", "new-a", "new-b"]
    code, out = q.run("priority", "new-b", "top")
    assert code == 0 and out["queue"] == ["old-waiter", "new-b", "new-a"]
    code, out = q.run("priority", "old-waiter", "top")
    assert code == 3 and "older runner" in out["error"]
    code, out = q.run("priority", "new-b", "up")
    assert code == 0 and out["changed"] is False
