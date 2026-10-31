# What to take from `dsh-superagent-prototype`

Research note, 2026-11-01. The subject is the public DeepSeek Harness research prototype
`deepseek-ai/dsh-superagent-prototype` (TypeScript, MIT, one commit `6337fc8`). This note
records what its documents and code actually say, what we adopted, what we deliberately did
not copy, and where each adopted idea lives in this repository. It is not a summary of the
prototype's feature list; it is a map from its concepts to our dispatch and cron systems.

## How I read it

In the order the documents require: `docs/000-philosophy.md`, `001-domain.md`,
`002-authorization.md`, `003-execution.md`, `004-prompts.md`, `005-panel.md`,
`006-deployment.md`, `007-architecture.md`, `008-cookbook.md`. The code read for the two
adopted ideas:

| File | What it settles |
|---|---|
| `src/core/model.ts` | `Mandate`, `MandateBasis`, `ReportState`, `waitsForPerson`, `latestReport` |
| `src/core/stage.ts` | the stage table as one ordered function: `person/delivery`, `person/answer`, `person/review`, `person/blocked`, `person/failed`, `working/queued`, `idle`, `working` |
| `src/policy.ts` | Policy version, gate, revalidation, accept mode |
| `src/core/reasons.ts`, `src/executor/dsh.ts` | why an accept exists and how an Executor receives its mandate |
| `tests/stage.spec.ts`, `tests/policy.spec.ts` | the row-by-row stage and mandate tests |

The two load-bearing sentences are in `003-execution.md`: *“A `person` stage means the Ticket
cannot continue without human input”*, and in `000-philosophy.md`: *“It speaks only when a
person must act or can use a result.”* Everything adopted below is a way to make those
sentences machine-checkable on our host.

## Adopted

### 1. Mandate: state why the work may be done, and how far it may go

The prototype's Mandate is immutable and records the Policy version, scope, strength, basis,
actor and matched rules; a wider request needs a new Ticket. Our dispatched task had only a
natural-language brief, which is why a brief saying “do not restart the gateway” did not stop
the worker from doing it. The machine-readable replacement is:

| Piece | Where |
|---|---|
| The record | `<task dir>/mandate.json`, written once by `dispatch.sh` before the unit starts; schema and guard in `ops/host/agent-dispatch/mandate.py` |
| Fields | `schema`, `task_id`, `name`, `agent`, `created`, `policy_version`, `strength`, `source {kind,id}`, `scope {cwd,root,repos}`, `actions`, `notify`, `contract` |
| Policy version | `dispatch-<sha256(dispatch.sh + run-agent.sh)[:12]>`, recorded as `MANDATE_POLICY_VERSION` in `result.env` |
| Default actions | `gateway.restart: allow`, `live.refresh: allow` (kcn 2026-11-01) |
| Denial | `dispatch.sh --no-restart` writes `gateway.restart: deny`; `--allow-restart` is the explicit default |
| Guarded entry points | `ops/host/refresh_live.sh` checks `live.refresh` and `gateway.restart` before any write; `ops/host/restart_gateway.sh` checks `gateway.restart`, records a restart and then runs `openclaw gateway restart` |
| Audit | a denial appends to `<task dir>/mandate-violations.jsonl` and the caller exits `3`; a restart appends to `<task dir>/restarts.log` |
| Read/check | `dispatch.sh mandate <id> [check <action>]` |

The runner exports `AGENT_DISPATCH_MANDATE` so a shell the task starts checks the same file.
A task from before mandates (no `mandate.json`) and an interactive shell are reported as
legacy/no mandate and proceed; this is what lets the change go live without rewriting history.

This is a guard for the host scripts we own, not a sandbox. The prototype says the same about
its own wrappers (`003-execution.md` § Execution variables): a worker can execute a program by
absolute path. A task that calls `openclaw gateway restart` directly, or `systemctl restart`,
still bypasses the wrapper. The contract says to use the wrapper, and the denial record makes
the bypass visible after the fact, but it is not syscall-level enforcement.

### 2. Stage by what the task waits for, and notify only when a person is needed

