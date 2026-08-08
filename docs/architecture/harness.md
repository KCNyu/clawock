# Harness architecture

clawock is an agent-native decision-workflow plugin kit backed by a verifiable
harness. It packages reusable skills, tool contracts and decision workflows for
external agents. It is not an agent orchestration framework: it does not
implement model routing, a ReAct loop or conversation memory. The external
agent/runtime remains complete in itself.

The runtime is intentionally external. OpenClaw, Hermes, Claude Code, Codex,
LangGraph or another runner may own the conversation, model and tools; clawock
calls clawock for workflow steps, certified input, deterministic reconciliation,
validation, outcome evaluation and publication receipts.

A generation is the correlated audit unit emitted by one workflow run, not the
product itself. The product-level loop is evidence → debate/workflow → decision →
execution/outcome → bounded, reviewable improvement proposal.

## Ownership

| Layer | Owns | Current location |
|---|---|---|
| Plugin/harness core | portable skills/workflows, generation-pinned artifact contract, validation/reconciliation, context assembly, tool schemas, evaluation contracts | `clawock/` + portable skill/workflow packages (in progress) |
| Instance | portfolio, schedules, selected skills/persona, delivery targets, dashboard skin | root data + `config/` + `skills/` |
| Runtime adapters | conversations, scheduling, delivery, run history | OpenClaw today; provider interfaces in `clawock/providers/` |
| Live desk adapter | market refresh, `.tmp` artifact placement, git coordination, publication/watchdogs | `scripts/harness/` |

The public CLI is the stable driver boundary:

```text
clawock init <workspace>
clawock workflow list|show|install
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

`clawock workflow install investment-decision --workspace <workspace>` exports
the package-owned pack to `<workspace>/.agents/skills/investment-decision` as a
standard Agent Skill (`SKILL.md`, progressive references and assets). Current
OpenClaw also [discovers project-agent skills](https://docs.openclaw.ai/skills)
from `.agents/skills`; other
skills-compatible runtimes can consume the same directory without a fork. The
installed skill tells the current agent how to call the CLI—it does not delegate
to a clawock-owned model.

The first shipped workflow pins its ID, semantic version, descriptor certificate
and bounded parameters into the prepared request. Its deterministic validator
requires supporting and opposing evidence, linked bull/bear cases, thesis
invalidation conditions, a bounded action, confidence provenance and exact
order/FX arithmetic. A prompt cannot waive those gates. Outcome evaluation and
review/apply/rollback of parameter proposals remain the next #386 slice and are
not claimed by version 1.0.0.

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

## Workflow pack contract

Package data under `clawock/workflows/packs/<workflow-id>/` owns reusable
semantics:

```text
investment-decision/
├── SKILL.md
├── workflow.json
├── agents/openai.yaml
├── references/decision-contract.md
├── references/decision.schema.json
└── assets/decision.example.json
```

`workflow.json` is the machine-readable discovery and parameter contract;
`SKILL.md` follows the open [Agent Skills specification](https://agentskills.io/specification)
and is the runtime-facing procedure; references and assets are loaded
progressively. Python validators remain package code so neither a runtime nor an
instance can silently edit financial or provenance invariants by changing prose.
