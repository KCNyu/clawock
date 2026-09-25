# Host operations

Host-local scheduler, cron visibility, session maintenance and launcher wiring.
These commands may read OpenClaw runtime state and the KCNyu schedule contract;
they must not implement portfolio or workflow semantics.

Common read-only entry points:

```bash
bash ops/host/check_crons.sh
bash ops/host/check_crons.sh --timeline
python3 ops/host/cron_health_check.py
```

## Patrol supervisor

`patrol.sh` is the versioned source for this host's existing
`/root/tools/clawock-patrol/patrol.sh`. The `clawock-patrol.service` systemd
service runs its `run` command, independently of cron. Its rotation, prompts,
issue gate and service unit remain under `/root/tools/clawock-patrol/`; dispatch
policy and helpers remain under `/root/tools/agent-dispatch/`. This script is
an update to an existing installation, not a standalone patrol installer.

After review and merge, compare the installed supervisor with the reviewed
source (check for intervening host edits), save the installed file for rollback,
then install the source:

```bash
cp /root/tools/clawock-patrol/patrol.sh /root/tools/clawock-patrol/patrol.sh.before-update
install -m 0755 ops/host/patrol.sh /root/tools/clawock-patrol/patrol.sh
systemctl restart clawock-patrol.service
cmp ops/host/patrol.sh /root/tools/clawock-patrol/patrol.sh
systemctl is-active clawock-patrol.service
journalctl -u clawock-patrol.service -n 20 --no-pager
```

The supervisor preserves `current-round` on restart and adopts the independent
worker without refreshing its worktree. A failed GitHub bypass audit now keeps
that same marker for retry through the existing backoff; it does not launch a
replacement worker or advance the recent-review cursor. Inspect the journal for
`bypass status unknown` versus `UNGATED issues`, and
`/root/logs/clawock-patrol/ungated.log` for findings. `refresh_live.sh` does not
install this host-local supervisor automatically. To roll back, restore the
saved executable and restart only `clawock-patrol.service`.
`patrol.sh.before-update` is only "what ran before the last install": every
install overwrites it, so never install by hand without that `cp` first, and
do not treat an older copy as a known-good version.

Priority: manual dispatched work outranks patrol, and a round is the lowest
priority work on the host. Since 2026-09-25 every agent has its own run slots
(`slot-<agent>-<n>.lock`, per-agent counts `MAX_RUNNING_<AGENT>` in `limits.env`),
so a round only ever holds the opencode lock and an opencode slot, and only work
that needs one of those is demand. `others_need_slot` blocks a new round, and
preempts the running one, when a task other than the round named in
`current-round` is an opencode task publishing `WAITING=lock` (queued behind the
opencode lock — the runner asks for a slot only after that lock) or
`WAITING=slot`. A claude/codex task queued for its own lock or slot waits for its
own agent and is not demand. The quota exception (kcn, 2026-09-24) stays: a queue
whose own agent's lock holder publishes `WAITING=quota` is not demand until the
holder wakes. `WAITING=quota`/`retry`/`memory` hold nothing and do not preempt.
Capacity (the opencode slots all held) and memory pressure only gate admission of
a new round.

Transition: runners from before 2026-09-25 shared `slot-1.lock`/`slot-2.lock`
among all agents, and a task started then may run for up to 72h. While both are
held, a new round waits, and a task waiting for a slot preempts a round that
holds one of them itself (its `SLOT=` is a bare number). Remove `LEGACY_SLOTS`
after 2026-09-29. Rounds are dispatched with
`AGENT_DISPATCH_PATROL=1`, because `dispatch.sh` reserves `patrol-*` names for
them; the supervisor still identifies its own round by `current-round`, never
by name.

Preemption is graceful when that costs the queued task nothing. The monitor
(every 30s) first appends a wrap-up instruction to the round (`dispatch.sh
append`): file the candidates it has already confirmed through the gate
(`issue-format.md` drafts + `file_issue.sh`), rewrite `ledger.md`, answer
`STATUS: PARTIAL`. It then waits up to `PATROL_PREEMPT_GRACE` seconds (default
300; `0` restores the immediate cancel). A round that ends within the grace is
closed like any other round (bypass audit, `rounds.tsv` as `yielded:<state>`, no
backoff), except that a `recent` round never advances the review cursor; one
still running is cancelled (`preempted:cancelled`). There is no grace, and the
round is cancelled at once, when:

- the round blocks someone: an opencode task waits for an opencode slot while
  all are held, an old runner's task waits while both shared slots are held (see
  Transition), or an opencode task is queued behind the opencode lock the round
  holds. This is rechecked every poll and ends a grace already running. With
  per-agent slots almost all demand is of this kind, so the grace path is a
  safety valve that rarely runs;
- the round has no session yet (`SESSION` empty in its `result.env`): no step has
  run, so there is nothing to land, and the runner cannot interrupt the attempt
  to deliver an append;
- `PATROL_PREEMPT_GRACE=0`.

`/root/logs/clawock-patrol/yielding` records the round and the grace's start, so
a supervisor restart during the grace does not append the instruction twice;
`patrol.sh status` shows it.

`PATROL_DISPATCH_DIR` can point tests at fixture policy/helpers; production uses
`/root/tools/agent-dispatch`. Run the focused supervisor coverage with
`env -u CLAWOCK_WORKSPACE PYTHONPATH="$PWD/src" python3 -m pytest -q tests/test_patrol_audit.py tests/test_patrol_supervisor.py`.
