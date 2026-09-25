"""Who the patrol supervisor gives way to, exercised without dispatching real tasks.

kcn's rule: manual dispatched work outranks patrol; a patrol round is the lowest
priority and may be preempted. `others_need_slot admission` decides whether a new
round may start, `others_need_slot monitor` whether the running round must yield.
"""
import contextlib
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

    @contextlib.contextmanager
    def slots(held):
        # Hold slot locks for real: flock(1) inside the script contends with this holder
        # exactly as it would with a running attempt. "ready" means the locks are taken.
        if not held:
            yield
            return
        command = ["sh", "-c", "echo ready; exec sleep 30"]
        for i in range(1, held + 1):
            command = ["flock", "-n", str(tasks / f"slot-{i}.lock")] + command
        holder = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, start_new_session=True)
        try:
            assert holder.stdout.readline().strip() == "ready"
            yield
        finally:
            os.killpg(holder.pid, signal.SIGTERM)  # flock's child holds the lock too
            holder.wait(timeout=10)
            holder.stdout.close()

    def ask(mode="admission", held=0, memory=""):
        with slots(held):
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; others_need_slot "$2"', "test", str(SCRIPT), mode],
                env=dict(env, TEST_MEMORY_REASON=memory), capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def own_round(result="STATE=running\nSLOT=2\n"):
        task(OWN_ROUND, result, agent="opencode")
        (tmp_path / "current-round").write_text(OWN_ROUND + "\n")

    ask.task, ask.own_round, ask.env, ask.slots = task, own_round, env, slots
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


@pytest.mark.parametrize("mode", ["monitor", "admission"])
def test_a_quota_parked_agent_queue_is_not_demand(patrol, mode):
    # 2026-09-24: three claude tasks queued behind a lock whose holder slept until the 5h
    # reset, and patrol sat out the whole window next to two free run slots. A queue whose
    # own agent cannot start is not demand; the 09-23 rule resumes when the holder wakes.
    patrol.own_round()
    patrol.task("claude-holder", "STATE=running\nWAITING=quota\nSLOT=''\n")
    patrol.task("claude-queued", "STATE=queued\nWAITING=lock\nSLOT=''\n")
    assert patrol(mode) == ""


def test_the_same_queue_outranks_patrol_once_the_holder_wakes(patrol):
    # Without the quota sleep these are the 09-23 tasks again: demand, preemption included.
    patrol.own_round()
    patrol.task("claude-holder", "STATE=running\nSLOT=1\n")
    patrol.task("claude-queued", "STATE=queued\nWAITING=lock\nSLOT=''\n")
    assert patrol("monitor") == "claude-queued is waiting for its agent lock"


def test_another_agents_quota_sleep_does_not_release_this_queue(patrol):
    # Only the queued task's own agent counts: a parked codex task says nothing about claude.
    patrol.task("codex-holder", "STATE=running\nWAITING=quota\nSLOT=''\n", agent="codex")
    patrol.task("claude-queued", "STATE=queued\nWAITING=lock\nSLOT=''\n")
    assert patrol("admission") == "claude-queued is waiting for its agent lock"


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
clock=0
now() { echo "$clock"; }
sleep() { clock=$((clock + $1)); }
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
                            env=patrol.env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "preempting " + OWN_ROUND + ": claude-task is waiting for its agent lock" in result.stdout
    assert (tmp_path / "actions").read_text() == f"cancel {OWN_ROUND}\n"
    assert "preempted:cancelled" in (tmp_path / "rounds.tsv").read_text()
    assert (tmp_path / "recent-since").read_text() == "older\n"
    assert not (tmp_path / "current-round").exists()


def test_supervisor_stop_leaves_the_round_for_adoption(patrol, tmp_path):
    (tmp_path / "current-round").write_text(OWN_ROUND + "\n")
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; DISPATCH=/must-not-cancel; round_active() { :; }; on_stop',
         "test", str(SCRIPT)],
        env=patrol.env, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert (tmp_path / "current-round").read_text() == OWN_ROUND + "\n"


@pytest.mark.parametrize("result_env, cursor", [
    ("STATE=ok\nOUTCOME=DONE\n", "2026-09-21 12:00:00\n"),
    ("STATE=partial\nOUTCOME=PARTIAL\n", "older\n"),
    ("STATE=unverified\nOUTCOME=''\n", "older\n"),
])
def test_only_a_done_recent_round_advances_the_review_cursor(patrol, tmp_path, result_env, cursor):
    rid = "patrol-recent-20260921-120000"
    task = tmp_path / "tasks" / rid
    task.mkdir()
    (task / "meta.env").write_text("CREATED='2026-09-21 12:00:00'\n")
    (task / "result.env").write_text(result_env)
    (tmp_path / "round-no").write_text("5\n")
    (tmp_path / "current-round").write_text(rid + "\n")
    (tmp_path / "recent-since").write_text("older\n")
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; round_active() { return 1; }; ' + RUN_ROUND, "test", str(SCRIPT)],
        env=patrol.env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "recent-since").read_text() == cursor


