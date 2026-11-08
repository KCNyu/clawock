# Project documentation

The repository root is reserved for files with a real discovery or runtime
contract: GitHub/Python metadata, OpenClaw bootstrap context, and the live
workspace ledgers. Static website source lives in `site/`; Pages combines it with
public runtime outputs through `ops/pages/stage_site.py`. General documentation
belongs here.

## Architecture

- [`harness.md`](architecture/harness.md) — package/profile/runtime boundaries,
  CLI lifecycle, context injection contract, and generation-pinned artifacts.
- [`decision-architecture.md`](architecture/decision-architecture.md) — who owns
  observations, computation, rule outputs, the hypothesis and the accounting; the
  `observations` and `compute` tools, immutable method proposals and prospective three-arm trials.
- [`session-reviews.md`](architecture/session-reviews.md) — same-session plan progress and
  read-only risk follow-ups on market cards.
- [`intraday-agent.md`](architecture/intraday-agent.md) — the intraday agent
  contract: context layering, card blocks, workflow ownership, objective and
  which rules are gates.
- [`data-plane.md`](architecture/data-plane.md) — why the live JSON snapshot is
  separate from Pages, what GitHub officially supports, and the replacement bar.
- [`openclaw-adapter.md`](architecture/openclaw-adapter.md) — OpenClaw as an
  external runtime and the parity contract the adapter must keep.
- [`runtime-protocol.md`](architecture/runtime-protocol.md) — how any external
  agent runtime invokes clawock.
- [`task-queue.md`](architecture/task-queue.md) — the agent-dispatch queue behind
  the dsh task chip: who owns which layer, the versioned ops entry, queue order, and
  the frozen task/token summary shown by the chip and `/dispatch-stats`.
- [`strategy-plugins.md`](architecture/strategy-plugins.md) — strategies, bars and
  the optimiser as plugins composed by config rows; what a parameter search may conclude.
- [`memory-components.md`](architecture/memory-components.md) — the two memory stores,
  their transcript/note/index/dreaming layers, the write-time salience/status/scope fields,
  the learning loop and the evaluations that keep them honest.
- [`agent-memory-unified.md`](architecture/agent-memory-unified.md) — the target: one shared
  store with scoped injection and publishing views, and the P0–P4 path to it.

## Research notes

- [`dsh-superagent-adoption.md`](research/dsh-superagent-adoption.md) — what the external
  dsh-superagent prototype's Mandate, stage and notification ideas mean for dispatch, what
  was adopted where, and what explicitly does not transfer. Runtime fields and
  notification rules are owned by `architecture/task-queue.md`.

## Product surfaces

- [`how-the-desk-works.md`](how-the-desk-works.md) — the detail behind the README:
  information layers, what each run reads, decision gates, grading rules, what was
  tested and failed, the twelve code-enforced rules ([中文](how-the-desk-works.zh.md)).
- [`decision-map.md`](decision-map.md) — the Decision Map board in Reflect: how
  to read coverage and snapshot age, the payload, and where it runs.
- [`decision-mind-ledger.md`](decision-mind-ledger.md) — the decision-mind
  ledger schema written by `clawock record`.
- [`influencer-radar.md`](influencer-radar.md) — the eight watched sources, how
  hits are linked to holdings, and a worked hit/miss example (moved out of the READMEs).
- [`glossary.md`](glossary.md) — source of truth for cross-document terminology.
- [`data-coverage.md`](reference/data-coverage.md) — data surfaces, independent sources, failure behavior and remaining gaps.
- [`data-health.md`](design/data-health.md) — the Data Health card's structure,
  visual rules and the tests that enforce them.
- [`design-system.md`](design/design-system.md) — the dashboard's colour layers
  (semantic vs. everything else), motion scale, component recipes and the list of
  what a new component may not do, each with the gate that checks it.
- [`workbench-type.md`](design/workbench-type.md) — the Workbench's one type
  table (page/row/metric/meta/chip/button/tab/badge roles), the no-literal
  audit, and the host token gap it declares.
- [`workbench-geometry.md`](design/workbench-geometry.md) — the phone sidebar,
  closing-report and patrol-coverage geometry the overlap test pins, with
  before/after captures.
- [`task-chip.md`](design/task-chip.md) — the task chip's queue panel, patrol page
  (KPI grid, outcome strip, rounds and coverage) and 7-day stacked provider chart,
  plus the frozen numbers behind `/dispatch-stats`.

## Operations

