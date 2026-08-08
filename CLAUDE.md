# CLAUDE.md

Entry pointer for Claude Code in kcn's investment workspace. Same workflow as `AGENTS.md` (openclaw entry) — content lives in the canonical files below, this is just the road map.

## Identity & user

- You're `Rick` (see `IDENTITY.md`)
- User is `kcn` / Shengyu Li (see `USER.md`)

## Required reads (every session, in order)

1. `SOUL.md` — disposition / how to think
2. `USER.md` — who kcn is + preferences
3. `MEMORY.md` — iron data rules + known traps
4. `TOOLS.md` — scripts / fallback chains / skill routing / cron map
5. `memory/YYYY-MM-DD.md` (today + yesterday) — recent context
6. `INVESTMENT_SOP.md` — investment-question startup sequence
7. `portfolio.json` — lazy-load when needed

## What lives where

| Topic | File |
|---|---|
| Disposition / persona | `SOUL.md`, `IDENTITY.md` |
| User profile / preferences | `USER.md` |
| Iron rules / traps | `MEMORY.md` |
| Scripts / fallback / skill routing / cron | `TOOLS.md` |
| Skill bodies | `skills/{name}/SKILL.md` |
| Data scripts | `scripts/data/` (analyze, fetch, update, build_dashboard) |
| Harness CLI / live adapter | `clawock brief\|report\|intraday` / `instances/kcnyu/` |
| Legacy / reference scripts | `scripts/legacy/` |
| Daily logs (template `_TEMPLATE.md`) | `memory/YYYY-MM-DD.md` |
| Daily deep brief output | `memory/{date}-pre-open.md` + `memory/{date}-plan.json` |
| Daily portfolio snapshots | `memory/snapshots/{date}.json` |
| Preflight context (gitignored) | `memory/.tmp/` |
| Startup sequence | `INVESTMENT_SOP.md` |
| Heartbeat workflow | `HEARTBEAT.md` (heartbeat poll only) |
| Auto-commit rules | `AGENTS.md` |
| Interactive code PR/worktree rules | `AGENTS.md` § Interactive Codex/Claude PR workflow |
| Pages dashboard input | `assets/data/dashboard.json` (built by `scripts/data/build_dashboard.py`) |
| Risk metrics snapshot | `assets/data/risk.json` (built by `scripts/data/portfolio_risk_metrics.py`, refreshed daily via brief preflight) |
| Decision execution marking | `memory/decisions.jsonl` `execution.status`; manual override via `scripts/data/mark_followed.py DECISION_ID [--no]` |
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
                      (all three auto-run build_dashboard.py; intraday commits only semantic diffs)
```

Don't ask permission for internal reads/edits. Action over confirmation.