The prototype's stage table is ordered; the first matching row wins. Our runner already knows
the facts (`STATE`, `OUTCOME`, `WAITING`, the model's final report), but it had no structured
“does a person have to act?” field and always called `notify()` and `wake_origin()`. Now:

| Field | Values | Owner |
|---|---|---|
| `NEEDS` | `none` or one concrete action, from the last line starting `NEEDS:` in the report | the agent, read by `classify_finish` in `run-agent.sh` |
| `NEED_SUMMARY` | the same text, capped at 300 characters | runner |
| `STAGE` | `working/queued`, `working`, `person/review`, `person/blocked`, `idle`, `ended` | runner (`write_result`, `classify_finish`) |
| `ATTENTION` | `person`, `none`, `unknown` | runner |
| `NOTICE` | `attempted`, `none`, `suppressed` | `finish()` |
| `RESTART` | the last `RESTART:` line (what/when/result) | the agent, published by the runner |

The rules, in order:

- `cancelled` → `ATTENTION=unknown`; the end notice stays (a stop is still news to the
  dispatcher), but no wake turn, as before.
- `ok` + `NEEDS: none` → `ATTENTION=none`, `STAGE=idle`, `NOTICE=suppressed`; no WeChat or
  Telegram send and no wake turn. `result.env`, the task chip and `/dispatch-list` still show
  the outcome.
- `ok` + a concrete `NEEDS` → `ATTENTION=person`, `STAGE=person/review`; send and wake.
- `ok` + no `NEEDS` line → `ATTENTION=unknown`; keep the old notice. Silence has to be
  reported, never inferred from prose.
- `partial` / `unverified` → `ATTENTION=person` even if the report says `NEEDS: none`;
  the work is not done.
- `blocked` / `failed` / `timeout` / `quota` → `ATTENTION=person`, `STAGE=person/blocked`.

`task_queue_ops.py summary` now counts `needs_person` per agent (and the JSON the chip reads
carries it), so “how many ended tasks actually want me?” is a number rather than a reading of
eight notices. `dispatch.sh status` prints `stage=`, `needs=` and `attention=` next to
`notify_sent=`.

The default contract in `dispatch.sh` now asks for the two final lines:

```
NEEDS: none | <one concrete person action>
STATUS: DONE|PARTIAL|BLOCKED
```

The same change is loaded by the agent skill and the host guidance; see the mapping table.

## Deliberately not copied

| Prototype concept | Why not | What we keep instead |
|---|---|---|
| Web panel (`005-panel.md`) | kcn's distribution surface is WeChat and `/dispatch-list`; a second panel is an attention cost with no new reader | the dsh task chip and `/dispatch-list`; the `needs_person` count is available to them |
| `Source` / `Thread` / `Trigger` / `Correlation` / `Channel` as a general router (`001`, `002`, `008`) | we have one dispatcher and one scheduler, not many event sources; a Source abstraction would add a layer with no second implementation | `dispatch.sh` creates the task, `run-agent.sh` runs it, `wake-session.py` reports back, `task_queue_ops.py` owns queue writes |
| Eval as gate + model assessment, accept modes `off`/`observe`/`auto` (`002`) | our dispatch is an explicit accept by a person or a named automated caller; there is no candidate stream to assess | explicit dispatch; patrol still files issues directly. **Gap:** an `observe` mode for patrol (record what it would file, file nothing) is the one part of this idea worth a follow-up; it would have changed the #3221 “口径差异” round from an issue to a record |
| Per-Ticket Executor Session, directory, prepare command, worker slots (`003`) | we already have one systemd unit per task, one cwd, agent locks and run slots; adding a second executor model would duplicate the queue | `run-agent.sh` unit + `task_queue_ops.py` queue + `limits.env` slots |
| Policy prompt store with per-part versions and a “Default updated” diff (`004`, `005`) | the panel and the override store are the expensive half; our contract is code and host guidance, loaded at dispatch | `dispatch.sh` contract text, `~/.agents/skills/agent-dispatch/SKILL.md`, `~/.agents/AGENTS.md`; `MANDATE_POLICY_VERSION` records which text a task ran under |
| Subscription = context only, never authority (`001`, `002`) | our `append` inbox is already a text channel, not an authorization path; the authority is the task's mandate | the mandate remains authoritative; an append changes instructions, not `actions` |
| Auto-merge policy in the Executor prompt (`003`) | our merge rule belongs to the repository (`AGENTS.md § Code changes`) and required CI, not to a per-task prompt | unchanged |
| Deployment scripts, tmux profile, state DB (`006`) | our installers (`install_agent_dispatch.sh`, `refresh_live.sh`) and runtime layout already exist and are tested | unchanged |

The prototype has **no quota or model-routing layer** of its own; it uses the Harness profile's
model. Our `limits.env`, `quota.mjs`, `opencode-fallback-models` and the free-pool audit are
load-bearing and were not simplified to match its model.

## Where the changes live

| File / section | Change |
|---|---|
| `ops/host/agent-dispatch/mandate.py` | new: create/show/check/violations; immutable `mandate.json`; exit `3` on deny and append the audit line |
| `ops/host/agent-dispatch/dispatch.sh` § Options, § contract heredoc, § `mandate` subcommand | `--no-restart`/`--allow-restart`; create the mandate before the unit; require `NEEDS` + `RESTART` + `STATUS`; `show_state` prints stage/needs/attention |
| `ops/host/agent-dispatch/run-agent.sh` § RUNNER_API, § `write_result`, § `classify_finish`, § `finish` | api 5; parse `NEEDS`/`RESTART`; publish the fields; suppress the end notice and wake when `ATTENTION=none` |
| `ops/host/refresh_live.sh` § mandate guard | checks `live.refresh` and `gateway.restart` before any write; records a failed check |
| `ops/host/restart_gateway.sh` | new guarded wrapper: `--check` decides only, otherwise records and restarts |
| `ops/host/install_agent_dispatch.sh` § FILES | installs `mandate.py` and `tests/test_mandate.py` |
| `ops/host/task_queue_ops.py` § `cmd_summary` | `needs_person` per agent, from `ATTENTION` or the legacy terminal states |
| `ops/host/agent-dispatch/tests/test_mandate.py` | create/immutable/deny/allow/unknown action/legacy, plus the real `restart_gateway.sh --check` and `refresh_live.sh` refusal |
| `ops/host/agent-dispatch/tests/run-tests.sh` § `[35b]`, `[40a]` | quiet `DONE` sends nothing, a real `NEEDS` still sends, `PARTIAL` is not quiet; a dispatch through a fake `systemd-run` writes the mandate and appends the contract |
| `docs/architecture/task-queue.md` § Mandate, § Runner fields, § Notifications, § wake table | the operational contract |
| `~/.agents/skills/agent-dispatch/SKILL.md` § Send the request / Continue or inspect | `--no-restart`, the mandate file, `NEEDS`/`RESTART` report rule |
| `~/.agents/AGENTS.md` § Delegation | one paragraph: restart is authorized by default, `--no-restart` is the exception, reports carry `NEEDS` |

The host guidance and skill are outside the repository (they are the user-level files every
coding agent loads), so they are changed on the host and are not part of the PR diff. The
repository owns the executable contract (`dispatch.sh`), which is what a resumed session gets
even when it never reads the skill.

## Evidence

Before (the old runner, observed in this task's own log): `finish()` called
`notify "$notice"` and `wake_origin end "$notice"` unconditionally; `result.env` had no
`NEEDS`/`STAGE`/`ATTENTION`; `dispatch.sh` created no mandate; `refresh_live.sh` had no guard.
The 2026-11-01 incident is the other half: a brief said “不要重启网关” and the worker ran
`refresh_live.sh` and restarted the gateway anyway.

After, on the worktree (`codex/superagent-adoption`):

```
DISPATCH_TEST_CASES=notify AGENT_DISPATCH_RUNNER=... bash ops/host/agent-dispatch/tests/run-tests.sh
  [35b] NEEDS/ATTENTION/NOTICE recorded  none/none/suppressed
        no completion message was sent   0
        the log says why it was quiet    notify: suppressed
        the action is published          <the action>/person/attempted
        PARTIAL is not a quiet end       partial/person/attempted
  PASS

python3 -m unittest ops/host/agent-dispatch/tests/test_mandate.py
  create is immutable; --deny-restart keeps live.refresh, denies gateway.restart
  denial appended to mandate-violations.jsonl
  restart_gateway.sh --check exits 3 with "refused" and records it
  refresh_live.sh exits 3 before writing on the same mandate
  Ran 6 tests ... OK

[40a] a dispatch through a fake systemd-run wrote mandate.json (actions allow/allow,
      policy_version dispatch-…), and prompt.md contains 默认授权, NEEDS: none and the
      notification-gate sentence.
```

The denial evidence is the pair `<task>/mandate-violations.jsonl` plus exit `3`; the quiet
evidence is `NOTICE=suppressed`, no `openclaw.sends` line, and no `notify:` send in `run.log`.

## Remaining risks / not done

- **Bypass:** a task that runs `openclaw gateway restart` or `systemctl` directly is not
  stopped. The wrapper and the contract are the enforceable path; full enforcement would need
  a sandbox or a PATH shim, which this host deliberately does not have.
- **Model compliance:** `NEEDS` is a line the model must write. A missing line keeps the old
  notice (never silence), but a model that writes `NEEDS: none` when it should have asked for
  a decision can still under-notify. The contract says not to invent an action and not to
  hide one; only the report can be audited.
- **`--no-restart` is conservative:** `refresh_live.sh` checks both actions before any write,
  so a task with `--no-restart` cannot even fast-forward without a restart. That is deliberate
  (no half-applied live state), but it means the flag is “do not touch the live desk”, not
  only “do not restart at the end”.
- **The task chip does not render `ATTENTION` yet.** `result.env` and `task_queue_ops.py summary`
  carry it (`needs_person` per agent), and `dispatch.sh status` prints it, but the dsh chip still
  shows the old `done`/`partial` word. Adding a badge would need a plugin build and a dsh
  restart; the notification gate is independent of it.
- **Patrol `observe` mode** is not implemented. The #3221 evidence (a measurement-basis
  difference filed as an issue and closed `not planned`) is the case for it; it belongs to
  patrol's `file_issue.sh` gate, not to this change.
- **Mandate revalidation on append** is not implemented. An `append` continues the same task
  and the same mandate; if the appended request is outside the original scope, the mandate
  still says the old scope. The prototype revalidates before resuming; we do not yet have a
  scope language to revalidate.
