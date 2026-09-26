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
| Profile | portfolio data, schedules, policy values, selected skills/persona, delivery targets and presentation resources | root data + `config/profiles/` + referenced resources |
| Runtime adapters | conversations, scheduling, delivery, run history | OpenClaw today; provider interfaces in `src/clawock/providers/` |
| Lifecycle runtime | market refresh, `.tmp` artifacts, publication, heartbeats and watchdogs | `src/clawock/{harness,automation}/` in the root wheel |

Reusable investment strategies remain product code under `src/clawock/decision/`,
even when the first consumer is the live KCNyu desk. Package lifecycle modules
bind those strategies into phases and provider-backed delivery; profiles only
select values and resources. The full provider → strategy → lifecycle rule is
documented in
[`product-profile-operations.md`](../reference/product-profile-operations.md#evidence-strategy-and-profile-rule).

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

The live workflow phase commands dispatch directly to package-owned lifecycle
modules selected by a declarative profile. The wheel contains the complete
implementation but no user's portfolio or generated state.

## Intraday decision and delivery boundary

The full contract — context layering, card blocks, workflow ownership,
objective and compliance gates — is [`intraday-agent.md`](intraday-agent.md).

The preflight gives the model its complete decision context. It includes every
open plan (including zero-share watch decisions), watch levels, all held-name
peer scans, source status, setup and T+0 reads, prior semantic state, a compact
all-holdings sweep, and soft candidates. The 3% anomaly threshold guarantees an
alert; it does not decide the model's agenda. Soft candidates include 1.5–3%
moves and names near the existing 20-day radar level. The model judges which
candidate matters, how primary evidence changes the thesis, and how plans and
strategy metadata constrain an action. Brief WeChat copy is a separate output
constraint. Reducing noise means fewer user wake-ups, not fewer decision inputs.

A full card follows a fixed layout contract (the block list lives above
`compose_card` in `intraday_preflight.py`; `test_card_layout_contract` and
`test_preflight_main_never_rewrites_the_analyzer_table` enforce it): title, a
P0 line only when one newly fired, the 变化 line, `⛔ 数据降级` lines
(unverified quotes said once, with since when the same names have been
carried), then the analyzer's market strip, book line and holdings table
**byte for byte**, one `↑` pointer line naming the rows with a new
move/trigger, the signal block with signals already
delivered this session folded into one `今日已报、仍在` line, the candidate
sections, the model's `▎我的看法` after the whole data block, and advisory
checker findings last. `⛔` is only data
health and `⚠️` only the analyzer's signal header. All of this is copy only:
the model still reads the full `signals_detail`, `source_signals_detail`,
`full_holdings` and `quote_coverage`.

The shared HK/US delta compares stable condition identities, including the
first appearance of a soft candidate or a breach that trading day, plan status and
source health. Breaches compare as the session's seen set, so a ticker flickering
across a bucket edge back to a state already delivered today stays quiet. The first session slot, a material condition change, or incomplete
evidence gets a full card. **The 2026-09-24 silence contract was overturned by kcn on 2026-09-25 (「全部都正常发」, as in the 2026-07-27 removal of the intraday delta gate); `always_full` is on and is final, and the silence code below runs only when that config is explicitly set to false:
every slot sends the full card; an unchanged one says `变化：无…` and its
judgment may be one honest line (`本档无实质变化…`), which is exempt from the
60-character floor, while claiming a new move on it is flagged.** With the
switch off, a healthy unchanged slot records a `no_change`
heartbeat and exact-slot marker without sending to WeChat or Telegram. A slot
with only a new soft candidate asks the model to choose whether to speak; an
exact `SILENT` response records the same audited quiet outcome. The watchdog
accepts only that matching marker; a failed postflight or missing marker
remains eligible for its normal fallback. The
`always_full` switch in `config/intraday-delivery.json` can still force every
slot's full card. Portfolio `strategy` selects declarative exception values in
`config/intraday-strategy-policies.json`; the harness has no ticker-specific
investment branch. Escalation rules name a `subject` (`holding`, or its registry
`signal_symbol` as `underlying`) rather than a ticker, so every holding that
selects a strategy is checked against its own instruments. The silent outcome is
filed in the workflow-outcome ledger as final `no_change` with
`primary_delivery=not_required`, not as a pending or failed send. The analyzer's
generic headline feed stays out of the card but reaches the model as
`headline_feed`. A future maximum silent-streak heartbeat would need its own
config and an auditable cursor; none is enabled by default.

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
progressively. Python validators remain package code so neither a runtime nor a
profile can silently edit financial or provenance invariants by changing prose.
