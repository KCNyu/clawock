# AGENTS.md

Instructions for every agent in this repository: the OpenClaw investment assistant
(Rick, see `IDENTITY.md`) and the coding agents (Claude Code, Codex, OpenCode).
`CLAUDE.md` only bridges here. Humans read `README.md` and `docs/README.md`.

## Session start

OpenClaw injects the bootstrap files for the session profile. Use what is already in
context; do not read an injected file again.

- Direct chat: `SOUL.md`, `IDENTITY.md`, `USER.md`, `TOOLS.md`, `HEARTBEAT.md` and
  `MEMORY.md` are injected. Keep `MEMORY.md` out of group and shared contexts.
- Isolated cron and subagent runs: follow the job payload and its skill. `MEMORY.md` is
  not injected there, so a rule a scheduled run must obey belongs in the payload, the
  skill mode or a postflight gate.
- Investment question: follow `INVESTMENT_SOP.md` and the skill `TOOLS.md` routes to.
- Ordinary chat: answer with known context. Load holdings, cron or repository state only
  when the question needs it.
- Coding work: no persona, SOP or holdings reads. Start at § Code changes.

### Delegation

- A request naming Claude Code (Claude/claudecode), Codex or OpenCode as the actor
  ("让 claudecode 看看…", "have Codex fix…") is explicit delegation, even for a small task
  and without words such as "委派" or "后台跑". Use the `agent-dispatch` skill and return
  once the dispatch succeeded. The named worker is distinct from the main session even
  when both use the same model family.
- Forward the request with known context. Look up only missing routing facts; the worker
  inspects code, issues and CI.
- "你直接做 / 当前会话做 / 不要委派" ("do it here / no delegation") overrides this routing.
  A request to investigate or optimize together stays in the current conversation.
- A dispatched worker (`AGENT_DISPATCH_TASK_ID` set, or a 【派发约定】 block in its prompt)
  finishes its own task and does not dispatch it again.

## Commands

Runtime commands are the installed `clawock` entry points; source is `src/clawock/`.
Host, publishing, CI and growth wiring lives under `ops/`. Parameters:
`docs/reference/commands.md`. Skill routing: `TOOLS.md` § Skill 路由表.

```bash
# market data and book
clawock analyze-us [TICKER]        # live US quotes + signals; run before any P&L statement
clawock analyze-hk [TICKER]        # live HK quotes + signals
clawock fx --json                  # USD/HKD rate with source and timestamp
clawock reconcile                  # after editing holdings[].trades[] or shares
clawock mark-followed DECISION_ID [--no]

# scheduled jobs (the cron payload names which one)
clawock {brief|report|intraday} preflight [args]
clawock {brief|report|intraday} postflight [args]

# development, from a task worktree
git config core.hooksPath .githooks                    # once per clone
pip install -e '.[test]'                               # isolated environment only
env -u CLAWOCK_WORKSPACE PYTHONPATH="$PWD/src" python3 -m pytest tests/<file>.py -q
ruff check .                                           # CI pins the version in ci.yml (job `lint`)
python3 ops/ci/generate_tool_reference.py --check      # docs/reference/commands.md drift
python3 ops/host/generate_cron_docs.py --check         # docs/operations/cron-schedules.md drift
python3 ops/system_check.py                            # live workspace audit
ops/host/refresh_live.sh                               # apply a merged PR to this host
```

CI runs the full suite on every PR; run only the tests your change touches locally.

## Where things live

| Path | What it is |
|---|---|
| `src/clawock/` | the portable package: CLI, workflows, market data, harness, publishing |
| `config/`, `config/profiles/` | declarative desk configuration; `config/cron-schedules.json` is the cron contract |
| `skills/<name>/SKILL.md` | skill bodies; a cron job runs the mode its payload names |
| `ops/{host,publish,ci,pages,growth}/` | host, publishing, CI and Pages wiring; not in the wheel |
| `site/` | website source; `site/index.html` is the dashboard |
| `portfolio.json` | authoritative holdings, written by the price-refresh commands |
| `memory/{date}-pre-open.md`, `memory/{date}-plan.json` | the daily brief and its plan |
| `memory/snapshots/`, `memory/bars/`, `memory/decisions.jsonl` | daily snapshots, bars, the decision ledger |
| `memory/.tmp/` | preflight context; ignored |
| `assets/data/` | generated dashboard inputs and history |
| `docs/` | project documentation; index in `docs/README.md` |

## Boundaries

### Always

- Fetch live prices with `clawock analyze-us` / `clawock analyze-hk` before stating a
  price, P&L or position value. Say which source failed when one did.
- Report book totals in both USD and HKD with the FX rate, its source and timestamp.
- Commit runtime changes as § Runtime commits lists, without asking.
- Deliver code, skill, workflow, configuration and documentation changes through
  § Code changes.
- Read, organise and edit inside the workspace freely.

### Ask first

- Anything that leaves the machine in kcn's name: email, public posts, messages to
  anyone other than kcn.
- `git push` from a chat-triggered session. Harness postflights push on their own.
- Destructive commands: `rm -r`, `git reset --hard`, `git clean`, force-push.
- Editing `~/.openclaw/openclaw.json`. Back it up first:
  `cp -p ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak.$(date +%Y%m%d-%H%M)`.
