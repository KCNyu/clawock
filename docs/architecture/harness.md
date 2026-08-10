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
| Plugin/harness core | portable skills/workflows, generation-pinned artifact contract, validation/reconciliation, context assembly, tool schemas, evaluation contracts | `src/clawock/` + portable skill/workflow packages (in progress) |
| Instance | portfolio, schedules, selected skills/persona, delivery targets, dashboard skin | root data + `config/` + `skills/` |
| Runtime adapters | conversations, scheduling, delivery, run history | OpenClaw today; provider interfaces in `src/clawock/providers/` |
| Live desk adapter | market refresh, `.tmp` artifact placement, git coordination, publication/watchdogs | separately installable `instances/kcnyu/` distribution |

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

The first shipped workflow pins its ID, semantic version, whole-pack certificate
and bounded parameters into the prepared request. Its deterministic validator
requires supporting and opposing evidence, linked bull/bear cases, thesis
invalidation conditions, a bounded action, confidence provenance and exact
order/FX arithmetic. A prompt cannot waive those gates.

Version 1.1 adds the bounded feedback loop without turning clawock into an
agent. An observed outcome is source-linked and reconciled across price and FX;
the evaluator reports a direction-adjusted basis-point result with an explicit
not-realized-P&L caveat. That evaluation, or a rejected validation receipt, can
anchor a proposal that changes only parameters already bounded by the pack.
Proposal review certifies an exact hash, apply records before/after overrides,
and rollback refuses to overwrite later drift. No command launches a model,
rewrites a skill, or lets a proposal accept itself.
The shipped parameters govern evidence/provenance strictness only; they do not
add or tune factors, catalysts, signals, entries, exits or portfolio rules. The
calling runtime's existing investment strategy remains the decision source.

The live workflow phase commands discover KCNyu's separately installed
`clawock-kcnyu` distribution through standard Python entry points. The portable
wheel contains neither that implementation nor portfolio data. The former
`scripts/harness/` launchers were removed after OpenClaw phases and host
watchdogs completed their installed-command cutover.

## Context contract

OpenClaw 2026.7.1 does not have one universal context allowlist. Normal chat
injects the five identity/tool bootstrap files plus `HEARTBEAT.md` and
`MEMORY.md`; isolated cron injects only the five-file runtime allowlist;
heartbeat-light keeps only `HEARTBEAT.md`; bootstrap-pending and subagent runs
have their own rules. `src/clawock/context/manifest.json` records each profile, the
lazy skill/memory capability roots, conversation-history ownership and the rule
that clawock never narrows OpenClaw's tools implicitly.

`clawock context audit` fails visibly when an injected file is missing/empty or
when moving `skills/`, `MEMORY.md` or `memory/` would silently remove
catalog/search capability. With no `--profile` it audits every profile and fails
if any one of them does — a file that only the interactive profile requires is
not covered by auditing isolated-cron alone. This is broader than comparing prompt text:
the skills catalog contains metadata rather than skill bodies, memory search can
remain available where `MEMORY.md` is not injected, and session history belongs
to the runtime rather than the bootstrap bundle.

`clawock context assemble` gives another runner the equivalent bootstrap. Skill
bodies remain lazy: the catalog is only an index, and only an explicitly selected
`skills/{name}/SKILL.md` is added. This preserves normal chat context and avoids
silently loading every skill into every run.

The runtime-required root files and capability directories must not move before
every active profile passes its parity gate. The manifest owns the portable
definition and audit gate; it cannot make an OpenClaw binary consume a different
path. The full adapter and cron cutover contract is in
[`openclaw-adapter.md`](openclaw-adapter.md).

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

Package data under `src/clawock/workflows/packs/<workflow-id>/` owns reusable
semantics:

```text
investment-decision/
├── SKILL.md
├── workflow.json
├── agents/openai.yaml
├── references/decision-contract.md
├── references/decision.schema.json
├── references/outcome.schema.json
├── references/improvement-proposal.schema.json
├── assets/decision.example.json
└── assets/outcome.example.json
```

`workflow.json` is the machine-readable discovery and parameter contract;
`SKILL.md` follows the open [Agent Skills specification](https://agentskills.io/specification)
and is the runtime-facing procedure; references and assets are loaded
progressively. Python validators remain package code so neither a runtime nor an
instance can silently edit financial or provenance invariants by changing prose.
