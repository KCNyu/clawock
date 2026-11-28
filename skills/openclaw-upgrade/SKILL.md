---
name: openclaw-upgrade
description: Safe OpenClaw version upgrade with regression checklist. Use when kcn says "升级 openclaw" / "openclaw 有没有更新" / "/openclaw-upgrade", or after noticing a newer npm version. Checks for in-flight crons, installs a pinned fork artifact, verifies its built adaptations, and runs the full regression gate without reducing context, skills, tools, thinking, or token budgets. Different from `openclaw-tune` (periodic maintenance, no version bump).
---

# OpenClaw Safe Upgrade

Kcn runs a live automated trading system on OpenClaw. An upgrade that loses crons, breaks embeddings, or orphans an in-flight cron is a production incident. This is the battle-tested flow (5.28→6.1→6.5→6.6→6.8). The current host runbook is `/root/.shared-memory/project-openclaw-upgrade-runbook.md`; historical version traps are in the archive it links. Read these only on this host, never copy them into the public repository.

## 0. Check + decide
1. `openclaw --version` vs `npm view openclaw version` (latest). Pull the changelog (`npm pack openclaw@<v>` → `package/CHANGELOG.md`) and judge relevance — don't upgrade reflexively.
2. Read the host runbook above for the target version's traps; use the installed version's changelog/source when the runbook has no entry.

## 1. 🔴 Never restart the gateway while a cron is in-flight
Use the structured runtime field, not a text grep:

```bash
openclaw cron list --json \
  | jq -e '[.jobs[] | select(.state.runningAtMs != null)] | length == 0'
```

If this is not `true`, wait. A SIGTERM mid-run can orphan the cron into
permanent `running`. Use `--no-restart` and pick a quiet window between slots
(`bash ops/host/check_crons.sh --timeline`).

## 2. Stage the fork artifact

Download the maintenance artifact for the full target commit. Verify its archive
checksum, extract it to a candidate directory named `.openclaw-kcn-<commit>`,
and check the package dependency contract against the existing installation.
Keep the running package selected until stage and verification pass.

## 3. Verify the staged package and replay host extensions

```bash
bash ops/host/reapply_openclaw_patches.sh --install "$CANDIDATE" --commit "$EXPECTED_COMMIT"
bash ops/host/install_skillhub_plugin.sh
bash ops/host/install_memory_corpus_plugin.sh
```

The wrapper checks the resolved directory name, version, build commit and every
adapted bundle against the fork build receipt. The ordered IDs match
`ops/host/openclaw-patches/manifest.json`. A missing receipt or mismatch stops
the upgrade. Retain the previous package selection for rollback. For details see
`docs/operations/openclaw-patch-kit.md`.

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
| **cron contract** | `openclaw cron list --json`; `clawock system check`; `bash ops/host/check_crons.sh --timeline` | names, schedules, enabled state, payloads and host triggers match `config/cron-schedules.json`; inspect the cron runtime/watchdog contract results, not only the total count |
| embedding | `openclaw memory search "<q>" --max-results 2 --json` | returns results, no `Unknown memory embedding provider` (6.8 has no `--limit`) |
| fork artifact | `bash ops/host/reapply_openclaw_patches.sh --check-only` | selected package matches the build receipt |
| MiniMax transport | transport log + fallback smoke | Anthropic protocol; retired `service_tier: "priority"` absent; transport/timeouts match `config/models.toml` and the manifest postconditions |
| weixin delivery | tail `/tmp/openclaw/openclaw-*.log` | `weixin monitor started` + `gateway ready`, no crash loop |
| model chain | the cron run log / a throwaway `openclaw agent` call | a model answers (⚠️ see note) |
| clean startup | gateway log + structured cron listing | scheduler starts the contract's enabled OpenClaw jobs; no plugin load errors |

Derive expected job identities, enabled states and host triggers from
`config/cron-schedules.json`, not a fixed count in this skill. Some jobs intentionally
remain disabled in OpenClaw and are queued by a host trigger; verify both sides.
Do not import legacy jobs or enable a job merely to make a count pass.

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
The model chain breaks silently from billing/auth, not upgrades. If cron runs show `FallbackSummaryError: All models failed`, check each provider (MiniMax overload, glm/deepseek balance, openai/anthropic auth expiry, openai-proxy quota) and tell kcn which to top up / re-login — you can't fix billing/auth yourself. Compare `config/models.toml` and `docs/operations/models.md`; report the failing hop without changing the configured chain.
