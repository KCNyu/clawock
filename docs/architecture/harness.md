# Harness architecture

clawock is an auditable agent harness for portfolio operation, with a
context-certification layer. It is not an agent orchestration framework: it does
not implement model routing, a ReAct loop or conversation memory. The external
agent/runtime remains complete in itself; clawock is the verifiable execution
envelope around it.

The runtime is intentionally external. OpenClaw, Hermes, Claude Code, Codex,
LangGraph or another runner may own the conversation, model and tools; clawock
wraps that run with certified input, deterministic artifacts, reconciliation,
validation and publication receipts.

## Ownership

| Layer | Owns | Current location |
|---|---|---|
| Harness core | complete `AgentRun` lifecycle, generation-pinned artifact contract, validation/repair, context assembly, tool schemas | `clawock/` |
| Instance | portfolio, schedules, selected skills/persona, delivery targets, dashboard skin | root data + `config/` + `skills/` |
| Runtime adapters | conversations, scheduling, delivery, run history | OpenClaw today; provider interfaces in `clawock/providers/` |
| Live desk adapter | market refresh, `.tmp` artifact placement, git coordination, publication/watchdogs | `scripts/harness/` |

The public CLI is the stable driver boundary:

```text
clawock init <workspace>
clawock run prepare --workspace <workspace>
clawock run publish --workspace <workspace> --request <json> --artifact <name=path>
clawock context audit|assemble
clawock brief preflight|postflight
clawock report preflight|postflight
clawock intraday preflight|postflight
```

`init` and `run` are package-native and work from an installed wheel outside the
repository. The control direction is external agent → clawock, like an
agent-native business CLI. `run prepare` emits certified input; the calling agent
keeps its own model, conversation, memory, skills, tools and repair loop; `run
publish` validates/reconciles its files and atomically emits generation-pinned
artifacts plus a receipt. clawock never launches the agent.

The live workflow phase commands dispatch in-process but currently resolve the
KCNyu implementation from `scripts/harness`. They are a compatibility seam, not
standalone wheel functionality. The old Python entry points remain available for
OpenClaw, GitHub workflows and operational rollback until the instance adapter
cutover is complete.

## Context contract

OpenClaw 2026.7.1 isolated cron injects, in order, `AGENTS.md`, `TOOLS.md`,
`SOUL.md`, `IDENTITY.md`, and `USER.md`. That profile excludes `MEMORY.md`,
`HEARTBEAT.md`, and `BOOTSTRAP.md`; normal chat, heartbeat and bootstrap have
different context behavior. `clawock/context_manifest.json` records the isolated
cron rule, and CI fails when one of those injected files disappears or is empty.

`clawock context assemble` gives another runner the equivalent bootstrap. Skill
bodies remain lazy: the catalog is only an index, and only an explicitly selected
`skills/{name}/SKILL.md` is added. This preserves normal chat context and avoids
silently loading every skill into every run.

Those five root files must not move while OpenClaw hard-codes their names. The
manifest owns the portable definition and audit gate; it cannot make an old
OpenClaw binary consume a different path.

Standalone runs instead list context files in `clawock.json`. Every document and
the assembled bundle receive SHA-256 certification in the runtime request and
published manifest. The command protocols are specified in
[`runtime-protocol.md`](runtime-protocol.md).

## Artifact contract

An `ArtifactSet` has one `generation_id`, and every member must carry the same
ID. This is the runtime-neutral seam after model deliberation: a runner may use
OpenClaw, a direct API or an interactive coding agent, but validation and publish
must reject artifacts mixed across generations.
