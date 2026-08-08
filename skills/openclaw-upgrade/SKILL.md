---
name: openclaw-upgrade
description: Safe OpenClaw version upgrade with regression checklist. Use when kcn says "升级 openclaw" / "openclaw 有没有更新" / "/openclaw-upgrade", or after noticing a newer npm version. Checks for in-flight crons, uses the built-in updater, reapplies all host-local dist patches, and runs the full regression gate without reducing context, skills, tools, thinking, or token budgets. Different from `openclaw-tune` (periodic maintenance, no version bump).
---

# OpenClaw Safe Upgrade

Kcn runs a live automated trading system on OpenClaw. An upgrade that loses crons, breaks embeddings, or orphans an in-flight cron is a production incident. This is the battle-tested flow (5.28→6.1→6.5→6.6→6.8). Full version-specific history lives in auto-memory `openclaw-update-missing-deps.md` — read it first for the target version's known traps.

## 0. Check + decide
1. `openclaw --version` vs `npm view openclaw version` (latest). Pull the changelog (`npm pack openclaw@<v>` → `package/CHANGELOG.md`) and judge relevance — don't upgrade reflexively.
2. Read auto-memory `openclaw-update-missing-deps.md` for that version's traps.

## 1. 🔴 Never restart the gateway while a cron is in-flight
Use the structured runtime field, not a text grep:

```bash
openclaw cron list --json \
  | jq -e '[.jobs[] | select(.state.runningAtMs != null)] | length == 0'
```

If this is not `true`, wait. A SIGTERM mid-run can orphan the cron into
permanent `running`. Use `--no-restart` and pick a quiet window between slots
(`./check_crons.sh --timeline`).

## 2. Update (built-in updater, since 6.x)
```
openclaw update --tag <version> --no-restart --yes
```
This auto-reinstalls/links managed plugins (weixin, llama-cpp, codex) — no manual `pnpm add`, no systemd edits, no `restore-llama-embeddings.sh` needed. (Pre-6.x manual flow is in the memory file.)

## 3. 🔴 Reapply all upgrade-sensitive local patches before restart
The updater replaces the installed `dist/` tree. From the live workspace run:

```bash
bash ops/host/reapply_openclaw_patches.sh
```

The wrapper applies these idempotent host scripts in order:

1. `/root/tools/openclaw/current/patch-embedding-threads1.sh`
2. `/root/tools/openclaw/current/patch-memory-search-timeout.sh`
3. `/root/tools/openclaw/current/patch-minimax-m3-priority.sh`
4. `/root/tools/openclaw/current/patch-minimax-response-header-timeout.sh`

It then verifies all four markers, runs `node --check` on every modified bundle,
and compiles the maintenance detector. It does **not** restart the gateway.

Any missing script, changed source anchor, syntax error, or missing marker is a
hard stop: do not restart and do not declare the upgrade complete. Inspect the
new OpenClaw source, revise the relevant patch script deliberately, and rerun
the wrapper. Never skip a failed patch just to make the new version start.

## 4. Restart once, in a clean window
Re-run the structured no-in-flight check from step 1, then:

```bash
openclaw gateway restart
bash ops/host/reapply_openclaw_patches.sh --check-only
```

## 5. Regression gate (ALL must pass before declaring done)
| Check | Command | Pass = |
|---|---|---|
| version | `openclaw --version` | shows target |
| **cron count** | `openclaw cron list \| grep -c isolated` | **11** (SQLite→SQLite keeps them; if lost → `openclaw doctor --fix` imports legacy jobs.json) |
| embedding | `openclaw memory search "<q>" --max-results 2 --json` | returns results, no `Unknown memory embedding provider` (6.8 has no `--limit`) |
| local patches | `bash ops/host/reapply_openclaw_patches.sh --check-only` | all four markers and JS/Python syntax pass |
| MiniMax transport | transport log + fallback smoke | Anthropic protocol; `priority` present; a no-header timeout is retryable; the 300s generation timeout remains |
| weixin delivery | tail `/tmp/openclaw/openclaw-*.log` | `weixin monitor started` + `gateway ready`, no crash loop |
| model chain | the cron run log / a throwaway `openclaw agent` call | a model answers (⚠️ see note) |
| clean startup | gateway log | `cron: started jobs:11`, no plugin load errors |

Run one complete isolated cron after the cheap checks. Inspect its actual
session and `systemPromptReport`, not only the final summary. Pass means:

- all allowed workspace bootstrap files are present with `truncatedFiles=0`
- the full skill catalog is present and the payload-required `SKILL.md` body
  was actually read before analysis
- the full tool set is present (no stale cron `tools` allowlist)
- normal prompt/context window, output budget, thinking level, and whole-turn
  timeout are unchanged
- postflight reports zero issues and the expected delivery/dashboard results
- the model fallback chain still advances on a retryable provider failure

Do not use `--light-context`, a tool allowlist, lower thinking, smaller token
budgets, or prompt trimming as an upgrade workaround. MiniMax token usage is
not a constraint for this deployment.

## 6. Known-benign post-6.8 noise (don't chase)
- `adp-openclaw` plugin disabled (ships TS source, no `dist/`) — stale `plugins.entries` warning; harmless, offer to delete the entry.
- systemd unit shows "installed by <old ver>" — cosmetic metadata; daemon runs the new global package. `openclaw doctor --repair` fixes it (non-blocking).
- `plugins.allow is empty` audit WARN — long-standing, harmless.

## ⚠️ Model fallback chain (verify, escalate to kcn)
The model chain breaks silently from billing/auth, not upgrades. If cron runs show `FallbackSummaryError: All models failed`, check each provider (MiniMax overload, glm/deepseek balance, openai/anthropic auth expiry, openai-proxy quota) and tell kcn which to top up / re-login — you can't fix billing/auth yourself. See `openclaw-xiaomi-fallback`.
