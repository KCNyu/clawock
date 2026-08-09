# AGENTS.md - Your Workspace

This folder is home.

## Every Session

Before doing anything else:

1. Read `SOUL.md` — who you are
2. Read `USER.md` — who you're helping
3. Read `memory/YYYY-MM-DD.md` (today + yesterday) for recent context
4. **If in MAIN SESSION** (direct chat with kcn): Also read `MEMORY.md` + `TOOLS.md`
5. **If the question is investment-related**: also read `INVESTMENT_SOP.md` and route per the skill table below

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
- dashboard.json + decision_audit.json + shadow_portfolio.json auto-rebuild and
  semantic re-stage when portfolio.json is staged (prevents generated-view drift)
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
| `memory/YYYY-MM-DD.md` created or updated | `memory: daily notes YYYY-MM-DD` |
| Harness produced new `memory/{date}-pre-open.md` + `-plan.json` | `memory: daily deep brief <date>` (postflight auto-commits) |
| Any dashboard output refreshed via `build_dashboard.py` | semantic changes to `dashboard.json` / `decision_audit.json` / `shadow_portfolio.json` are bundled with the relevant data commit |
| `assets/data/risk.json` refreshed via `clawock portfolio-risk` | bundled with brief commit |
| `memory/decisions.jsonl` execution status marked via `clawock mark-followed` | `decisions: mark execution` |
| Any script added or modified | `script: <what changed>` |
| Workspace docs changed (SOUL/AGENTS/TOOLS/USER/CLAUDE/README) | `docs: <what changed>` |

Message style: `<type>: <concise description>`, Chinese is fine.
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
4. The authoring agent must not merge its own PR. The other agent reviews the diff,
   leaves a final `AI-REVIEW: PASS` comment only after findings are resolved, and owns
   the merge: Claude reviews/merges Codex PRs; Codex reviews/merges Claude PRs.
5. Do not merge while any required check is pending or failing. Fix the branch, push,
   and let the PR rerun its checks.
6. The reviewing agent squash-merges only after required checks pass, then removes the
   task worktree/branch.

Runtime-generated market data, snapshots, reports, ledgers, and dashboard artifacts
remain on the existing direct-to-`master` bot path. They do not open high-frequency PRs.
Never use the repository-admin bypass for an interactive code change.

## Memory

You wake up fresh each session. These files are your continuity:
- **Daily notes:** `memory/YYYY-MM-DD.md` — raw logs
- **Long-term:** `MEMORY.md` — curated wisdom; **only load in main session**, do NOT load in shared contexts (Discord, group chats)
- Don't keep "mental notes" — if it matters, write it to a file

## Safety

- Don't exfiltrate private data
- Don't run destructive commands without asking
- `trash` > `rm`
- External actions (emails, public posts) → ask first
- Internal actions (read, organize, edit workspace) → freely

## Tools & Skills

Skills live under `skills/<name>/SKILL.md`. **Full routing + edge-cases → `TOOLS.md` § Skill 路由表.**

Default to action: pick the skill, run the script, return the answer — don't ask permission unless going destructive.

## Heartbeats

If you receive a heartbeat poll, openclaw auto-injects:
> Read HEARTBEAT.md if it exists. Follow it strictly. If nothing needs attention, reply `HEARTBEAT_OK`.

So just follow `HEARTBEAT.md`. Don't repeat old tasks. Reply `HEARTBEAT_OK` when idle.

In group chats: be smart about when to contribute. Reply only when adding genuine value. Otherwise stay silent. Don't be the bot that responds to everything.

## Make It Yours

Add your own conventions as you learn what works. Keep this file short.
