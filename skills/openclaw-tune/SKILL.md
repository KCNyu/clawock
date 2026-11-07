---
name: openclaw-tune
description: OpenClaw host maintenance for session backup growth, disk usage, model/cron drift and memory health. Use for periodic maintenance or a specific health symptom. Version upgrades use openclaw-upgrade; repository document/skill cleanup follows AGENTS.md and its worktree/PR workflow.
---

# OpenClaw host maintenance

Start from the reported symptom. Inspect the relevant surface below; a maintenance
request does not require loading investment data, running quote refreshes or changing
model choices. Workspace documentation changes follow `AGENTS.md` § Code changes.

## Inspect before changing

| Surface | Evidence | Owner / action |
|---|---|---|
| Session storage | Sizes, ages and matching transcript for `~/.openclaw/agents/main/sessions/*.bak-*`; distinguish active transcripts, backups and trajectory logs | Propose a bounded archive set. Preserve active sessions and useful diagnostic logs; file age or absence from the catalog alone does not establish that a file is disposable. |
| Other disk growth | `~/.openclaw/openclaw.json.clobbered.*`, old stability dumps, media and SQLite temporary files | Check references and open handles (`lsof`) before moving anything. Never move an open database, WAL or SHM file. For index/state database compaction use `docs/operations/sqlite-maintenance.md`, including its offline/rollback requirements. |
| Injected context | `config/context-manifest.json` plus actual `systemPromptReport`, file sizes and truncation | Remove duplicate ownership only after checking consumers. Preserve concrete incident rules, scheduled input contracts and tool/skill availability. No byte target justifies dropping required context. |
| Model/fallback drift | `python3 ops/host/sync_models.py --effective`; compare with `config/models.toml` | `docs/operations/models.md` owns parameters, chains and synchronization. Report failing hops; do not reorder providers or change thinking/budgets as a cleanup. |
| Cron drift | `openclaw cron list --json`, `bash ops/host/check_crons.sh --timeline`, `clawock system check` | Compare identities, schedules, enabled state, payloads and host triggers with `config/cron-schedules.json`; `docs/operations/cron-schedules.md` is generated. Change runtime cron only via supported CLI/sync tools. |
| Recall / dreaming | Latest diagnostics and source dates, not just file counts or trading keywords | `docs/operations/dreaming-review.md` owns candidate review and promotion; `docs/operations/memory-recall-performance.md` owns recall diagnosis. Never prune a live recall store by keyword or promote daily prices as durable lessons. |
| After an upgrade | Installed version, patch-kit checks, actual agent context and delivery | Follow `../openclaw-upgrade/SKILL.md`; do not duplicate its update/restart sequence here. |

## Apply only the evidenced cleanup

1. Enumerate the exact files and why each is stale. For inactive session backups,
   retaining the latest three per session is a starting proposal, not permission
   to discard transcripts or recovery evidence.
2. Check live ownership and preserve a recovery path. Archive approved inactive
   files under `/root/scratch/openclaw-cleanup-<date>/`, with original paths and
   before/after sizes recorded there. Do not use `/tmp` for recovery material.
3. Follow the owning runbook for state/config changes. Back up `openclaw.json`
   before authorized edits. Repository files are changed in a task worktree and
   delivered through PR, checks, merge and live refresh.
4. Restart only when required and authorized for the task; first confirm no cron
   is in flight with the upgrade skill's structured check. Archiving inactive
   files and editing documentation alone do not require a restart.

Do not delete published briefs, trade records or incident lessons merely because
positions were closed. Do not edit raw cron stores, SQLite internals or provider
credentials to make a health check green. Generic prompt-writing advice and
arbitrary file-size caps are not acceptance criteria.

## Verify and report

Re-run the check that exposed the symptom. For host health, check
`curl -sf http://127.0.0.1:18789/health` and the relevant structured CLI output;
a healthy HTTP endpoint alone does not prove cron, recall or delivery works.
For repository documents, run the affected reference/schema checks.

Report the finding, exact changes, file/byte counts, archive/recovery path,
verification results and remaining gaps. State whether a restart happened.