- [`release.md`](operations/release.md) — publishing to PyPI/npm, and running the
  latest code on the host without a release.
- [`openclaw-patch-kit.md`](operations/openclaw-patch-kit.md) — versioned dist adaptations, isolated rehearsal, transaction receipts and guarded rollback.
- [`sqlite-maintenance.md`](operations/sqlite-maintenance.md) — offline checkpoint/VACUUM for the OpenClaw memory index and state store, rollback and the quarterly cron job.
- [`dreaming-review.md`](operations/dreaming-review.md) — private candidates, explicit review receipts, permanent promotion and rollback.
- [`models.md`](operations/models.md) — `config/models.toml`: every model, its parameters and which scenario uses it; OpenClaw, cron, dsh and the MiniMax client follow it.
- [`cron-schedules.md`](operations/cron-schedules.md) — generated human view of
  the tracked cron contract.
- [`research-cadence.md`](operations/research-cadence.md) — which research
  question runs daily, which runs on an event, and why.
- [`skills-store-policy.md`](operations/skills-store-policy.md) — registry
  discovery and installation policy.

- [`agent-discovery.md`](operations/agent-discovery.md) — public machine documentation,
  documented engine discovery paths and a bounded citation measurement protocol.

## Reference

- [`commands.md`](reference/commands.md) — the generated command inventory plus
  the hand-written harness detail (`scripts.md` is a moved-page stub pointing here).
- [`tool-operations.md`](reference/tool-operations.md) — per-task tool detail;
  routing lives in the root `TOOLS.md`.
- [`product-profile-operations.md`](reference/product-profile-operations.md) —
  what belongs to the product, profiles, operations and runtime state.

## Moved pages

Old paths stay reachable; each stub points at the document that owns the subject now.

- [`design/task-chip-patrol.md`](design/task-chip-patrol.md) → [`design/task-chip.md`](design/task-chip.md)
- [`design/task-chip-stats.md`](design/task-chip-stats.md) → [`design/task-chip.md`](design/task-chip.md)
- [`design/intraday-strategy-research.md`](design/intraday-strategy-research.md) → [`architecture/intraday-research-workflow.md`](architecture/intraday-research-workflow.md)
- [`operations/memory-recall-performance.md`](operations/memory-recall-performance.md) → [`operations/sqlite-maintenance.md`](operations/sqlite-maintenance.md)

## Legal

- [`third-party-data.md`](legal/third-party-data.md) — data-provider terms,
  attribution, and redistribution boundaries.

Everything under `docs/` is published with the Pages build
(`ops/pages/stage_site.py`). Keep this index current when adding or removing docs.

A document here describes how the project works now. The record of one task — measurements,
before/after captures, command output, proposed patches, what was and was not verified —
belongs in that task's pull request, where it stays attached to the change it explains.
Write the conclusion into the document that owns the subject; do not add a dated folder.

## Maintaining docs and skills

Keep project-specific contracts, execution boundaries and incident-prevention rules
with their owner; link to them from entrypoints. A skill should contribute a workflow,
a tool adapter or a constraint the model cannot infer from general knowledge.
Concept definitions, generic CLI examples and duplicate report templates do not need
separate skills or mandatory reference reads. Shared HK/US rules belong in
`skills/_shared/`; job-specific schemas stay with their payload/skill and gates.

Before retiring a file, check the last three months of git changes, `TOOLS.md`,
cron payloads/contract and code/test references. A route establishes reachability,
not execution frequency; an unchanged file may still be a live dependency. Record
the keep/merge/delete evidence and consequences in the PR. Preserve published URL
compatibility and verify references, skill schemas and generated command/cron docs.

## Why OpenClaw files stay at the root

`AGENTS.md`, `TOOLS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`,
`HEARTBEAT.md`, `BOOTSTRAP.md`, `skills/` and `memory/` participate in the live
OpenClaw workspace contract. They remain at their required runtime paths until
an adjacent context-parity canary proves a supported alternative. Website files
have no such constraint and therefore live under `site/`.

- [持仓外候选发现](architecture/stock-discovery.md)：免费全市场筛选、研究交接与参考实现。

## Intraday research

- [Open-source strategy research](research/intraday-strategies.md): sources, failure conditions, verified fees and market selection.

- [Intraday research / 盘中研究验证与卡片](architecture/intraday-research-workflow.md)：
  三种 research 插件及其 packet/config 契约、模型回执、净 walk-forward、数据许可、历史研究展示及独立人工条件推荐 / independent manual conditional recommendations。
