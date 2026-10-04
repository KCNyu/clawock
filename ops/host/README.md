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

## Task queue ops entry

`task_queue_ops.py` is the versioned entry point for the agent-dispatch queue: the
runner asks it who takes an agent lock next, and the dsh task chip runs every write
(cancel, …) through it. Contract, exit codes and queue order:
`docs/architecture/task-queue.md`. It is installed next to the host-local runner, and
merging does not install it:

```bash
ops/host/install_task_queue_ops.sh           # task_queue_ops.py + model_prices.json: saves .before-update, installs atomically, cmp
ops/host/install_task_queue_ops.sh --check   # does the installed copy match this checkout?
ops/host/install_task_queue_ops.sh --rollback
```

Focused coverage: `python3 -m pytest -q tests/test_task_queue_ops.py`.

## Agent-dispatch runner

`agent-dispatch/` is the versioned source of `/root/tools/agent-dispatch/` (the runner
`run-agent.sh`, the CLI `dispatch.sh`, their helpers, the review template and the runner's own
tests), mirrored path for path. It is a separate install target from the ops entry above:

```bash
ops/host/install_agent_dispatch.sh            # per file: .before-update, install by rename, cmp
ops/host/install_agent_dispatch.sh --check    # exit 1 for file drift; 3 for missing limits keys
ops/host/install_agent_dispatch.sh --check-files # file drift only; exit 1
ops/host/install_agent_dispatch.sh --rollback # undo the last install that changed something
```

`refresh_live.sh` runs it whenever the installed copy fails `--check`, even when the checkout
was already current (cron's pushes fast-forward it too; merging
alone installs nothing). Running tasks keep the file they opened; no unit is restarted.
`limits.env` and `notify.env` stay on the host and are never written by the installer. Why,
and what else stays: `docs/architecture/task-queue.md` § What stays on the host. The suite
runs in CI (`dispatch-runner.yml`, groups and timings in its header), and on the host against a
staged copy:
`AGENT_DISPATCH_RUNNER=<copy>/run-agent.sh DISPATCH_TEST_CASES=<groups> bash <copy>/tests/run-tests.sh`.

## Patrol supervisor

`patrol.sh` is the versioned source for this host's existing
`/root/tools/clawock-patrol/patrol.sh`. The `clawock-patrol.service` systemd
service runs its `run` command, independently of cron. Dispatch policy and
helpers remain under `/root/tools/agent-dispatch/`. This script is an update to
an existing installation, not a standalone patrol installer.

What each round reads — `round-prompt.md`, the lessons and hunting-pattern
lists, `axes.tsv`/`rotation`/`surfaces.json`, the filing gate `gate_issue.py`
with its helpers, and the service unit — is versioned in
`ops/host/clawock-patrol/`, which mirrors `/root/tools/clawock-patrol/` path for
path (its `README.md` says who reads which file when). It is installed by
`ops/host/install_patrol_assets.sh` (atomic per file, `.before-update`, `cmp`;
`--check`, `--rollback` undoes only the last install), and `refresh_live.sh`
runs it whenever `--check` fails. Nothing restarts: every round rereads them. A
changed unit file still needs `systemctl daemon-reload` and a restart by hand.
Findings are graded and routed by `triage.py` (severity with evidence, labels, a
digest issue for P3 and over-budget findings, one issue per root cause) and
`patrol_intel.py` feeds each round its own precision and today's budget; the
rules are in that directory's `README.md` § 分级与路由. When closing a patrol
issue as untrue or not worth fixing, close it as not planned or add
`patrol:noise`: that is the feedback loop's only input.
Only kcn's standing instructions (`steer.md`, written by `patrol.sh steer`) and
the state under `/root/logs/clawock-patrol/` stay on the host: the first is a
live operator note, the second is run state. Prompt and gate changes go through
a PR like any other code, so the lessons they encode can be reviewed.

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

Runners from before 2026-09-25 shared `slot-1.lock`/`slot-2.lock` among all agents;
the supervisor's `LEGACY_SLOTS` handling for them (and the dsh chip's "old shared
slots" bucket) was removed on 2026-09-27, after checking that no such runner was
left (every active unit's `run.log` header read `agent_slots=`, neither shared lock
was held). Rounds are dispatched with
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
  all are held, or an opencode task is queued behind the opencode lock the round
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

## Skill registry host extension

`skillhub/` is the maintained host plugin, installed at `$OPENCLAW_STATE_DIR/extensions/skillhub` (default `~/.openclaw/extensions/skillhub`), outside the OpenClaw package tree. `openclaw.json` owns registry fields; `docs/operations/skills-store-policy.md` owns the six rules. The plugin renders that document once at registration and contributes stable system context on every assembled prompt. It never writes policy into user input/history. A per-session "already injected" flag is unsafe: native providers rebuild their system prompt, so subsequent turns, restarts or compaction would lose the constraints. API requests still carry the stable policy; no zero-token claim is made.

After a merge/`refresh_live.sh`, run:

```bash
bash ops/host/install_skillhub_plugin.sh
bash ops/host/install_skillhub_plugin.sh --check
```

In host `openclaw.json`, add the installed extension directory to `plugins.load.paths` while preserving every existing entry (and keep `plugins.entries.skillhub.enabled=true`). On this host that directory is `/root/.openclaw/extensions/skillhub`. The explicit load path pins the intended source and avoids untracked-discovery provenance. Also set `plugins.entries.skillhub.hooks.allowPromptInjection=true`: the installed gateway startup planner requires explicit hook intent for this legacy hook-only manifest. `enabled=true` and a load path alone do not include it in the narrowed runtime startup registry. Both are official configuration fields and survive package upgrades. A restart is required after changing the load path. Verify the actual policy block; a healthy gateway can start while this plugin is absent.

The installer does not restart or edit config. Before activation, check `runningAtMs != null` via `openclaw cron list --json`, recompute the timeline with `check_crons.sh --timeline`, inspect `dispatch.sh status` and active gateway runs, and wait until other work is safe. Record the gateway PID/start time, then `systemctl --user restart openclaw-gateway.service`. Verify a changed PID, `/health`, `NRestarts=0`, unchanged version and enabled cron identities, and a new multi-turn session: zero policy blocks in user prompts, exactly one in system context, real primary search execution/output, no progress `message` calls. Do not send test messages to live chat recipients.

Upgrades do not replace this extension, and `reapply_openclaw_patches.sh` replays/verifies it before restart. A future SDK incompatibility is a hard failure to investigate, not permission to drop a rule. `SKILLHUB_PLUGIN_DIR` provides an isolated install target for tests. Rollback: `bash ops/host/install_skillhub_plugin.sh --rollback`; restore the policy document matching that generation if its template changed, then use the same safe restart gate. `.before-update` copies remain on the host and are not published.
