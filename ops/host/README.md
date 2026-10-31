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

`restart_gateway.sh` is the guarded restart path for a dispatched task: it checks
`gateway.restart` in the task's `mandate.json`, records the restart under the task directory,
and then runs `openclaw gateway restart`. `refresh_live.sh` checks the same mandate before it
writes; a task dispatched with `--no-restart` is refused and the denial is appended to
`mandate-violations.jsonl`. Details: `docs/architecture/task-queue.md` § Mandate.

Wake events stay spooled until the turn succeeds. Failure recovery, explicit retry commands,
the four silence guards and the turn budget are described in
[the wake contract](../../docs/architecture/task-queue.md#a-turn-in-the-session-that-dispatched).
The focused acknowledgment tests run with
`python3 -m unittest discover -s ops/host/agent-dispatch/tests -p test_wake_session.py -v`.

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

When every model in a fresh patrol's pool returns only errors or no events, the runner stops
after one lap with `STATE=failed`, `FAILURE_REASON=pool_no_response`. It still
allows 210 seconds for a first event, except that a model call refused with
`Rate limit exceeded` (opencode's log, written to `attempt<N>.err` by
`--print-logs`) ends the attempt at once as `kind=rate_limited` and moves to the
next model without `FALLBACK_WAIT`; a session that has made progress retains
the normal retry budget. A session ID on a provider error alone is not progress;
any non-error event (including `step_start`) preserves the normal budget, as
does resuming an existing session. An empty OpenCode exit is an error, never a finished
review. `MODEL_USED` names the last attempted model, not the next fallback.

The supervisor records the failed round, preserves its area without spending an
area retry, and waits one hour. `pool-cooldown-until` persists this wait across
restarts; `status` reports the remaining seconds. Expiry admits a normal round
with the same pool and gates, which also tests recovery. This is an elapsed-time
cooldown, not a claim about provider quota reset times. Other failures keep the
existing retry/backoff policy. No availability probe advances the review cursor.

`PATROL_DISPATCH_DIR` can point tests at fixture policy/helpers; production uses
`/root/tools/agent-dispatch`. Run the focused supervisor coverage with
`env -u CLAWOCK_WORKSPACE PYTHONPATH="$PWD/src" python3 -m pytest -q tests/test_patrol_audit.py tests/test_patrol_supervisor.py`.

## Coding agents' shared memory

`shared-memory/` is the versioned source of the skill every coding agent on the host loads
(`~/.agents/skills/shared-memory`, linked from each agent's own skill directory): `memory.py`
(format owner), `memctl` (history, audit, wiring self-check), the Claude Code hook and
`wiring.json`. It carries the mechanism only; the memory itself, its history and ledger stay
outside the repository. `install_shared_memory.sh` installs it (atomic per file,
`.before-update`, `--check`, `--rollback`; `--units` renders the two systemd timers) and
`refresh_live.sh` runs it when the installed copy differs. How it works, which working
directories share the store and which keep their own (an OpenClaw workspace), and what
`memctl doctor --deep` proves: `shared-memory/README.md`. Tests: `tests/test_shared_memory.py`.

### OpenClaw read-only corpus plugin

`shared-memory/openclaw/` is a host OpenClaw plugin (`shared-memory-corpus`) that registers a
memory corpus supplement, so the assistant's `memory_search corpus=all` / `memory_get` can read
the coding agents' store without it ever entering the workspace: read-only, direct chats only
(groups, channels, cron and keyless runs get nothing), redacted, and silent on read errors.
OpenClaw's short-term recall records only its own index hits, so dreaming cannot promote these
notes into the public `MEMORY.md`. Install with `install_memory_corpus_plugin.sh` (`--check`,
`--rollback`) into `$OPENCLAW_STATE_DIR/extensions/shared-memory-corpus`, add that directory to
`plugins.load.paths`, set `plugins.entries.shared-memory-corpus.enabled=true` (optional
`config.root`, default `~/.shared-memory`), and restart the gateway once through the same gate as
any restart (no cron run in flight). `reapply_openclaw_patches.sh` reinstalls and checks it after
an upgrade. Tests: `tests/test_shared_memory_corpus.py`.

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

## Automatic free-model selection

The immutable `agent-dispatch/opencode-fallback-models` is the reviewed **seed order**.
Its installation still requires the pool's backup/check/rename/chattr procedure and
identical repository bytes. The runtime selection is derived data, not a second copy
that `refresh_live.sh` tries to restore. `free-pool-policy.json` authorizes automatic
selection; changing that policy or the hard retirement list requires a reviewed PR.

`audit-free-pool.py --due --repo-pool <repository-pool>` refreshes OpenCode's catalog
cache and fetches Zen membership and models.dev prices. Catalog input/output must
explicitly be zero; every supplied price component is checked. Any positive catalog
or models.dev price vetoes eligibility, including partial price records. Missing
models.dev metadata is recorded as unknown and is allowed with catalog zero. Zen
supplies membership, not pricing: its missing `cost` field is not an alert. These are
kcn's 2026-10-16 rules. The five hard-retired IDs stay rejected. `big-pickle` is the
only allowed non-suffixed name, explicitly requested that day; it still needs fresh
zero-price evidence and Zen membership.

Discovery runs on this host before the patrol supervisor's cooldown check and before
OpenCode dispatch. Network work is cached for one hour, retried after 15 minutes on
source/integrity failure, and bounded by a 50-second outer timeout. The helper uses a
lock and atomic reports. Unreadable sources fail closed: previous reports are retained
for diagnosis, never substituted for a fresh failure. Missing/malformed/older-than-two-
hour evidence blocks new inference. A running attempt cannot be recalled by a later
price change; a provider can change prices between checks, so this is bounded polling,
not a billing guarantee.

`select-free-models.py` takes the eligible seed priorities plus automatically discovered
eligible models. It selects at most nine per task. When new names outnumber capacity,
one rotating newcomer gets position two; the remaining slots follow seed priorities.
No name needs manual per-model approval after satisfying this policy. Models removed
from Zen/catalog or reporting positive prices disappear from effective selection on
the next audit. Fresh, valid evidence automatically restores transient exclusions;
hard retirements never restore. `mode: seed-only` disables discovery while retaining
all price/retirement gates; `mode: paused` blocks selection entirely. Both changes go
through PR/installer; no recovery path automatically returns to an unchecked pool.

Dispatch saves `free-pool-selection.json` beside each task's `meta.env`, with the audit
time, order, seed hash and a reason for every model. Explicit `--model`/fallback lists
pass the same gates. Before **each attempt**, the runner filters its task pool against
the current report (including manual overrides). If nothing remains, it records
`free_pool_unavailable` without calling inference. This does not switch models on
output quality. Existing error/stall fallback, quota handling and whole-pool cooldown
still apply. In-flight tasks created before this deployment retain their old metadata.

The report lives at `/root/logs/clawock-patrol/free-pool-audit.json`; the last selection
is `free-pool-selection.json` next to it. Both the supervisor journal and `patrol.sh
status` expose the audit, and `ops/system_check.py` reads cached evidence only. A pool
member removed/charged, source failure, seed drift or stale audit warns; market-data
publication is not blocked by this unrelated health warning. No audit chat messages
or GitHub issues are sent automatically. No cron identity is added: the existing
supervisor owns scheduling, and active rounds/manual-work waits can delay its checks.
Dispatch itself also refreshes due evidence so a delayed loop cannot bypass the gate.

`probe-free-candidates.py` runs only with no current round/demand and a nonblocking
OpenCode run slot. It skips 01:00–08:00 HKT, tests at most one due model every six hours,
and uses a 45-second `--tool` probe. Structured completed bash events and exact output
are required; text containing the marker is not proof. Timeouts/rate limits remain
unknown availability, never permanent retirement. Failed probes back off for one,
two, four, then seven days, leaving other names their turn; successful probes are due
again after seven days. Results and raw evidence live under `free-model-probes*` beside
the audit. Probes are diagnostic, not admission prerequisites or quality rankings.

Rollback: deploy reviewed `seed-only` (or `paused`) policy while investigating, restore
code through a revert PR and refresh_live, then reinstall/restart the supervisor using
its adoption procedure. Never restore an older report to revive a charged model. Seed
rollback still uses the immutable-file procedure; restore the matching repo copy too.
No autonomous process edits the seed, lifts chattr, opens PRs or merges code.

## Dreaming promotion review

The promotion writer uses a private candidate file; the commit job screens candidates
and requires explicit review receipts before adding permanent conclusions. Installation,
review, verification and rollback: [dreaming review](../../docs/operations/dreaming-review.md).
