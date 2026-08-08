# OpenClaw adapter and parity contract

OpenClaw is an external agent runtime, not an implementation detail to absorb
into clawock. It owns the model, conversation/session transcript, prompt
assembly, memory index, skill discovery, tool schemas and permissions, cron
scheduler, and delivery channel. clawock contributes a stable CLI plus portable
decision workflows, deterministic validation/reconciliation, artifacts and
receipts.

## Context profiles

The contract was verified against the installed OpenClaw 2026.7.1 source and
its stored system-prompt reports. The machine-readable source is
`clawock/context_manifest.json`.

| Profile | Injected workspace files | History and lazy capabilities |
|---|---|---|
| interactive | `AGENTS`, `SOUL`, `TOOLS`, `IDENTITY`, `USER`, `HEARTBEAT`, `MEMORY` | existing session transcript; skill catalog; selected skill bodies; memory search |
| isolated cron | `AGENTS`, `SOUL`, `TOOLS`, `IDENTITY`, `USER` | isolated run transcript; skill catalog; selected skill bodies; memory tools remain runtime-owned |
| heartbeat full | same root context as interactive after bootstrap | configured heartbeat session; full runtime policy |
| heartbeat light | `HEARTBEAT` only | history depends on `isolatedSession`; runtime tools remain policy-controlled |
| bootstrap pending | normal roots plus `BOOTSTRAP` while setup is incomplete | primary interactive startup flow |
| subagent | `AGENTS`, `TOOLS` | subagent-owned context; other identity/memory files are not inherited as bootstrap |

The skills prompt is a catalog, not a concatenation of every `SKILL.md`. A
workflow payload that requires a strategy skill must still read that selected
body before analysis. The default memory-search source is `MEMORY.md` plus
`memory/*.md`; indexed session transcripts are a separate optional source.
Bare `/new` and `/reset` also receive OpenClaw-owned bounded startup context from
recent dated memory files. None of those surfaces may be replaced by copying a
five-file cron bundle into normal chat.

Audit the live workspace without invoking a model:

```bash
clawock context audit --workspace /path/to/workspace --profile interactive
clawock context audit --workspace /path/to/workspace --profile isolated-cron
clawock context audit --workspace /path/to/workspace --profile heartbeat-full
```

## OpenClaw cron is a separate runtime contract

A passing context audit does not certify a scheduled workflow. Every OpenClaw
cron row also owns:

```text
schedule + timezone + DST + enabled state
                     │
payload.message ──► selected SKILL read + clawock preflight
                     │
             external model/tool loop
                     │
              clawock postflight
                     │
artifact generation + delivery receipt + watchdog state
```

The tracked payload templates in `config/cron-payloads/` are the reviewable
instruction source. Live rows must preserve model/fallback/thinking/timeout,
full tool policy, `--no-deliver` versus postflight delivery ownership,
context/generation IDs, retry/idempotency, watchdog behavior and market-session
no-overlap windows. OpenClaw's managed memory-dreaming job is also runtime state;
it is inventoried separately because it is not a clawock market-workflow row.

Cutover order is deliberately conservative:

1. Snapshot prompt reports and live cron rows.
2. Prove interactive, cron and heartbeat profiles before moving root files.
3. Canary one low-risk scheduled run through the installed package adapter.
4. Compare context, artifact, delivery and watchdog receipts.
5. Roll through the remaining live rows only after parity holds.
6. Keep a named compatibility path until its final consumer and removal gate are
   documented.

System crontab and GitHub Actions are separate schedulers. They belong in the
end-to-end operations/freshness matrix and cannot be used as evidence that the
OpenClaw cron contract passed.
