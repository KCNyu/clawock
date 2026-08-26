# AGENTS.md - Your Workspace

This folder is home.

## Every Session

Before doing anything else:

1. Read `SOUL.md` — who you are
2. Read `USER.md` — who you're helping
3. **If in MAIN SESSION** (direct chat with kcn): Also read `MEMORY.md` + `TOOLS.md`
4. **If the question is investment-related**: also read `INVESTMENT_SOP.md` and route per the skill table below

Don't ask permission. Just do it.

## kcn 偏好

详见 `USER.md` § 沟通偏好 + § 不要做的事。要点：表格、不 hedging、数据缺口必说、terse 风格、14:00 HKT 也盘中查。

## Git hook (one-time setup per clone)

```bash
git config core.hooksPath .githooks
```

`.githooks/pre-commit` enforces on every commit (openclaw cron / GH Action / manual):
- portfolio.json valid JSON + required structure
- memory/*-plan.json schema (bucket enum, trigger_type enum, confidence ∈ [0,1])
- the dashboard write set rebuilds when portfolio.json is staged, but is no longer
  staged with it: since #319 those four payloads live on the `data-plane` branch and
  `git add` on a now-ignored path fails the commit rather than skipping
- paranoid scan for leaked API keys (`sk-…`, `tp-…`, `FINNHUB_API_KEY=`, etc.)

Override with `--no-verify` if false positive (rare).

## Git Auto-Commit Rules

The workspace is a local git repo. **`origin` is the public repo `github.com/KCNyu/clawock`** — the
contents (positions, plans, memory logs) are intentionally public per kcn's instruction.
This table governs the live runtime workspace and its scheduled writers. Interactive
Codex/Claude code changes follow the PR workflow in the next section.
After any of the following changes, run a git commit automatically — no need to ask:

| Change | Commit |
|---|---|
| `portfolio.json` updated (price refresh / buy / sell) | `portfolio: <brief>` |
| Harness produced new `memory/{date}-pre-open.md` + `-plan.json` | `memory: daily deep brief <date>` (postflight auto-commits) |
| KCNyu harness/publisher refreshed dashboard outputs | publish the complete semantic generation through the data plane; do not stage individual generated files ad hoc |
| `assets/data/risk.json` refreshed via `clawock portfolio-risk` | bundled with brief commit |
| `memory/decisions.jsonl` execution status marked via `clawock mark-followed` | `decisions: mark execution` |
| Package, profile or `ops/` code changed | `refactor:`/`fix:`/`feat: <what changed>` (via PR, never direct) |
| Workspace docs changed (SOUL/AGENTS/TOOLS/USER/CLAUDE/README) | `docs: <what changed>` |

Message style: `<type>: <concise description>`, Chinese is fine. Commit message
bodies use real newlines (multi-line `-m` / heredoc), never a literal `\n`
(#615: two past commits shipped the two characters `\n` and rendered as one
blob).
**Never commit:** `.api_keys`, scratch `*.png`/`*.jpg` outside the shipped `site/assets/`/`docs/` allowlists, `.openclaw/`, `.clawhub/`, `memory/.dreams/`, `memory/.tmp/` (gitignored). Shipped `site/assets/*.png` are committed; `screenshot-refresh.yml` generates `site/assets/social-card.png` directly from the light editorial HTML/CSS composition plus a fresh dashboard capture, refreshes `site/assets/shadow-backtest.png`, and updates `site/assets/dashboard.gif` only on manual dispatch.

Push: harness postflight now **auto-pushes** after commit (rebase+retry on race).
Interactive Codex/Claude work must never push `master`; it may push only its task
branch to create or update a PR.

## Interactive Codex/Claude PR workflow

The live checkout `/root/.openclaw/workspace` must stay on `master` because cron and
OpenClaw write runtime data there throughout the day. Never switch that checkout to a
feature branch and never make interactive code edits in it.

For changes to code, scripts, workflows, skills, UI, configuration, or repository
documentation:

1. Create an isolated worktree from current `origin/master`, using a branch named
   `codex/<task>` or `claude/<task>`.
2. Make and commit the change in that worktree, then push the task branch and open a PR.
3. Let GitHub Actions run the full test suite. Local full-suite runs are optional; the
   required remote checks are the merge gate.
4. The authoring agent must not merge its own PR. Claude reviews/merges Codex PRs;
   Codex reviews/merges Claude PRs.
5. **Never post the review as a PR comment.** Both agents authenticate as the GitHub
   user `KCNyu`, so a posted review reads as kcn talking to themself — findings go in
   the interactive handoff instead. Do not add a signature, an `AI-REVIEW` prefix, or
   any other marker to work around this; it is an identity problem, not a labelling one.
6. If the reviewing agent is unavailable because its quota is exhausted, the author may
   audit its own diff, checks and merge state and squash-merge. That is permission to
   finish the workflow alone — never to skip a required check.
7. Do not merge while any required check is pending or failing. Fix the branch, push,
   and let the PR rerun its checks.
8. Squash-merge only after required checks pass, then remove the task worktree/branch.
9. Apply the merge to this host with `ops/host/refresh_live.sh` — **merging is what
   makes a fix live here; a release is for people who are not this host.** 本机不用为
   每个修复发版。The install is editable, so a fast-forward is usually the whole job;
   the script re-runs the launcher installer only when `pyproject.toml` moved and the
   DSH plugin installer only when `examples/dsh/packages/clawock-dsh/` moved, then
   verifies what is actually serving. Rule and evidence:
   `docs/operations/release.md` § Running the latest code on this host.

Runtime-generated market data, snapshots, reports, ledgers, and dashboard artifacts
remain on the existing direct-to-`master` bot path. They do not open high-frequency PRs.
Never use the repository-admin bypass for an interactive code change.

## Memory

You wake up fresh each session. `MEMORY.md` is your continuity:
- **Long-term:** `MEMORY.md` — curated wisdom; **only load in main session**, do NOT load in shared contexts (Discord, group chats)
- Don't keep "mental notes" — if it matters, write it to `MEMORY.md` (or, for the
  interactive coding agents, their own durable memory outside this repository).
- Dated diaries (`memory/YYYY-MM-DD.md`) were retired in #1038: untracked first,
  then removed from disk. They were raw session logs nothing read back — the
  curated surfaces (`MEMORY.md`, the interactive agents' own memory) carry what
  actually gets reused. Do not start writing them again.

## Safety

- Don't exfiltrate private data
- Don't run destructive commands without asking
- `trash` > `rm`
- External actions (emails, public posts) → ask first
- Internal actions (read, organize, edit workspace) → freely

## Tools & Skills

Skills live under `skills/<name>/SKILL.md`. **Full routing + edge-cases → `TOOLS.md` § Skill 路由表.**

Runtime commands come from the installed distributions: portable workflows and
tools, harness, watchdogs and automation all use the installed `clawock` distribution
entry points. Host, publishing, CI and growth wiring lives under `ops/`. Never
recover an old command by executing a root script or a file under `scripts/data/`.

Default to action: pick the skill, run the script, return the answer — don't ask permission unless going destructive.

## Heartbeats

If you receive a heartbeat poll, openclaw auto-injects:
> Read HEARTBEAT.md if it exists. Follow it strictly. If nothing needs attention, reply `HEARTBEAT_OK`.

So just follow `HEARTBEAT.md`. Don't repeat old tasks. Reply `HEARTBEAT_OK` when idle.

In group chats: be smart about when to contribute. Reply only when adding genuine value. Otherwise stay silent. Don't be the bot that responds to everything.

## Make It Yours

Add your own conventions as you learn what works. Keep this file short.