- Installing a skill: `docs/operations/skills-store-policy.md`.

### Never

- Compute P&L from `portfolio.json` `current_price`. It is a cache.
- Add HKD and USD amounts without converting.
- Invent a quote, a level or a "new high" claim. Without a verified number, say the data
  is missing.
- Push `master` or use the repository-admin bypass for an interactive change.
- Switch `/root/.openclaw/workspace` off `master`, or edit code in it. Cron and OpenClaw
  write runtime data there all day.
- Post a review as a PR comment. Every agent authenticates as the GitHub user `KCNyu`, so
  it reads as kcn reviewing their own work. Do not work around it with a signature or an
  `AI-REVIEW` prefix. Findings go in the handoff.
- Merge while a required check is pending or failing.
- Commit `.api_keys`, credentials, `.openclaw/`, `.clawhub/`, `memory/.tmp/`,
  `memory/.dreams/`, or scratch `*.png`/`*.jpg` outside `site/assets/` and `docs/`.
- Commit coding-agent notes under `memory/*.md`. Their store is outside this repository;
  `.gitignore` and `.githooks/pre-commit` refuse that class.
- Never write dated diaries (`memory/YYYY-MM-DD.md`). `MEMORY.md` is the only prose memory.
- `git add` a dashboard payload on `master`. They are published on the `data-plane` branch
  and the path is ignored, so the commit fails.
- Edit the cron store (SQLite or the old `jobs.json`) by hand. Use `openclaw cron edit`
  or `ops/host/sync_us_cron_dst.py`, then regenerate `docs/operations/cron-schedules.md`.
- Run an old root script or anything under `scripts/data/`, or rebuild one from old notes.
- Link third-party repositories, issues, PRs, commits or users in public GitHub issues,
  PRs and comments. Name the project as plain text; keep source links in repository docs.

## Runtime commits

`origin` is the public repository `github.com/KCNyu/clawock`. Positions, plans, briefs
and `MEMORY.md` are public on purpose; chat or session metadata, credentials and
coding-agent memory are not. This table covers the live workspace and its scheduled
writers.

| Change | Commit |
|---|---|
| `portfolio.json` updated (price refresh / buy / sell) | `portfolio: <brief>` |
| New `memory/{date}-pre-open.md` + `-plan.json` | `memory: daily deep brief <date>` (postflight commits it) |
| Dashboard outputs refreshed | published as one generation through the data plane; never staged file by file |
| `assets/data/risk.json` refreshed by `clawock portfolio-risk` | bundled with the brief commit |
| `memory/decisions.jsonl` execution status set by `clawock mark-followed` | `decisions: mark execution` |
| `MEMORY.md` / `DREAMS.md` appended by dreaming | `ops/host/commit_dreaming.sh` commits them at 03:20 HKT |

Message style: `<type>: <concise description>`; Chinese is fine. Write the body with real
newlines (multi-line `-m` or a heredoc), never a literal `\n`.

`.githooks/pre-commit` checks every commit: `portfolio.json` structure, the
`memory/*-plan.json` schema, and a scan for API keys. Use `--no-verify` only for a
confirmed false positive.

Harness postflights push after committing, with rebase and retry. Runtime data stays on
this direct-to-`master` bot path and never opens PRs.

## Code changes

For code, scripts, workflows, skills, UI, configuration and repository documentation:

1. Create a worktree from current `origin/master` on a branch named `codex/<task>` or
   `claude/<task>`.
2. Commit there, push the branch, open a PR. Commit types: `fix:`, `feat:`, `refactor:`,
   `docs:`.
3. Review your own diff, checks and merge state. A cross-agent review happens only when
   kcn asks for one in that task.
4. Squash-merge once the required checks pass, then remove the worktree and branch.
5. Run `ops/host/refresh_live.sh`. Merging plus this script is what makes a fix live on
   this host; no release is needed. Details: `docs/operations/release.md` § Running the
   latest code on this host.

A document under `docs/` describes how the project works now. Measurements, before/after
captures, command output and proposed patches from one task go in its PR description.

### Closing issues

Handle every open issue on its evidence; there is no issue-count ceiling.

- Verified fix: close as completed, citing the merged PR or a reproducible check.
- Patrol finding that is false, a duplicate, out of scope or not worth fixing: record the
  verified reason and close as not planned, or apply `patrol:noise`. These closures feed
  patrol's quality signal.
- Never mark an unimplemented finding completed to clear the queue.
- Partly resolved digest: record each item's result and keep the unresolved items open.

## Memory

- `MEMORY.md` is the OpenClaw assistant's long-term memory and is tracked. If something
  must survive the session, write the conclusion there, self-contained.
- The dreaming job appends to `MEMORY.md` and `DREAMS.md` at 03:00 HKT. Leave the
  `openclaw:dreaming` and `openclaw-memory-promotion` markers intact.
- `memory/*-pre-open.md` and `memory/weekly/` are published briefs, and the plan JSON is
  runtime data. Do not add other prose under `memory/`.

## Heartbeats and group chats

- On a heartbeat poll, follow `HEARTBEAT.md`. Reply `HEARTBEAT_OK` when it lists no task.
- In a group chat, reply only when it adds something. Otherwise stay silent.
