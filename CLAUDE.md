# CLAUDE.md

Entry pointer for Claude Code in kcn's investment workspace. Same workflow as `AGENTS.md` (openclaw entry) — content lives in the canonical files below, this is just the road map.

## Identity & user

- Investment chat: you're `Rick` (see `IDENTITY.md`). Coding sessions in this
  repository keep the coding-agent identity; they read Rick's files only when the
  task is about that behaviour. (OpenClaw's own claude-cli backend starts Claude
  with `--setting-sources user`, so WeChat chat does not load this file.)
- User is `kcn` / Shengyu Li (see `USER.md`)

## Context on demand

Session start rules (which bootstrap files are injected, when to read `INVESTMENT_SOP.md`,
group contexts never load main-session memory, isolated jobs follow their profile,
delegation) live once in `AGENTS.md` § Every Session. Claude-specific:

- OpenClaw's session profile owns runtime bootstrap; Claude Code separately owns native
  project auto-memory and compaction. Do not add a second startup scan or memory pipeline
  over either mechanism.
- Coding work and ordinary delegation need no persona, SOP or holdings reads; skill and
  tool routing is in `TOOLS.md`.
- For an investment question, load `portfolio.json` only when it needs positions or prices.

## What lives where

| Topic | File |
|---|---|
| Disposition / persona | `SOUL.md`, `IDENTITY.md` |
| User profile / preferences | `USER.md` |
| Iron rules / traps | `MEMORY.md` |
| Scripts / fallback / skill routing / cron | `TOOLS.md` |
| Skill bodies | `skills/{name}/SKILL.md` |
| Portable workflows / market / portfolio tools | installed `clawock` CLI; source in `src/clawock/` |
| Harness CLI / live profile | `clawock brief\|report\|intraday`; package-owned lifecycle selected by `CLAWOCK_PROFILE` |
| Host / publish / CI / growth wiring | `ops/{host,publish,ci,growth}/` |
| Repository automation | installed `clawock-*` commands and named `ops/*` entry points |
| Daily deep brief output | `memory/{date}-pre-open.md` + `memory/{date}-plan.json` |
| Daily portfolio snapshots | `memory/snapshots/{date}.json` |
| Preflight context (gitignored) | `memory/.tmp/` |
| Startup sequence | `INVESTMENT_SOP.md` |
| Heartbeat workflow | `HEARTBEAT.md` (heartbeat poll only) |
| Auto-commit rules | `AGENTS.md` |
| Interactive code PR/worktree rules | `AGENTS.md` § Interactive Codex/Claude PR workflow |
| Getting a merged fix onto this host (no release needed) | `ops/host/refresh_live.sh`; rule in `docs/operations/release.md` § Running the latest code on this host |
| Pages dashboard input | data-plane generation refreshed by KCNyu postflight and `ops/publish/publish_dashboard.sh` |
| Risk metrics snapshot | `assets/data/risk.json` (built by `clawock portfolio-risk`, refreshed daily via brief preflight) |
| Decision execution marking | `memory/decisions.jsonl` `execution.status`; manual override via `clawock mark-followed DECISION_ID [--no]` |
| Pages source | `site/index.html` (dashboard) + `site/briefs.md` (daily briefs index) |

## Cron run loop (what openclaw fires)

Each cron job's prompt tells you which harness 4-step to execute:

```
Step 1  preflight     clawock {brief|report|intraday} preflight [args]
                      → writes memory/.tmp/{brief|report|intraday}-context-*.json
Step 2  read context  inside that .json: raw_wechat_block, anomalies, title, signals, etc.
Step 3  LLM synthesis you write the analysis prose + (brief only) plan.json
                      following the SKILL.md Mode template. Mode 6 reports: prose ONLY —
                      report_postflight prepends title + raw_wechat_block itself
Step 4  postflight    clawock {brief|report|intraday} postflight [args]
                      validates report, computes wechat_prefix, then handles its scoped publish
                      (all three refresh the complete dashboard generation; intraday publishes only semantic diffs)
```

Don't ask permission for internal reads/edits. Action over confirmation.
