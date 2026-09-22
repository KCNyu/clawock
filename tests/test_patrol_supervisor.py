"""Who the patrol supervisor gives way to, exercised without dispatching real tasks.

kcn's rule: manual dispatched work outranks patrol; a patrol round is the lowest
priority and may be preempted. `others_need_slot admission` decides whether a new
round may start, `others_need_slot monitor` whether the running round must yield.
"""
import os
from pathlib import Path
import signal
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "ops/host/patrol.sh"
OWN_ROUND = "patrol-render-20260923-023515"


@pytest.fixture
def patrol(tmp_path):
    dispatch = tmp_path / "dispatch"
    dispatch.mkdir()
    (dispatch / "limits.env").write_text("MAX_RUNNING=2\n")
    # The real thresholds live with the host's resource-pressure.sh; here it only reports
    # whatever the test sets, so the admission-vs-monitor split stays visible.
    (dispatch / "resource-pressure.sh").write_text(
        'memory_pressure_reason() { printf "%s" "${TEST_MEMORY_REASON:-}"; }\n')
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    units = tmp_path / "units"
    units.write_text("")
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(f'#!/bin/sh\n[ "$1" = list-units ] && cat "{units}"\nexit 0\n')
    systemctl.chmod(0o755)
    env = dict(os.environ, PATROL_DISPATCH_DIR=str(dispatch), PATROL_STATE_DIR=str(tmp_path),
               PATROL_TASKS_DIR=str(tasks), PATH=f"{tmp_path}:{os.environ['PATH']}")
    env.pop("AGENT_DISPATCH_MAX_RUNNING", None)

    def task(tid, result, agent="claude"):
        d = tasks / tid
        d.mkdir()
        (d / "meta.env").write_text(f"AGENT={agent}\n")
        (d / "result.env").write_text(result)
        with units.open("a") as f:
            f.write(f"agent-dispatch-{tid}.service loaded active running agent-dispatch\n")

    def ask(mode="admission", held=0, memory=""):
        # Hold slot locks for real: flock(1) inside the script contends with this holder
        # exactly as it would with a running attempt. "ready" means the locks are taken.
        command = ["sh", "-c", "echo ready; exec sleep 30"]
        for i in range(1, held + 1):
            command = ["flock", "-n", str(tasks / f"slot-{i}.lock")] + command
        holder = subprocess.Popen(command, stdout=subprocess.PIPE, text=True,
                                  start_new_session=True) if held else None
        try:
            if holder:
                assert holder.stdout.readline().strip() == "ready"
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; others_need_slot "$2"', "test", str(SCRIPT), mode],
                env=dict(env, TEST_MEMORY_REASON=memory), capture_output=True, text=True, timeout=10)
        finally:
            if holder:
                os.killpg(holder.pid, signal.SIGTERM)  # flock's child holds the lock too
                holder.wait(timeout=10)
                holder.stdout.close()
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def own_round(result="STATE=running\nSLOT=2\n"):
        task(OWN_ROUND, result, agent="opencode")
        (tmp_path / "current-round").write_text(OWN_ROUND + "\n")

    ask.task, ask.own_round = task, own_round
    return ask


@pytest.mark.parametrize("mode", ["monitor", "admission"])
@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_task_queued_on_its_agent_lock_outranks_patrol(patrol, mode, agent):
    # 2026-09-23: a manual claude task sat 33 minutes behind the claude lock while a
    # round ran to completion. The runner asks for a slot only once it holds that lock,
    # so without WAITING=lock the queue never reached the supervisor.
    patrol.own_round()
    patrol.task(f"{agent}-task", "STATE=queued\nWAITING=lock\nSLOT=''\n", agent=agent)
    assert patrol(mode) == f"{agent}-task is waiting for its agent lock"


def test_lock_waiter_is_demand_even_with_free_slots(patrol):
    patrol.task("claude-task", "STATE=queued\nWAITING=lock\nSLOT=''\n")
    assert patrol("admission", held=0) == "claude-task is waiting for its agent lock"


def test_patrols_own_round_waiting_is_not_demand(patrol):
    patrol.own_round("STATE=queued\nWAITING=lock\nSLOT=''\n")
    assert patrol("monitor") == ""


def test_manual_task_named_like_a_round_is_still_demand(patrol):
    # Only the current-round marker identifies the supervisor's own worker. Skipping every
    # patrol-* id hid manual tasks with that name (patrol-source-sync, 2026-09-23).
    patrol.own_round()
    patrol.task("patrol-source-sync-20260923-023843", "STATE=queued\nWAITING=lock\n")
    assert patrol("monitor") == "patrol-source-sync-20260923-023843 is waiting for its agent lock"


@pytest.mark.parametrize("mode", ["monitor", "admission"])
def test_quota_sleepers_hold_nothing_and_do_not_preempt(patrol, mode):
    patrol.task("claude-task", "STATE=running\nWAITING=quota\nSLOT=''\n")
    patrol.task("codex-task", "STATE=running\nWAITING=quota\nSLOT=''\n", agent="codex")
    assert patrol(mode) == ""


