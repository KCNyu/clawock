# Harness architecture

clawock is an auditable agent harness for portfolio operation, with a
context-certification layer. It is not an agent orchestration framework: it does
not implement model routing, a ReAct loop or conversation memory. A complete
agent is **clawock + model + runtime**.

## Ownership

| Layer | Owns | Current location |
|---|---|---|
| Harness core | lifecycle vocabulary, generation-pinned artifact contract, validation, context assembly, tool schemas | `clawock/` |
| Instance | portfolio, schedules, selected skills/persona, delivery targets, dashboard skin | root data + `config/` + `skills/` |
| Runtime adapters | conversations, scheduling, delivery, run history | OpenClaw today; provider interfaces in `clawock/providers/` |
| Live desk adapter | market refresh, `.tmp` artifact placement, git coordination, publication/watchdogs | `scripts/harness/` |

The public CLI is the stable driver boundary:

```text
clawock context audit|assemble
clawock brief preflight|postflight
clawock report preflight|postflight
clawock intraday preflight|postflight
```

The workflow commands dispatch in-process; they do not shell out to the old
scripts. The live implementation remains an instance adapter during the
strangler migration, which preserves the old Python entry points for GitHub
workflows and operational rollback.

## Context contract

OpenClaw 2026.7.1 injects, in order, `AGENTS.md`, `TOOLS.md`, `SOUL.md`,
`IDENTITY.md`, and `USER.md`. It excludes `MEMORY.md`, `HEARTBEAT.md`, and
`BOOTSTRAP.md`. `clawock/context_manifest.json` records that exact runtime rule;
CI fails when an injected file disappears or becomes empty.

`clawock context assemble` gives another runner the equivalent bootstrap. Skill
bodies remain lazy: the catalog is only an index, and only an explicitly selected
`skills/{name}/SKILL.md` is added. This preserves normal chat context and avoids
silently loading every skill into every run.

Those five root files must not move while OpenClaw hard-codes their names. The
manifest owns the portable definition and audit gate; it cannot make an old
OpenClaw binary consume a different path.

## Artifact contract

An `ArtifactSet` has one `generation_id`, and every member must carry the same
ID. This is the runtime-neutral seam after model deliberation: a runner may use
OpenClaw, a direct API or an interactive coding agent, but validation and publish
must reject artifacts mixed across generations.
