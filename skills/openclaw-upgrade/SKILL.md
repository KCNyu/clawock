---
name: openclaw-upgrade
description: Safe OpenClaw version upgrade with regression checklist. Use when kcn says "升级 openclaw" / "openclaw 有没有更新" / "/openclaw-upgrade", or after noticing a newer npm version. Encodes the validated 6.8 flow — checks for in-flight crons before restart, uses the built-in updater, and runs the full regression gate (cron count, embedding, weixin delivery, model chain). Different from `openclaw-tune` (periodic maintenance, no version bump).
---

# OpenClaw Safe Upgrade

Kcn runs a live automated trading system on OpenClaw. An upgrade that loses crons, breaks embeddings, or orphans an in-flight cron is a production incident. This is the battle-tested flow (5.28→6.1→6.5→6.6→6.8). Full version-specific history lives in auto-memory `openclaw-update-missing-deps.md` — read it first for the target version's known traps.

## 0. Check + decide
1. `openclaw --version` vs `npm view openclaw version` (latest). Pull the changelog (`npm pack openclaw@<v>` → `package/CHANGELOG.md`) and judge relevance — don't upgrade reflexively.
2. Read auto-memory `openclaw-update-missing-deps.md` for that version's traps.

## 1. 🔴 Never restart the gateway while a cron is in-flight
`openclaw cron list | grep running` — if anything is **running**, WAIT (a SIGTERM mid-run orphans it into permanent `running`). Use `--no-restart` and pick a quiet window between cron slots (`./check_crons.sh --timeline`).

## 2. Update (built-in updater, since 6.x)
```
openclaw update --tag <version> --no-restart --yes
```
This auto-reinstalls/links managed plugins (weixin, llama-cpp, codex) — no manual `pnpm add`, no systemd edits, no `restore-llama-embeddings.sh` needed. (Pre-6.x manual flow is in the memory file.)

## 3. Restart in a clean window
Re-confirm nothing running → `openclaw gateway restart`.

## 4. Regression gate (ALL must pass before declaring done)
| Check | Command | Pass = |
|---|---|---|
| version | `openclaw --version` | shows target |
| **cron count** | `openclaw cron list \| grep -c isolated` | **11** (SQLite→SQLite keeps them; if lost → `openclaw doctor --fix` imports legacy jobs.json) |
| embedding | `openclaw memory search "<q>" --max-results 2 --json` | returns results, no `Unknown memory embedding provider` (6.8 has no `--limit`) |
| weixin delivery | tail `/tmp/openclaw/openclaw-*.log` | `weixin monitor started` + `gateway ready`, no crash loop |
| model chain | the cron run log / a throwaway `openclaw agent` call | a model answers (⚠️ see note) |
| clean startup | gateway log | `cron: started jobs:11`, no plugin load errors |

## 5. Known-benign post-6.8 noise (don't chase)
- `adp-openclaw` plugin disabled (ships TS source, no `dist/`) — stale `plugins.entries` warning; harmless, offer to delete the entry.
- systemd unit shows "installed by <old ver>" — cosmetic metadata; daemon runs the new global package. `openclaw doctor --repair` fixes it (non-blocking).
- `plugins.allow is empty` audit WARN — long-standing, harmless.

## ⚠️ Model fallback chain (verify, escalate to kcn)
The model chain breaks silently from billing/auth, not upgrades. If cron runs show `FallbackSummaryError: All models failed`, check each provider (MiniMax overload, glm/deepseek balance, openai/anthropic auth expiry, openai-proxy quota) and tell kcn which to top up / re-login — you can't fix billing/auth yourself. See `openclaw-xiaomi-fallback`.