def test_slot_waiter_preempts_the_running_round(patrol):
    patrol.own_round()
    patrol.task("codex-task", "STATE=running\nSLOT=1\n", agent="codex")
    patrol.task("claude-task", "STATE=running\nWAITING=slot\n")
    assert patrol("monitor", held=2) == "claude-task is waiting for a run slot"


def test_real_slot_locks_gate_admission(patrol):
    # Probe the locks themselves: one runner reports SLOT, the other predates the field.
    patrol.task("codex-task", "STATE=running\nSLOT=1\n", agent="codex")
    patrol.task("claude-task", "STATE=running\n")
    assert patrol("admission", held=2) == "all 2 run slots are busy"
    # Stale SLOT reports without held locks do not block a new round.
    assert patrol("admission", held=0) == ""


def test_running_round_does_not_preempt_itself_on_capacity(patrol):
    patrol.own_round()
    patrol.task("codex-task", "STATE=running\nSLOT=1\n", agent="codex")
    assert patrol("monitor", held=2) == ""


def test_pre_marker_opencode_queue_still_counts(patrol):
    patrol.task("opencode-task", "STATE=queued\n", agent="opencode")
    assert patrol("monitor") == "opencode-task is waiting for the opencode lock"


def test_memory_pressure_defers_admission_but_never_preempts(patrol):
    assert patrol("admission", memory="memory headroom low") == "memory headroom low"
    assert patrol("monitor", memory="memory headroom low") == ""


RUN_ROUND = '''
DISPATCH="$PATROL_STATE_DIR/dispatch.sh"
round_active() { [ -e "$PATROL_STATE_DIR/active" ]; }
sleep() { :; }
audit_ungated() { :; }
prepare_worktree() { echo 'must not reset an adopted worktree' >&2; return 99; }
run_round
'''


def test_preemption_cancels_only_the_round_and_keeps_the_cursor(patrol, tmp_path):
    patrol.own_round()
    (tmp_path / "tasks" / OWN_ROUND / "meta.env").write_text("CREATED='2026-09-23 02:35:15'\n")
    patrol.task("claude-task", "STATE=queued\nWAITING=lock\n")
    (tmp_path / "round-no").write_text("138\n")
    (tmp_path / "recent-since").write_text("older\n")
    (tmp_path / "active").touch()
    dispatch = tmp_path / "dispatch.sh"
    dispatch.write_text('''#!/bin/sh
echo "$1 $2" >>"$PATROL_STATE_DIR/actions"
printf 'STATE=cancelled\\n' >"$PATROL_TASKS_DIR/$2/result.env"
rm -f "$PATROL_STATE_DIR/active"
''')
    dispatch.chmod(0o755)
    result = subprocess.run(["bash", "-c", 'source "$1"; ' + RUN_ROUND, "test", str(SCRIPT)],
                            env=dict(os.environ, PATROL_DISPATCH_DIR=str(tmp_path / "dispatch"),
                                     PATROL_STATE_DIR=str(tmp_path),
                                     PATROL_TASKS_DIR=str(tmp_path / "tasks"),
                                     PATH=f"{tmp_path}:{os.environ['PATH']}"),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "preempting " + OWN_ROUND + ": claude-task is waiting for its agent lock" in result.stdout
    assert (tmp_path / "actions").read_text() == f"cancel {OWN_ROUND}\n"
    assert "preempted:cancelled" in (tmp_path / "rounds.tsv").read_text()
    assert (tmp_path / "recent-since").read_text() == "older\n"
    assert not (tmp_path / "current-round").exists()


def test_supervisor_stop_leaves_the_round_for_adoption(tmp_path):
    (tmp_path / "current-round").write_text(OWN_ROUND + "\n")
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; DISPATCH=/must-not-cancel; round_active() { :; }; on_stop',
         "test", str(SCRIPT)],
        env=dict(os.environ, PATROL_STATE_DIR=str(tmp_path)), capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert (tmp_path / "current-round").read_text() == OWN_ROUND + "\n"


@pytest.mark.parametrize("result_env, cursor", [
    ("STATE=ok\nOUTCOME=DONE\n", "2026-09-21 12:00:00\n"),
    ("STATE=partial\nOUTCOME=PARTIAL\n", "older\n"),
    ("STATE=unverified\nOUTCOME=''\n", "older\n"),
])
def test_only_a_done_recent_round_advances_the_review_cursor(tmp_path, result_env, cursor):
    rid = "patrol-recent-20260921-120000"
    task = tmp_path / "tasks" / rid
    task.mkdir(parents=True)
    (task / "meta.env").write_text("CREATED='2026-09-21 12:00:00'\n")
    (task / "result.env").write_text(result_env)
    (tmp_path / "round-no").write_text("5\n")
    (tmp_path / "current-round").write_text(rid + "\n")
    (tmp_path / "recent-since").write_text("older\n")
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; round_active() { return 1; }; ' + RUN_ROUND, "test", str(SCRIPT)],
        env=dict(os.environ, PATROL_STATE_DIR=str(tmp_path), PATROL_TASKS_DIR=str(tmp_path / "tasks")),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "recent-since").read_text() == cursor