# ---- graceful preemption: a round that has to give way first lands its findings --------

SESSION = "SESSION=ses_f2ba4c4e3ffe1By3CJODcDSEQj\n"


@pytest.fixture
def adopted(patrol, tmp_path):
    """An adopted round (R138) under a stub dispatch.sh that records what it was asked.

    `append` keeps the instruction and runs `on-append` (how the round reacts); `cancel`
    ends the round the way the runner does.
    """
    dispatch = tmp_path / "dispatch.sh"
    dispatch.write_text('''#!/bin/sh
echo "$1 $2" >>"$PATROL_STATE_DIR/actions"
case "$1" in
  append) cat >"$PATROL_STATE_DIR/appended"
          [ ! -f "$PATROL_STATE_DIR/on-append" ] || . "$PATROL_STATE_DIR/on-append" ;;
  cancel) printf 'STATE=cancelled\\nRC=143\\n' >"$PATROL_TASKS_DIR/$2/result.env"
          rm -f "$PATROL_STATE_DIR/active" ;;
esac
''')
    dispatch.chmod(0o755)
    (tmp_path / "round-no").write_text("138\n")
    (tmp_path / "recent-since").write_text("older\n")
    (tmp_path / "active").touch()

    def start(rid=OWN_ROUND, result="STATE=running\nSLOT=2\n" + SESSION):
        task = tmp_path / "tasks" / rid
        task.mkdir()
        (task / "meta.env").write_text("AGENT=opencode\nCREATED='2026-09-23 02:35:15'\n")
        (task / "result.env").write_text(result)
        with (tmp_path / "units").open("a") as f:
            f.write(f"agent-dispatch-{rid}.service loaded active running agent-dispatch\n")
        (tmp_path / "current-round").write_text(rid + "\n")

    def on_append(script):
        (tmp_path / "on-append").write_text(script)

    def run(held=0, **env):
        with patrol.slots(held):
            result = subprocess.run(["bash", "-c", 'source "$1"; ' + RUN_ROUND, "test", str(SCRIPT)],
                                    env=dict(patrol.env, **env), capture_output=True, text=True, timeout=20)
        actions = tmp_path / "actions"
        return result, actions.read_text() if actions.exists() else ""

    run.start, run.on_append, run.task = start, on_append, patrol.task
    return run


ROUND_ENDS = '''printf 'STATE=%s\\nOUTCOME=%s\\n' "$END_STATE" "$END_OUTCOME" >"$PATROL_TASKS_DIR/$2/result.env"
rm -f "$PATROL_STATE_DIR/active"
'''


@pytest.mark.parametrize("held", [0, 2])
def test_a_round_that_must_give_way_is_told_to_land_its_findings_first(adopted, tmp_path, held):
    # 2026-09-24: six rounds in a row were cancelled outright for queued claude/codex tasks;
    # ledger.md is rewritten only at the end, so everything a round had found went with it.
    # A task queued behind another agent's lock waits for that holder, whose slot frees with
    # the lock, so wrapping up costs it nothing even when both slots are busy.
    adopted.start()
    adopted.task("claude-task", "STATE=queued\nWAITING=lock\n")
    adopted.on_append(ROUND_ENDS)
    result, actions = adopted(held=held, END_STATE="partial", END_OUTCOME="PARTIAL")
    assert result.returncode == 0, result.stdout + result.stderr
    assert actions == f"append {OWN_ROUND}\n"
    assert "asking " + OWN_ROUND + " to wrap up within 300s: claude-task is waiting for its agent lock" \
        in result.stdout
    note = (tmp_path / "appended").read_text()
    for what in ("issue-format.md", f"{tmp_path}/drafts/R138-", "file_issue.sh", f"{tmp_path}/ledger.md",
                 "STATUS: PARTIAL"):
        assert what in note
    assert "\tyielded:partial/PARTIAL\t" in (tmp_path / "rounds.tsv").read_text()
    assert not (tmp_path / "current-round").exists()
    assert not (tmp_path / "yielding").exists()


def test_a_round_that_ignores_the_wrap_up_is_cancelled_when_the_grace_runs_out(adopted, tmp_path):
    adopted.start()
    adopted.task("claude-task", "STATE=queued\nWAITING=lock\n")
    result, actions = adopted()
    assert result.returncode == 1, result.stdout + result.stderr
    assert actions == f"append {OWN_ROUND}\ncancel {OWN_ROUND}\n"
    assert "preempting " + OWN_ROUND + " after a 300s wrap-up grace: claude-task is waiting for its agent lock" \
        in result.stdout
    assert "\tpreempted:cancelled\t" in (tmp_path / "rounds.tsv").read_text()
    assert not (tmp_path / "yielding").exists()


def test_the_grace_is_overridable(adopted):
    adopted.start()
    adopted.task("claude-task", "STATE=queued\nWAITING=lock\n")
    result, actions = adopted(PATROL_PREEMPT_GRACE="60")
    assert actions == f"append {OWN_ROUND}\ncancel {OWN_ROUND}\n"
    assert "after a 60s wrap-up grace" in result.stdout


@pytest.mark.parametrize("case", ["no session yet", "grace disabled", "slot waiter, slots full",
                                  "queued behind the round's opencode lock"])
def test_the_round_is_cancelled_at_once_when_a_grace_would_cost_someone(adopted, case):
    # Without a session no step has run (nothing to land) and an append cannot interrupt the
    # attempt; with every slot busy, or an opencode task behind this round's own lock, the
    # grace is exactly what the queued task would wait for.
    adopted.start(result="STATE=running\nSLOT=2\n" + ("SESSION=''\n" if case == "no session yet" else SESSION))
    held, env, expected = 0, {}, "claude-task is waiting for its agent lock"
    if case == "slot waiter, slots full":
        held, expected = 2, "claude-task is waiting for a run slot and all 2 are busy"
        adopted.task("codex-task", "STATE=running\nSLOT=1\n", agent="codex")
        adopted.task("claude-task", "STATE=running\nWAITING=slot\n")
    elif case == "queued behind the round's opencode lock":
        expected = "opencode-task is queued behind the round's opencode lock"
        adopted.task("opencode-task", "STATE=queued\nWAITING=lock\n", agent="opencode")
    else:
        adopted.task("claude-task", "STATE=queued\nWAITING=lock\n")
        if case == "grace disabled":
            env["PATROL_PREEMPT_GRACE"] = "0"
    result, actions = adopted(held=held, **env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert actions == f"cancel {OWN_ROUND}\n"
    assert f"preempting {OWN_ROUND}: {expected}" in result.stdout


def test_the_grace_ends_as_soon_as_the_round_blocks_someone(adopted, tmp_path):
    # Both slots busy, a claude task queued on its lock: grace. Then another task starts
    # waiting for a slot — from that poll on the round's slot is in its way.
    adopted.start()
    adopted.task("codex-task", "STATE=running\nSLOT=1\n", agent="codex")
    adopted.task("claude-task", "STATE=queued\nWAITING=lock\n")
    adopted.on_append(f'''mkdir "$PATROL_TASKS_DIR/codex-late"
printf 'AGENT=codex\\n' >"$PATROL_TASKS_DIR/codex-late/meta.env"
printf 'STATE=running\\nWAITING=slot\\n' >"$PATROL_TASKS_DIR/codex-late/result.env"
echo "agent-dispatch-codex-late.service loaded active running x" >>"{tmp_path}/units"
''')
    result, actions = adopted(held=2)
    assert actions == f"append {OWN_ROUND}\ncancel {OWN_ROUND}\n"
    assert f"preempting {OWN_ROUND} after a 30s wrap-up grace: codex-late is waiting for a run slot" \
        in result.stdout


def test_an_adopted_round_already_wrapping_up_is_not_told_twice(adopted, tmp_path):
    # The supervisor restarted mid-grace (e.g. an install): the grace keeps its start time.
    adopted.start()
    adopted.task("claude-task", "STATE=queued\nWAITING=lock\n")
    (tmp_path / "yielding").write_text(f"{OWN_ROUND} -180\n")
    result, actions = adopted()
    assert actions == f"cancel {OWN_ROUND}\n"
    assert "after a 300s wrap-up grace" in result.stdout


def test_a_recent_round_cut_short_does_not_advance_the_review_cursor(adopted, tmp_path):
    rid = "patrol-recent-20260923-023515"
    adopted.start(rid=rid)
    adopted.task("claude-task", "STATE=queued\nWAITING=lock\n")
    adopted.on_append(ROUND_ENDS)
    result, actions = adopted(END_STATE="ok", END_OUTCOME="DONE")
    assert result.returncode == 0, result.stdout + result.stderr
    assert actions == f"append {rid}\n"
    assert (tmp_path / "recent-since").read_text() == "older\n"
